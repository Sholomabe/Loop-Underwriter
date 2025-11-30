"""
Logic Engine - Core Underwriting Calculations

This module processes raw transaction data and calculates key underwriting metrics:
- Income & Revenue metrics
- Monthly breakdowns
- MCA/Diesel payment detection
- Ratios and position tables
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
from fuzzywuzzy import fuzz, process
from transfer_hunter import safe_float, sanitize_transactions, detect_payment_frequency


class LogicEngine:
    """
    Core processing engine for underwriting calculations.
    Handles multiple bank accounts combined or separated.
    """
    
    def __init__(self, transactions: List[Dict], known_vendors: Optional[List[Dict]] = None):
        """
        Initialize the logic engine with transaction data.
        
        Args:
            transactions: List of transaction dicts with keys:
                - date, description, amount, type (debit/credit), source_account_id
            known_vendors: List of known vendor dicts for matching
        """
        self.transactions = sanitize_transactions(transactions)
        self.known_vendors = known_vendors or []
        self.df = self._prepare_dataframe()
        
    def _prepare_dataframe(self) -> pd.DataFrame:
        """Convert transactions to DataFrame with proper types."""
        if not self.transactions:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.transactions)
        
        if 'amount' in df.columns:
            df['amount'] = df['amount'].apply(safe_float)
        
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        elif 'transaction_date' in df.columns:
            df['date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
        
        if 'type' in df.columns:
            df['type'] = df['type'].str.lower().fillna('unknown')
        else:
            df['type'] = df['amount'].apply(lambda x: 'credit' if x > 0 else 'debit')
        
        if 'source_account_id' not in df.columns:
            df['source_account_id'] = 'default'
        
        df['month'] = df['date'].dt.to_period('M') if 'date' in df.columns else None
        df['description_clean'] = df.get('description', '').fillna('').str.upper().str.strip()
        
        return df
    
    def calculate_income_metrics(self) -> Dict:
        """
        Calculate all income and revenue metrics.
        
        Returns:
            Dict with total_income, deductions, net_revenue, avg_monthly, annual
        """
        if self.df.empty:
            return {
                'total_income': 0,
                'deductions': 0,
                'net_revenue': 0,
                'average_monthly_income': 0,
                'annual_income': 0,
                'months_analyzed': 0
            }
        
        credits = self.df[
            ((self.df['type'] == 'credit') | (self.df['amount'] > 0)) &
            (~self.df.get('is_internal_transfer', False).fillna(False))
        ]
        total_income = credits['amount'].abs().sum()
        
        deduction_keywords = ['FEE', 'CHARGE', 'NSF', 'OVERDRAFT', 'RETURN', 'REVERSAL']
        deductions_mask = self.df['description_clean'].str.contains('|'.join(deduction_keywords), na=False)
        deductions = self.df[deductions_mask & (self.df['amount'] < 0)]['amount'].abs().sum()
        
        net_revenue = total_income - deductions
        
        months = self.df['month'].nunique() if 'month' in self.df.columns else 1
        months = max(months, 1)
        
        avg_monthly = net_revenue / months
        annual = avg_monthly * 12
        
        return {
            'total_income': round(total_income, 2),
            'deductions': round(deductions, 2),
            'net_revenue': round(net_revenue, 2),
            'average_monthly_income': round(avg_monthly, 2),
            'annual_income': round(annual, 2),
            'months_analyzed': months
        }
    
    def get_monthly_revenue_breakdown(self, last_n_months: int = 12) -> List[Dict]:
        """
        Generate monthly revenue breakdown table.
        
        Args:
            last_n_months: Number of months to include
            
        Returns:
            List of dicts with month and revenue
        """
        if self.df.empty or 'month' not in self.df.columns:
            return []
        
        credits = self.df[
            ((self.df['type'] == 'credit') | (self.df['amount'] > 0)) &
            (~self.df.get('is_internal_transfer', False).fillna(False))
        ]
        
        monthly = credits.groupby('month')['amount'].apply(lambda x: x.abs().sum()).reset_index()
        monthly.columns = ['month', 'revenue']
        monthly = monthly.sort_values('month', ascending=False).head(last_n_months)
        
        result = []
        for _, row in monthly.iterrows():
            result.append({
                'month': str(row['month']),
                'revenue': round(row['revenue'], 2)
            })
        
        return result
    
    def detect_mca_positions(self) -> Dict:
        """
        Detect MCA positions (daily and weekly payments).
        
        Returns:
            Dict with daily_positions, weekly_positions, and totals
        """
        from openai_integration import MCA_KEYWORDS
        
        if self.df.empty:
            return {
                'daily_positions': [],
                'weekly_positions': [],
                'total_daily_payment': 0,
                'total_weekly_payment': 0,
                'total_monthly_mca_payment': 0
            }
        
        debits = self.df[
            (self.df['type'] == 'debit') | (self.df['amount'] < 0)
        ].copy()
        
        if debits.empty:
            return {
                'daily_positions': [],
                'weekly_positions': [],
                'total_daily_payment': 0,
                'total_weekly_payment': 0,
                'total_monthly_mca_payment': 0
            }
        
        debits['is_mca'] = debits['description_clean'].apply(
            lambda x: any(kw in x for kw in MCA_KEYWORDS) if x else False
        )
        
        mca_debits = debits[debits['is_mca']]
        
        merchant_groups = {}
        for _, row in mca_debits.iterrows():
            name = self._extract_merchant_name(row['description_clean'])
            amount = abs(row['amount'])
            date = row.get('date')
            
            if name not in merchant_groups:
                merchant_groups[name] = []
            merchant_groups[name].append({'amount': amount, 'date': date})
        
        daily_positions = []
        weekly_positions = []
        
        for merchant, txns in merchant_groups.items():
            if len(txns) < 2:
                continue
            
            frequency = detect_payment_frequency([{'amount': t['amount'], 'date': t['date']} for t in txns])
            avg_amount = sum(t['amount'] for t in txns) / len(txns)
            
            position = {
                'name': merchant,
                'amount': round(avg_amount, 2),
                'frequency': frequency,
                'occurrence_count': len(txns),
                'current_balance': 0
            }
            
            if frequency == 'daily':
                position['monthly_payment'] = round(avg_amount * 22, 2)
                daily_positions.append(position)
            elif frequency == 'weekly':
                position['monthly_payment'] = round(avg_amount * 4.33, 2)
                weekly_positions.append(position)
        
        total_daily = sum(p['monthly_payment'] for p in daily_positions)
        total_weekly = sum(p['monthly_payment'] for p in weekly_positions)
        
        return {
            'daily_positions': daily_positions,
            'weekly_positions': weekly_positions,
            'total_daily_payment': round(total_daily, 2),
            'total_weekly_payment': round(total_weekly, 2),
            'total_monthly_mca_payment': round(total_daily + total_weekly, 2)
        }
    
    def detect_diesel_payments(self) -> Dict:
        """
        Detect Diesel-specific payments (scenario calculation).
        
        Returns:
            Dict with diesel payments and projections
        """
        if self.df.empty:
            return {
                'diesel_total_monthly_payments': 0,
                'diesel_positions': []
            }
        
        diesel_keywords = ['DIESEL', 'FUEL', 'FUEL ADVANCE']
        
        debits = self.df[
            (self.df['type'] == 'debit') | (self.df['amount'] < 0)
        ]
        
        diesel_mask = debits['description_clean'].str.contains('|'.join(diesel_keywords), na=False)
        diesel_txns = debits[diesel_mask]
        
        if diesel_txns.empty:
            return {
                'diesel_total_monthly_payments': 0,
                'diesel_positions': []
            }
        
        total = diesel_txns['amount'].abs().sum()
        months = self.df['month'].nunique() if 'month' in self.df.columns else 1
        months = max(months, 1)
        
        monthly_avg = total / months
        
        return {
            'diesel_total_monthly_payments': round(monthly_avg, 2),
            'diesel_positions': [{
                'name': 'Diesel/Fuel',
                'total': round(total, 2),
                'monthly_average': round(monthly_avg, 2),
                'occurrence_count': len(diesel_txns)
            }]
        }
    
    def calculate_total_monthly_payments(self) -> Dict:
        """
        Calculate total monthly payments including all MCA/Loan payments.
        
        Returns:
            Dict with payment totals and breakdown
        """
        mca = self.detect_mca_positions()
        diesel = self.detect_diesel_payments()
        
        total_mca = mca['total_monthly_mca_payment']
        total_diesel = diesel['diesel_total_monthly_payments']
        
        return {
            'total_monthly_payments': round(total_mca, 2),
            'diesel_total_monthly_payments': round(total_diesel, 2),
            'total_monthly_payments_with_diesel': round(total_mca + total_diesel, 2),
            'breakdown': {
                'daily_mca': mca['total_daily_payment'],
                'weekly_mca': mca['total_weekly_payment'],
                'diesel': total_diesel
            }
        }
    
    def calculate_ratios(self, new_deal_payment: float = 0) -> Dict:
        """
        Calculate underwriting ratios.
        
        Args:
            new_deal_payment: Optional new deal monthly payment for projection
            
        Returns:
            Dict with key ratios
        """
        income = self.calculate_income_metrics()
        payments = self.calculate_total_monthly_payments()
        
        avg_monthly_income = income['average_monthly_income']
        annual_income = income['annual_income']
        total_monthly_payments = payments['total_monthly_payments_with_diesel']
        
        if avg_monthly_income > 0:
            payment_to_income_pct = (total_monthly_payments / avg_monthly_income) * 100
            payment_with_new_deal_pct = ((total_monthly_payments + new_deal_payment) / avg_monthly_income) * 100
        else:
            payment_to_income_pct = 0
            payment_with_new_deal_pct = 0
        
        return {
            'monthly_payment_to_income_pct': round(payment_to_income_pct, 2),
            'monthly_payment_with_new_deal_pct': round(payment_with_new_deal_pct, 2),
            'available_for_new_payment': round(avg_monthly_income * 0.5 - total_monthly_payments, 2) if avg_monthly_income > 0 else 0,
            'projected_balance_after_new_deal': round(avg_monthly_income - (total_monthly_payments + new_deal_payment), 2) if avg_monthly_income > 0 else 0
        }
    
    def generate_positions_table(self) -> List[Dict]:
        """
        Generate the daily positions table with current balances.
        
        Returns:
            List of position dicts with name, balance, payment
        """
        mca = self.detect_mca_positions()
        
        positions = []
        
        for p in mca['daily_positions']:
            positions.append({
                'name': p['name'],
                'current_balance': p.get('current_balance', 0),
                'daily_payment': p['amount'],
                'weekly_payment': 0,
                'frequency': 'Daily',
                'monthly_payment': p['monthly_payment']
            })
        
        for p in mca['weekly_positions']:
            positions.append({
                'name': p['name'],
                'current_balance': p.get('current_balance', 0),
                'daily_payment': 0,
                'weekly_payment': p['amount'],
                'frequency': 'Weekly',
                'monthly_payment': p['monthly_payment']
            })
        
        return positions
    
    def get_complete_analysis(self, new_deal_payment: float = 0) -> Dict:
        """
        Get complete underwriting analysis.
        
        Args:
            new_deal_payment: Optional new deal monthly payment for projection
            
        Returns:
            Complete analysis dict with all metrics
        """
        income = self.calculate_income_metrics()
        monthly_breakdown = self.get_monthly_revenue_breakdown()
        mca = self.detect_mca_positions()
        diesel = self.detect_diesel_payments()
        payments = self.calculate_total_monthly_payments()
        ratios = self.calculate_ratios(new_deal_payment)
        positions = self.generate_positions_table()
        
        return {
            'income_metrics': income,
            'monthly_revenue_breakdown': monthly_breakdown,
            'mca_positions': mca,
            'diesel': diesel,
            'payments': payments,
            'ratios': ratios,
            'positions_table': positions,
            'summary': {
                'total_income': income['total_income'],
                'net_revenue': income['net_revenue'],
                'average_monthly_income': income['average_monthly_income'],
                'annual_income': income['annual_income'],
                'total_monthly_payments': payments['total_monthly_payments_with_diesel'],
                'payment_to_income_ratio': ratios['monthly_payment_to_income_pct'],
                'months_analyzed': income['months_analyzed'],
                'position_count': len(positions)
            }
        }
    
    def _extract_merchant_name(self, description: str) -> str:
        """Extract clean merchant name from description."""
        if not description:
            return "Unknown"
        
        prefixes = ['ACH DEBIT', 'ACH CREDIT', 'WIRE', 'TRANSFER', 'PAYMENT TO', 'PAYMENT FROM']
        desc = description.upper().strip()
        
        for prefix in prefixes:
            if desc.startswith(prefix):
                desc = desc[len(prefix):].strip()
        
        words = desc.split()[:4]
        if words:
            return ' '.join(words).title()
        
        return description[:30].title()


class PatternRecognizer:
    """
    Advanced pattern recognition for transactions.
    Detects transfers, recurring payments, and anomalies.
    """
    
    def __init__(self, transactions: List[Dict], window_days: int = 2):
        """
        Initialize pattern recognizer.
        
        Args:
            transactions: List of transaction dicts
            window_days: Window for transfer matching (default 2 days)
        """
        self.transactions = sanitize_transactions(transactions)
        self.window_days = window_days
        self.df = self._prepare_dataframe()
    
    def _prepare_dataframe(self) -> pd.DataFrame:
        """Convert transactions to DataFrame."""
        if not self.transactions:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.transactions)
        
        if 'amount' in df.columns:
            df['amount'] = df['amount'].apply(safe_float)
        
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        elif 'transaction_date' in df.columns:
            df['date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
        
        if 'type' not in df.columns:
            df['type'] = df['amount'].apply(lambda x: 'credit' if x > 0 else 'debit')
        
        if 'source_account_id' not in df.columns:
            df['source_account_id'] = 'default'
        
        df['description_clean'] = df.get('description', '').fillna('').str.upper().str.strip()
        
        return df
    
    def detect_internal_transfers(self) -> List[Dict]:
        """
        Detect internal transfers between accounts.
        
        Logic: If Bank A has debit of $X and Bank B has credit of $X 
        within 2-day window, tag both as "Internal Transfer".
        
        Returns:
            List of detected transfer pairs
        """
        if self.df.empty or self.df['source_account_id'].nunique() < 2:
            return []
        
        transfers = []
        matched_ids = set()
        
        debits = self.df[(self.df['type'] == 'debit') | (self.df['amount'] < 0)].copy()
        credits = self.df[(self.df['type'] == 'credit') | (self.df['amount'] > 0)].copy()
        
        for _, debit in debits.iterrows():
            if debit.get('id') in matched_ids:
                continue
            
            debit_amount = abs(debit['amount'])
            debit_date = debit['date']
            debit_account = debit['source_account_id']
            
            if pd.isna(debit_date):
                continue
            
            date_min = debit_date - timedelta(days=self.window_days)
            date_max = debit_date + timedelta(days=self.window_days)
            
            potential_matches = credits[
                (credits['source_account_id'] != debit_account) &
                (credits['date'] >= date_min) &
                (credits['date'] <= date_max) &
                (credits['amount'].abs().between(debit_amount * 0.99, debit_amount * 1.01)) &
                (~credits['id'].isin(matched_ids) if 'id' in credits.columns else True)
            ]
            
            if not potential_matches.empty:
                match = potential_matches.iloc[0]
                
                transfer = {
                    'debit_id': debit.get('id'),
                    'credit_id': match.get('id'),
                    'amount': debit_amount,
                    'debit_account': debit_account,
                    'credit_account': match['source_account_id'],
                    'debit_date': str(debit_date),
                    'credit_date': str(match['date']),
                    'debit_description': debit.get('description', ''),
                    'credit_description': match.get('description', ''),
                    'days_apart': abs((match['date'] - debit_date).days)
                }
                transfers.append(transfer)
                
                if debit.get('id'):
                    matched_ids.add(debit['id'])
                if match.get('id'):
                    matched_ids.add(match['id'])
        
        return transfers
    
    def detect_recurring_patterns(self, min_occurrences: int = 4) -> List[Dict]:
        """
        Analyze debits to find recurring patterns (daily or weekly).
        
        Args:
            min_occurrences: Minimum occurrences to consider recurring
            
        Returns:
            List of detected recurring payment patterns
        """
        if self.df.empty:
            return []
        
        debits = self.df[(self.df['type'] == 'debit') | (self.df['amount'] < 0)].copy()
        
        if debits.empty:
            return []
        
        description_groups = defaultdict(list)
        for _, row in debits.iterrows():
            desc = row['description_clean']
            if desc:
                normalized = self._normalize_description(desc)
                description_groups[normalized].append({
                    'amount': abs(row['amount']),
                    'date': row['date'],
                    'description': row.get('description', '')
                })
        
        recurring = []
        for desc, txns in description_groups.items():
            if len(txns) < min_occurrences:
                continue
            
            frequency = self._detect_frequency_pattern(txns)
            if frequency in ['daily', 'weekly']:
                avg_amount = sum(t['amount'] for t in txns) / len(txns)
                
                recurring.append({
                    'description': desc,
                    'frequency': frequency,
                    'average_amount': round(avg_amount, 2),
                    'occurrence_count': len(txns),
                    'sample_dates': [str(t['date']) for t in txns[:5]],
                    'is_recurring': True
                })
        
        return recurring
    
    def detect_stop_start_patterns(self) -> List[Dict]:
        """
        Detect if recurring payments stopped and restarted or amounts changed.
        
        Returns:
            List of detected stop/start or refinance patterns
        """
        if self.df.empty:
            return []
        
        debits = self.df[(self.df['type'] == 'debit') | (self.df['amount'] < 0)].copy()
        debits = debits.sort_values('date')
        
        description_groups = defaultdict(list)
        for _, row in debits.iterrows():
            desc = self._normalize_description(row['description_clean'])
            if desc:
                description_groups[desc].append({
                    'amount': abs(row['amount']),
                    'date': row['date']
                })
        
        patterns = []
        for desc, txns in description_groups.items():
            if len(txns) < 3:
                continue
            
            sorted_txns = sorted(txns, key=lambda x: x['date'] if pd.notna(x['date']) else datetime.min)
            
            for i in range(1, len(sorted_txns)):
                if pd.isna(sorted_txns[i]['date']) or pd.isna(sorted_txns[i-1]['date']):
                    continue
                    
                days_gap = (sorted_txns[i]['date'] - sorted_txns[i-1]['date']).days
                
                if days_gap > 5:
                    patterns.append({
                        'description': desc,
                        'pattern_type': 'paused_resumed',
                        'gap_days': days_gap,
                        'pause_date': str(sorted_txns[i-1]['date']),
                        'resume_date': str(sorted_txns[i]['date'])
                    })
                
                prev_amount = sorted_txns[i-1]['amount']
                curr_amount = sorted_txns[i]['amount']
                if prev_amount > 0:
                    change_pct = abs(curr_amount - prev_amount) / prev_amount
                    if change_pct > 0.15:
                        patterns.append({
                            'description': desc,
                            'pattern_type': 'refinanced',
                            'old_amount': round(prev_amount, 2),
                            'new_amount': round(curr_amount, 2),
                            'change_percentage': round(change_pct * 100, 2),
                            'date': str(sorted_txns[i]['date'])
                        })
        
        return patterns
    
    def _normalize_description(self, description: str) -> str:
        """Normalize transaction description for grouping."""
        import re
        if not description:
            return ""
        
        desc = description.upper().strip()
        desc = re.sub(r'\d{4,}', 'XXXX', desc)
        desc = re.sub(r'#\d+', '', desc)
        desc = re.sub(r'\s+', ' ', desc)
        
        return desc.strip()
    
    def _detect_frequency_pattern(self, transactions: List[Dict]) -> str:
        """Detect frequency pattern from transaction dates."""
        if len(transactions) < 2:
            return 'unknown'
        
        dates = sorted([t['date'] for t in transactions if pd.notna(t['date'])])
        if len(dates) < 2:
            return 'unknown'
        
        gaps = []
        for i in range(1, len(dates)):
            gap = (dates[i] - dates[i-1]).days
            if gap > 0:
                gaps.append(gap)
        
        if not gaps:
            return 'unknown'
        
        avg_gap = sum(gaps) / len(gaps)
        
        if avg_gap <= 2:
            return 'daily'
        elif avg_gap <= 10:
            return 'weekly'
        elif avg_gap <= 35:
            return 'monthly'
        else:
            return 'irregular'


class VendorMatcher:
    """
    Vendor learning system with fuzzy matching.
    Matches transaction descriptions against known vendors.
    """
    
    def __init__(self, known_vendors: List[Dict]):
        """
        Initialize vendor matcher.
        
        Args:
            known_vendors: List of known vendor dicts with name, category, match_type
        """
        self.known_vendors = known_vendors or []
        self.fuzzy_threshold = 80
    
    def match_transaction(self, description: str) -> Optional[Dict]:
        """
        Match a transaction description against known vendors.
        
        Args:
            description: Transaction description
            
        Returns:
            Matched vendor dict or None
        """
        if not description or not self.known_vendors:
            return None
        
        desc_upper = description.upper().strip()
        
        for vendor in self.known_vendors:
            vendor_name = vendor.get('name', '').upper()
            match_type = vendor.get('match_type', 'fuzzy')
            
            if match_type == 'exact':
                if desc_upper == vendor_name:
                    return vendor
            elif match_type == 'contains':
                if vendor_name in desc_upper:
                    return vendor
            else:
                ratio = fuzz.partial_ratio(desc_upper, vendor_name)
                if ratio >= self.fuzzy_threshold:
                    return vendor
        
        return None
    
    def categorize_transactions(self, transactions: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """
        Categorize transactions using known vendors.
        
        Args:
            transactions: List of transaction dicts
            
        Returns:
            Tuple of (categorized_transactions, unknown_transactions)
        """
        categorized = []
        unknown = []
        
        for txn in transactions:
            description = txn.get('description', '')
            match = self.match_transaction(description)
            
            if match:
                txn_copy = txn.copy()
                txn_copy['matched_vendor'] = match.get('name')
                txn_copy['vendor_category'] = match.get('category')
                txn_copy['is_mca_lender'] = match.get('is_mca_lender', False)
                categorized.append(txn_copy)
            else:
                unknown.append(txn)
        
        return categorized, unknown
    
    def find_unknown_recurring(self, transactions: List[Dict], min_occurrences: int = 3) -> List[Dict]:
        """
        Find unknown recurring transactions that need human review.
        
        Args:
            transactions: List of unknown transaction dicts
            min_occurrences: Minimum occurrences to flag as recurring
            
        Returns:
            List of unknown recurring patterns
        """
        if not transactions:
            return []
        
        description_groups = defaultdict(list)
        for txn in transactions:
            desc = self._normalize_description(txn.get('description', ''))
            if desc:
                description_groups[desc].append(txn)
        
        unknown_recurring = []
        for desc, txns in description_groups.items():
            if len(txns) >= min_occurrences:
                amounts = [abs(safe_float(t.get('amount', 0))) for t in txns]
                avg_amount = sum(amounts) / len(amounts)
                
                dates = []
                for t in txns:
                    d = t.get('date') or t.get('transaction_date')
                    if d:
                        dates.append(str(d))
                
                unknown_recurring.append({
                    'description': desc,
                    'normalized_name': desc.title(),
                    'average_amount': round(avg_amount, 2),
                    'occurrence_count': len(txns),
                    'sample_dates': dates[:5],
                    'sample_descriptions': [t.get('description', '') for t in txns[:3]]
                })
        
        return unknown_recurring
    
    def _normalize_description(self, description: str) -> str:
        """Normalize description for grouping."""
        import re
        if not description:
            return ""
        
        desc = description.upper().strip()
        desc = re.sub(r'\d{4,}', 'XXXX', desc)
        desc = re.sub(r'#\d+', '', desc)
        desc = re.sub(r'\s+', ' ', desc)
        
        return desc.strip()


def process_deal_transactions(
    transactions: List[Dict],
    known_vendors: Optional[List[Dict]] = None,
    new_deal_payment: float = 0
) -> Dict:
    """
    Main processing function for a deal's transactions.
    
    Args:
        transactions: List of transaction dicts
        known_vendors: Optional list of known vendor patterns
        new_deal_payment: Optional new deal monthly payment for projection
        
    Returns:
        Complete analysis with all metrics
    """
    engine = LogicEngine(transactions, known_vendors)
    analysis = engine.get_complete_analysis(new_deal_payment)
    
    pattern_recognizer = PatternRecognizer(transactions)
    
    analysis['internal_transfers'] = pattern_recognizer.detect_internal_transfers()
    analysis['recurring_patterns'] = pattern_recognizer.detect_recurring_patterns()
    analysis['stop_start_patterns'] = pattern_recognizer.detect_stop_start_patterns()
    
    if known_vendors:
        vendor_matcher = VendorMatcher(known_vendors)
        categorized, unknown = vendor_matcher.categorize_transactions(transactions)
        unknown_recurring = vendor_matcher.find_unknown_recurring(unknown)
        
        analysis['categorized_count'] = len(categorized)
        analysis['unknown_count'] = len(unknown)
        analysis['unknown_recurring'] = unknown_recurring
    
    return analysis
