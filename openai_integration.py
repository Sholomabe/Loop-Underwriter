import os
import json
import base64
import re
from typing import Dict, List, Optional, Tuple, Any
from openai import OpenAI
from PIL import Image
import io

# This is using Replit's AI Integrations service, which provides OpenAI-compatible API access
# without requiring your own OpenAI API key. Charges are billed to your Replit credits.
AI_INTEGRATIONS_OPENAI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
AI_INTEGRATIONS_OPENAI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")

openai = OpenAI(
    api_key=AI_INTEGRATIONS_OPENAI_API_KEY,
    base_url=AI_INTEGRATIONS_OPENAI_BASE_URL
)

# =============================================================================
# SMART MCA DETECTION SYSTEM
# 3-Layer approach: Whitelist → Blacklist → Pattern Detection
# =============================================================================

# LAYER 1: MCA WHITELIST - Known MCA lenders (always flag as MCA)
# These are confirmed MCA/merchant cash advance companies
MCA_WHITELIST = [
    # User-confirmed MCA lenders from training
    "FORA FINANCIAL", "FORAFINANCIAL", "FORA FIN",
    "SPARTAN CAP", "SPARTAN CAPITAL",
    "EBF HOLDINGS", "EBF HOLDINGS EBF", "EBF DEBIT",
    "MCA SERVICING", "MCA SERVICE", "MCA SERVIC",
    "LENDR", "LENDR 190", "LENDR 180", "LENDR CAPITAL",
    "FOX", "FOX 180", "FOX 190", "FOX CAPITAL", "FOX FUNDING",
    "SECUREACCOUNT", "SECUREACCOUNTSER", "SECURE ACCOUNT",
    
    # Well-known MCA lenders
    "CREDIBLY", "CREDIBLY FUND",
    "ONDECK", "ON DECK", "ONDECK CAPITAL",
    "CAN CAPITAL", "CANCAPITAL",
    "HEADWAY CAPITAL", "HEADWAY",
    "KALAMATA", "KALAMATA CAPITAL",
    "LIBERTAS", "LIBERTAS FUNDING",
    "YELLOWSTONE", "YELLOWSTONE CAPITAL",
    "CLEARVIEW", "CLEARVIEW FUNDING",
    "BIZFUND", "BIZ FUND", "BIZ2CREDIT",
    "RAPID ADVANCE", "RAPID CAPITAL", "RAPIDADVANCE",
    "MERCHANT CASH", "MERCHANT ADVANCE",
    "FORWARD FINANCING", "FORWARD FIN",
    "KING TRADE", "KINGTRADE",
    "LENDISTRY",
    "FUNDBOX",
    "BLUEVINE", "BLUE VINE",
    "KABBAGE",
    "PAYABILITY",
    "BEHALF",
    "NATIONAL FUNDING", "NATIONALFUNDING",
    "RELIANT FUNDING", "RELIANTFUNDING",
    "UNITED CAPITAL", "UNITED CAP SOURCE",
    "PEARL CAPITAL", "PEARLCAPITAL",
    "GREEN CAPITAL", "GREENCAPITAL",
    "WORLD BUSINESS", "WORLD BUS LENDERS",
    "CFG MERCHANT", "CFG",
    "SQUARE CAPITAL", "SQ CAPITAL",
    "SHOPIFY CAPITAL",
    "AMAZON LENDING",
    "PAYPAL WORKING", "PAYPAL LOAN",
    "STRIPE CAPITAL",
    
    # Additional common MCA lenders
    "ACH DAILY", "ACH WEEKLY",
    "EVEREST BUSINESS", "EVEREST FUNDING",
    "TITAN FUNDING", "TITAN CAPITAL",
    "VELOCITY CAPITAL", "VELOCITY FUNDING",
    "SWIFT CAPITAL", "SWIFTCAPITAL",
    "FIRST CAPITAL", "1ST CAPITAL",
    "BUSINESS BACKER", "BUSINESSBACKER",
    "SNAP ADVANCE", "SNAPADVANCE",
    "MERCHANT ADVANCE", "MERCHANT FUNDING",
]

# LAYER 2: MCA BLACKLIST - Known false positives (never flag as MCA)
# These contain MCA-like keywords but are NOT MCAs
MCA_BLACKLIST = [
    # Credit cards (contain "CAPITAL" but are cards, not MCA)
    "CAPITAL ONE", "CAPITALONE", "CAP ONE",
    
    # Business loans/financing (not MCA structure)
    "INTUIT FINANCING", "INTUIT FIN", "QUICKBOOKS",
    "WEBBANK", "WEB BANK",
    "SOFI", "SOFI LENDING",
    "LENDING CLUB", "LENDINGCLUB",
    "PROSPER",
    "UPSTART",
    
    # Credit card companies
    "AMERICAN EXPRESS", "AMEX",
    "DISCOVER", "DISCOVER CARD",
    "CHASE CARD", "CHASE CREDIT",
    "VISA", "MASTERCARD",
    "SYNCHRONY",
    "CITI CARD", "CITICARD",
    "BARCLAYS",
    "BANK OF AMERICA", "BOFA",
    
    # Insurance companies
    "PROGRESSIVE", "STATE FARM", "ALLSTATE", "GEICO", "LIBERTY MUTUAL",
    "UTICA", "AMTRUST", "NATIONWIDE", "FARMERS", "TRAVELERS",
    "HARTFORD", "ERIE INSURANCE",
    
    # Payroll / HR
    "ADP", "PAYCHEX", "GUSTO", "PAYLOCITY", "PAYROLL",
    
    # Utilities
    "ELECTRIC", "GAS COMPANY", "WATER COMPANY", "UTILITY",
    "COMCAST", "VERIZON", "ATT", "AT&T", "TMOBILE", "T-MOBILE",
    
    # Common business expenses
    "RENT", "LEASE", "LANDLORD",
    "AMAZON PURCHASE", "AMAZON PRIME", "AMAZON ORDER",
    "OFFICE DEPOT", "STAPLES",
    "HOME DEPOT", "LOWES",
]

# LAYER 3: Pattern-based keywords (used with pattern detection)
# Generic keywords that MIGHT indicate MCA - require pattern validation
MCA_PATTERN_KEYWORDS = [
    "CAPITAL", "FUNDING", "ADVANCE", "FINANCING", "FUNDER",
    "DAILY ACH", "ACH DEBIT", "FACTOR", "FACTORING",
]

# Operating Expense Keywords - These go to "Other Liabilities", NOT Positions
OPERATING_EXPENSE_KEYWORDS = [
    "DISCOVER", "AMEX", "AMERICAN EXPRESS", "CHASE CARD", "CHASE CREDIT",
    "INSURANCE", "UTICA", "AMTRUST", "VISA", "MASTERCARD",
    "PROGRESSIVE", "STATE FARM", "ALLSTATE", "GEICO", "LIBERTY MUTUAL",
    "CREDIT CARD", "CARD SERVICES", "CAPITAL ONE", "INTUIT"
]

# Legacy compatibility - combine whitelist for simple matching
MCA_KEYWORDS = MCA_WHITELIST + MCA_PATTERN_KEYWORDS


def is_mca_whitelist(description: str) -> bool:
    """Check if transaction matches a known MCA lender (definite MCA)."""
    desc_upper = description.upper()
    return any(lender in desc_upper for lender in MCA_WHITELIST)


