import pandas as pd
import re
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional


def safe_float(value, default=0.0) -> float:
    """Safely convert a value to float, handling strings and None."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Remove currency symbols and commas
        cleaned = value.replace('$', '').replace(',', '').replace(' ', '').strip()
        if cleaned == '' or cleaned == '-':
            return default
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


# Known lender keywords for debt identification
KNOWN_LENDER_KEYWORDS = [
    "financing", "capital", "funding", "advance", "lending", 
    "merchant", "mca", "loan", "credit", "payoff", "factor",
    "business funding", "cash advance", "working capital"
]


def is_explicit_internal_transfer(description: Optional[str], known_account_numbers: Optional[List[str]] = None) -> bool:
    """
    Check if a transaction is an EXPLICIT internal transfer based on description.
    
    NEW RULE: Only exclude deposits as "Internal Transfers" if:
    a) The description explicitly says "Online Transfer from Chk... [Last 4 of merchant's accounts]"
    b) OR the text explicitly says "Intra-bank Transfer"
    
    Args:
        description: Transaction description
        known_account_numbers: List of known account numbers for this merchant
    
    Returns:
        True only if this is an explicit internal transfer
    """
    if not description:
        return False
    
    desc_lower = description.lower().strip()
    
    # Pattern 1: Explicit "Intra-bank Transfer"
    if "intra-bank transfer" in desc_lower or "intrabank transfer" in desc_lower:
        return True
    
    # Pattern 2: "Online Transfer from Chk..." with known account numbers
    online_transfer_pattern = r"online\s+transfer\s+from\s+chk\s*\.?\s*(\d{4})"
    match = re.search(online_transfer_pattern, desc_lower)
    
    if match and known_account_numbers:
        last_4 = match.group(1)
        # Check if the last 4 digits match any known account
        for acct in known_account_numbers:
            if acct and str(acct).endswith(last_4):
                return True
    
    # Pattern 3: Other explicit internal transfer keywords
    explicit_patterns = [
        "transfer between accounts",
        "internal transfer",
        "account to account transfer",
        "transfer to savings",
        "transfer from savings",
        "funds transfer internal"
    ]
    
    for pattern in explicit_patterns:
        if pattern in desc_lower:
            return True
    
    return False


def is_related_entity_revenue(sender_name: Optional[str], merchant_name: Optional[str], description: Optional[str]) -> bool:
    """
    Check if a transfer from a "related entity" should be treated as REVENUE.
    
    Related entities (e.g., "Big World Enterprises" -> "Big World Travel") should be
    counted as revenue, NOT excluded as internal transfers.
    
    Args:
        sender_name: Name of the sender/payer
        merchant_name: Name of the merchant/business
        description: Transaction description
    
    Returns:
        True if this appears to be revenue from a related entity
    """
    if not sender_name or not merchant_name:
        return False
    
    sender_lower = sender_name.lower().strip()
    merchant_lower = merchant_name.lower().strip()
    
    # If exact match, it's not a related entity - it's the same entity
    if sender_lower == merchant_lower:
        return False
    
    # Check for fuzzy match - might be related entity
    # Extract the first significant word from each name
    sender_words = [w for w in sender_lower.split() if len(w) > 2]
    merchant_words = [w for w in merchant_lower.split() if len(w) > 2]
    
    if not sender_words or not merchant_words:
        return False
    
    # If they share a significant common word, they might be related
    common_words = set(sender_words) & set(merchant_words)
    
    # Exclude common business words
    business_words = {"inc", "llc", "corp", "company", "enterprises", "group", "services"}
    significant_common = common_words - business_words
    
    # If they share a significant word (like "Big World"), treat as related entity revenue
    if significant_common:
        return True
    
    return False


def is_known_lender_payment(description: Optional[str], amount=None, txn_type: Optional[str] = None) -> bool:
    """
    Check if a transaction matches known lender keywords.
    
    NEW RULE: If a recurring debit matches ANY of the Known_Lender_Keywords,
    it should be flagged as a potential MCA/lending position.
    
    IMPORTANT: Use txn_type ('debit'/'credit') to determine cash flow direction,
    NOT the amount sign. Amounts may always be positive with type indicating direction.
    
    Args:
        description: Transaction description
        amount: Transaction amount (can be positive or negative)
        txn_type: Transaction type - 'debit' or 'credit' (preferred over amount sign)
    
    Returns:
        True if this matches lender keywords and is a debit
    """
    if not description:
        return False
    
    # Determine if this is a debit (outflow)
    is_debit = False
    if txn_type:
        # Prefer using type field
        is_debit = txn_type.lower() == 'debit'
    elif amount is not None:
        # Fallback to amount sign
        is_debit = safe_float(amount) < 0
    
    if not is_debit:
        return False
    
    desc_lower = description.lower()
    
    for keyword in KNOWN_LENDER_KEYWORDS:
        if keyword in desc_lower:
            return True
    
    return False


def is_payment_category_debit(txn: Dict) -> bool:
    """
    Check if a transaction is a payment-category debit.
    
    NEW RULE: Include ALL payment-category debits in total_monthly_payments,
    regardless of lender_payment flag.
    
    Args:
        txn: Transaction dict with type, category, amount fields
    
    Returns:
        True if this should count toward total_monthly_payments
    """
    txn_type = str(txn.get('type', '')).lower()
    category = str(txn.get('category', '')).lower()
    amount = safe_float(txn.get('amount', 0))
    
    # Determine if it's a debit using type field OR amount sign
    is_debit = False
    if txn_type == 'debit':
        is_debit = True
    elif txn_type == 'credit':
        is_debit = False
    else:
        # Fallback to amount sign if no type field
        is_debit = amount < 0
    
    # Count if it's a payment-category debit
    if is_debit and category in ['payment', 'debit', 'withdrawal']:
        return True
    
    # Also count if it's flagged as a lender payment
    if is_debit and txn.get('lender_payment', False):
        return True
    
    return False


def find_inter_account_transfers(
    transactions: List[Dict],
    window_days: int = 2,
    known_account_numbers: Optional[List[str]] = None,
    merchant_name: Optional[str] = None
) -> List[Dict]:
    """
    Identify inter-account transfers using the Transfer Hunter algorithm.
    
    Logic:
    - Find Transaction_A: Amount = -X, Date = T, Account = 1
    - Find Transaction_B: Amount = +X, Date = T +/- window_days, Account = 2
    - Mark both as is_internal_transfer = True
    
    Args:
        transactions: List of transaction dicts with keys:
            - id, amount, transaction_date, source_account_id, description
        window_days: Number of days +/- to search for matching transactions
    
    Returns:
        Updated list of transactions with is_internal_transfer flags
    """
    if not transactions:
        return []
    
    # Convert to DataFrame for easier analysis
    df = pd.DataFrame(transactions)
    
    # Ensure we have required columns
    required_cols = ['id', 'amount', 'transaction_date', 'source_account_id']
    for col in required_cols:
        if col not in df.columns:
            print(f"Warning: Required column '{col}' not found in transactions")
            return transactions
    
    # Convert amount column to float (handling string amounts like "$1,234.56")
    df['amount'] = df['amount'].apply(safe_float)
    
    # Convert date strings to datetime if needed
    if df['transaction_date'].dtype == 'object':
        df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
    
    # Initialize transfer flags and lender flags
    df['is_internal_transfer'] = False
    df['matched_transfer_id'] = None
    df['is_lender_payment'] = False
    df['transfer_reason'] = None
    df['user_override'] = False  # For UI toggle functionality
    
    # Sort by date for efficient matching
    df = df.sort_values('transaction_date')
    
    # Track matched transactions to avoid double-matching
    matched_ids = set()
    
    # STEP 1: First, identify explicit internal transfers based on description
    # NEW RULE: Only exclude deposits if description EXPLICITLY says it's internal
    for idx, row in df.iterrows():
        description = row.get('description', '')
        amount = row['amount']
        txn_type = str(row.get('type', '')).lower() if 'type' in row else None
        
        # Check if this is an EXPLICIT internal transfer
        if is_explicit_internal_transfer(description, known_account_numbers):
            df.at[idx, 'is_internal_transfer'] = True
            df.at[idx, 'transfer_reason'] = 'explicit_transfer_description'
            matched_ids.add(row['id'])
        
        # Check if this is a lender payment (debit matching known lender keywords)
        # Pass type field to properly handle positive amounts with type='debit'
        if is_known_lender_payment(description, amount, txn_type):
            df.at[idx, 'is_lender_payment'] = True
    
    # STEP 2: Find amount-matched transfers between different accounts
    # BUT only mark as transfer if it's not a related entity revenue
    for idx, row in df.iterrows():
        if row['id'] in matched_ids:
            continue
        
        amount = row['amount']
        date = row['transaction_date']
        account = row['source_account_id']
        description = row.get('description', '')
        
        # Look for opposite amount in different account within window
        target_amount = -amount
        date_min = date - timedelta(days=window_days)
        date_max = date + timedelta(days=window_days)
        
        # Find potential matches
        matches = df[
            (df['id'] != row['id']) &
            (df['id'].isin(matched_ids) == False) &
            (df['source_account_id'] != account) &
            (df['amount'].between(target_amount * 0.99, target_amount * 1.01)) &
            (df['transaction_date'] >= date_min) &
            (df['transaction_date'] <= date_max)
        ]
        
        if len(matches) > 0:
            # Take the closest match by date
            matches_copy = matches.copy()
            matches_copy['date_diff'] = (matches_copy['transaction_date'] - date).abs()
            best_match = matches_copy.sort_values('date_diff').iloc[0]
            
            # NEW RULE: Check if this is a related entity transfer (should be revenue)
            sender_name = description  # In bank statements, description often contains sender
            
            if is_related_entity_revenue(sender_name, merchant_name or '', description):
                # This is revenue from a related entity, NOT an internal transfer
                df.at[idx, 'transfer_reason'] = 'related_entity_revenue'
                continue
            
            # Check if the matched transaction description indicates explicit transfer
            match_desc = best_match.get('description', '')
            if is_explicit_internal_transfer(description, known_account_numbers) or \
               is_explicit_internal_transfer(match_desc, known_account_numbers):
                # Mark both transactions as internal transfers
                df.at[idx, 'is_internal_transfer'] = True
                df.at[idx, 'matched_transfer_id'] = best_match['id']
                df.at[idx, 'transfer_reason'] = 'matched_amount_explicit'
                
                match_idx = df[df['id'] == best_match['id']].index[0]
                df.at[match_idx, 'is_internal_transfer'] = True
                df.at[match_idx, 'matched_transfer_id'] = row['id']
                df.at[match_idx, 'transfer_reason'] = 'matched_amount_explicit'
                
                matched_ids.add(row['id'])
                matched_ids.add(best_match['id'])
    
    # Convert back to list of dicts
    result = df.to_dict('records')
    return result

def calculate_revenue_excluding_transfers(transactions: List[Dict]) -> float:
    """
    Calculate total revenue excluding internal transfers.
    
    Args:
        transactions: List of transaction dicts
    
    Returns:
        Total revenue (sum of credits excluding internal transfers)
    """
    total_revenue = 0.0
    
    for txn in transactions:
        # Only count credits (positive amounts) - safely convert to float
        amount = safe_float(txn.get('amount', 0))
        if amount > 0:
            # Exclude internal transfers
            if not txn.get('is_internal_transfer', False):
                total_revenue += amount
    
    return total_revenue

def get_transfer_summary(transactions: List[Dict]) -> Dict:
    """
    Generate summary statistics about detected transfers.
    
    Returns:
        Dict with transfer statistics
    """
    total_transfers = sum(1 for txn in transactions if txn.get('is_internal_transfer', False))
    transfer_amount = sum(abs(safe_float(txn.get('amount', 0))) for txn in transactions if txn.get('is_internal_transfer', False))
    
    # Get unique transfer pairs
    transfer_pairs = set()
    for txn in transactions:
        if txn.get('is_internal_transfer', False) and txn.get('matched_transfer_id'):
            pair = tuple(sorted([txn['id'], txn['matched_transfer_id']]))
            transfer_pairs.add(pair)
    
    return {
        'total_transfer_transactions': total_transfers,
        'unique_transfer_pairs': len(transfer_pairs),
        'total_transfer_amount': transfer_amount / 2,  # Divide by 2 since we count both sides
        'transfer_details': [
            {
                'id': txn['id'],
                'date': txn.get('transaction_date'),
                'amount': txn.get('amount'),
                'account': txn.get('source_account_id'),
                'description': txn.get('description', ''),
                'matched_with': txn.get('matched_transfer_id'),
                'transfer_reason': txn.get('transfer_reason', ''),
                'user_override': txn.get('user_override', False)
            }
            for txn in transactions if txn.get('is_internal_transfer', False)
        ]
    }


def calculate_revenue_with_overrides(transactions: List[Dict], overrides: Optional[Dict] = None) -> Dict:
    """
    Calculate revenue with user override support.
    
    Args:
        transactions: List of transaction dicts
        overrides: Dict mapping transaction IDs to include_in_revenue boolean
    
    Returns:
        Dict with revenue calculation and breakdown
    """
    overrides = overrides or {}
    
    total_revenue = 0.0
    included_transfers = 0
    excluded_count = 0
    
    revenue_breakdown = []
    
    for txn in transactions:
        amount = safe_float(txn.get('amount', 0))
        txn_id = txn.get('id')
        
        if amount > 0:  # Credit/deposit
            is_transfer = txn.get('is_internal_transfer', False)
            user_override = overrides.get(txn_id, None)
            
            # Determine if we should include in revenue
            if user_override is True:
                # User explicitly wants to include this
                total_revenue += amount
                included_transfers += 1 if is_transfer else 0
                include = True
            elif user_override is False:
                # User explicitly wants to exclude this
                excluded_count += 1
                include = False
            elif is_transfer:
                # Default: exclude internal transfers
                excluded_count += 1
                include = False
            else:
                # Default: include non-transfers
                total_revenue += amount
                include = True
            
            revenue_breakdown.append({
                'id': txn_id,
                'amount': amount,
                'description': txn.get('description', ''),
                'is_transfer': is_transfer,
                'included': include,
                'reason': txn.get('transfer_reason', ''),
                'user_override': user_override
            })
    
    return {
        'total_revenue': total_revenue,
        'excluded_count': excluded_count,
        'included_transfers': included_transfers,
        'breakdown': revenue_breakdown
    }


def cluster_positions_by_merchant(transactions: List[Dict], amount_tolerance: float = 0.03) -> List[Dict]:
    """
    Cluster transactions by merchant name and similar amounts to detect position patterns.
    
    NEW RULE: Group debits by normalized merchant label + amount tolerance (within 3%)
    with cadence detection (daily, weekly, monthly).
    
    Args:
        transactions: List of transaction dicts with type, amount, description, date
        amount_tolerance: Percentage tolerance for grouping similar amounts (0.03 = 3%)
    
    Returns:
        List of detected position clusters
    """
    if not transactions:
        return []
    
    # Group debits by merchant
    merchant_groups = {}
    
    for txn in transactions:
        # Determine if it's a debit
        txn_type = str(txn.get('type', '')).lower()
        amount = safe_float(txn.get('amount', 0))
        
        is_debit = False
        if txn_type == 'debit':
            is_debit = True
            amount = abs(amount)  # Ensure positive for grouping
        elif txn_type == 'credit':
            is_debit = False
        else:
            is_debit = amount < 0
            amount = abs(amount)
        
        if not is_debit or amount == 0:
            continue
        
        description = txn.get('description', '')
        merchant = extract_lender_name(description)
        date = txn.get('transaction_date')
        
        if merchant not in merchant_groups:
            merchant_groups[merchant] = []
        
        merchant_groups[merchant].append({
            'amount': amount,
            'date': date,
            'description': description,
            'lender_payment': txn.get('lender_payment', False)
        })
    
    # Cluster by similar amounts within each merchant
    positions = []
    
    for merchant, txns in merchant_groups.items():
        if len(txns) < 2:
            continue
        
        # Group by similar amounts
        amount_clusters = []
        for txn in txns:
            amt = txn['amount']
            matched = False
            
            for cluster in amount_clusters:
                cluster_amt = cluster['amount']
                if abs(amt - cluster_amt) / max(cluster_amt, 1) <= amount_tolerance:
                    cluster['transactions'].append(txn)
                    matched = True
                    break
            
            if not matched:
                amount_clusters.append({
                    'amount': amt,
                    'transactions': [txn]
                })
        
        # Create positions from clusters
        for cluster in amount_clusters:
            if len(cluster['transactions']) < 2:
                continue
            
            frequency = detect_payment_frequency(cluster['transactions'])
            amount = cluster['amount']
            
            if frequency == 'daily':
                monthly_payment = amount * 22
            elif frequency == 'weekly':
                monthly_payment = amount * 4.33
            else:
                monthly_payment = amount
            
            positions.append({
                'merchant': merchant,
                'amount': round(amount, 2),
                'frequency': frequency,
                'monthly_payment': round(monthly_payment, 2),
                'count': len(cluster['transactions']),
                'is_lender': any(t.get('lender_payment') for t in cluster['transactions'])
            })
    
    return positions


def detect_lender_positions(
    transactions: List[Dict],
    min_occurrences: int = 2
) -> List[Dict]:
    """
    Detect lender/MCA positions from transactions with STACKING support.
    
    NEW RULE: If a Lender appears with DIFFERENT amounts or frequencies
    in the same month, list BOTH as separate active positions (stacking).
    
    Only consolidate to one position if a "Payoff" deposit is detected.
    
    IMPORTANT: Uses 'type' field to determine debits, NOT amount sign.
    
    Args:
        transactions: List of transaction dicts
        min_occurrences: Minimum occurrences to consider it a position
    
    Returns:
        List of detected positions with stacking info
    """
    if not transactions:
        return []
    
    # Group debits by lender name and analyze patterns
    lender_transactions = {}
    
    for txn in transactions:
        amount = safe_float(txn.get('amount', 0))
        description = txn.get('description', '')
        date = txn.get('transaction_date')
        txn_type = str(txn.get('type', '')).lower()
        
        # Determine if this is a debit - use type field preferentially
        is_debit = False
        if txn_type == 'debit':
            is_debit = True
            amount = abs(amount)
        elif txn_type == 'credit':
            is_debit = False
        else:
            # Fallback to amount sign
            is_debit = amount < 0
            amount = abs(amount)
        
        if not is_debit:
            continue
        
        # Check if this matches lender keywords (passing type for proper detection)
        if not is_known_lender_payment(description, amount, txn_type or ('debit' if is_debit else 'credit')):
            continue
        
        # Extract lender name from description
        lender_name = extract_lender_name(description)
        
        if lender_name not in lender_transactions:
            lender_transactions[lender_name] = []
        
        lender_transactions[lender_name].append({
            'amount': amount,
            'date': date,
            'description': description
        })
    
    # Analyze each lender for stacking
    positions = []
    
    for lender_name, txns in lender_transactions.items():
        if len(txns) < min_occurrences:
            continue
        
        # Group by unique amounts to detect stacking
        amount_groups = {}
        for txn in txns:
            amt = round(txn['amount'], 2)
            if amt not in amount_groups:
                amount_groups[amt] = []
            amount_groups[amt].append(txn)
        
        # Detect frequency for each amount group
        for amount, group_txns in amount_groups.items():
            if len(group_txns) < min_occurrences:
                continue
            
            frequency = detect_payment_frequency(group_txns)
            
            # Calculate monthly payment equivalent
            if frequency == 'daily':
                monthly_payment = amount * 22  # ~22 business days
            elif frequency == 'weekly':
                monthly_payment = amount * 4.33
            else:
                monthly_payment = amount
            
            positions.append({
                'lender_name': lender_name,
                'amount': amount,
                'frequency': frequency,
                'monthly_payment': round(monthly_payment, 2),
                'occurrence_count': len(group_txns),
                'is_stacked': len(amount_groups) > 1,
                'stack_count': len(amount_groups)
            })
    
    return positions


def extract_lender_name(description: str) -> str:
    """Extract lender name from transaction description."""
    if not description:
        return "Unknown Lender"
    
    # Common prefixes to remove
    prefixes = ['ach debit', 'ach credit', 'wire', 'transfer', 'payment to', 'payment from']
    
    desc_lower = description.lower().strip()
    
    for prefix in prefixes:
        if desc_lower.startswith(prefix):
            desc_lower = desc_lower[len(prefix):].strip()
    
    # Take first significant portion
    words = desc_lower.split()
    significant_words = [w for w in words[:4] if len(w) > 2]
    
    if significant_words:
        return ' '.join(significant_words).title()
    
    return description[:30]


def detect_payment_frequency(transactions: List[Dict]) -> str:
    """
    Detect payment frequency from transaction dates.
    
    Returns: 'daily', 'weekly', or 'monthly'
    """
    if len(transactions) < 2:
        return 'monthly'
    
    # Sort by date
    sorted_txns = sorted(transactions, key=lambda x: x.get('date') or '')
    
    # Calculate average days between payments
    total_days = 0
    count = 0
    
    for i in range(1, len(sorted_txns)):
        date1 = sorted_txns[i-1].get('date')
        date2 = sorted_txns[i].get('date')
        
        if date1 and date2:
            try:
                if isinstance(date1, str):
                    date1 = pd.to_datetime(date1)
                if isinstance(date2, str):
                    date2 = pd.to_datetime(date2)
                
                days_diff = abs((date2 - date1).days)
                if days_diff > 0:
                    total_days += days_diff
                    count += 1
            except:
                pass
    
    if count == 0:
        return 'monthly'
    
    avg_days = total_days / count
    
    if avg_days <= 2:
        return 'daily'
    elif avg_days <= 10:
        return 'weekly'
    else:
        return 'monthly'


def check_for_payoff(
    transactions: List[Dict],
    lender_name: str
) -> bool:
    """
    Check if there's a payoff deposit for a lender.
    
    If found, it suggests the position was refinanced/paid off
    and shouldn't be stacked with new position.
    
    Args:
        transactions: List of all transactions
        lender_name: Name of the lender to check
    
    Returns:
        True if payoff detected
    """
    lender_lower = lender_name.lower()
    
    for txn in transactions:
        amount = safe_float(txn.get('amount', 0))
        description = txn.get('description', '').lower()
        
        # Look for credits (payoffs) mentioning this lender
        if amount > 0:
            if lender_lower in description:
                # Check for payoff keywords
                payoff_keywords = ['payoff', 'pay off', 'refund', 'settlement', 'paid in full']
                for keyword in payoff_keywords:
                    if keyword in description:
                        return True
    
    return False
