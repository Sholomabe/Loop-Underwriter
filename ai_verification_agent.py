"""
AI Verification Agent - LLM Second Opinion on Underwriting

This module provides AI-powered verification of calculated underwriting metrics.
Acts as a "Senior Underwriter" to review data and flag anomalies.
"""

import os
import json
from typing import Dict, List, Optional
from openai import OpenAI

AI_INTEGRATIONS_OPENAI_API_KEY = os.environ.get("AI_INTEGRATIONS_OPENAI_API_KEY")
AI_INTEGRATIONS_OPENAI_BASE_URL = os.environ.get("AI_INTEGRATIONS_OPENAI_BASE_URL")

openai = OpenAI(
    api_key=AI_INTEGRATIONS_OPENAI_API_KEY,
    base_url=AI_INTEGRATIONS_OPENAI_BASE_URL
)


def get_ai_verification(
    calculated_metrics: Dict,
    positions: List[Dict],
    monthly_breakdown: List[Dict],
    raw_transaction_count: int = 0,
    detected_transfers: int = 0
) -> Dict:
    """
    Get AI verification and second opinion on calculated underwriting metrics.
    
    Args:
        calculated_metrics: Summary of calculated metrics from Logic Engine
        positions: List of detected MCA positions
        monthly_breakdown: Monthly revenue breakdown
        raw_transaction_count: Total number of transactions analyzed
        detected_transfers: Number of internal transfers detected
        
    Returns:
        Dict with AI verification results including opinion, flags, and confidence
    """
    
    system_prompt = """You are a Senior MCA (Merchant Cash Advance) Underwriter with 15+ years of experience.
Your role is to review automated underwriting calculations and provide a second opinion.

Your responsibilities:
1. Verify that Total Monthly Payments seem consistent with identified positions
2. Check if revenue figures make sense for the business type
3. Look for anomalies in payment patterns that the automated system might have missed
4. Flag any concerns about data quality or completeness
5. Provide actionable recommendations

Be direct and specific. If something looks wrong, say exactly what and why.
If the data looks solid, confirm it with specific reasons."""

    metrics_summary = f"""
## CALCULATED METRICS TO REVIEW

### Income & Revenue
- Total Income: ${calculated_metrics.get('total_income', 0):,.2f}
- Net Revenue: ${calculated_metrics.get('net_revenue', 0):,.2f}
- Average Monthly Income: ${calculated_metrics.get('average_monthly_income', 0):,.2f}
- Annual Income (Projected): ${calculated_metrics.get('annual_income', 0):,.2f}
- Months of Data Analyzed: {calculated_metrics.get('months_analyzed', 0)}

### Payments & Positions
- Total Monthly Payments (MCA): ${calculated_metrics.get('total_monthly_payments', 0):,.2f}
- Diesel Payments: ${calculated_metrics.get('diesel_total_monthly_payments', 0):,.2f}
- Total Monthly Payments (with Diesel): ${calculated_metrics.get('total_monthly_payments_with_diesel', 0):,.2f}
- Number of Active Positions: {len(positions)}

### Ratios
- Payment to Income Ratio: {calculated_metrics.get('payment_to_income_ratio', 0):.1f}%

### Data Quality
- Total Transactions Analyzed: {raw_transaction_count}
- Internal Transfers Detected: {detected_transfers}

### Monthly Revenue Breakdown (Last 12 months):
"""
    
    for month_data in monthly_breakdown[:12]:
        metrics_summary += f"- {month_data.get('month', 'N/A')}: ${month_data.get('revenue', 0):,.2f}\n"
    
    if positions:
        metrics_summary += "\n### Active MCA Positions:\n"
        for pos in positions:
            metrics_summary += f"- {pos.get('name', 'Unknown')}: ${pos.get('daily_payment', 0):,.2f}/day or ${pos.get('weekly_payment', 0):,.2f}/week → ${pos.get('monthly_payment', 0):,.2f}/month\n"
    
    metrics_summary += """
## YOUR TASK

Review the above metrics and provide:
1. **Overall Assessment**: Is the data quality good? Are the calculations reasonable?
2. **Position Verification**: Do the Total Monthly Payments align with the listed positions?
3. **Anomaly Flags**: Any red flags or concerns? (e.g., missing months, unusual patterns, data gaps)
4. **Recommendations**: What should the underwriter look at more closely?

Be specific and actionable. Reference actual numbers when making your points."""

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": metrics_summary}
            ],
            temperature=0.3,
            max_tokens=1500
        )
        
        ai_opinion = response.choices[0].message.content
        
        result = {
            'success': True,
            'ai_opinion': ai_opinion,
            'confidence': 'high',
            'flags': extract_flags_from_opinion(ai_opinion),
            'metrics_reviewed': {
                'total_income': calculated_metrics.get('total_income', 0),
                'total_monthly_payments': calculated_metrics.get('total_monthly_payments_with_diesel', 0),
                'positions_count': len(positions),
                'months_analyzed': calculated_metrics.get('months_analyzed', 0)
            }
        }
        
        return result
        
    except Exception as e:
        return {
            'success': False,
            'ai_opinion': f"Unable to generate AI verification: {str(e)}",
            'confidence': 'none',
            'flags': [],
            'error': str(e)
        }