def is_mca_whitelist_fuzzy(description: str, threshold: int = 80) -> Tuple[bool, Optional[str], int]:
    """
    Check if transaction fuzzy-matches a known MCA lender.
    Uses fuzzywuzzy for approximate string matching.
    
    Args:
        description: Transaction description to check
        threshold: Minimum similarity score (0-100) to consider a match
        
    Returns:
        Tuple of (is_match, matched_lender, similarity_score)
    """
    try:
        from fuzzywuzzy import fuzz
    except ImportError:
        return (False, None, 0)
    
    desc_upper = description.upper()
    
    # First check exact match (fast path)
    for lender in MCA_WHITELIST:
        if lender in desc_upper:
            return (True, lender, 100)
    
    # Try fuzzy matching
    best_match = None
    best_score = 0
    
    for lender in MCA_WHITELIST:
        # Use token_set_ratio for better matching of partial strings
        score = fuzz.token_set_ratio(lender, desc_upper)
        if score > best_score:
            best_score = score
            best_match = lender
    
    if best_score >= threshold:
        return (True, best_match, best_score)
    
    return (False, None, best_score)


def get_learned_mca_patterns() -> List[str]:
    """
    Load learned MCA patterns from the database (GoldStandard_Rules).
    Returns a list of merchant names/patterns that have been identified as MCA.
    """
    learned_patterns = []
    try:
        from database import get_db
        from models import GoldStandardRule
        
        with get_db() as db:
            rules = db.query(GoldStandardRule).filter(
                GoldStandardRule.rule_type == 'mca_vendor'
            ).all()
            
            for rule in rules:
                if rule.rule_pattern:
                    learned_patterns.append(rule.rule_pattern.upper())
    except Exception:
        pass
    
    return learned_patterns


def is_mca_learned(description: str, threshold: int = 80) -> Tuple[bool, Optional[str], int]:
    """
    Check if transaction matches a learned MCA pattern from training.
    Uses fuzzy matching against patterns stored in GoldStandard_Rules.
    
    Args:
        description: Transaction description to check
        threshold: Minimum similarity score (0-100) to consider a match
        
    Returns:
        Tuple of (is_match, matched_pattern, similarity_score)
    """
    learned_patterns = get_learned_mca_patterns()
    if not learned_patterns:
        return (False, None, 0)
    
    try:
        from fuzzywuzzy import fuzz
    except ImportError:
        # Fallback to exact match
        desc_upper = description.upper()
        for pattern in learned_patterns:
            if pattern in desc_upper:
                return (True, pattern, 100)
        return (False, None, 0)
    
    desc_upper = description.upper()
    
    # First check exact match (fast path)
    for pattern in learned_patterns:
        if pattern in desc_upper:
            return (True, pattern, 100)
    
    # Try fuzzy matching
    best_match = None
    best_score = 0
    
    for pattern in learned_patterns:
        score = fuzz.token_set_ratio(pattern, desc_upper)
        if score > best_score:
            best_score = score
            best_match = pattern
    
    if best_score >= threshold:
        return (True, best_match, best_score)
    
    return (False, None, best_score)


def save_mca_to_learned(vendor_name: str, source: str = 'training') -> Tuple[bool, bool]:
    """
    Save a newly identified MCA vendor to the database for future matching.
    
    Args:
        vendor_name: Name of the MCA vendor to save
        source: Where this pattern was learned from
        
    Returns:
        Tuple of (success, is_new): 
        - success: True if operation succeeded (saved or already exists)
        - is_new: True if this was a new pattern, False if it already existed
    """
    try:
        from database import get_db
        from models import GoldStandardRule
        from datetime import datetime
        
        with get_db() as db:
            # Check if already exists
            existing = db.query(GoldStandardRule).filter(
                GoldStandardRule.rule_type == 'mca_vendor',
                GoldStandardRule.rule_pattern == vendor_name.upper()
            ).first()
            
            if existing:
                return (True, False)  # Already exists - success but not new
            
            rule = GoldStandardRule(
                rule_pattern=vendor_name.upper(),
                rule_type='mca_vendor',
                original_classification='unknown',
                correct_classification='mca_position',
                confidence_score=1.0,
                context_json={'source': source, 'added_by': 'auto_learning'},
                created_at=datetime.utcnow()
            )
            db.add(rule)
            db.commit()
            return (True, True)  # Saved successfully and is new
    except Exception as e:
        print(f"Error saving MCA pattern: {e}")
        return (False, False)


def is_mca_blacklist(description: str) -> bool:
    """Check if transaction matches a known false positive (definitely NOT MCA)."""
    desc_upper = description.upper()
    return any(excluded in desc_upper for excluded in MCA_BLACKLIST)


def has_mca_pattern_keyword(description: str) -> bool:
    """Check if transaction has generic MCA-like keywords (needs pattern validation)."""
    desc_upper = description.upper()
    return any(kw in desc_upper for kw in MCA_PATTERN_KEYWORDS)


def is_mca_position(description: str, transactions: Optional[list] = None, 
                    use_fuzzy: bool = True, fuzzy_threshold: int = 80) -> bool:
    """
    Smart MCA detection using 4-layer logic with fuzzy matching:
    1. Check whitelist first (known MCA lenders) → True
    2. Check learned patterns from training → True  
    3. Check blacklist (known false positives) → False
    4. Check pattern keywords + validate with transaction data → True only if pattern validates
    5. Fuzzy match against whitelist if enabled → True if high similarity
    
    Args:
        description: Transaction description to check
        transactions: Optional list of transactions for pattern validation
                     (required for Layer 4 pattern-based detection)
        use_fuzzy: Whether to use fuzzy matching (default True)
        fuzzy_threshold: Minimum similarity score for fuzzy match (0-100)
    
    Returns:
        True if definitely or likely MCA, False otherwise
    """
    # Layer 1: Whitelist - definite MCA (exact match)
    if is_mca_whitelist(description):
        return True
    
    # Layer 2: Learned patterns from training (exact or fuzzy)
    is_learned, _, _ = is_mca_learned(description, threshold=fuzzy_threshold)
    if is_learned:
        return True
    
    # Layer 3: Blacklist - definite NOT MCA
    if is_mca_blacklist(description):
        return False
    
    # Layer 4: Fuzzy match against whitelist
    if use_fuzzy:
        is_fuzzy_match, _, score = is_mca_whitelist_fuzzy(description, threshold=fuzzy_threshold)
        if is_fuzzy_match:
            return True
    
    # Layer 5: Pattern keywords - ONLY flag as MCA if transaction pattern validates
    # This prevents false positives like "CAPITAL EQUIPMENT LEASE"
    if has_mca_pattern_keyword(description):
        # If we have transaction data, validate the pattern
        if transactions and is_likely_mca_pattern(transactions):
            return True
        # Without transaction data, be conservative - don't assume it's MCA
        return False
    
    return False


def is_mca_position_simple(description: str) -> bool:
    """
    Simple MCA detection using only whitelist/blacklist (no pattern validation).
    Use this when you don't have transaction history available.
    
    Returns True ONLY for known MCA lenders (whitelist).
    Returns False for blacklisted merchants and unknown merchants.
    """
    if is_mca_whitelist(description):
        return True
    return False


