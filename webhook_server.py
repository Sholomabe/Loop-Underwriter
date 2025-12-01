from flask import Flask, request, jsonify
import os
import json
from datetime import datetime
from database import get_db, init_db
from models import Deal, PDFFile, Transaction
from pdf_processor import calculate_pdf_hash, extract_account_number_from_pdf
from koncile_integration import extract_with_koncile, KoncileClient
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
                
                # Process PDF with Koncile extraction
                extracted_data, reasoning_log, verification_result = extract_with_koncile(file_path)
                
                # Check for extraction errors
                if extracted_data.get('error'):
                    final_status = "Extraction Failed"
                    reasoning_log += f"\n\nExtraction Error: {extracted_data.get('error')}"
                # Determine status based on verification
                elif verification_result.is_valid:
                    final_status = "Pending Approval"
                elif verification_result.confidence_score >= 0.7:
                    final_status = "Pending Approval"
                elif verification_result.confidence_score >= 0.5:
                    final_status = "Needs Human Review"
                else:
                    final_status = "Needs Human Review"
                
                # Update account number from Koncile if available
                koncile_account = extracted_data.get('koncile_summary', {}).get('account_number') or account_number
                
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
                        # Parse date from various formats
                        date_str = txn.get('date', '2024-01-01')
                        txn_date = None
                        for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%d/%m/%Y', '%Y/%m/%d']:
                            try:
                                txn_date = datetime.strptime(str(date_str), fmt)
                                break
                            except ValueError:
                                continue
                        if txn_date is None:
                            txn_date = datetime.utcnow()
                        
                        transaction = Transaction(
                            deal_id=new_deal.id,
                            source_account_id=txn.get('source_account_id'),
                            transaction_date=txn_date,
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
                new_deal.retry_count = 0
                new_deal.status = final_status
                new_deal.updated_at = datetime.utcnow()
                
                # Update PDF file with Koncile account number if found
                if koncile_account and koncile_account != account_number:
                    pdf_file.account_number = koncile_account
                
                db.commit()
                
                return jsonify({
                    "status": "success",
                    "message": "Email processed with Koncile extraction",
                    "deal_id": new_deal.id,
                    "final_status": final_status,
                    "verification_passed": verification_result.is_valid,
                    "confidence_score": verification_result.confidence_score,
                    "account_number": koncile_account or account_number
                }), 200
        
    except Exception as e:
        print(f"Error processing email: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/koncile-callback', methods=['POST'])
def koncile_callback():
    """
    Webhook endpoint to receive extraction results from Koncile.
    Configure this URL in your Koncile dashboard under webhook settings.
    
    Expected payload from Koncile:
    {
        "task_id": "string",
        "status": "DONE|DUPLICATE|IN_PROGRESS",
        "general_fields": {...},
        "repeated_fields": [...]
    }
    """
    try:
        data = request.json
        
        if not data:
            return jsonify({"error": "No JSON payload received"}), 400
        
        task_id = data.get('task_id', '')
        status = data.get('status', '')
        general_fields = data.get('general_fields', {})
        repeated_fields = data.get('repeated_fields', [])
        
        # Log the callback
        print(f"Koncile callback received - Task: {task_id}, Status: {status}")
        
        # Only process completed extractions
        if status not in ['DONE', 'done', 'completed']:
            return jsonify({
                "status": "acknowledged",
                "message": f"Task {task_id} status: {status} - waiting for completion"
            }), 200
        
        # Parse Koncile data using our existing integration
        from koncile_integration import KoncileClient, StatementVerifier
        
        # Create client to use its parsing methods
        client = KoncileClient()
        
        # Parse summary from general_fields
        summary = client.parse_summary(general_fields)
        
        # Parse transactions from repeated_fields (line items)
        transactions = client.parse_transactions({'Line_fields': repeated_fields})
        
        # Run verification
        verifier = StatementVerifier()
        verification = verifier.verify(summary, transactions)
        
        # Determine status based on verification
        if verification.is_valid:
            final_status = "Pending Approval"
        elif verification.confidence_score >= 0.7:
            final_status = "Pending Approval"
        elif verification.confidence_score >= 0.5:
            final_status = "Needs Human Review"
        else:
            final_status = "Needs Human Review"
        
        # Get account info for transaction linking
        account_number = summary.account_number or general_fields.get('account_number', 'Unknown')
        bank_name = summary.bank_name or general_fields.get('bank_name', 'Unknown')
        
        with get_db() as db:
            # Check for duplicate by task_id (prevent reprocessing same Koncile task)
            existing_deal = db.query(Deal).filter(
                Deal.email_body.contains(f"Task ID: {task_id}")
            ).first()
            
            if existing_deal:
                return jsonify({
                    "status": "duplicate",
                    "message": f"Task {task_id} already processed",
                    "deal_id": existing_deal.id
                }), 200
            
            # Create a new deal from the Koncile callback
            new_deal = Deal(
                sender=f"koncile-email@{bank_name.lower().replace(' ', '')}.com",
                subject=f"[Koncile] Bank Statement - {account_number}",
                email_body=f"Koncile Task ID: {task_id}\nProcessed via email integration\nBank: {bank_name}\nAccount: {account_number}",
                status=final_status,
                created_at=datetime.utcnow()
            )
            db.add(new_deal)
            db.flush()
            
            # Create a virtual PDFFile record for tracking (no actual file since Koncile has it)
            import hashlib
            virtual_hash = hashlib.sha256(f"koncile:{task_id}".encode()).hexdigest()
            
            pdf_file = PDFFile(
                deal_id=new_deal.id,
                filename=f"koncile_statement_{task_id}.pdf",
                file_path=f"koncile://{task_id}",
                file_hash=virtual_hash,
                account_number=account_number,
                account_status="from_koncile",
                uploaded_at=datetime.utcnow()
            )
            db.add(pdf_file)
            db.flush()
            
            # Build extracted data structure
            extracted_data = {
                'transactions': transactions,
                'koncile_summary': {
                    'account_number': summary.account_number,
                    'bank_name': summary.bank_name,
                    'statement_period': f"{summary.statement_start_date} to {summary.statement_end_date}",
                    'opening_balance': float(summary.opening_balance),
                    'closing_balance': float(summary.closing_balance),
                    'total_deposits': float(summary.total_deposits),
                    'total_deposits_count': summary.total_deposits_count,
                    'total_withdrawals': float(summary.total_withdrawals),
                    'total_withdrawals_count': summary.total_withdrawals_count,
                    'total_checks': float(summary.total_checks),
                    'total_fees': float(summary.total_fees),
                },
                'verification': {
                    'is_valid': verification.is_valid,
                    'confidence_score': verification.confidence_score,
                    'discrepancies': verification.discrepancies,
                    'warnings': verification.warnings
                },
                'extraction_source': 'koncile_email',
                'task_id': task_id,
                'daily_positions': [],
                'weekly_positions': [],
                'monthly_positions_non_mca': [],
                'other_liabilities': [],
            }
            
            # Store transactions in database with source_account_id
            for txn in transactions:
                txn_date = None
                if txn.get('date'):
                    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y']:
                        try:
                            txn_date = datetime.strptime(str(txn['date']), fmt)
                            break
                        except ValueError:
                            continue
                if txn_date is None:
                    txn_date = datetime.utcnow()
                
                transaction = Transaction(
                    deal_id=new_deal.id,
                    source_account_id=account_number,
                    transaction_date=txn_date,
                    description=txn.get('description', ''),
                    amount=txn.get('amount', 0),
                    transaction_type=txn.get('type', 'unknown'),
                    category=txn.get('category', 'other'),
                    created_at=datetime.utcnow()
                )
                db.add(transaction)
            
            # Update deal with extracted data
            new_deal.extracted_data = extracted_data
            new_deal.ai_reasoning_log = f"Koncile Email Integration\nTask ID: {task_id}\nVerification: {'PASSED' if verification.is_valid else 'NEEDS REVIEW'}\nConfidence: {verification.confidence_score:.0%}"
            new_deal.updated_at = datetime.utcnow()
            
            db.commit()
            
            return jsonify({
                "status": "success",
                "message": "Koncile extraction processed successfully",
                "deal_id": new_deal.id,
                "final_status": final_status,
                "verification_passed": verification.is_valid,
                "confidence_score": verification.confidence_score,
                "transaction_count": len(transactions)
            }), 200
    
    except Exception as e:
        print(f"Error processing Koncile callback: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/gmail-webhook', methods=['POST'])
def gmail_webhook():
    """
    Webhook endpoint specifically for Google Apps Script integration.
    Receives emails with a specific Gmail label and processes PDF attachments.
    
    Expected JSON payload from Google Apps Script:
    {
        "sender": "sender@example.com",
        "subject": "Bank Statement",
        "body": "Email body text",
        "message_id": "gmail_message_id",
        "label": "Process",
        "attachments": [
            {
                "filename": "statement.pdf",
                "content": "<base64 encoded PDF>",
                "mimeType": "application/pdf"
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
        message_id = data.get('message_id', '')
        label = data.get('label', 'Unknown')
        attachments = data.get('attachments', [])
        
        # Filter to only PDF attachments
        pdf_attachments = [
            a for a in attachments 
            if a.get('mimeType', '').lower() == 'application/pdf' 
            or a.get('filename', '').lower().endswith('.pdf')
        ]
        
        if not pdf_attachments:
            return jsonify({
                "status": "skipped",
                "message": "No PDF attachments found in email"
            }), 200
        
        processed_deals = []
        
        with get_db() as db:
            for attachment in pdf_attachments:
                # Save attachment to disk
                file_path = save_attachment(attachment, 0)
                
                # Calculate PDF hash for duplicate detection
                pdf_hash = calculate_pdf_hash(file_path)
                
                # Check if this PDF already exists
                existing_pdf = db.query(PDFFile).filter(PDFFile.file_hash == pdf_hash).first()
                
                if existing_pdf:
                    existing_deal = existing_pdf.deal
                    processed_deals.append({
                        "status": "duplicate",
                        "filename": attachment.get('filename'),
                        "original_deal_id": existing_deal.id
                    })
                    continue
                
                # Extract account number
                account_number, account_status = extract_account_number_from_pdf(file_path)
                
                # Create new deal with Gmail metadata
                new_deal = Deal(
                    sender=sender,
                    subject=f"[Gmail:{label}] {subject}",
                    email_body=f"Gmail Message ID: {message_id}\n\n{body}",
                    status="Processing",
                    created_at=datetime.utcnow()
                )
                db.add(new_deal)
                db.flush()
                
                # Create PDF file record
                pdf_file = PDFFile(
                    deal_id=new_deal.id,
                    filename=attachment.get('filename', 'attachment.pdf'),
                    file_path=file_path,
                    file_hash=pdf_hash,
                    account_number=account_number,
                    account_status=account_status,
                    uploaded_at=datetime.utcnow()
                )
                db.add(pdf_file)
                db.flush()
                
                # Process PDF with Koncile extraction
                extracted_data, reasoning_log, verification_result = extract_with_koncile(file_path)
                
                # Check for extraction errors
                if extracted_data.get('error'):
                    final_status = "Extraction Failed"
                    reasoning_log += f"\n\nExtraction Error: {extracted_data.get('error')}"
                elif verification_result.is_valid:
                    final_status = "Pending Approval"
                elif verification_result.confidence_score >= 0.7:
                    final_status = "Pending Approval"
                elif verification_result.confidence_score >= 0.5:
                    final_status = "Needs Human Review"
                else:
                    final_status = "Needs Human Review"
                
                # Update account number from Koncile if available
                koncile_account = extracted_data.get('koncile_summary', {}).get('account_number') or account_number
                
                # Store transactions
                transactions = extracted_data.get('transactions', [])
                if transactions:
                    transfers = find_inter_account_transfers(transactions)
                    for txn in transactions:
                        txn_date = None
                        if txn.get('date'):
                            for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y']:
                                try:
                                    txn_date = datetime.strptime(str(txn['date']), fmt)
                                    break
                                except ValueError:
                                    continue
                        if txn_date is None:
                            txn_date = datetime.utcnow()
                        
                        transaction = Transaction(
                            deal_id=new_deal.id,
                            source_account_id=txn.get('source_account_id'),
                            transaction_date=txn_date,
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
                new_deal.retry_count = 0
                new_deal.status = final_status
                new_deal.updated_at = datetime.utcnow()
                
                if koncile_account and koncile_account != account_number:
                    pdf_file.account_number = koncile_account
                
                processed_deals.append({
                    "status": "success",
                    "filename": attachment.get('filename'),
                    "deal_id": new_deal.id,
                    "final_status": final_status,
                    "confidence_score": verification_result.confidence_score
                })
            
            db.commit()
        
        return jsonify({
            "status": "success",
            "message": f"Processed {len(processed_deals)} attachment(s) from Gmail",
            "gmail_label": label,
            "deals": processed_deals
        }), 200
        
    except Exception as e:
        print(f"Error processing Gmail webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "service": "underwriting-webhook"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
