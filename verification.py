from typing import Dict, Tuple, Optional, List
import json
from datetime import datetime
from openai_integration import extract_financial_data_from_pdf
from transfer_hunter import calculate_revenue_excluding_transfers, is_payment_category_debit, cluster_positions_by_merchant


def safe_float(value, default=0.0) -> float:
    """Safely convert a value to float, handling strings and None."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Handle "not_computable" marker
        if value.lower() == 'not_computable':
            return default
        # Remove currency symbols and commas
        cleaned = value.replace('$', '').replace(',', '').replace(' ', '').strip()
        if cleaned == '' or cleaned == '-':
            return default
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


def is_not_computable(value) -> bool:
    """Check if a value is marked as 'not_computable'."""
    if isinstance(value, str):
        return value.lower() == 'not_computable'
    return False


def analyze_transaction_types(transactions: List[Dict]) -> Dict:
    """
    Analyze transaction types to detect debit-only or credit-only datasets.
    
    Uses the 'type' field preferentially, falls back to amount sign.
    
    Returns:
        Dict with counts and flags for data completeness
    """
    credit_count = 0
    debit_count = 0
    
    for txn in transactions:
        txn_type = str(txn.get('type', '')).lower()
        amount = safe_float(txn.get('amount', 0))
        
        # Determine type using type field preferentially
        if txn_type == 'credit':
            credit_count += 1
        elif txn_type == 'debit':
            debit_count += 1
        elif amount > 0:
            credit_count += 1
        elif amount < 0:
            debit_count += 1
    
    return {
        'credit_count': credit_count,
        'debit_count': debit_count,
        'total_count': len(transactions),
        'is_debit_only': debit_count > 0 and credit_count == 0,
        'is_credit_only': credit_count > 0 and debit_count == 0,
        'has_both': credit_count > 0 and debit_count > 0
    }


def calculate_payment_total_from_type_field(transactions: List[Dict]) -> float:
    """
    Calculate total payments using the type field (not amount sign).
    
    NEW RULE: Include ALL payment-category debits regardless of lender_payment flag.
    
    Args:
        transactions: List of transaction dicts
    
    Returns:
        Total of all payment debits
    """
    total = 0.0
    
    for txn in transactions:
        if is_payment_category_debit(txn):
            # Get absolute amount for debit
            amount = abs(safe_float(txn.get('amount', 0)))
            total += amount
    
    return total


def verify_extraction_math(extracted_data: Dict, transactions: list) -> Tuple[bool, Optional[str]]:
    """
    Perform mathematical verification on extracted data.
    
    Checks:
    1. Sum of transaction amounts matches extracted totals
    2. Revenue calculation excludes internal transfers
    3. Category totals are consistent
    4. Handles "not_computable" markers properly
    5. Uses type field for debit/credit detection
    
    Args:
        extracted_data: Dict containing extracted financial metrics (supports both flat and nested structures)
        transactions: List of transaction dicts
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if verification passes
        - error_message: None if valid, otherwise detailed error description
    """
    if not transactions:
        return True, None  # No transactions to verify
    
    # Analyze transaction types to understand data completeness
    type_analysis = analyze_transaction_types(transactions)
    
    # Calculate totals using type field (not amount sign)
    total_credits = 0.0
    total_debits = 0.0
    
    for txn in transactions:
        txn_type = str(txn.get('type', '')).lower()
        amount = abs(safe_float(txn.get('amount', 0)))
        
        if txn_type == 'credit':
            total_credits += amount
        elif txn_type == 'debit':
            total_debits += amount
        else:
            # Fallback to amount sign
            raw_amount = safe_float(txn.get('amount', 0))
            if raw_amount > 0:
                total_credits += raw_amount
            elif raw_amount < 0:
                total_debits += abs(raw_amount)
    
    # Calculate payments using type field and category
    calculated_payments = calculate_payment_total_from_type_field(transactions)
    
    # Calculate revenue excluding transfers
    revenue_excluding_transfers = calculate_revenue_excluding_transfers(transactions)
    
    # Handle both old flat format and new nested format
    info_needed = extracted_data.get('info_needed', extracted_data)
    
    # Allow 5% tolerance for rounding (increased for complex calculations)
    tolerance = 0.05
    errors = []
    
    # VALIDATION 1: Check if income metrics are properly marked for debit-only data
    if type_analysis['is_debit_only']:
        # For debit-only data, income metrics should be "not_computable"
        avg_income = info_needed.get('average_monthly_income')
        annual_income = info_needed.get('annual_income')
        
        if safe_float(avg_income) > 0 and not is_not_computable(avg_income):
            errors.append(
                f"Data insufficiency issue: Dataset contains only debits ({type_analysis['debit_count']} debits, 0 credits). "
                f"You reported average_monthly_income=${safe_float(avg_income):,.2f}, but this cannot be calculated from debit-only data. "
                f"Use 'not_computable' for income metrics when no credit/deposit transactions are present."
            )
        
        if safe_float(annual_income) > 0 and not is_not_computable(annual_income):
            errors.append(
                f"Data insufficiency issue: annual_income should be 'not_computable' when no credit transactions exist."
            )
    
    # VALIDATION 2: Verify total_monthly_payments includes ALL payment debits
    extracted_payments = safe_float(info_needed.get('total_monthly_payments', 0))
    
    if extracted_payments == 0 and calculated_payments > 0:
        errors.append(
            f"Payment totals error: You reported total_monthly_payments=0, "
            f"but there are {type_analysis['debit_count']} debit transactions totaling ${calculated_payments:,.2f}. "
            f"CRITICAL: Use the 'type' field to identify debits, not the amount sign. "
            f"Include ALL payment-category debits regardless of lender_payment flag."
        )
    elif extracted_payments > 0:
        # Allow some tolerance for different calculation methods
        payments_diff = abs(calculated_payments - extracted_payments)
        payments_diff_pct = payments_diff / max(extracted_payments, calculated_payments, 1)
        
        if payments_diff_pct > tolerance:
            errors.append(
                f"Payments verification warning: "
                f"You extracted Total Monthly Payments of ${extracted_payments:,.2f}, "
                f"but calculated sum of payment-category debits is ${calculated_payments:,.2f}. "
                f"Difference: ${payments_diff:,.2f} ({payments_diff_pct*100:.1f}%). "
                f"Remember: Include ALL payment debits regardless of lender_payment flag. "
                f"Use the 'type' field (debit/credit) to determine cash flow direction."
            )
    
    # VALIDATION 3: Verify revenue calculation (only if we have credits)
    if type_analysis['has_both'] or not type_analysis['is_debit_only']:
        extracted_avg_income = safe_float(info_needed.get('average_monthly_income', 0))
        
        if not is_not_computable(info_needed.get('average_monthly_income')):
            extracted_revenue = safe_float(extracted_data.get('revenues_last_4_months', 0))
            
            # If no explicit revenue field, use average income * 4 as estimate for 4 months
            if extracted_revenue == 0 and extracted_avg_income > 0:
                extracted_revenue = extracted_avg_income * 4
            
            if extracted_revenue > 0:
                revenue_diff = abs(revenue_excluding_transfers - extracted_revenue)
                revenue_diff_pct = revenue_diff / extracted_revenue if extracted_revenue > 0 else 0
                
                if revenue_diff_pct > tolerance:
                    errors.append(
                        f"Revenue verification warning: "
                        f"You extracted Total Revenue of ${extracted_revenue:,.2f}, "
                        f"but the sum of credit transaction rows (excluding internal transfers) is ${revenue_excluding_transfers:,.2f}. "
                        f"Difference: ${revenue_diff:,.2f} ({revenue_diff_pct*100:.1f}%). "
                        f"Remember: Use the 'type' field to identify credits."
                    )
    
    # VALIDATION 4: Check position detection
    daily_positions = extracted_data.get('daily_positions', [])
    if len(daily_positions) == 0 and type_analysis['debit_count'] >= 5:
        # Use actual clustering to detect if there are repeating patterns
        detected_clusters = cluster_positions_by_merchant(transactions)
        daily_clusters = [c for c in detected_clusters if c.get('frequency') == 'daily']
        
        # Only flag if we actually detected daily patterns that weren't reported
        if len(daily_clusters) > 0:
            cluster_info = ", ".join([
                f"{c['merchant']} (${c['amount']:.2f} x {c['count']})" 
                for c in daily_clusters[:3]
            ])
            errors.append(
                f"Position detection issue: You reported 0 daily positions, "
                f"but we detected {len(daily_clusters)} repeating daily debit patterns: {cluster_info}. "
                f"Look for REPEATING debits from the same merchant on consecutive business days."
            )
    
    # VALIDATION 5: Verify transaction count consistency
    listed_txn_count = len(transactions)
    if listed_txn_count < 2:
        errors.append(
            f"Insufficient transactions: You only listed {listed_txn_count} transactions. "
            f"A typical bank statement has many more. Please re-scan and extract ALL transactions."
        )
    
    # Return results
    if errors:
        combined_error = "\n\n".join(errors)
        return False, combined_error
    
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
    extracted_data: Dict = {}
    reasoning_log: str = ""
    
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


def save_correction_pattern(
    db_session,
    original_data: Dict,
    corrected_data: Dict,
    correction_report: str,
    deal_id: Optional[int] = None
) -> bool:
    """
    Save correction patterns to TrainingExamples for few-shot learning.
    
    Captures the learned patterns from AI corrections so they can be
    used in future analyses.
    
    Args:
        db_session: SQLAlchemy database session
        original_data: AI's original extracted data
        corrected_data: Human-corrected or adversarial-corrected data
        correction_report: Detailed explanation of what was corrected
        deal_id: Optional link to the deal
    
    Returns:
        True if saved successfully
    """
    try:
        from models import TrainingExample
        
        # Create training example with detailed correction info
        correction_details = {
            'timestamp': datetime.utcnow().isoformat(),
            'error_types': [],
            'learned_rules': []
        }
        
        # Analyze what was corrected
        original_info = original_data.get('info_needed', original_data)
        corrected_info = corrected_data.get('info_needed', corrected_data)
        
        # Check for type field issues
        if safe_float(original_info.get('total_monthly_payments', 0)) == 0:
            if safe_float(corrected_info.get('total_monthly_payments', 0)) > 0:
                correction_details['error_types'].append('type_field_not_used')
                correction_details['learned_rules'].append(
                    "RULE: Use 'type' field (debit/credit) to determine cash flow direction, not amount sign"
                )
        
        # Check for over-restrictive lender filter
        original_positions = len(original_data.get('daily_positions', []))
        corrected_positions = len(corrected_data.get('daily_positions', []))
        if original_positions == 0 and corrected_positions > 0:
            correction_details['error_types'].append('position_detection_failed')
            correction_details['learned_rules'].append(
                "RULE: Cluster repeating debits by merchant name and amount to detect positions"
            )
        
        # Check for not_computable issues
        if safe_float(original_info.get('average_monthly_income', 0)) > 0:
            if is_not_computable(corrected_info.get('average_monthly_income')):
                correction_details['error_types'].append('not_computable_not_used')
                correction_details['learned_rules'].append(
                    "RULE: Use 'not_computable' for income metrics when only debit data is available"
                )
        
        # Build user_corrected_summary from correction report
        training_example = TrainingExample(
            original_financial_json=original_data,
            user_corrected_summary=correction_report,
            correction_details=correction_details,
            deal_id=deal_id
        )
        
        db_session.add(training_example)
        db_session.commit()
        
        return True
        
    except Exception as e:
        print(f"Error saving correction pattern: {e}")
        db_session.rollback()
        return False


def save_gold_standard_rule(
    db_session,
    rule_pattern: str,
    correct_classification: str,
    original_classification: str,
    description: str
) -> bool:
    """
    Save a learned pattern to GoldStandard_Rules for automatic application.
    
    These rules are applied automatically to future transactions.
    
    Args:
        db_session: SQLAlchemy database session
        rule_pattern: The pattern to match (e.g., "type='debit' AND category='payment'")
        correct_classification: How this should be classified
        original_classification: What it was incorrectly classified as
        description: Human-readable description of the rule
    
    Returns:
        True if saved successfully
    """
    try:
        from models import GoldStandardRule
        
        rule = GoldStandardRule(
            rule_pattern=rule_pattern,
            correct_classification=correct_classification,
            original_classification=original_classification,
            confidence_score=1.0,
            times_applied=0,
            times_successful=0
        )
        
        db_session.add(rule)
        db_session.commit()
        
        return True
        
    except Exception as e:
        print(f"Error saving gold standard rule: {e}")
        db_session.rollback()
        return False


# Pre-defined correction rules from the AI correction report
DEFAULT_CORRECTION_RULES = [
    {
        'rule_pattern': "type='debit' for cash outflow",
        'correct_classification': "Use type field to identify debits",
        'original_classification': "Relied on negative amount sign",
        'description': "Always use the 'type' field (debit/credit) to determine cash flow direction, not the amount sign"
    },
    {
        'rule_pattern': "category='payment' AND type='debit'",
        'correct_classification': "Include in total_monthly_payments",
        'original_classification': "Excluded due to lender_payment=false",
        'description': "Include ALL payment-category debits in totals, regardless of lender_payment flag"
    },
    {
        'rule_pattern': "repeating debits same merchant",
        'correct_classification': "Daily/Weekly/Monthly position",
        'original_classification': "Not detected as position",
        'description': "Cluster repeating debits by merchant and amount to detect MCA positions"
    },
    {
        'rule_pattern': "debit-only dataset income metrics",
        'correct_classification': "not_computable",
        'original_classification': "0",
        'description': "Mark income metrics as 'not_computable' when only debit data is available"
    }
]


def initialize_default_rules(db_session) -> int:
    """
    Initialize database with default correction rules learned from past mistakes.
    
    Returns:
        Number of rules added
    """
    count = 0
    for rule in DEFAULT_CORRECTION_RULES:
        if save_gold_standard_rule(
            db_session,
            rule['rule_pattern'],
            rule['correct_classification'],
            rule['original_classification'],
            rule['description']
        ):
            count += 1
    return count