def is_likely_mca_pattern(transactions: list, min_payments: int = 10, 
                          amount_variance_threshold: float = 0.15) -> bool:
    """
    Analyze transaction patterns to determine if they look like MCA payments.
    
    MCA characteristics:
    - Regular frequency (daily Mon-Fri or weekly)
    - Consistent amounts (low variance)
    - Multiple payments over time
    - Typical amount range ($100-$2,000 daily, $500-$10,000 weekly)
    
    Args:
        transactions: List of dicts with 'amount' and optionally 'date'
        min_payments: Minimum number of payments to consider as MCA pattern
        amount_variance_threshold: Max coefficient of variation for amounts
        
    Returns:
        True if pattern looks like MCA payments
    """
    if len(transactions) < min_payments:
        return False
    
    amounts = [abs(t.get('amount', 0)) for t in transactions if t.get('amount')]
    if not amounts:
        return False
    
    avg_amount = sum(amounts) / len(amounts)
    
    # Check amount range (typical MCA: $100-$2,500 per payment)
    if avg_amount < 50 or avg_amount > 5000:
        return False
    
    # Check amount consistency (MCA payments are usually very consistent)
    if avg_amount > 0:
        variance = sum((a - avg_amount) ** 2 for a in amounts) / len(amounts)
        std_dev = variance ** 0.5
        coef_variation = std_dev / avg_amount
        
        if coef_variation > amount_variance_threshold:
            return False
    
    return True


def is_operating_expense(description: str) -> bool:
    """Check if a transaction description matches operating expense keywords."""
    desc_upper = description.upper()
    return any(kw in desc_upper for kw in OPERATING_EXPENSE_KEYWORDS)


def classify_position(description: str, transactions: Optional[list] = None) -> str:
    """
    Classify a debit using smart 3-layer MCA detection.
    Returns 'mca_position' only if it's a known MCA or matches validated patterns.
    
    Args:
        description: Transaction description
        transactions: Optional list of transactions for pattern validation
    
    Returns:
        'mca_position' - Known MCA lender or validated MCA pattern
        'operating_expense' - Blacklisted/known operating expense
        'other' - Unknown or unvalidated pattern keyword match
    """
    # First check blacklist/operating expenses
    if is_mca_blacklist(description) or is_operating_expense(description):
        return 'operating_expense'
    
    # Check whitelist (definite MCA)
    if is_mca_whitelist(description):
        return 'mca_position'
    
    # Check pattern keywords with validation
    if has_mca_pattern_keyword(description):
        # If we have transaction data, validate the pattern
        if transactions and is_likely_mca_pattern(transactions):
            return 'mca_position'
        # Without validation, mark as 'potential_mca' for review
        return 'potential_mca'
    
    return 'other'


def get_mca_confidence(description: str, transactions: Optional[list] = None) -> dict:
    """
    Get MCA detection confidence with reasoning.
    
    Returns:
        dict with 'is_mca', 'confidence', 'reason', 'layer'
    """
    desc_upper = description.upper()
    
    # Layer 1: Whitelist
    if is_mca_whitelist(description):
        matched = [l for l in MCA_WHITELIST if l in desc_upper][0]
        return {
            'is_mca': True,
            'confidence': 'high',
            'reason': f'Known MCA lender: {matched}',
            'layer': 'whitelist'
        }
    
    # Layer 2: Blacklist
    if is_mca_blacklist(description):
        matched = [b for b in MCA_BLACKLIST if b in desc_upper][0]
        return {
            'is_mca': False,
            'confidence': 'high',
            'reason': f'Known non-MCA (blacklisted): {matched}',
            'layer': 'blacklist'
        }
    
    # Layer 3: Pattern detection
    if has_mca_pattern_keyword(description):
        matched = [k for k in MCA_PATTERN_KEYWORDS if k in desc_upper][0]
        
        # If we have transaction data, validate the pattern
        if transactions and is_likely_mca_pattern(transactions):
            return {
                'is_mca': True,
                'confidence': 'medium',
                'reason': f'Pattern keyword "{matched}" + MCA-like payment pattern',
                'layer': 'pattern'
            }
        elif transactions:
            return {
                'is_mca': False,
                'confidence': 'low',
                'reason': f'Has keyword "{matched}" but payment pattern not MCA-like',
                'layer': 'pattern'
            }
        else:
            # Without transaction data, be conservative - don't assume it's MCA
            return {
                'is_mca': False,
                'confidence': 'low',
                'reason': f'Has keyword "{matched}" but no transaction data to validate pattern',
                'layer': 'pattern'
            }
    
    return {
        'is_mca': False,
        'confidence': 'high',
        'reason': 'No MCA indicators found',
        'layer': 'none'
    }


# PDF Chunking Configuration
CHUNK_SIZE = 50000  # Characters per chunk (OpenAI can handle ~100k tokens)
CHUNK_OVERLAP = 2000  # Overlap between chunks to avoid cutting transactions


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """
    Split large text into overlapping chunks for processing.
    
    Args:
        text: Full PDF text
        chunk_size: Maximum characters per chunk
        overlap: Characters to overlap between chunks
        
    Returns:
        List of text chunks
    """
    if len(text) <= chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + chunk_size
        
        if end < len(text):
            newline_pos = text.rfind('\n', start + chunk_size - overlap, end)
            if newline_pos > start:
                end = newline_pos + 1
        
        chunks.append(text[start:end])
        start = end - overlap if end < len(text) else end
    
    return chunks


