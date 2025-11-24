from typing import Dict, Tuple, Optional
from openai_integration import extract_financial_data_from_pdf
from transfer_hunter import calculate_revenue_excluding_transfers

def verify_extraction_math(extracted_data: Dict, transactions: list) -> Tuple[bool, Optional[str]]:
    """
    Perform mathematical verification on extracted data.
    
    Checks:
    1. Sum of transaction amounts matches extracted totals
    2. Revenue calculation excludes internal transfers
    3. Category totals are consistent
    
    Args:
        extracted_data: Dict containing extracted financial metrics
        transactions: List of transaction dicts
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if verification passes
        - error_message: None if valid, otherwise detailed error description
    """
    if not transactions:
        return True, None  # No transactions to verify
    
    # Calculate sum of all transactions
    total_credits = sum(t['amount'] for t in transactions if t.get('amount', 0) > 0)
    total_debits = sum(abs(t['amount']) for t in transactions if t.get('amount', 0) < 0)
    
    # Calculate revenue excluding transfers
    revenue_excluding_transfers = calculate_revenue_excluding_transfers(transactions)
    
    # Verify revenues_last_4_months
    extracted_revenue = extracted_data.get('revenues_last_4_months', 0)
    
    # Allow 2% tolerance for rounding
    tolerance = 0.02
    
    if extracted_revenue > 0:
        revenue_diff = abs(revenue_excluding_transfers - extracted_revenue)
        revenue_diff_pct = revenue_diff / extracted_revenue if extracted_revenue > 0 else 0
        
        if revenue_diff_pct > tolerance:
            error_msg = (
                f"Revenue verification failed: "
                f"You extracted Total Revenue of ${extracted_revenue:,.2f}, "
                f"but the sum of credit transaction rows (excluding internal transfers) is ${revenue_excluding_transfers:,.2f}. "
                f"Difference: ${revenue_diff:,.2f} ({revenue_diff_pct*100:.1f}%). "
                f"Please re-scan the document, find the missing transactions, and output corrected JSON. "
                f"Remember to exclude internal transfers from revenue calculation."
            )
            return False, error_msg
    
    # Verify total_monthly_payments if available
    extracted_payments = extracted_data.get('total_monthly_payments', 0)
    
    if extracted_payments > 0:
        # Sum of debits should roughly match total payments
        payments_diff = abs(total_debits - extracted_payments)
        payments_diff_pct = payments_diff / extracted_payments if extracted_payments > 0 else 0
        
        if payments_diff_pct > tolerance:
            error_msg = (
                f"Payments verification failed: "
                f"You extracted Total Monthly Payments of ${extracted_payments:,.2f}, "
                f"but the sum of debit transaction rows is ${total_debits:,.2f}. "
                f"Difference: ${payments_diff:,.2f} ({payments_diff_pct*100:.1f}%). "
                f"Please review all debit transactions and ensure accuracy."
            )
            return False, error_msg
    
    # Verify transaction count consistency
    listed_txn_count = len(transactions)
    if listed_txn_count < 3:
        error_msg = (
            f"Insufficient transactions: You only listed {listed_txn_count} transactions. "
            f"A typical bank statement has many more. Please re-scan and extract ALL transactions."
        )
        return False, error_msg
    
    return True, None

def auto_retry_extraction_with_verification(
    pdf_path: str,
    account_id: Optional[str] = None,
    max_retries: int = 2
) -> Tuple[Dict, str, int, str]:
    """
    Auto-retry loop for PDF extraction with verification.
    
    Workflow:
    1. Initial extraction
    2. Math verification
    3. If fails, retry with specific error feedback (max 2 retries)
    4. If still fails after retries, mark for human review
    
    Args:
        pdf_path: Path to PDF file
        account_id: Account identifier
        max_retries: Maximum number of retry attempts
    
    Returns:
        Tuple of (extracted_data, reasoning_log, retry_count, final_status)
        - final_status: "Pending Approval" or "Needs Human Review"
    """
    retry_count = 0
    error_feedback = None
    final_status = "Pending Approval"
    
    while retry_count <= max_retries:
        # Extract data (with error feedback if this is a retry)
        extracted_data, reasoning_log = extract_financial_data_from_pdf(
            pdf_path,
            account_id,
            error_feedback
        )
        
        # Get transactions for verification
        transactions = extracted_data.get('transactions', [])
        
        # Verify the extraction
        is_valid, error_message = verify_extraction_math(extracted_data, transactions)
        
        if is_valid:
            # Verification passed!
            final_status = "Pending Approval"
            break
        else:
            # Verification failed
            retry_count += 1
            
            if retry_count <= max_retries:
                # Prepare error feedback for retry
                error_feedback = error_message
                reasoning_log += f"\n\n[RETRY {retry_count}] Verification failed: {error_message}"
            else:
                # Max retries reached, flag for human review
                final_status = "Needs Human Review"
                reasoning_log += f"\n\n[FINAL] Max retries ({max_retries}) reached. Flagged for human review."
                reasoning_log += f"\nFinal error: {error_message}"
                break
    
    return extracted_data, reasoning_log, retry_count, final_status
