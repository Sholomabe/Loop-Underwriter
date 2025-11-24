import os
import json
import base64
from typing import Dict, List, Optional, Tuple
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
    
    # Build prompt
    system_prompt = """You are an expert financial data extractor specializing in bank statements.
Extract the following metrics with high precision:
- Total Monthly Payments
- Diesel Payments
- Average Monthly Income
- Annual Income
- Revenues (Last 4 Months)
- NSF Count (Non-Sufficient Funds)

CRITICAL INSTRUCTIONS:
1. Provide detailed transaction-level data, not just totals
2. Show your mathematical reasoning for each calculated total
3. List individual transactions that contribute to each category
4. If you exclude any transaction, explain why in detail
5. Verify that the sum of individual transactions matches your stated total

Output format must be JSON with this structure:
{
  "total_monthly_payments": <number>,
  "diesel_payments": <number>,
  "avg_monthly_income": <number>,
  "annual_income": <number>,
  "revenues_last_4_months": <number>,
  "nsf_count": <number>,
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "...",
      "amount": <number>,
      "type": "debit|credit",
      "category": "income|diesel|payment|other"
    }
  ],
  "reasoning": "Detailed explanation of your calculations and any exclusions"
}"""
    
    if error_feedback:
        system_prompt += f"\n\nPREVIOUS ATTEMPT HAD AN ERROR:\n{error_feedback}\n\nPlease re-scan the document carefully, find the missing transactions or correct your calculations."
    
    user_prompt = f"""Analyze this bank statement and extract financial data.

Account ID: {account_id or 'Unknown'}

Bank Statement Text:
{pdf_text[:8000]}  

Remember:
1. List ALL transactions individually
2. Show your math for totals
3. Explain any exclusions
4. Verify sums match"""
    
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
        result_data = json.loads(result_text)
        
        reasoning_log = result_data.get("reasoning", "No reasoning provided")
        
        return result_data, reasoning_log
        
    except Exception as e:
        print(f"Error in OpenAI Vision extraction: {e}")
        return {
            "error": str(e),
            "total_monthly_payments": 0,
            "diesel_payments": 0,
            "avg_monthly_income": 0,
            "annual_income": 0,
            "revenues_last_4_months": 0,
            "nsf_count": 0,
            "transactions": []
        }, f"Error: {str(e)}"

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
        ai_result: AI's original analysis
        human_truth: Human-provided correct values
        transactions_data: List of transactions for investigation
    
    Returns:
        AI's correction report
    """
    # Calculate differences
    differences = []
    for key in human_truth:
        if key in ai_result and ai_result[key] != human_truth[key]:
            diff_amount = human_truth[key] - ai_result[key]
            differences.append(f"- {key}: You said ${ai_result[key]:,.2f}, Human says ${human_truth[key]:,.2f} (Difference: ${diff_amount:,.2f})")
    
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