def merge_extraction_results(results: List[Dict]) -> Dict:
    """
    Merge multiple extraction results from chunked processing.
    
    Combines transactions, positions, and aggregates metrics.
    Uses intelligent deduplication and preserves AI-calculated values.
    
    Args:
        results: List of extraction results from each chunk
        
    Returns:
        Merged extraction result
    """
    if not results:
        return get_default_extraction_result()
    
    if len(results) == 1:
        return results[0]
    
    merged = get_default_extraction_result()
    
    all_transactions = []
    all_daily_positions = []
    all_weekly_positions = []
    all_monthly_positions = []
    all_other_liabilities = []
    all_bank_accounts = {}
    revenues_by_month = {}  # Use max value per month (avoid double-counting)
    all_deductions = {}
    total_nsf = 0
    reasoning_parts = []
    
    # Collect AI-calculated info_needed values from each chunk
    chunk_info_needed = []
    
    for idx, result in enumerate(results):
        if 'transactions' in result:
            all_transactions.extend(result.get('transactions', []))
        
        all_daily_positions.extend(result.get('daily_positions', []))
        all_weekly_positions.extend(result.get('weekly_positions', []))
        all_monthly_positions.extend(result.get('monthly_positions_non_mca', []))
        all_other_liabilities.extend(result.get('other_liabilities', []))
        
        # Collect info_needed from each chunk for later reconciliation
        if 'info_needed' in result:
            chunk_info_needed.append(result['info_needed'])
        
        # Bank accounts - dedupe by month
        for account, data in result.get('bank_accounts', {}).items():
            if account not in all_bank_accounts:
                all_bank_accounts[account] = {'months': []}
            existing_months = {m.get('month') for m in all_bank_accounts[account].get('months', [])}
            for month_data in data.get('months', []):
                if month_data.get('month') not in existing_months:
                    all_bank_accounts[account]['months'].append(month_data)
        
        # Revenues by month - take MAX per month to avoid double-counting overlapping chunks
        for month, revenue in result.get('total_revenues_by_month', {}).items():
            if isinstance(revenue, (int, float)):
                if month not in revenues_by_month:
                    revenues_by_month[month] = revenue
                else:
                    # Take max to handle chunk overlap
                    revenues_by_month[month] = max(revenues_by_month[month], revenue)
        
        # Deductions - similar max approach
        for account, months in result.get('deductions', {}).items():
            if account not in all_deductions:
                all_deductions[account] = {}
            for month, amount in months.items():
                if isinstance(amount, (int, float)):
                    if month not in all_deductions[account]:
                        all_deductions[account][month] = amount
                    else:
                        all_deductions[account][month] = max(all_deductions[account][month], amount)
        
        total_nsf += result.get('nsf_count', 0)
        
        if result.get('reasoning'):
            reasoning_parts.append(f"[Chunk {idx+1}]: {result.get('reasoning')}")
    
    # Dedupe transactions by date+description+amount
    seen_txn_keys = set()
    unique_transactions = []
    for txn in all_transactions:
        key = (txn.get('date', ''), txn.get('description', ''), txn.get('amount', 0))
        if key not in seen_txn_keys:
            seen_txn_keys.add(key)
            unique_transactions.append(txn)
    
    def dedupe_positions(positions: List[Dict]) -> List[Dict]:
        seen = set()
        unique = []
        for p in positions:
            # Use name + amount as key (allow same lender with different amounts = stacking)
            key = (p.get('name', '').upper(), round(p.get('amount', 0), 2))
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique
    
    merged['transactions'] = unique_transactions
    merged['daily_positions'] = dedupe_positions(all_daily_positions)
    merged['weekly_positions'] = dedupe_positions(all_weekly_positions)
    merged['monthly_positions_non_mca'] = dedupe_positions(all_monthly_positions)
    merged['other_liabilities'] = dedupe_positions(all_other_liabilities)
    merged['bank_accounts'] = all_bank_accounts
    merged['total_revenues_by_month'] = revenues_by_month
    merged['deductions'] = all_deductions
    merged['nsf_count'] = total_nsf
    
    # Calculate monthly payments from deduplicated positions
    total_monthly_payments = sum(
        p.get('monthly_payment', 0) for p in merged['daily_positions']
    ) + sum(
        p.get('monthly_payment', 0) for p in merged['weekly_positions']
    ) + sum(
        p.get('monthly_payment', 0) for p in merged['monthly_positions_non_mca']
    )
    
    # Calculate income from revenues (already deduplicated by month)
    total_revenue = sum(revenues_by_month.values()) if revenues_by_month else 0
    num_months = len(revenues_by_month) if revenues_by_month else 1
    avg_monthly_income = total_revenue / num_months if num_months > 0 else 0
    
    # Aggregate diesel payments from chunk info_needed
    diesel_total = 0
    holdback_pct = 'not_computable'
    monthly_holdback = 0
    
    for info in chunk_info_needed:
        diesel_val = info.get('diesel_total_monthly_payments', 0)
        if isinstance(diesel_val, (int, float)):
            diesel_total += diesel_val
        
        # Take first valid holdback found
        hb = info.get('holdback_percentage')
        if holdback_pct == 'not_computable' and isinstance(hb, (int, float)):
            holdback_pct = hb
        
        mh = info.get('monthly_holdback', 0)
        if isinstance(mh, (int, float)):
            monthly_holdback = max(monthly_holdback, mh)
    
    merged['info_needed'] = {
        'total_monthly_payments': total_monthly_payments,
        'diesel_total_monthly_payments': diesel_total,
        'total_monthly_payments_with_diesel': total_monthly_payments + diesel_total,
        'average_monthly_income': avg_monthly_income if avg_monthly_income > 0 else 'not_computable',
        'annual_income': avg_monthly_income * 12 if avg_monthly_income > 0 else 'not_computable',
        'length_of_deal_months': num_months,
        'holdback_percentage': holdback_pct,
        'monthly_holdback': monthly_holdback,
        'monthly_payment_to_income_pct': (total_monthly_payments / avg_monthly_income * 100) if avg_monthly_income > 0 else 'not_computable',
        'original_balance_to_annual_income_pct': 0
    }
    
    merged['reasoning'] = "\n\n".join(reasoning_parts) if reasoning_parts else "Merged from multiple chunks"
    merged['chunk_count'] = len(results)
    
    return merged


