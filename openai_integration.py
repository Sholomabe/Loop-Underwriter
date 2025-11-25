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
    
    # Step 6: Try aggressive repair - find valid JSON subset
    # Start from the beginning and find the longest valid JSON
    for end_pos in range(len(working_json), 100, -100):
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
        
        # Parse amount safely
        amount_raw = txn.get('amount', 0)
        if isinstance(amount_raw, (int, float)):
            validated_txn['amount'] = float(amount_raw)
        elif isinstance(amount_raw, str):
            try:
                cleaned = amount_raw.replace('$', '').replace(',', '').strip()
                validated_txn['amount'] = float(cleaned) if cleaned else 0
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

## 2. DAILY POSITIONS (Daily payment MCA positions)
Cluster repeating debits from same merchant occurring on consecutive business days:
- Name: Lender/Company name
- Amount: Per-payment amount
- Monthly Payment: Amount × 22 (average business days per month)

## 3. WEEKLY POSITIONS (Weekly payment MCA positions)
Cluster repeating debits from same merchant occurring ~7 days apart:
- Name: Lender/Company name
- Amount: Per-payment amount
- Monthly Payment: Amount × 4.33

## 4. MONTHLY POSITIONS (Non-MCA monthly obligations)
List each monthly position with:
- Name: Creditor/Lender name
- Monthly Payment: Monthly payment amount

IMPORTANT - LENDER DETECTION:
- Look for ANY recurring debits containing these keywords: Financing, Capital, Funding, Advance, Lending, Merchant, MCA, Loan, Factor
- Examples: "Intuit Financing", "JNG Capital", "Oat Financial", "Paymentech" - these are ALL lender positions
- If a lender appears with DIFFERENT amounts or frequencies, list BOTH as separate positions (stacking)
- Only consolidate positions if you see a "Payoff" credit from that lender

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
    {"name": "<creditor name>", "monthly_payment": <number>}
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
    
    user_prompt = f"""Analyze this bank statement and extract ALL financial data for MCA underwriting.

Account ID: {account_id or 'Unknown'}

Bank Statement Text:
{pdf_text[:12000]}  

Remember:
1. Extract ALL sections (info_needed, positions, bank accounts, revenues, deductions, transactions)
2. All values must be numbers (no currency symbols or percentage signs)
3. Show your math for calculated totals
4. Explain any exclusions or assumptions
5. Verify sums match"""
    
    try:
        # the newest OpenAI model is "gpt-5" which was released August 7, 2025.
        # do not change this unless explicitly requested by the user
        response = openai.chat.completions.create(
            model="gpt-4o",  # Using gpt-4o for vision capabilities
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=8192
        )
        
        result_text = response.choices[0].message.content or "{}"
        
        # Try to parse JSON, with repair fallback
        result_data = None
        parse_log = ""
        
        try:
            result_data = json.loads(result_text)
            parse_log = "JSON parsed successfully"
        except json.JSONDecodeError as json_err:
            print(f"JSON parse error, attempting repair: {json_err}")
            result_data, parse_log = repair_json(result_text)
            
            if result_data is None:
                # Repair failed, return default with error info
                default_result = get_default_extraction_result()
                default_result["error"] = f"JSON parse failed: {json_err}"
                default_result["parse_log"] = parse_log
                return default_result, f"Error: JSON parsing failed after repair attempt.\n{parse_log}"
        
        # Validate and sanitize transactions
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
        return "No significant differences found."
    
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