def extract_flags_from_opinion(opinion: str) -> List[Dict]:
    """
    Extract specific flags/concerns from AI opinion text.
    
    Args:
        opinion: AI's opinion text
        
    Returns:
        List of extracted flag dicts
    """
    flags = []
    
    flag_keywords = {
        'red flag': 'critical',
        'concern': 'warning',
        'missing': 'warning',
        'inconsistent': 'warning',
        'anomaly': 'warning',
        'unusual': 'info',
        'recommend': 'info',
        'verify': 'info',
        'confirm': 'info'
    }
    
    opinion_lower = opinion.lower()
    
    for keyword, severity in flag_keywords.items():
        if keyword in opinion_lower:
            start = opinion_lower.find(keyword)
            end = min(start + 150, len(opinion))
            sentence_end = opinion.find('.', start)
            if sentence_end > 0 and sentence_end < end:
                end = sentence_end + 1
            
            context = opinion[max(0, start-20):end].strip()
            
            flags.append({
                'keyword': keyword,
                'severity': severity,
                'context': context
            })
    
    return flags


def get_quick_validation(
    total_monthly_income: float,
    total_monthly_payments: float,
    position_count: int,
    months_of_data: int
) -> Dict:
    """
    Quick validation check without full AI analysis.
    
    Args:
        total_monthly_income: Average monthly income
        total_monthly_payments: Total monthly payments
        position_count: Number of active positions
        months_of_data: Months of data analyzed
        
    Returns:
        Dict with validation results and warnings
    """
    warnings = []
    passed = True
    
    if total_monthly_income > 0:
        payment_ratio = (total_monthly_payments / total_monthly_income) * 100
        
        if payment_ratio > 80:
            warnings.append({
                'type': 'critical',
                'message': f'Payment ratio extremely high at {payment_ratio:.1f}% - merchant may be over-leveraged'
            })
            passed = False
        elif payment_ratio > 50:
            warnings.append({
                'type': 'warning',
                'message': f'Payment ratio elevated at {payment_ratio:.1f}% - approaching capacity'
            })
    else:
        warnings.append({
            'type': 'critical',
            'message': 'No income data detected - unable to calculate ratios'
        })
        passed = False
    
    if months_of_data < 3:
        warnings.append({
            'type': 'warning',
            'message': f'Only {months_of_data} month(s) of data - recommend obtaining more history'
        })
    
    if position_count == 0 and total_monthly_payments > 0:
        warnings.append({
            'type': 'warning',
            'message': 'Payments detected but no positions identified - review transaction categorization'
        })
    
    if position_count > 5:
        warnings.append({
            'type': 'info',
            'message': f'Multiple stacked positions ({position_count}) - verify all are active'
        })
    
    return {
        'passed': passed,
        'warnings': warnings,
        'summary': 'All basic checks passed' if passed else 'Issues detected - review required'
    }


def generate_underwriting_recommendation(
    analysis: Dict,
    business_type: str = "Unknown",
    requested_amount: float = 0
) -> Dict:
    """
    Generate final underwriting recommendation based on complete analysis.
    
    Args:
        analysis: Complete analysis from Logic Engine
        business_type: Type of business
        requested_amount: Requested funding amount
        
    Returns:
        Dict with recommendation, reasoning, and conditions
    """
    summary = analysis.get('summary', {})
    
    avg_monthly_income = summary.get('average_monthly_income', 0)
    total_monthly_payments = summary.get('total_monthly_payments', 0)
    payment_ratio = summary.get('payment_to_income_ratio', 0)
    months_analyzed = summary.get('months_analyzed', 0)
    position_count = summary.get('position_count', 0)
    
    if avg_monthly_income <= 0:
        return {
            'recommendation': 'DECLINE',
            'reason': 'Insufficient income data',
            'confidence': 'low',
            'conditions': ['Obtain bank statements with deposit history']
        }
    
    if payment_ratio > 80:
        return {
            'recommendation': 'DECLINE',
            'reason': f'Payment ratio too high ({payment_ratio:.1f}%)',
            'confidence': 'high',
            'conditions': ['Wait for existing positions to be paid down']
        }
    
    if months_analyzed < 3:
        return {
            'recommendation': 'PENDING',
            'reason': f'Insufficient history ({months_analyzed} months)',
            'confidence': 'medium',
            'conditions': ['Obtain at least 3 months of bank statements']
        }
    
    if payment_ratio > 50:
        max_new_payment = avg_monthly_income * 0.15
        return {
            'recommendation': 'CONDITIONAL APPROVAL',
            'reason': f'Elevated payment ratio ({payment_ratio:.1f}%) limits capacity',
            'confidence': 'medium',
            'conditions': [
                f'Maximum new payment: ${max_new_payment:,.2f}/month',
                'Verify all existing positions are current'
            ],
            'max_payment': max_new_payment
        }
    
    available_capacity = avg_monthly_income * 0.50 - total_monthly_payments
    max_new_payment = min(available_capacity, avg_monthly_income * 0.25)
    
    return {
        'recommendation': 'APPROVE',
        'reason': f'Strong capacity (payment ratio: {payment_ratio:.1f}%)',
        'confidence': 'high',
        'conditions': ['Standard verification of business operations'],
        'max_payment': max_new_payment,
        'available_capacity': available_capacity
    }