def repair_json(malformed_json: str) -> Tuple[Optional[Dict], str]:
    """
    Attempt to repair malformed JSON from AI responses.
    
    Common issues:
    - Truncated JSON (unclosed brackets/braces)
    - Extra text before/after JSON
    - Invalid escape sequences
    
    Args:
        malformed_json: The potentially broken JSON string
        
    Returns:
        Tuple of (repaired_dict or None, repair_log)
    """
    repair_log = []
    
    # First, try parsing as-is
    try:
        return json.loads(malformed_json), "JSON parsed successfully without repair"
    except json.JSONDecodeError as e:
        repair_log.append(f"Initial parse failed: {e}")
    
    working_json = malformed_json
    
    # Step 1: Extract JSON from markdown code blocks if present
    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', working_json)
    if code_block_match:
        working_json = code_block_match.group(1)
        repair_log.append("Extracted JSON from markdown code block")
    
    # Step 2: Find the outermost JSON object
    first_brace = working_json.find('{')
    if first_brace > 0:
        working_json = working_json[first_brace:]
        repair_log.append(f"Removed {first_brace} chars before first brace")
    
    # Step 3: Count brackets and braces to detect truncation
    open_braces = working_json.count('{')
    close_braces = working_json.count('}')
    open_brackets = working_json.count('[')
    close_brackets = working_json.count(']')
    
    # Step 4: Try to close unclosed structures
    if open_braces > close_braces or open_brackets > close_brackets:
        repair_log.append(f"Detected truncation: {open_braces} {{ vs {close_braces} }}, {open_brackets} [ vs {close_brackets} ]")
        
        # Try to find a valid truncation point (after a complete value)
        # Look for patterns like: ,"key": or ],"key": or },"key":
        truncation_patterns = [
            (r',\s*"[^"]*":\s*$', ''),  # Ends with ,"key":
            (r',\s*"[^"]*":\s*"[^"]*$', '"'),  # Ends mid-string value
            (r',\s*"[^"]*":\s*\d+\.?\d*$', ''),  # Ends with number
            (r',\s*$', ''),  # Ends with comma
        ]
        
        for pattern, suffix in truncation_patterns:
            if re.search(pattern, working_json):
                working_json = re.sub(pattern, suffix, working_json)
                repair_log.append(f"Cleaned truncated ending matching: {pattern}")
                break
        
        # Add missing closing brackets/braces
        missing_brackets = close_brackets - open_brackets
        missing_braces = close_braces - open_braces
        
        # Close arrays first, then objects (reverse order of opening)
        if open_brackets > close_brackets:
            working_json += ']' * (open_brackets - close_brackets)
            repair_log.append(f"Added {open_brackets - close_brackets} closing brackets")
        
        if open_braces > close_braces:
            working_json += '}' * (open_braces - close_braces)
            repair_log.append(f"Added {open_braces - close_braces} closing braces")
    
    # Step 5: Try to parse the repaired JSON
    try:
        result = json.loads(working_json)
        repair_log.append("Successfully parsed repaired JSON")
        return result, "\n".join(repair_log)
    except json.JSONDecodeError as e:
        repair_log.append(f"Repair attempt failed: {e}")
    
    # Step 6: Strip trailing non-JSON text after the last closing brace
    last_brace = working_json.rfind('}')
    if last_brace > 0 and last_brace < len(working_json) - 1:
        trailing_text = working_json[last_brace + 1:].strip()
        if trailing_text and not trailing_text.startswith(','):
            working_json = working_json[:last_brace + 1]
            repair_log.append(f"Stripped trailing non-JSON text: {trailing_text[:50]}...")
            
            # Try parsing after stripping
            try:
                result = json.loads(working_json)
                repair_log.append("Successfully parsed after stripping trailing text")
                return result, "\n".join(repair_log)
            except json.JSONDecodeError:
                pass  # Continue to aggressive repair
    
    # Step 7: Try aggressive repair - find valid JSON subset
    # Use finer-grained steps (10 chars) for better recovery of short truncations
    min_length = min(100, len(working_json) // 2)
    for end_pos in range(len(working_json), min_length, -10):
        test_json = working_json[:end_pos]
        
        # Balance brackets
        ob = test_json.count('{')
        cb = test_json.count('}')
        oq = test_json.count('[')
        cq = test_json.count(']')
        
        test_json += ']' * max(0, oq - cq)
        test_json += '}' * max(0, ob - cb)
        
        try:
            result = json.loads(test_json)
            repair_log.append(f"Found valid JSON subset at position {end_pos}")
            return result, "\n".join(repair_log)
        except:
            continue
    
    repair_log.append("All repair attempts failed")
    return None, "\n".join(repair_log)


def validate_and_sanitize_transactions(transactions: Any) -> List[Dict]:
    """
    Validate and sanitize a transactions list, ensuring all elements are proper dictionaries
    with required fields.
    
    Args:
        transactions: Raw transactions data (might be list, dict, string, or None)
        
    Returns:
        List of valid transaction dictionaries
    """
    if transactions is None:
        return []
    
    # If it's a string, it might be JSON - try to parse
    if isinstance(transactions, str):
        try:
            transactions = json.loads(transactions)
        except:
            return []
    
    # If it's not a list, wrap it or return empty
    if not isinstance(transactions, list):
        if isinstance(transactions, dict):
            transactions = [transactions]
        else:
            return []
    
    valid_transactions = []
    txn_counter = 1
    
    for txn in transactions:
        # Skip non-dict items
        if not isinstance(txn, dict):
            continue
        
        # Ensure required fields with defaults
        validated_txn = {
            'id': txn.get('id') or f"txn_{txn_counter}",
            'date': txn.get('date') or txn.get('transaction_date') or '1900-01-01',
            'description': str(txn.get('description', 'Unknown'))[:500],  # Limit length
            'amount': 0,
            'type': str(txn.get('type', 'unknown')).lower(),
            'category': str(txn.get('category', 'other')).lower()
        }
        
        # Parse amount safely - handle various bank formats
        amount_raw = txn.get('amount', 0)
        is_negative = False
        
        if isinstance(amount_raw, (int, float)):
            validated_txn['amount'] = float(amount_raw)
        elif isinstance(amount_raw, str):
            try:
                cleaned = amount_raw.strip()
                
                # Handle parentheses format for negatives: (1,234.56)
                if cleaned.startswith('(') and cleaned.endswith(')'):
                    cleaned = cleaned[1:-1]
                    is_negative = True
                
                # Handle trailing minus: 1,234.56-
                if cleaned.endswith('-'):
                    cleaned = cleaned[:-1]
                    is_negative = True
                
                # Handle leading minus: -1,234.56
                if cleaned.startswith('-'):
                    cleaned = cleaned[1:]
                    is_negative = True
                
                # Remove currency symbols
                cleaned = cleaned.replace('$', '').replace('€', '').replace('£', '')
                
                # Remove various space characters (including non-breaking space)
                cleaned = cleaned.replace(' ', '').replace('\u00a0', '').replace('\u202f', '')
                
                # Handle different number formats
                has_comma = ',' in cleaned
                has_period = '.' in cleaned
                
                if has_comma and has_period:
                    # Both separators present - determine which is decimal
                    comma_pos = cleaned.rindex(',')
                    period_pos = cleaned.rindex('.')
                    
                    if comma_pos > period_pos:
                        # European format: 1.234,56 -> 1234.56
                        cleaned = cleaned.replace('.', '').replace(',', '.')
                    else:
                        # US format: 1,234.56 -> 1234.56
                        cleaned = cleaned.replace(',', '')
                elif has_comma and not has_period:
                    # Check if comma is likely a decimal separator
                    # If only one comma and 1-2 digits after it, treat as decimal
                    comma_count = cleaned.count(',')
                    if comma_count == 1:
                        parts = cleaned.split(',')
                        if len(parts[1]) <= 2:
                            # European decimal: 1234,56 -> 1234.56
                            cleaned = cleaned.replace(',', '.')
                        else:
                            # US thousands separator: 1,234 -> 1234
                            cleaned = cleaned.replace(',', '')
                    else:
                        # Multiple commas = thousands separators: 1,234,567 -> 1234567
                        cleaned = cleaned.replace(',', '')
                elif has_period and not has_comma:
                    # Single period - could be decimal or thousands
                    period_count = cleaned.count('.')
                    if period_count == 1:
                        # Likely decimal, keep as-is
                        pass
                    else:
                        # Multiple periods = likely European thousands: 1.234.567 -> 1234567
                        cleaned = cleaned.replace('.', '')
                
                parsed_amount = float(cleaned) if cleaned else 0
                validated_txn['amount'] = -parsed_amount if is_negative else parsed_amount
            except:
                validated_txn['amount'] = 0
        
        # Copy over optional fields if they exist and are valid types
        optional_fields = ['source_account_id', 'lender_payment', 'is_internal_transfer', 
                          'matched_transfer_id', 'transfer_reason']
        for field in optional_fields:
            if field in txn and txn[field] is not None:
                validated_txn[field] = txn[field]
        
        valid_transactions.append(validated_txn)
        txn_counter += 1
    
    return valid_transactions


def get_default_extraction_result() -> Dict:
    """Return a default empty extraction result structure."""
    return {
        "info_needed": {
            "total_monthly_payments": 0,
            "diesel_total_monthly_payments": 0,
            "total_monthly_payments_with_diesel": 0,
            "average_monthly_income": "not_computable",
            "annual_income": "not_computable",
            "length_of_deal_months": 0,
            "holdback_percentage": "not_computable",
            "monthly_holdback": 0,
            "monthly_payment_to_income_pct": "not_computable",
            "original_balance_to_annual_income_pct": 0
        },
        "daily_positions": [],
        "weekly_positions": [],
        "monthly_positions_non_mca": [],
        "other_liabilities": [],
        "bank_accounts": {},
        "total_revenues_by_month": {},
        "deductions": {},
        "transactions": [],
        "nsf_count": 0
    }

def encode_image_to_base64(image_path: str) -> str:
    """Encode image to base64 for OpenAI Vision API."""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def extract_financial_data_from_pdf(
    pdf_path: str,
    account_id: Optional[str] = None,
    error_feedback: Optional[str] = None
) -> Tuple[Dict, str]:
    """
    Extract financial data from PDF bank statement using OpenAI Vision API.
    
    Args:
        pdf_path: Path to PDF file
        account_id: Account identifier (if known)
        error_feedback: Specific error feedback from previous attempt (for retries)
    
    Returns:
        Tuple of (extracted_data_dict, reasoning_log)
    """
    # Read PDF as text first
    from pdf_processor import extract_text_from_pdf
    pdf_text = extract_text_from_pdf(pdf_path)
    
    # Build comprehensive prompt matching truth Excel structure
    system_prompt = """You are an expert financial data extractor specializing in bank statements for MCA (Merchant Cash Advance) underwriting.

## BANK FORMAT FLEXIBILITY
You will encounter statements from many different banks with varying formats:
- Major banks: Chase, Bank of America, Wells Fargo, Citibank, US Bank, PNC, Capital One
- Regional banks: TD Bank, Regions, Fifth Third, KeyBank, Huntington, M&T Bank
- Credit unions, online banks (Ally, Chime, Discover), business banks
- International banks with US branches

Adapt to each bank's format:
- DATE FORMATS: MM/DD/YYYY, DD/MM/YYYY, YYYY-MM-DD, "Jan 15", "15-Jan-2024" - standardize to YYYY-MM-DD
- AMOUNT FORMATS: $1,234.56, 1234.56, (1,234.56) for debits, 1,234.56- for debits
- COLUMN LAYOUTS: Debits/Credits in separate columns, single Amount column with +/-, or Amount with separate Type column
- TRANSACTION DESCRIPTIONS: Vary in length and detail - extract the core merchant/payee name
- RUNNING BALANCES: Some show balance after each transaction, some only show opening/closing
- MULTI-PAGE STATEMENTS: Data may span multiple pages with repeated headers

When extracting:
1. First identify the bank and its format patterns
2. Look for column headers to understand the layout
3. Determine how debits vs credits are indicated (negative sign, parentheses, separate columns, type labels)
4. Extract ALL transactions regardless of format

## CRITICAL RULE 1: USE THE 'TYPE' FIELD, NOT AMOUNT SIGN
- Transactions may have POSITIVE amounts but be marked with type='debit' or type='credit'
- ALWAYS use the 'type' field to determine cash flow direction:
  - type='debit' = money OUT (payments, withdrawals) - counts toward payments
  - type='credit' = money IN (deposits, revenue) - counts toward income
- NEVER assume negative amounts = debits. The type field is authoritative!

## CRITICAL RULE 2: INCLUDE ALL PAYMENT DEBITS IN TOTALS
- total_monthly_payments should include ALL transactions where:
  - type='debit' AND category='payment' (regardless of lender_payment flag)
- DO NOT restrict to only lender_payment=true - that misses valid payments like "Paymentech"
- Include merchant services fees, ACH debits, recurring payments - ALL payment-type debits

## CRITICAL RULE 3: DETECT POSITION PATTERNS BY CLUSTERING
- Look for REPEATING debits from the same merchant with similar amounts
- Daily positions: Same merchant, similar amount, occurring on consecutive business days
- Weekly positions: Same merchant, similar amount, ~7 days apart
- Monthly positions: Same merchant, similar amount, ~30 days apart
- Example: 7 debits from "JNG Capital" at $906.25 on consecutive business days = DAILY MCA POSITION

## CRITICAL RULE 4: MARK "NOT_COMPUTABLE" WHEN DATA IS INSUFFICIENT
- If the dataset only contains debits (no credits), you CANNOT calculate income metrics
- Use "not_computable" instead of 0 when data is genuinely missing:
  - average_monthly_income: "not_computable" if no credit transactions
  - annual_income: "not_computable" if cannot derive from data
  - holdback_percentage: "not_computable" if not stated in documents
- ONLY use 0 when the value is genuinely zero (e.g., no diesel payments found)

Extract ALL of the following data with high precision:

## 1. INFO NEEDED METRICS (Core underwriting data)
- Total Monthly Payments: Sum of ALL payment-type debits (not just lender payments!)
- Diesel Total Monthly Payments: Sum of diesel/fuel-related payments only (0 if none found, "not_computable" if can't determine)
- Total Monthly Payments with Diesel: Total payments including diesel
- Average Monthly Income: Average of monthly credits/deposits ("not_computable" if no credit data)
- Annual Income: Projected or actual annual income ("not_computable" if cannot derive)
- Length of Deal (Months): Duration of the MCA deal
- Holdback Percentage: The percentage being held back ("not_computable" if not stated)
- Monthly Holdback: Dollar amount of monthly holdback
- Monthly Payment to Income %: Payment as percentage of monthly income ("not_computable" if income unknown)
- Original Balance to Annual Income %: Original loan balance as % of annual income

## 2. DAILY POSITIONS (MCA-ONLY - Daily payment positions)
**CRITICAL: Only include debits that match MCA keywords!**
Cluster repeating debits from same MCA lender occurring on consecutive business days:
- Name: MCA Lender name
- Amount: Per-payment amount
- Monthly Payment: Amount × 22 (average business days per month)

## 3. WEEKLY POSITIONS (MCA-ONLY - Weekly payment positions)
**CRITICAL: Only include debits that match MCA keywords!**
Cluster repeating debits from same MCA lender occurring ~7 days apart:
- Name: MCA Lender name
- Amount: Per-payment amount
- Monthly Payment: Amount × 4.33

## 4. MONTHLY POSITIONS (MCA-ONLY monthly obligations)
**CRITICAL: Only include debits that match MCA keywords!**
- Name: MCA Lender name
- Monthly Payment: Monthly payment amount

## 5. OTHER LIABILITIES (Non-MCA recurring debits - separate table)
Put credit cards, insurance, and non-MCA debts HERE, not in Positions:
- Name: Creditor name
- Type: "credit_card", "insurance", "operating_expense"
- Monthly Payment: Amount

### MCA POSITION DETECTION RULES:
**WHITELIST - ONLY these keywords qualify as MCA Positions:**
CAPITAL, FUNDING, ADVANCE, FINANCING, MANAGEMENT, CREDIBLY, FORWARD, ONDECK, CAN CAPITAL, HEADWAY, KALAMATA, HUNTER, KING, LIBERTAS, YELLOWSTONE, CLEARVIEW, BIZFUND, RAPID, MERCHANT, FACTOR, MCA, CASH ADVANCE, DAILY ACH, FUNDER

**BLACKLIST - These are Operating Expenses, NOT Positions:**
DISCOVER, AMEX, AMERICAN EXPRESS, CHASE CARD, CHASE CREDIT, INSURANCE, UTICA, AMTRUST, VISA, MASTERCARD, PROGRESSIVE, STATE FARM, ALLSTATE, GEICO, LIBERTY MUTUAL, CREDIT CARD, CARD SERVICES

**Example Classifications:**
- "Kalamata Capital ACH" → DAILY POSITION (matches MCA keyword)
- "Hunter Funding" → DAILY POSITION (matches MCA keyword)  
- "Discover Card Payment" → OTHER LIABILITIES (matches blacklist)
- "AmTrust Insurance" → OTHER LIABILITIES (matches blacklist)
- "Chase Credit Card" → OTHER LIABILITIES (matches blacklist)

If a debit matches BOTH lists, classify as Operating Expense (blacklist wins).
If a lender appears with DIFFERENT amounts or frequencies, list BOTH as separate positions (stacking).

## 5. BANK ACCOUNT DATA (Per-account monthly breakdown)
For each bank account identified, extract per-month data:
- Account Name/Number (if no account identifiers, note this limitation)
- For each month: Total Income (from credits), Deductions (from debits), Net Revenue

## 6. TOTAL REVENUES BY MONTH
Monthly revenue totals across all accounts ("not_computable" if no credit data)

IMPORTANT - TRANSFER CLASSIFICATION:
- ONLY exclude deposits as "Internal Transfers" if:
  a) Description says "Online Transfer from Chk... [account number]" where the account number matches another known account
  b) OR description says "Intra-bank Transfer" or "Internal Transfer"
- Transfers from "Related Entities" (e.g., "Big World Enterprises" -> "Big World Travel") should be counted as REVENUE
- Do NOT exclude deposits just because sender name is similar to merchant name

## 7. DEDUCTIONS
Monthly deduction amounts per account

## 8. TRANSACTIONS (Individual transactions for verification)
List ALL transactions with:
- date: Transaction date
- description: Full description
- amount: Numeric amount (always positive)
- type: "debit" or "credit" (USE THIS TO DETERMINE CASH FLOW!)
- category: "income", "diesel", "payment", "transfer", "other"
- lender_payment: true/false (true if matches lender keywords)

CRITICAL INSTRUCTIONS:
1. Extract ALL data fields - do not skip any section
2. All amounts must be NUMBERS (no $ symbols or commas in values)
3. Percentages should be NUMBERS (e.g., 10 not "10%")
4. Show your mathematical reasoning
5. Use "not_computable" (string) for metrics that cannot be calculated from available data
6. Use 0 only when the value is genuinely zero
7. Verify sums match your calculations
8. Mark each transaction with lender_payment: true if it matches lender keywords
9. USE THE TYPE FIELD to determine debits vs credits - DO NOT rely on amount sign!

Output format must be JSON with this EXACT structure:
{
  "info_needed": {
    "total_monthly_payments": <number>,
    "diesel_total_monthly_payments": <number>,
    "total_monthly_payments_with_diesel": <number>,
    "average_monthly_income": <number>,
    "annual_income": <number>,
    "length_of_deal_months": <number>,
    "holdback_percentage": <number>,
    "monthly_holdback": <number>,
    "monthly_payment_to_income_pct": <number>,
    "original_balance_to_annual_income_pct": <number>
  },
  "daily_positions": [
    {"name": "<lender name>", "amount": <number>, "monthly_payment": <number>}
  ],
  "weekly_positions": [
    {"name": "<lender name>", "amount": <number>, "monthly_payment": <number>}
  ],
  "monthly_positions_non_mca": [
    {"name": "<MCA lender name>", "monthly_payment": <number>}
  ],
  "other_liabilities": [
    {"name": "<creditor name>", "type": "credit_card|insurance|operating_expense", "monthly_payment": <number>}
  ],
  "bank_accounts": {
    "<account_name>": {
      "months": [
        {"month": "<month name>", "total_income": <number>, "deductions": <number>, "net_revenue": <number>}
      ]
    }
  },
  "total_revenues_by_month": {
    "<month name>": <number>
  },
  "deductions": {
    "<account_name>": {
      "<month name>": <number>
    }
  },
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "<description>",
      "amount": <number>,
      "type": "debit|credit",
      "category": "income|diesel|payment|transfer|other"
    }
  ],
  "nsf_count": <number>,
  "reasoning": "<detailed explanation of your calculations and any exclusions>"
}"""
    
    if error_feedback:
        system_prompt += f"\n\nPREVIOUS ATTEMPT HAD AN ERROR:\n{error_feedback}\n\nPlease re-scan the document carefully, find the missing data or correct your calculations."
    
    # Check if we need chunked processing for large PDFs
    text_length = len(pdf_text)
    print(f"PDF text length: {text_length} characters")
    
    if text_length > CHUNK_SIZE:
        # Large PDF - use chunked processing
        chunks = chunk_text(pdf_text, CHUNK_SIZE, CHUNK_OVERLAP)
        print(f"Large PDF detected. Processing {len(chunks)} chunks...")
        
        chunk_results = []
        all_reasoning = []
        
        for chunk_idx, chunk in enumerate(chunks):
            print(f"Processing chunk {chunk_idx + 1}/{len(chunks)} ({len(chunk)} chars)...")
            
            user_prompt = f"""Analyze this bank statement CHUNK ({chunk_idx + 1} of {len(chunks)}) and extract ALL financial data for MCA underwriting.

Account ID: {account_id or 'Unknown'}

**NOTE: This is chunk {chunk_idx + 1} of {len(chunks)}. Extract all data you find in THIS chunk - results will be merged later.**

Bank Statement Text (Chunk {chunk_idx + 1}):
{chunk}

Remember:
1. Extract ALL sections (info_needed, positions, bank accounts, revenues, deductions, transactions)
2. All values must be numbers (no currency symbols or percentage signs)
3. This is a partial document - extract what's visible in this chunk
4. Include all transactions visible in this chunk
5. Use "not_computable" for metrics that can't be determined from this chunk alone"""

            try:
                response = openai.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                    max_completion_tokens=8192
                )
                
                result_text = response.choices[0].message.content or "{}"
                
                try:
                    result_data = json.loads(result_text)
                except json.JSONDecodeError as json_err:
                    print(f"Chunk {chunk_idx + 1} JSON parse error, attempting repair: {json_err}")
                    result_data, repair_log = repair_json(result_text)
                    if result_data is None:
                        result_data = get_default_extraction_result()
                        result_data["error"] = f"Chunk {chunk_idx + 1} parse failed"
                
                if 'transactions' in result_data:
                    result_data['transactions'] = validate_and_sanitize_transactions(result_data['transactions'])
                
                chunk_results.append(result_data)
                all_reasoning.append(f"[Chunk {chunk_idx + 1}]: {result_data.get('reasoning', 'No reasoning')}")
                
            except Exception as e:
                print(f"Error processing chunk {chunk_idx + 1}: {e}")
                chunk_results.append(get_default_extraction_result())
                all_reasoning.append(f"[Chunk {chunk_idx + 1}]: Error - {str(e)}")
        
        # Merge all chunk results
        merged_result = merge_extraction_results(chunk_results)
        merged_reasoning = f"Processed {len(chunks)} chunks from {text_length} character PDF.\n\n" + "\n\n".join(all_reasoning)
        
        return merged_result, merged_reasoning
    
    # Standard processing for smaller PDFs
    user_prompt = f"""Analyze this bank statement and extract ALL financial data for MCA underwriting.

Account ID: {account_id or 'Unknown'}

Bank Statement Text:
{pdf_text}

Remember:
1. Extract ALL sections (info_needed, positions, bank accounts, revenues, deductions, transactions)
2. All values must be numbers (no currency symbols or percentage signs)
3. Show your math for calculated totals
4. Explain any exclusions or assumptions
5. Verify sums match"""
    
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=8192
        )
        
        result_text = response.choices[0].message.content or "{}"
        
        result_data = None
        parse_log = ""
        
        try:
            result_data = json.loads(result_text)
            parse_log = "JSON parsed successfully"
        except json.JSONDecodeError as json_err:
            print(f"JSON parse error, attempting repair: {json_err}")
            result_data, parse_log = repair_json(result_text)
            
            if result_data is None:
                default_result = get_default_extraction_result()
                default_result["error"] = f"JSON parse failed: {json_err}"
                default_result["parse_log"] = parse_log
                return default_result, f"Error: JSON parsing failed after repair attempt.\n{parse_log}"
        
        if 'transactions' in result_data:
            original_count = len(result_data.get('transactions', []))
            result_data['transactions'] = validate_and_sanitize_transactions(result_data['transactions'])
            sanitized_count = len(result_data['transactions'])
            if original_count != sanitized_count:
                parse_log += f"\nSanitized transactions: {original_count} -> {sanitized_count}"
        
        reasoning_log = result_data.get("reasoning", "No reasoning provided")
        if parse_log and parse_log != "JSON parsed successfully":
            reasoning_log = f"[Parse Log: {parse_log}]\n\n{reasoning_log}"
        
        return result_data, reasoning_log
        
    except Exception as e:
        print(f"Error in OpenAI Vision extraction: {e}")
        default_result = get_default_extraction_result()
        default_result["error"] = str(e)
        return default_result, f"Error: {str(e)}"

