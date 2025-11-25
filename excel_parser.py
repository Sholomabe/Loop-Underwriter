"""
Excel Parser for Underwriting Truth Files

Parses the 'underwriting' sheet (sheet 2) from uploaded Excel files.
Extracts all financial data including:
- Info Needed section (9 key metrics)
- Daily Positions (Name, Amount, Monthly Payment)
- Bank Account data (Total Income, Deductions, Net Revenue by month)
- Total Revenues by month
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple


def parse_underwriting_excel(file_path_or_buffer) -> Dict[str, Any]:
    """
    Parse the underwriting sheet from an Excel file.
    
    Returns a dictionary with all extracted data:
    {
        'info_needed': {
            'total_monthly_payments': float,
            'diesel_total_monthly_payments': float,
            'total_monthly_payments_with_diesel': float,
            'average_monthly_income': float,
            'annual_income': float,
            'length_of_deal_months': int,
            'holdback_percentage': float,
            'monthly_holdback': float,
            'monthly_payment_to_income_pct': float,
            'original_balance_to_annual_income_pct': float,
        },
        'daily_positions': [
            {'name': str, 'amount': float, 'monthly_payment': float},
            ...
        ],
        'bank_accounts': {
            'Bank Account 1': {
                'months': [
                    {'month': 'Month 1', 'total_income': float, 'deductions': float, 'net_revenue': float},
                    ...
                ]
            },
            'Bank Account 2': {...},
            ...
        },
        'total_revenues_by_month': {
            'Month 1': float,
            'Month 2': float,
            ...
        },
        'raw_preview': str  # First 30 rows as text for debugging
    }
    """
    result = {
        'info_needed': {},
        'daily_positions': [],
        'bank_accounts': {},
        'total_revenues_by_month': {},
        'raw_preview': '',
        'parse_log': []
    }
    
    try:
        # Try to read the 'underwriting' sheet specifically
        xl = pd.ExcelFile(file_path_or_buffer)
        sheet_names = xl.sheet_names
        result['parse_log'].append(f"Found sheets: {sheet_names}")
        
        # Find the underwriting sheet (case-insensitive)
        underwriting_sheet = None
        for name in sheet_names:
            if 'underwriting' in name.lower():
                underwriting_sheet = name
                break
        
        # If not found by name, try sheet index 1 (second sheet)
        if underwriting_sheet is None and len(sheet_names) > 1:
            underwriting_sheet = sheet_names[1]
            result['parse_log'].append(f"No 'underwriting' sheet found, using second sheet: {underwriting_sheet}")
        elif underwriting_sheet is None:
            underwriting_sheet = sheet_names[0]
            result['parse_log'].append(f"Only one sheet found, using: {underwriting_sheet}")
        else:
            result['parse_log'].append(f"Using underwriting sheet: {underwriting_sheet}")
        
        # Read the sheet without headers (treat as raw grid)
        df = pd.read_excel(xl, sheet_name=underwriting_sheet, header=None)
        result['parse_log'].append(f"Sheet has {len(df)} rows and {len(df.columns)} columns")
        
        # Store raw preview
        result['raw_preview'] = df.head(30).to_string()
        
        # Parse Info Needed Section
        result['info_needed'] = parse_info_needed_section(df, result['parse_log'])
        
        # Parse Daily Positions
        result['daily_positions'] = parse_daily_positions(df, result['parse_log'])
        
        # Parse Bank Account Data
        result['bank_accounts'] = parse_bank_accounts(df, result['parse_log'])
        
        # Parse Total Revenues by Month
        result['total_revenues_by_month'] = parse_total_revenues(df, result['parse_log'])
        
    except Exception as e:
        result['parse_log'].append(f"ERROR: {str(e)}")
    
    return result


def find_cell_location(df: pd.DataFrame, search_terms: List[str], exact: bool = False) -> Optional[Tuple[int, int]]:
    """Find the row and column index of a cell containing any of the search terms."""
    for row_idx in range(len(df)):
        for col_idx in range(len(df.columns)):
            cell_value = df.iloc[row_idx, col_idx]
            if pd.notna(cell_value):
                cell_str = str(cell_value).strip().lower()
                for term in search_terms:
                    term_lower = term.lower()
                    if exact:
                        if cell_str == term_lower:
                            return (row_idx, col_idx)
                    else:
                        if term_lower in cell_str:
                            return (row_idx, col_idx)
    return None


def get_value_at_offset(df: pd.DataFrame, row: int, col: int, row_offset: int = 0, col_offset: int = 1) -> Any:
    """Get the value at an offset from a given position."""
    target_row = row + row_offset
    target_col = col + col_offset
    if 0 <= target_row < len(df) and 0 <= target_col < len(df.columns):
        return df.iloc[target_row, target_col]
    return None


def parse_numeric(value: Any) -> float:
    """Parse a value to float, handling currency symbols and percentages."""
    if pd.isna(value) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        # Remove currency symbols, commas, and percentage signs
        cleaned = str(value).replace('$', '').replace(',', '').replace('%', '').strip()
        if cleaned == '' or cleaned == '-':
            return 0.0
        return float(cleaned)
    except:
        return 0.0


def parse_info_needed_section(df: pd.DataFrame, log: List[str]) -> Dict[str, Any]:
    """Parse the 'Info Needed For Sheet' section."""
    info = {
        'total_monthly_payments': 0.0,
        'diesel_total_monthly_payments': 0.0,
        'total_monthly_payments_with_diesel': 0.0,
        'average_monthly_income': 0.0,
        'annual_income': 0.0,
        'length_of_deal_months': 0,
        'holdback_percentage': 0.0,
        'monthly_holdback': 0.0,
        'monthly_payment_to_income_pct': 0.0,
        'original_balance_to_annual_income_pct': 0.0,
    }
    
    # Define search patterns for each field
    field_patterns = {
        'total_monthly_payments': ['total monthly payments', 'total monthly payment'],
        'diesel_total_monthly_payments': ["diesel's total monthly payments", "diesel total monthly", "diesel's total"],
        'total_monthly_payments_with_diesel': ['total monthly payments (including diesel', 'including diesel'],
        'average_monthly_income': ['average monthly income', 'avg monthly income'],
        'annual_income': ['annual income'],
        'length_of_deal_months': ['length of deal', 'deal length'],
        'holdback_percentage': ['holdback percentage', 'holdback %'],
        'monthly_holdback': ['monthly holdback'],
        'monthly_payment_to_income_pct': ['monthly payment to monthly income', 'payment to income'],
        'original_balance_to_annual_income_pct': ['original balance to annual income', 'balance to annual'],
    }
    
    for field_name, patterns in field_patterns.items():
        location = find_cell_location(df, patterns)
        if location:
            row, col = location
            # Try getting value to the right first
            value = get_value_at_offset(df, row, col, 0, 1)
            if pd.isna(value) or value is None:
                # Try next column over
                value = get_value_at_offset(df, row, col, 0, 2)
            
            parsed = parse_numeric(value)
            
            # Handle integer field
            if field_name == 'length_of_deal_months':
                info[field_name] = int(parsed)
            else:
                info[field_name] = parsed
            
            log.append(f"Found {field_name}: {info[field_name]} at row {row+1}, col {col+1}")
        else:
            log.append(f"Could not find: {field_name}")
    
    return info


def parse_daily_positions(df: pd.DataFrame, log: List[str]) -> List[Dict[str, Any]]:
    """Parse the Daily Positions section."""
    positions = []
    
    # Find "Daily Positions" header
    location = find_cell_location(df, ['daily positions'])
    if not location:
        log.append("Could not find 'Daily Positions' section")
        return positions
    
    start_row, start_col = location
    log.append(f"Found 'Daily Positions' at row {start_row+1}, col {start_col+1}")
    
    # Find the header row with Name, Amount, Monthly Payment
    header_row = None
    for row_offset in range(1, 5):
        if start_row + row_offset < len(df):
            row_values = [str(df.iloc[start_row + row_offset, c]).lower() if pd.notna(df.iloc[start_row + row_offset, c]) else '' 
                         for c in range(len(df.columns))]
            if any('name' in val for val in row_values):
                header_row = start_row + row_offset
                break
    
    if header_row is None:
        log.append("Could not find Daily Positions header row")
        return positions
    
    # Find column indices for Name, Amount, Monthly Payment
    name_col = None
    amount_col = None
    payment_col = None
    
    for col_idx in range(len(df.columns)):
        cell = str(df.iloc[header_row, col_idx]).lower() if pd.notna(df.iloc[header_row, col_idx]) else ''
        if 'name' in cell and name_col is None:
            name_col = col_idx
        elif 'amount' in cell and amount_col is None:
            amount_col = col_idx
        elif 'monthly payment' in cell or 'payment' in cell:
            payment_col = col_idx
    
    if name_col is None:
        log.append("Could not find 'Name' column in Daily Positions")
        return positions
    
    log.append(f"Daily Positions columns - Name: {name_col}, Amount: {amount_col}, Payment: {payment_col}")
    
    # Read position rows until we hit an empty name or a new section
    data_row = header_row + 1
    while data_row < len(df):
        name_value = df.iloc[data_row, name_col] if name_col is not None else None
        
        # Stop if name is empty or we hit a new section
        if pd.isna(name_value) or str(name_value).strip() == '':
            break
        if any(term in str(name_value).lower() for term in ['bank account', 'total', 'monthly revenue']):
            break
        
        position = {
            'name': str(name_value).strip(),
            'amount': parse_numeric(df.iloc[data_row, amount_col]) if amount_col is not None else 0.0,
            'monthly_payment': parse_numeric(df.iloc[data_row, payment_col]) if payment_col is not None else 0.0
        }
        positions.append(position)
        log.append(f"  Position: {position['name']} - Amount: ${position['amount']:,.2f}, Payment: ${position['monthly_payment']:,.2f}")
        
        data_row += 1
    
    log.append(f"Found {len(positions)} daily positions")
    return positions


def parse_bank_accounts(df: pd.DataFrame, log: List[str]) -> Dict[str, Any]:
    """Parse Bank Account data for multiple accounts."""
    bank_accounts = {}
    
    # Find all "Bank Account X" headers
    account_locations = []
    for row_idx in range(len(df)):
        for col_idx in range(len(df.columns)):
            cell_value = df.iloc[row_idx, col_idx]
            if pd.notna(cell_value) and 'bank account' in str(cell_value).lower():
                account_name = str(cell_value).strip()
                # Avoid duplicates
                if not any(loc[2] == account_name for loc in account_locations):
                    account_locations.append((row_idx, col_idx, account_name))
    
    log.append(f"Found {len(account_locations)} bank account sections")
    
    for row_idx, col_idx, account_name in account_locations:
        log.append(f"Processing: {account_name} at row {row_idx+1}, col {col_idx+1}")
        
        # Find the header row with Month, Total Income, Deductions, Net Revenue
        # Usually it's 1-2 rows below the account name
        header_row = None
        for offset in range(0, 3):
            check_row = row_idx + offset
            if check_row < len(df):
                row_text = ' '.join([str(df.iloc[check_row, c]).lower() for c in range(len(df.columns)) if pd.notna(df.iloc[check_row, c])])
                if 'total income' in row_text or 'monthly revenue' in row_text:
                    header_row = check_row
                    break
        
        if header_row is None:
            log.append(f"  Could not find header row for {account_name}")
            continue
        
        # Find column indices - they should be near the account header column
        month_col = None
        income_col = None
        deductions_col = None
        net_revenue_col = None
        
        # Search in nearby columns (within 5 columns of the account header)
        search_start = max(0, col_idx - 1)
        search_end = min(len(df.columns), col_idx + 6)
        
        for c in range(search_start, search_end):
            cell = str(df.iloc[header_row, c]).lower() if pd.notna(df.iloc[header_row, c]) else ''
            if 'monthly revenue' in cell or 'month' in cell:
                month_col = c
            elif 'total income' in cell:
                income_col = c
            elif 'deduction' in cell:
                deductions_col = c
            elif 'net revenue' in cell:
                net_revenue_col = c
        
        log.append(f"  Columns - Month: {month_col}, Income: {income_col}, Deductions: {deductions_col}, Net: {net_revenue_col}")
        
        # Read month rows (Month 1 through Month 12)
        months_data = []
        data_row = header_row + 1
        
        while data_row < len(df) and len(months_data) < 12:
            # Check if this row has month data
            month_cell = df.iloc[data_row, month_col] if month_col is not None else None
            
            if pd.isna(month_cell):
                data_row += 1
                continue
            
            month_str = str(month_cell).strip()
            if not month_str.lower().startswith('month'):
                break
            
            month_entry = {
                'month': month_str,
                'total_income': parse_numeric(df.iloc[data_row, income_col]) if income_col is not None else 0.0,
                'deductions': parse_numeric(df.iloc[data_row, deductions_col]) if deductions_col is not None else 0.0,
                'net_revenue': parse_numeric(df.iloc[data_row, net_revenue_col]) if net_revenue_col is not None else 0.0
            }
            months_data.append(month_entry)
            
            data_row += 1
        
        bank_accounts[account_name] = {'months': months_data}
        log.append(f"  Found {len(months_data)} months of data for {account_name}")
    
    return bank_accounts


def parse_total_revenues(df: pd.DataFrame, log: List[str]) -> Dict[str, float]:
    """Parse Total Revenues by month section."""
    revenues = {}
    
    # Look for "Total Revenues" or similar section
    location = find_cell_location(df, ['total revenues', 'revenues total'])
    
    if not location:
        # Try calculating from bank accounts net revenues
        log.append("No 'Total Revenues' section found - will calculate from bank accounts")
        return revenues
    
    row_idx, col_idx = location
    log.append(f"Found 'Total Revenues' at row {row_idx+1}, col {col_idx+1}")
    
    # Read revenue values for each month
    for month_offset in range(1, 13):
        data_row = row_idx + month_offset
        if data_row < len(df):
            month_label = f"Month {month_offset}"
            # Revenue value might be in the next column
            value = get_value_at_offset(df, row_idx, col_idx, month_offset, 1)
            revenues[month_label] = parse_numeric(value)
    
    log.append(f"Found {len(revenues)} months of total revenue data")
    return revenues


def format_extracted_data_for_display(data: Dict[str, Any]) -> str:
    """Format the extracted data as a readable string for display."""
    lines = []
    
    lines.append("=" * 60)
    lines.append("📋 INFO NEEDED SECTION")
    lines.append("=" * 60)
    info = data.get('info_needed', {})
    lines.append(f"Total Monthly Payments: ${info.get('total_monthly_payments', 0):,.2f}")
    lines.append(f"Diesel's Total Monthly Payments: ${info.get('diesel_total_monthly_payments', 0):,.2f}")
    lines.append(f"Total Monthly Payments (with Diesel): ${info.get('total_monthly_payments_with_diesel', 0):,.2f}")
    lines.append(f"Average Monthly Income: ${info.get('average_monthly_income', 0):,.2f}")
    lines.append(f"Annual Income: ${info.get('annual_income', 0):,.2f}")
    lines.append(f"Length of Deal (months): {info.get('length_of_deal_months', 0)}")
    lines.append(f"Holdback Percentage: {info.get('holdback_percentage', 0):.2f}%")
    lines.append(f"Monthly Holdback: ${info.get('monthly_holdback', 0):,.2f}")
    lines.append(f"Monthly Payment to Income %: {info.get('monthly_payment_to_income_pct', 0):.2f}%")
    lines.append(f"Original Balance to Annual Income %: {info.get('original_balance_to_annual_income_pct', 0):.2f}%")
    
    lines.append("")
    lines.append("=" * 60)
    lines.append("📊 DAILY POSITIONS")
    lines.append("=" * 60)
    positions = data.get('daily_positions', [])
    if positions:
        for pos in positions:
            lines.append(f"  {pos['name']}: Amount=${pos['amount']:,.2f}, Monthly=${pos['monthly_payment']:,.2f}")
    else:
        lines.append("  (No positions found)")
    
    lines.append("")
    lines.append("=" * 60)
    lines.append("🏦 BANK ACCOUNTS")
    lines.append("=" * 60)
    bank_accounts = data.get('bank_accounts', {})
    for account_name, account_data in bank_accounts.items():
        lines.append(f"\n  {account_name}:")
        for month in account_data.get('months', []):
            lines.append(f"    {month['month']}: Income=${month['total_income']:,.2f}, Deductions=${month['deductions']:,.2f}, Net=${month['net_revenue']:,.2f}")
    
    lines.append("")
    lines.append("=" * 60)
    lines.append("📈 TOTAL REVENUES BY MONTH")
    lines.append("=" * 60)
    revenues = data.get('total_revenues_by_month', {})
    if revenues:
        for month, amount in revenues.items():
            lines.append(f"  {month}: ${amount:,.2f}")
    else:
        lines.append("  (No separate totals found - use bank account net revenues)")
    
    return "\n".join(lines)
