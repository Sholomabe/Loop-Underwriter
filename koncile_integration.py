"""
Koncile API Integration Module

This module handles:
1. Connecting to Koncile API for bank statement extraction
2. Pulling both summary (General_fields) and transaction (Line_fields) data
3. Verifying extracted transactions match the bank statement summary
"""

import os
import requests
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class BankStatementSummary:
    """Bank statement summary data from Koncile General_fields"""
    beginning_balance: float
    ending_balance: float
    total_deposits: float
    total_deposits_count: int
    total_withdrawals: float
    total_withdrawals_count: int
    total_checks: float
    total_checks_count: int
    total_fees: float
    total_fees_count: int
    statement_period_start: str
    statement_period_end: str
    account_holder: str
    account_number: str
    bank_name: str


@dataclass
class VerificationResult:
    """Result of verifying transactions against summary"""
    is_valid: bool
    discrepancies: List[Dict[str, Any]]
    summary_totals: Dict[str, float]
    calculated_totals: Dict[str, float]
    confidence_score: float
    warnings: List[str]


class KoncileClient:
    """Client for Koncile API integration"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("KONCILE_API_KEY")
        self.base_url = "https://api.koncile.ai"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def is_configured(self) -> bool:
        """Check if API key is configured"""
        return bool(self.api_key)
    
    def upload_document(self, file_path: str, folder_id: str = "", template_id: str = "") -> Dict:
        """
        Upload a bank statement document to Koncile for extraction
        
        Args:
            file_path: Path to PDF/image file
            folder_id: Optional folder identifier
            template_id: Optional Koncile template ID (leave empty for auto-classification)
            
        Returns:
            Dict with task_ids list for polling results
        """
        if not self.is_configured():
            raise ValueError("Koncile API key not configured. Set KONCILE_API_KEY environment variable.")
        
        url = f"{self.base_url}/v1/upload_file/"
        
        with open(file_path, 'rb') as f:
            files = {'files': (os.path.basename(file_path), f)}
            data = {}
            if folder_id:
                data['folder_id'] = folder_id
            if template_id:
                data['template_id'] = template_id
            
            response = requests.post(
                url, 
                headers={"Authorization": f"Bearer {self.api_key}"},
                files=files,
                data=data if data else None
            )
        
        response.raise_for_status()
        return response.json()
    
    def get_task_results(self, task_id: str) -> Dict:
        """
        Fetch task results including status and extracted data
        
        Returns:
            Dict containing:
            - status: DONE, IN PROGRESS, DUPLICATE, or FAILED
            - General_fields: Summary data with confidence scores
            - Line_fields: Transaction data with confidence scores
        """
        if not self.is_configured():
            raise ValueError("Koncile API key not configured.")
        
        url = f"{self.base_url}/v1/fetch_tasks_results/?task_id={task_id}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "accept": "application/json"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    
    def get_task_status(self, task_id: str) -> Dict:
        """Check the status of an extraction task (uses fetch_tasks_results)"""
        return self.get_task_results(task_id)
    
    def get_extraction_results(self, task_id: str) -> Dict:
        """
        Get the full extraction results including General_fields and Line_fields
        Alias for get_task_results for backwards compatibility
        """
        return self.get_task_results(task_id)
    
    def parse_summary(self, general_fields: Dict) -> BankStatementSummary:
        """
        Parse Koncile General_fields into BankStatementSummary object
        
        Args:
            general_fields: Dict from Koncile API response
            
        Returns:
            BankStatementSummary object with extracted values
        """
        def get_value(field_name: str, default: Any = None) -> Any:
            field = general_fields.get(field_name, {})
            if isinstance(field, dict):
                return field.get('value', default)
            return field if field is not None else default
        
        def parse_amount(value: Any) -> float:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                cleaned = value.replace('$', '').replace(',', '').replace(' ', '')
                try:
                    return float(cleaned)
                except ValueError:
                    return 0.0
            return 0.0
        
        def parse_count(value: Any) -> int:
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                try:
                    return int(value.replace(',', ''))
                except ValueError:
                    return 0
            return 0
        
        return BankStatementSummary(
            beginning_balance=parse_amount(get_value('Opening_Balance', 0)),
            ending_balance=parse_amount(get_value('Closing_Balance', 0)),
            total_deposits=parse_amount(get_value('Total_Deposits', 0)),
            total_deposits_count=parse_count(get_value('Deposits_Count', 0)),
            total_withdrawals=parse_amount(get_value('Total_Withdrawals', 0)),
            total_withdrawals_count=parse_count(get_value('Withdrawals_Count', 0)),
            total_checks=parse_amount(get_value('Total_Checks', 0)),
            total_checks_count=parse_count(get_value('Checks_Count', 0)),
            total_fees=parse_amount(get_value('Total_Fees', 0)),
            total_fees_count=parse_count(get_value('Fees_Count', 0)),
            statement_period_start=str(get_value('Statement_Period_Start', '')),
            statement_period_end=str(get_value('Statement_Period_End', '')),
            account_holder=str(get_value('Account_Holder', '')),
            account_number=str(get_value('Account_Number', '')),
            bank_name=str(get_value('Bank_Name', ''))
        )
    
    def parse_transactions(self, line_fields: Dict) -> List[Dict]:
        """
        Parse Koncile Line_fields into transaction list
        
        Returns:
            List of transaction dicts with date, amount, type, description
        """
        transactions = []
        
        dates = line_fields.get('Date', [])
        amounts = line_fields.get('Amount', [])
        types = line_fields.get('Transaction_Type', [])
        descriptions = line_fields.get('Description', [])
        
        num_transactions = max(len(dates), len(amounts), len(types), len(descriptions))
        
        for i in range(num_transactions):
            def get_field_value(field_list, idx, default: Any = ''):
                if idx < len(field_list):
                    item = field_list[idx]
                    if isinstance(item, dict):
                        return item.get('value', default)
                    return item if item else default
                return default
            
            txn = {
                'date': get_field_value(dates, i),
                'amount': self._parse_amount(get_field_value(amounts, i, '0')),
                'type': get_field_value(types, i, 'unknown'),
                'description': get_field_value(descriptions, i),
                'confidence': self._get_avg_confidence(line_fields, i)
            }
            transactions.append(txn)
        
        return transactions
    
    def _parse_amount(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            cleaned = value.replace('$', '').replace(',', '').replace(' ', '')
            is_negative = '(' in value or '-' in cleaned
            cleaned = cleaned.replace('(', '').replace(')', '').replace('-', '')
            try:
                amount = float(cleaned)
                return -amount if is_negative else amount
            except ValueError:
                return 0.0
        return 0.0
    
    def _get_avg_confidence(self, line_fields: Dict, idx: int) -> float:
        """Get average confidence score for a transaction row"""
        scores = []
        for field_name, field_list in line_fields.items():
            if idx < len(field_list) and isinstance(field_list[idx], dict):
                score = field_list[idx].get('confidence_score')
                if score is not None:
                    scores.append(float(score))
        return sum(scores) / len(scores) if scores else 0.0


class StatementVerifier:
    """Verifies extracted transactions match bank statement summary"""
    
    TOLERANCE_PERCENT = 0.01  # 1% tolerance for rounding differences
    TOLERANCE_ABSOLUTE = 1.00  # $1 absolute tolerance
    
    def verify(
        self, 
        summary: BankStatementSummary, 
        transactions: List[Dict]
    ) -> VerificationResult:
        """
        Verify that extracted transactions match the bank statement summary
        
        Args:
            summary: Parsed summary from General_fields
            transactions: Parsed transactions from Line_fields
            
        Returns:
            VerificationResult with match status and any discrepancies
        """
        discrepancies = []
        warnings = []
        
        if not transactions:
            return VerificationResult(
                is_valid=False,
                discrepancies=[{
                    'field': 'Transaction Count',
                    'summary_value': summary.total_deposits_count + summary.total_withdrawals_count,
                    'calculated_value': 0,
                    'difference': -(summary.total_deposits_count + summary.total_withdrawals_count),
                    'severity': 'high'
                }],
                summary_totals={
                    'deposits_total': float(summary.total_deposits),
                    'deposits_count': float(summary.total_deposits_count),
                    'withdrawals_total': float(summary.total_withdrawals),
                    'withdrawals_count': float(summary.total_withdrawals_count),
                },
                calculated_totals={
                    'deposits_total': 0.0,
                    'deposits_count': 0.0,
                    'withdrawals_total': 0.0,
                    'withdrawals_count': 0.0,
                },
                confidence_score=0.0,
                warnings=["No transactions extracted - verification failed"]
            )
        
        deposits = [t for t in transactions if self._is_deposit(t)]
        withdrawals = [t for t in transactions if self._is_withdrawal(t)]
        checks = [t for t in transactions if self._is_check(t)]
        fees = [t for t in transactions if self._is_fee(t)]
        
        calc_deposits_total = sum(abs(t['amount']) for t in deposits)
        calc_withdrawals_total = sum(abs(t['amount']) for t in withdrawals)
        calc_checks_total = sum(abs(t['amount']) for t in checks)
        calc_fees_total = sum(abs(t['amount']) for t in fees)
        
        calculated_totals: Dict[str, float] = {
            'deposits_total': float(calc_deposits_total),
            'deposits_count': float(len(deposits)),
            'withdrawals_total': float(calc_withdrawals_total),
            'withdrawals_count': float(len(withdrawals)),
            'checks_total': float(calc_checks_total),
            'checks_count': float(len(checks)),
            'fees_total': float(calc_fees_total),
            'fees_count': float(len(fees))
        }
        
        summary_totals: Dict[str, float] = {
            'deposits_total': float(summary.total_deposits),
            'deposits_count': float(summary.total_deposits_count),
            'withdrawals_total': float(summary.total_withdrawals),
            'withdrawals_count': float(summary.total_withdrawals_count),
            'checks_total': float(summary.total_checks),
            'checks_count': float(summary.total_checks_count),
            'fees_total': float(summary.total_fees),
            'fees_count': float(summary.total_fees_count)
        }
        
        if not self._amounts_match(calc_deposits_total, summary.total_deposits):
            diff = calc_deposits_total - summary.total_deposits
            discrepancies.append({
                'field': 'Total Deposits',
                'summary_value': summary.total_deposits,
                'calculated_value': calc_deposits_total,
                'difference': diff,
                'severity': 'high' if abs(diff) > 100 else 'medium'
            })
        
        if len(deposits) != summary.total_deposits_count and summary.total_deposits_count > 0:
            discrepancies.append({
                'field': 'Deposits Count',
                'summary_value': summary.total_deposits_count,
                'calculated_value': len(deposits),
                'difference': len(deposits) - summary.total_deposits_count,
                'severity': 'medium'
            })
        
        if not self._amounts_match(calc_withdrawals_total, summary.total_withdrawals):
            diff = calc_withdrawals_total - summary.total_withdrawals
            discrepancies.append({
                'field': 'Total Withdrawals',
                'summary_value': summary.total_withdrawals,
                'calculated_value': calc_withdrawals_total,
                'difference': diff,
                'severity': 'high' if abs(diff) > 100 else 'medium'
            })
        
        if not self._amounts_match(calc_checks_total, summary.total_checks):
            diff = calc_checks_total - summary.total_checks
            discrepancies.append({
                'field': 'Total Checks',
                'summary_value': summary.total_checks,
                'calculated_value': calc_checks_total,
                'difference': diff,
                'severity': 'medium'
            })
        
        if summary.beginning_balance > 0 and summary.ending_balance > 0:
            expected_ending = (
                summary.beginning_balance 
                + summary.total_deposits 
                - summary.total_withdrawals 
                - summary.total_checks 
                - summary.total_fees
            )
            if not self._amounts_match(expected_ending, summary.ending_balance):
                warnings.append(
                    f"Balance calculation check: Beginning (${summary.beginning_balance:,.2f}) "
                    f"+ Deposits (${summary.total_deposits:,.2f}) "
                    f"- Withdrawals (${summary.total_withdrawals:,.2f}) "
                    f"= ${expected_ending:,.2f}, but Ending Balance is ${summary.ending_balance:,.2f}"
                )
        
        high_severity = len([d for d in discrepancies if d['severity'] == 'high'])
        medium_severity = len([d for d in discrepancies if d['severity'] == 'medium'])
        
        if high_severity > 0:
            confidence = max(0.0, 0.5 - (high_severity * 0.15))
        elif medium_severity > 0:
            confidence = max(0.5, 0.9 - (medium_severity * 0.1))
        else:
            confidence = 1.0
        
        return VerificationResult(
            is_valid=len(discrepancies) == 0,
            discrepancies=discrepancies,
            summary_totals=summary_totals,
            calculated_totals=calculated_totals,
            confidence_score=confidence,
            warnings=warnings
        )
    
    def _amounts_match(self, amount1: float, amount2: float) -> bool:
        """Check if two amounts match within tolerance"""
        if amount2 == 0:
            return abs(amount1) <= self.TOLERANCE_ABSOLUTE
        
        abs_diff = abs(amount1 - amount2)
        pct_diff = abs_diff / abs(amount2) if amount2 != 0 else float('inf')
        
        return abs_diff <= self.TOLERANCE_ABSOLUTE or pct_diff <= self.TOLERANCE_PERCENT
    
    def _is_deposit(self, txn: Dict) -> bool:
        """Check if transaction is a deposit/credit"""
        txn_type = str(txn.get('type', '')).lower()
        return any(keyword in txn_type for keyword in ['deposit', 'credit', 'addition'])
    
    def _is_withdrawal(self, txn: Dict) -> bool:
        """Check if transaction is a withdrawal/debit (excluding checks and fees)"""
        txn_type = str(txn.get('type', '')).lower()
        if self._is_check(txn) or self._is_fee(txn):
            return False
        return any(keyword in txn_type for keyword in ['withdrawal', 'debit', 'ach', 'electronic'])
    
    def _is_check(self, txn: Dict) -> bool:
        """Check if transaction is a check payment"""
        txn_type = str(txn.get('type', '')).lower()
        desc = str(txn.get('description', '')).lower()
        return 'check' in txn_type or 'check paid' in desc
    
    def _is_fee(self, txn: Dict) -> bool:
        """Check if transaction is a fee"""
        txn_type = str(txn.get('type', '')).lower()
        desc = str(txn.get('description', '')).lower()
        return 'fee' in txn_type or 'service fee' in desc or 'monthly fee' in desc


def verify_koncile_extraction(api_response: Dict) -> VerificationResult:
    """
    Main function to verify a Koncile extraction response
    
    Args:
        api_response: Full response from Koncile API with General_fields and Line_fields
        
    Returns:
        VerificationResult with validation status
    """
    client = KoncileClient()
    verifier = StatementVerifier()
    
    general_fields = api_response.get('General_fields', {})
    line_fields = api_response.get('Line_fields', {})
    
    summary = client.parse_summary(general_fields)
    transactions = client.parse_transactions(line_fields)
    
    return verifier.verify(summary, transactions)


def verify_csv_against_summary(
    csv_transactions: List[Dict],
    summary_data: Dict
) -> VerificationResult:
    """
    Verify CSV transaction data against manually provided summary
    
    Args:
        csv_transactions: List of transaction dicts from CSV
        summary_data: Dict with summary values:
            - beginning_balance
            - ending_balance
            - deposits_total
            - deposits_count
            - withdrawals_total (electronic + atm)
            - checks_total
            - fees_total
            
    Returns:
        VerificationResult
    """
    summary = BankStatementSummary(
        beginning_balance=summary_data.get('beginning_balance', 0),
        ending_balance=summary_data.get('ending_balance', 0),
        total_deposits=summary_data.get('deposits_total', 0),
        total_deposits_count=summary_data.get('deposits_count', 0),
        total_withdrawals=summary_data.get('withdrawals_total', 0),
        total_withdrawals_count=summary_data.get('withdrawals_count', 0),
        total_checks=summary_data.get('checks_total', 0),
        total_checks_count=summary_data.get('checks_count', 0),
        total_fees=summary_data.get('fees_total', 0),
        total_fees_count=summary_data.get('fees_count', 0),
        statement_period_start=summary_data.get('period_start', ''),
        statement_period_end=summary_data.get('period_end', ''),
        account_holder=summary_data.get('account_holder', ''),
        account_number=summary_data.get('account_number', ''),
        bank_name=summary_data.get('bank_name', '')
    )
    
    verifier = StatementVerifier()
    return verifier.verify(summary, csv_transactions)


def extract_with_koncile(file_path: str, max_poll_seconds: int = 1800) -> Tuple[Dict, str, VerificationResult]:
    """
    Complete extraction flow using Koncile API
    
    1. Upload document
    2. Poll for completion
    3. Parse results
    4. Verify against summary
    
    Args:
        file_path: Path to PDF file
        max_poll_seconds: Maximum time to wait for extraction (default: 30 minutes)
        
    Returns:
        Tuple of (extracted_data, reasoning_log, verification_result)
    """
    import time
    
    client = KoncileClient()
    
    if not client.is_configured():
        no_config_verification = VerificationResult(
            is_valid=False,
            discrepancies=[],
            summary_totals={},
            calculated_totals={},
            confidence_score=0.0,
            warnings=["Koncile API not configured"]
        )
        return {
            'error': 'Koncile API not configured',
            'transactions': [],
            'info_needed': {},
            'extraction_source': 'koncile',
            'verification': {
                'is_valid': False,
                'confidence_score': 0.0,
                'discrepancies': [],
                'warnings': ["Koncile API not configured"]
            },
            'daily_positions': [],
            'weekly_positions': [],
            'monthly_positions_non_mca': [],
            'other_liabilities': [],
        }, "Koncile API key not set", no_config_verification
    
    reasoning_parts = []
    reasoning_parts.append(f"Starting Koncile extraction for: {file_path}")
    
    try:
        upload_response = client.upload_document(file_path)
        
        task_ids = upload_response.get('task_ids', [])
        if not task_ids:
            task_id = upload_response.get('task_id') or upload_response.get('id')
            if task_id:
                task_ids = [task_id]
        
        if not task_ids:
            reasoning_parts.append(f"Upload response: {upload_response}")
            no_task_verification = VerificationResult(
                is_valid=False,
                discrepancies=[],
                summary_totals={},
                calculated_totals={},
                confidence_score=0.0,
                warnings=["Failed to get task_id from Koncile"]
            )
            return {
                'error': 'No task_id in Koncile response',
                'transactions': [],
                'info_needed': {},
                'extraction_source': 'koncile',
                'verification': {
                    'is_valid': False,
                    'confidence_score': 0.0,
                    'discrepancies': [],
                    'warnings': ["Failed to get task_id from Koncile"]
                },
                'daily_positions': [],
                'weekly_positions': [],
                'monthly_positions_non_mca': [],
                'other_liabilities': [],
            }, "\n".join(reasoning_parts), no_task_verification
        
        task_id = task_ids[0]
        reasoning_parts.append(f"Upload successful. Task ID: {task_id}")
        reasoning_parts.append(f"[RECOVERY INFO] If this times out, use task_id: {task_id} to resume")
        print(f"Koncile Task ID: {task_id} - polling for results...")
        
        start_time = time.time()
        status = 'IN PROGRESS'
        results = None
        poll_count = 0
        last_log_time = start_time
        
        while status == 'IN PROGRESS' and (time.time() - start_time) < max_poll_seconds:
            time.sleep(5)  # Poll every 5 seconds
            poll_count += 1
            results = client.get_task_results(task_id)
            status = results.get('status', 'unknown')
            
            elapsed = int(time.time() - start_time)
            # Log progress every 30 seconds to avoid spam
            if time.time() - last_log_time >= 30:
                reasoning_parts.append(f"[{elapsed}s] Still waiting... Status: {status}")
                print(f"Koncile [{elapsed}s]: Status = {status}")
                last_log_time = time.time()
        
        # DUPLICATE status means Koncile cached the results from a previous upload - still valid
        if status not in ['DONE', 'done', 'completed', 'DUPLICATE']:
            elapsed = int(time.time() - start_time)
            reasoning_parts.append(f"Extraction did not complete after {elapsed}s. Final status: {status}")
            status_message = results.get('status_message', '') if results else ''
            if status_message:
                reasoning_parts.append(f"Status message: {status_message}")
            incomplete_verification = VerificationResult(
                is_valid=False,
                discrepancies=[],
                summary_totals={},
                calculated_totals={},
                confidence_score=0.0,
                warnings=[f"Koncile extraction failed with status: {status}"]
            )
            return {
                'error': f'Koncile extraction status: {status}',
                'transactions': [],
                'info_needed': {},
                'extraction_source': 'koncile',
                'verification': {
                    'is_valid': False,
                    'confidence_score': 0.0,
                    'discrepancies': [],
                    'warnings': [f"Koncile extraction failed with status: {status}"]
                },
                'daily_positions': [],
                'weekly_positions': [],
                'monthly_positions_non_mca': [],
                'other_liabilities': [],
            }, "\n".join(reasoning_parts), incomplete_verification
        
        reasoning_parts.append("Extraction completed successfully")
        
        if not results:
            results = client.get_task_results(task_id)
        
        general_fields = results.get('General_fields', results.get('general_fields', {}))
        line_fields = results.get('Line_fields', results.get('line_fields', {}))
        
        summary = client.parse_summary(general_fields)
        transactions = client.parse_transactions(line_fields)
        
        reasoning_parts.append(f"Parsed {len(transactions)} transactions")
        reasoning_parts.append(f"Account: {summary.account_number}")
        reasoning_parts.append(f"Period: {summary.statement_period_start} to {summary.statement_period_end}")
        reasoning_parts.append(f"Beginning Balance: ${summary.beginning_balance:,.2f}")
        reasoning_parts.append(f"Ending Balance: ${summary.ending_balance:,.2f}")
        reasoning_parts.append(f"Total Deposits: ${summary.total_deposits:,.2f}")
        reasoning_parts.append(f"Total Withdrawals: ${summary.total_withdrawals:,.2f}")
        
        verifier = StatementVerifier()
        verification = verifier.verify(summary, transactions)
        
        if verification.is_valid:
            reasoning_parts.append(f"✅ Verification PASSED - Confidence: {verification.confidence_score:.0%}")
        else:
            reasoning_parts.append(f"⚠️ Verification found {len(verification.discrepancies)} discrepancies")
            for d in verification.discrepancies:
                reasoning_parts.append(f"  - {d['field']}: Expected ${d['summary_value']:,.2f}, Got ${d['calculated_value']:,.2f}")
        
        deposits = [t for t in transactions if 'credit' in str(t.get('type', '')).lower() or 'deposit' in str(t.get('type', '')).lower()]
        withdrawals = [t for t in transactions if 'debit' in str(t.get('type', '')).lower() or 'withdrawal' in str(t.get('type', '')).lower()]
        
        total_deposits = sum(abs(t['amount']) for t in deposits)
        total_withdrawals = sum(abs(t['amount']) for t in withdrawals)
        avg_monthly_income = total_deposits / max(1, len(set(t.get('date', '')[:7] for t in deposits if t.get('date'))))
        
        extracted_data = {
            'transactions': transactions,
            'info_needed': {
                'annual_income': total_deposits,
                'average_monthly_income': avg_monthly_income,
                'total_monthly_payments': total_withdrawals / max(1, len(set(t.get('date', '')[:7] for t in withdrawals if t.get('date')))),
                'beginning_balance': summary.beginning_balance,
                'ending_balance': summary.ending_balance,
                'length_of_deal_months': 1,
            },
            'bank_accounts': {
                summary.account_number: {
                    'bank_name': summary.bank_name,
                    'account_holder': summary.account_holder,
                    'period_start': summary.statement_period_start,
                    'period_end': summary.statement_period_end,
                }
            },
            'koncile_summary': {
                'beginning_balance': summary.beginning_balance,
                'ending_balance': summary.ending_balance,
                'total_deposits': summary.total_deposits,
                'total_deposits_count': summary.total_deposits_count,
                'total_withdrawals': summary.total_withdrawals,
                'total_withdrawals_count': summary.total_withdrawals_count,
                'total_checks': summary.total_checks,
                'total_fees': summary.total_fees,
            },
            'verification': {
                'is_valid': verification.is_valid,
                'confidence_score': verification.confidence_score,
                'discrepancies': verification.discrepancies,
                'warnings': verification.warnings
            },
            'extraction_source': 'koncile',
            'task_id': task_id,
            'daily_positions': [],
            'weekly_positions': [],
            'monthly_positions_non_mca': [],
            'other_liabilities': [],
        }
        
        return extracted_data, "\n".join(reasoning_parts), verification
        
    except requests.exceptions.RequestException as e:
        reasoning_parts.append(f"API request error: {str(e)}")
        error_verification = VerificationResult(
            is_valid=False,
            discrepancies=[],
            summary_totals={},
            calculated_totals={},
            confidence_score=0.0,
            warnings=[f"API error: {str(e)}"]
        )
        return {
            'error': str(e),
            'transactions': [],
            'info_needed': {},
            'extraction_source': 'koncile',
            'verification': {
                'is_valid': False,
                'confidence_score': 0.0,
                'discrepancies': [],
                'warnings': [f"API error: {str(e)}"]
            },
            'daily_positions': [],
            'weekly_positions': [],
            'monthly_positions_non_mca': [],
            'other_liabilities': [],
        }, "\n".join(reasoning_parts), error_verification
    except Exception as e:
        reasoning_parts.append(f"Unexpected error: {str(e)}")
        error_verification = VerificationResult(
            is_valid=False,
            discrepancies=[],
            summary_totals={},
            calculated_totals={},
            confidence_score=0.0,
            warnings=[f"Error: {str(e)}"]
        )
        return {
            'error': str(e),
            'transactions': [],
            'info_needed': {},
            'extraction_source': 'koncile',
            'verification': {
                'is_valid': False,
                'confidence_score': 0.0,
                'discrepancies': [],
                'warnings': [f"Error: {str(e)}"]
            },
            'daily_positions': [],
            'weekly_positions': [],
            'monthly_positions_non_mca': [],
            'other_liabilities': [],
        }, "\n".join(reasoning_parts), error_verification


def format_verification_report(result: VerificationResult) -> str:
    """Format verification result as human-readable report"""
    lines = []
    lines.append("=" * 60)
    lines.append("BANK STATEMENT VERIFICATION REPORT")
    lines.append("=" * 60)
    
    if result.is_valid:
        lines.append("\n✅ VERIFICATION PASSED - All totals match!")
        lines.append(f"   Confidence Score: {result.confidence_score:.0%}")
    else:
        lines.append(f"\n⚠️ VERIFICATION FOUND {len(result.discrepancies)} DISCREPANCIES")
        lines.append(f"   Confidence Score: {result.confidence_score:.0%}")
    
    lines.append("\n--- SUMMARY vs CALCULATED ---")
    lines.append(f"{'Category':<25} {'Summary':>15} {'Calculated':>15} {'Match':>10}")
    lines.append("-" * 65)
    
    categories = [
        ('Deposits Total', 'deposits_total'),
        ('Deposits Count', 'deposits_count'),
        ('Withdrawals Total', 'withdrawals_total'),
        ('Withdrawals Count', 'withdrawals_count'),
        ('Checks Total', 'checks_total'),
        ('Checks Count', 'checks_count'),
        ('Fees Total', 'fees_total'),
        ('Fees Count', 'fees_count'),
    ]
    
    for label, key in categories:
        summary_val = result.summary_totals.get(key, 0)
        calc_val = result.calculated_totals.get(key, 0)
        
        if 'count' in key.lower():
            match = "✓" if summary_val == calc_val else "✗"
            lines.append(f"{label:<25} {summary_val:>15} {calc_val:>15} {match:>10}")
        else:
            match = "✓" if abs(summary_val - calc_val) < 1.0 else "✗"
            lines.append(f"{label:<25} ${summary_val:>14,.2f} ${calc_val:>14,.2f} {match:>10}")
    
    if result.discrepancies:
        lines.append("\n--- DISCREPANCIES ---")
        for d in result.discrepancies:
            severity_icon = "🔴" if d['severity'] == 'high' else "🟡"
            lines.append(f"{severity_icon} {d['field']}:")
            lines.append(f"   Summary: ${d['summary_value']:,.2f}")
            lines.append(f"   Calculated: ${d['calculated_value']:,.2f}")
            lines.append(f"   Difference: ${d['difference']:,.2f}")
    
    if result.warnings:
        lines.append("\n--- WARNINGS ---")
        for w in result.warnings:
            lines.append(f"⚠️ {w}")
    
    lines.append("\n" + "=" * 60)
    
    return "\n".join(lines)