def generate_underwriting_summary(
    financial_data: Dict,
    few_shot_examples: List[Dict],
    gold_standard_rules: List[Dict],
    settings: Dict
) -> str:
    """
    Generate intelligent underwriting summary using GPT-5.
    
    Incorporates:
    - Few-shot learning from TrainingExamples
    - Pattern matching from GoldStandard_Rules
    - Dynamic rules from Settings
    
    Args:
        financial_data: Extracted financial metrics
        few_shot_examples: Recent corrected examples from TrainingExamples
        gold_standard_rules: Learned patterns from GoldStandard_Rules
        settings: Current underwriting rules from Settings table
    
    Returns:
        Underwriting summary text
    """
    # Build context from few-shot examples
    few_shot_context = ""
    if few_shot_examples:
        few_shot_context = "\n\nLEARNING FROM PAST CORRECTIONS:\n"
        for idx, example in enumerate(few_shot_examples[:3], 1):
            few_shot_context += f"\nExample {idx}:\n"
            few_shot_context += f"Original Data: {json.dumps(example.get('original_financial_json', {}), indent=2)}\n"
            few_shot_context += f"Corrected Analysis: {example.get('user_corrected_summary', '')}\n"
    
    # Build context from gold standard rules
    rules_context = ""
    if gold_standard_rules:
        rules_context = "\n\nLEARNED PATTERN RULES (Apply these automatically):\n"
        for rule in gold_standard_rules:
            rules_context += f"- Pattern: '{rule.get('rule_pattern', '')}' → "
            rules_context += f"Classification: {rule.get('correct_classification', '')} "
            rules_context += f"(was originally: {rule.get('original_classification', 'unknown')})\n"
    
    # Build settings context
    settings_context = "\n\nUNDERWRITING RULES:\n"
    for key, value in settings.items():
        settings_context += f"- {key}: {value}\n"
    
    system_prompt = f"""You are an expert underwriting analyst. Analyze the financial data and provide a comprehensive underwriting recommendation.

{settings_context}
{few_shot_context}
{rules_context}

Your analysis should:
1. Evaluate against the underwriting rules
2. Apply learned patterns from past corrections
3. Identify any red flags or concerns
4. Provide a clear recommendation (Approve, Reject, or Needs Review)
5. Explain your reasoning in detail"""
    
    user_prompt = f"""Analyze this financial data:

{json.dumps(financial_data, indent=2)}

Provide a comprehensive underwriting analysis and recommendation."""
    
    try:
        # the newest OpenAI model is "gpt-5" which was released August 7, 2025.
        # do not change this unless explicitly requested by the user
        response = openai.chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_completion_tokens=8192
        )
        
        summary = response.choices[0].message.content or "Unable to generate summary"
        return summary
        
    except Exception as e:
        print(f"Error generating underwriting summary: {e}")
        return f"Error generating summary: {str(e)}"

