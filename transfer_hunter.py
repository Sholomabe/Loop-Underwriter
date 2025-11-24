import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

def find_inter_account_transfers(
    transactions: List[Dict],
    window_days: int = 2
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
    
    # Convert date strings to datetime if needed
    if df['transaction_date'].dtype == 'object':
        df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
    
    # Initialize transfer flags
    df['is_internal_transfer'] = False
    df['matched_transfer_id'] = None
    
    # Sort by date for efficient matching
    df = df.sort_values('transaction_date')
    
    # Track matched transactions to avoid double-matching
    matched_ids = set()
    
    # Iterate through transactions to find matches
    for idx, row in df.iterrows():
        if row['id'] in matched_ids:
            continue
        
        amount = row['amount']
        date = row['transaction_date']
        account = row['source_account_id']
        
        # Look for opposite amount in different account within window
        # If current is debit (-X), look for credit (+X) in another account
        target_amount = -amount
        date_min = date - timedelta(days=window_days)
        date_max = date + timedelta(days=window_days)
        
        # Find potential matches
        matches = df[
            (df['id'] != row['id']) &
            (df['id'].isin(matched_ids) == False) &
            (df['source_account_id'] != account) &
            (df['amount'].between(target_amount * 0.99, target_amount * 1.01)) &  # Allow 1% tolerance
            (df['transaction_date'] >= date_min) &
            (df['transaction_date'] <= date_max)
        ]
        
        if len(matches) > 0:
            # Take the closest match by date
            matches['date_diff'] = (matches['transaction_date'] - date).abs()
            best_match = matches.sort_values('date_diff').iloc[0]
            
            # Mark both transactions as internal transfers
            df.at[idx, 'is_internal_transfer'] = True
            df.at[idx, 'matched_transfer_id'] = best_match['id']
            
            match_idx = df[df['id'] == best_match['id']].index[0]
            df.at[match_idx, 'is_internal_transfer'] = True
            df.at[match_idx, 'matched_transfer_id'] = row['id']
            
            # Mark as matched
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
        # Only count credits (positive amounts)
        if txn.get('amount', 0) > 0:
            # Exclude internal transfers
            if not txn.get('is_internal_transfer', False):
                total_revenue += txn['amount']
    
    return total_revenue

def get_transfer_summary(transactions: List[Dict]) -> Dict:
    """
    Generate summary statistics about detected transfers.
    
    Returns:
        Dict with transfer statistics
    """
    total_transfers = sum(1 for txn in transactions if txn.get('is_internal_transfer', False))
    transfer_amount = sum(abs(txn.get('amount', 0)) for txn in transactions if txn.get('is_internal_transfer', False))
    
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
                'matched_with': txn.get('matched_transfer_id')
            }
            for txn in transactions if txn.get('is_internal_transfer', False)
        ]
    }
