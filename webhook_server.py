from flask import Flask, request, jsonify
import os
import json
from datetime import datetime
from database import get_db, init_db
from models import Deal, PDFFile, Transaction
from pdf_processor import calculate_pdf_hash, extract_account_number_from_pdf
from verification import auto_retry_extraction_with_verification
from transfer_hunter import find_inter_account_transfers
import base64

app = Flask(__name__)

# Ensure database is initialized
init_db()

def save_attachment(attachment_data: dict, deal_id: int) -> str:
    """Save email attachment to disk and return file path."""
    # Create uploads directory if it doesn't exist
    upload_dir = "uploads"
    os.makedirs(upload_dir, exist_ok=True)
    
    # Get filename and content
    filename = attachment_data.get('filename', f'attachment_{deal_id}.pdf')
    content_base64 = attachment_data.get('content', '')
    
    # Decode base64 content
    try:
        content_bytes = base64.b64decode(content_base64)
    except:
        # If not base64, assume it's raw bytes or content
        content_bytes = content_base64.encode() if isinstance(content_base64, str) else content_base64
    
    # Save file
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, 'wb') as f:
        f.write(content_bytes)
    
    return file_path

@app.route('/incoming-email', methods=['POST'])
def incoming_email():
    """
    Webhook endpoint to receive email payloads from SendGrid or similar services.
    
    Expected JSON payload:
    {
        "sender": "sender@example.com",
        "subject": "Bank Statement",
        "body": "Email body text",
        "attachments": [
            {
                "filename": "statement.pdf",
                "content": "<base64 encoded PDF>"
            }
        ]
    }
    """
    try:
        data = request.json
        
        if not data:
            return jsonify({"error": "No JSON payload received"}), 400
        
        sender = data.get('sender', 'unknown@example.com')
        subject = data.get('subject', 'No Subject')
        body = data.get('body', '')
        attachments = data.get('attachments', [])
        
        if not attachments:
            return jsonify({"error": "No attachments found"}), 400
        
        with get_db() as db:
            # Process each attachment
            for attachment in attachments:
                # Save attachment to disk
                file_path = save_attachment(attachment, 0)  # Temporary ID
                
                # Calculate PDF hash for duplicate detection
                pdf_hash = calculate_pdf_hash(file_path)
                
                # Check if this PDF already exists
                existing_pdf = db.query(PDFFile).filter(PDFFile.file_hash == pdf_hash).first()
                
                if existing_pdf:
                    # Duplicate found! Link to existing deal
                    existing_deal = existing_pdf.deal
                    
                    # Create new deal but mark as duplicate
                    duplicate_deal = Deal(
                        sender=sender,
                        subject=subject,
                        email_body=body,
                        status="Duplicate",
                        duplicate_of_deal_id=existing_deal.id,
                        created_at=datetime.utcnow()
                    )
                    db.add(duplicate_deal)
                    db.flush()
                    
                    return jsonify({
                        "status": "duplicate",
                        "message": f"Duplicate PDF detected. Linked to existing Deal ID: {existing_deal.id}",
                        "deal_id": duplicate_deal.id,
                        "original_deal_id": existing_deal.id
                    }), 200
                
                # Not a duplicate - process new PDF
                # Extract account number
                account_number, account_status = extract_account_number_from_pdf(file_path)
                
                # Create new deal
                new_deal = Deal(
                    sender=sender,
                    subject=subject,
                    email_body=body,
                    status="Processing",
                    created_at=datetime.utcnow()
                )
                db.add(new_deal)
                db.flush()
                
                # Create PDF file record
                pdf_file = PDFFile(
                    deal_id=new_deal.id,
                    file_path=file_path,
                    file_hash=pdf_hash,
                    account_number=account_number,
                    account_status=account_status,
                    created_at=datetime.utcnow()
                )
                db.add(pdf_file)
                db.flush()
                
                # Process PDF with auto-retry verification
                extracted_data, reasoning_log, retry_count, final_status = auto_retry_extraction_with_verification(
                    file_path,
                    account_number
                )
                
                # Extract transactions and run transfer hunter
                transactions = extracted_data.get('transactions', [])
                if transactions:
                    # Add deal_id and source_account_id to each transaction
                    for txn in transactions:
                        txn['deal_id'] = new_deal.id
                        txn['source_account_id'] = account_number or 'Unknown'
                    
                    # Find inter-account transfers
                    transactions = find_inter_account_transfers(transactions)
                    
                    # Save transactions to database
                    for txn in transactions:
                        transaction = Transaction(
                            deal_id=new_deal.id,
                            source_account_id=txn.get('source_account_id'),
                            transaction_date=datetime.strptime(txn.get('date', '2024-01-01'), '%Y-%m-%d'),
                            description=txn.get('description', ''),
                            amount=txn.get('amount', 0),
                            transaction_type=txn.get('type', 'unknown'),
                            is_internal_transfer=txn.get('is_internal_transfer', False),
                            matched_transfer_id=txn.get('matched_transfer_id'),
                            category=txn.get('category', 'other'),
                            created_at=datetime.utcnow()
                        )
                        db.add(transaction)
                
                # Update deal with extracted data
                new_deal.extracted_data = extracted_data
                new_deal.ai_reasoning_log = reasoning_log
                new_deal.retry_count = retry_count
                new_deal.status = final_status
                new_deal.updated_at = datetime.utcnow()
                
                db.commit()
                
                return jsonify({
                    "status": "success",
                    "message": "Email processed successfully",
                    "deal_id": new_deal.id,
                    "final_status": final_status,
                    "retry_count": retry_count,
                    "account_number": account_number
                }), 200
        
    except Exception as e:
        print(f"Error processing email: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "underwriting-webhook"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