def safe_float_compare(value, default=0.0) -> float:
    """Safely convert a value to float for comparison."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace('$', '').replace(',', '').replace('%', '').strip()
        if cleaned == '' or cleaned == '-':
            return default
        try:
            return float(cleaned)
        except ValueError:
            return default
    return default


def adversarial_correction_prompt(
    ai_result: Dict,
    human_truth: Dict,
    transactions_data: List[Dict]
) -> str:
    """
    Generate adversarial prompt for AI self-correction.
    
    Compares AI's analysis against human truth and generates specific
    interrogation questions.
    
    Args:
        ai_result: AI's original analysis (new nested structure with info_needed)
        human_truth: Human-provided correct values (from Excel parser)
        transactions_data: List of transactions for investigation
    
    Returns:
        AI's correction report
    """
    differences = []
    
    # Get AI's info_needed (handle both old flat format and new nested format)
    ai_info = ai_result.get('info_needed', ai_result)
    human_info = human_truth.get('info_needed', human_truth)
    
    # Compare info_needed metrics
    info_needed_fields = [
        'total_monthly_payments', 'diesel_total_monthly_payments', 
        'total_monthly_payments_with_diesel', 'average_monthly_income',
        'annual_income', 'length_of_deal_months', 'holdback_percentage',
        'monthly_holdback', 'monthly_payment_to_income_pct',
        'original_balance_to_annual_income_pct'
    ]
    
    for field in info_needed_fields:
        ai_val = safe_float_compare(ai_info.get(field, 0))
        human_val = safe_float_compare(human_info.get(field, 0))
        if abs(ai_val - human_val) > 0.01:  # Allow small tolerance
            diff = human_val - ai_val
            if 'pct' in field or 'percentage' in field:
                differences.append(f"- {field}: You said {ai_val:.2f}%, Human says {human_val:.2f}% (Difference: {diff:.2f}%)")
            else:
                differences.append(f"- {field}: You said ${ai_val:,.2f}, Human says ${human_val:,.2f} (Difference: ${diff:,.2f})")
    
    # Compare positions counts
    for pos_type in ['daily_positions', 'weekly_positions', 'monthly_positions_non_mca']:
        ai_positions = ai_result.get(pos_type, [])
        human_positions = human_truth.get(pos_type, [])
        if len(ai_positions) != len(human_positions):
            differences.append(f"- {pos_type}: You found {len(ai_positions)} positions, Human truth has {len(human_positions)}")
    
    # Compare bank accounts
    ai_accounts = ai_result.get('bank_accounts', {})
    human_accounts = human_truth.get('bank_accounts', {})
    if len(ai_accounts) != len(human_accounts):
        differences.append(f"- Bank Accounts: You found {len(ai_accounts)} accounts, Human truth has {len(human_accounts)}")
    
    if not differences:
        return json.dumps({
            "errors_found": [],
            "missed_transactions": [],
            "miscategorized_transactions": [],
            "correction_explanation": "No significant differences found between AI analysis and human truth. Both values may be empty or matching.",
            "learned_pattern": "No new patterns to learn - results already match."
        })
    
    differences_text = "\n".join(differences)
    
    prompt = f"""ADVERSARIAL SELF-AUDIT REQUIRED

You previously analyzed a deal and made the following errors:

{differences_text}

Your task:
1. Review ALL transactions you had access to
2. List EVERY transaction you excluded and explain WHY
3. Identify which transactions you missed or miscategorized
4. Find the EXACT transactions that account for the difference
5. Provide a detailed correction report

Transactions data:
{json.dumps(transactions_data, indent=2)}

Output a detailed JSON report with:
{{
  "errors_found": ["list of specific errors"],
  "missed_transactions": [{{ "description": "...", "amount": ..., "why_missed": "..." }}],
  "miscategorized_transactions": [{{ "description": "...", "amount": ..., "was_categorized_as": "...", "should_be": "..." }}],
  "correction_explanation": "Detailed explanation of what went wrong and how to prevent it",
  "learned_pattern": "Generalizable rule to apply in future"
}}"""
    
    try:
        # the newest OpenAI model is "gpt-5" which was released August 7, 2025.
        # do not change this unless explicitly requested by the user
        response = openai.chat.completions.create(
            model="gpt-5",
            messages=[
                {"role": "system", "content": "You are conducting a rigorous self-audit of your previous analysis."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=8192
        )
        
        correction_report = response.choices[0].message.content or "{}"
        return correction_report
        
    except Exception as e:
        print(f"Error in adversarial correction: {e}")
        return json.dumps({"error": str(e)})
