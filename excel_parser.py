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
        
        # Parse Deductions Section (separate from bank accounts)
        result['deductions'] = parse_deductions(df, result['parse_log'])
        
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
    # Format: field_name -> (patterns, column_offset) 
    # column_offset specifies which adjacent column to read
    # User confirmed: data is 3 columns to the right of the label
    field_patterns = {
        'total_monthly_payments': (['total monthly payments', 'total monthly payment'], 3),
        'diesel_total_monthly_payments': (["diesel's total monthly payments", "diesel total monthly", "diesel's total"], 3),
        'total_monthly_payments_with_diesel': (['total monthly payments (including diesel', 'including diesel'], 3),
        'average_monthly_income': (['average monthly income', 'avg monthly income'], 3),
        'annual_income': (['annual income'], 3),
        'length_of_deal_months': (['length of deal', 'deal length'], 3),
        'holdback_percentage': (['holdback percentage', 'holdback %', 'holdback percentage / monthly holdback'], 3),
        'monthly_holdback': (['holdback percentage / monthly holdback'], 4),  # Second value (4th column from label)
        'monthly_payment_to_income_pct': (['monthly payment to monthly income', 'payment to income'], 3),
        'original_balance_to_annual_income_pct': (['original balance to annual income', 'balance to annual'], 3),
    }
    
    for field_name, (patterns, col_offset) in field_patterns.items():
        location = find_cell_location(df, patterns)
        if location:
            row, col = location
            # Get value at the specified column offset
            value = get_value_at_offset(df, row, col, 0, col_offset)
            if pd.isna(value) or value is None:
                # Try next column over as fallback
                value = get_value_at_offset(df, row, col, 0, col_offset + 1)
            
            parsed = parse_numeric(value)
            
            # Handle integer field
            if field_name == 'length_of_deal_months':
                info[field_name] = int(parsed)
            else:
                info[field_name] = parsed
            
            log.append(f"Found {field_name}: {info[field_name]} at row {row+1}, col {col+col_offset}")
        else:
            log.append(f"Could not find: {field_name}")
    
    return info


def parse_daily_positions(df: pd.DataFrame, log: List[str]) -> List[Dict[str, Any]]:
    """Parse the Daily Positions section.
    
    Layout (user confirmed):
    Row 9:  Daily Positions | Name | Amount | Monthly Payment  (headers on SAME row)
    Row 10: Position 1      | John | 1000   | 500
    Row 11: Position 2      | Jane | 2000   | 600
    """
    positions = []
    
    # Find "Daily Positions" header
    location = find_cell_location(df, ['daily positions'])
    if not location:
        log.append("Could not find 'Daily Positions' section")
        return positions
    
    header_row, start_col = location
    log.append(f"Found 'Daily Positions' at row {header_row+1}, col {start_col+1}")
    
    # Headers are on the SAME row as "Daily Positions", to the right
    # Find column indices for Name, Amount, Monthly Payment on this row
    name_col = None
    amount_col = None
    payment_col = None
    
    for col_idx in range(start_col + 1, len(df.columns)):
        cell = str(df.iloc[header_row, col_idx]).lower() if pd.notna(df.iloc[header_row, col_idx]) else ''
        if 'name' in cell and name_col is None:
            name_col = col_idx
        elif 'amount' in cell and amount_col is None:
            amount_col = col_idx
        elif 'monthly payment' in cell or 'payment' in cell:
            payment_col = col_idx
    
    if name_col is None:
        log.append("Could not find 'Name' column in Daily Positions row")
        return positions
    
    log.append(f"Daily Positions columns (row {header_row+1}) - Name: col {name_col+1}, Amount: col {amount_col+1 if amount_col else 'N/A'}, Payment: col {payment_col+1 if payment_col else 'N/A'}")
    
    # Read position rows - data starts on the row BELOW the header
    data_row = header_row + 1
    while data_row < len(df):
        name_value = df.iloc[data_row, name_col] if name_col is not None else None
        
        # Stop if name is empty or we hit a new section
        is_na = bool(pd.isna(name_value)) if not isinstance(pd.isna(name_value), bool) else pd.isna(name_value)
        if is_na or str(name_value).strip() == '':
            break
        # Stop if we hit another section
        first_col_value = str(df.iloc[data_row, start_col]).lower() if pd.notna(df.iloc[data_row, start_col]) else ''
        if any(term in first_col_value for term in ['weekly positions', 'bank account', 'total revenues']):
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
    """Parse Bank Account data for multiple accounts.
    
    Layout (user confirmed):
    Row 33: Bank Account 1 (spans cols 2-5)
    Row 34: Monthly Revenue | Total Income | Deductions | Net Revenue  (headers)
    Row 35: Month 1         | $310,682     | $78,650    | $232,032
    Row 36: Month 2         | $291,796     | $34,100    | $257,696
    ...
    """
    bank_accounts = {}
    
    # Find all "Bank Account X" headers
    account_locations = []
    for row_idx in range(len(df)):
        for col_idx in range(len(df.columns)):
            cell_value = df.iloc[row_idx, col_idx]
            # Search for both "Bank Account" and "Bank Accoount" (typo with double 'o')
            cell_str = str(cell_value).lower() if pd.notna(cell_value) else ''
            if 'bank account' in cell_str or 'bank accoount' in cell_str:
                account_name = str(cell_value).strip()
                # Avoid duplicates
                if not any(loc[2] == account_name for loc in account_locations):
                    account_locations.append((row_idx, col_idx, account_name))
    
    log.append(f"Found {len(account_locations)} bank account sections")
    
    for row_idx, col_idx, account_name in account_locations:
        log.append(f"Processing: {account_name} at row {row_idx+1}, col {col_idx+1}")
        
        # Header row is 1 row below "Bank Account X"
        header_row = row_idx + 1
        if header_row >= len(df):
            log.append(f"  Header row out of bounds for {account_name}")
            continue
        
        # Log what's in the header row for debugging
        header_contents = []
        for c in range(col_idx, min(col_idx + 6, len(df.columns))):
            val = df.iloc[header_row, c] if pd.notna(df.iloc[header_row, c]) else ''
            header_contents.append(f"col{c+1}='{val}'")
        log.append(f"  Header row {header_row+1} contents: {', '.join(header_contents)}")
        
        # Find column indices starting from the account column
        month_col = None
        income_col = None
        deductions_col = None
        net_revenue_col = None
        
        for c in range(col_idx, min(col_idx + 8, len(df.columns))):
            cell = str(df.iloc[header_row, c]).lower() if pd.notna(df.iloc[header_row, c]) else ''
            if ('monthly revenue' in cell or cell == 'month' or 'month' in cell) and month_col is None:
                month_col = c
            elif 'total income' in cell and income_col is None:
                income_col = c
            elif 'deduction' in cell and deductions_col is None:
                deductions_col = c
            elif 'net revenue' in cell and net_revenue_col is None:
                net_revenue_col = c
        
        log.append(f"  Found columns - Month: col {month_col+1 if month_col is not None else 'N/A'}, Income: col {income_col+1 if income_col is not None else 'N/A'}, Deductions: col {deductions_col+1 if deductions_col is not None else 'N/A'}, Net: col {net_revenue_col+1 if net_revenue_col is not None else 'N/A'}")
        
        # Read month rows (Month 1 through Month 12)
        months_data = []
        data_row = header_row + 1
        
        while data_row < len(df) and len(months_data) < 12:
            # Check first column value to detect section end
            first_col_val = str(df.iloc[data_row, col_idx]).lower() if pd.notna(df.iloc[data_row, col_idx]) else ''
            if 'bank account' in first_col_val or 'total revenues' in first_col_val or 'weekly' in first_col_val:
                break
            
            # Get month cell
            month_cell = df.iloc[data_row, month_col] if month_col is not None else None
            is_month_na = bool(pd.isna(month_cell)) if not isinstance(pd.isna(month_cell), bool) else pd.isna(month_cell)
            
            if is_month_na or str(month_cell).strip() == '':
                data_row += 1
                continue
            
            month_str = str(month_cell).strip()
            if not month_str.lower().startswith('month'):
                data_row += 1
                continue
            
            month_entry = {
                'month': month_str,
                'total_income': parse_numeric(df.iloc[data_row, income_col]) if income_col is not None else 0.0,
                'deductions': parse_numeric(df.iloc[data_row, deductions_col]) if deductions_col is not None else 0.0,
                'net_revenue': parse_numeric(df.iloc[data_row, net_revenue_col]) if net_revenue_col is not None else 0.0
            }
            months_data.append(month_entry)
            log.append(f"    {month_str}: Income=${month_entry['total_income']:,.2f}, Ded=${month_entry['deductions']:,.2f}, Net=${month_entry['net_revenue']:,.2f}")
            
            data_row += 1
        
        bank_accounts[account_name] = {'months': months_data}
        log.append(f"  Found {len(months_data)} months of data for {account_name}")
    
    return bank_accounts


def parse_total_revenues(df: pd.DataFrame, log: List[str]) -> Dict[str, float]:
    """Parse Total Revenues by month section.
    
    Layout: Similar to Bank Accounts
    Row X: Total Revenues (header)
    Row X+1: Month | Revenue Amount  (sub-headers)
    Row X+2: Month 1 | $value
    Row X+3: Month 2 | $value
    ...
    """
    revenues = {}
    
    # Look for "Total Revenues" or similar section
    location = find_cell_location(df, ['total revenues', 'revenues total'])
    
    if not location:
        log.append("No 'Total Revenues' section found - will calculate from bank accounts")
        return revenues
    
    row_idx, col_idx = location
    log.append(f"Found 'Total Revenues' at row {row_idx+1}, col {col_idx+1}")
    
    # Look at the header row below to find column structure
    header_row = row_idx + 1
    log.append(f"  Checking header row {header_row+1}")
    
    # Log header row contents
    if header_row < len(df):
        header_contents = []
        for c in range(col_idx, min(col_idx + 4, len(df.columns))):
            val = df.iloc[header_row, c] if pd.notna(df.iloc[header_row, c]) else ''
            header_contents.append(f"col{c+1}='{val}'")
        log.append(f"  Header contents: {', '.join(header_contents)}")
    
    # Find the revenue value column (usually 1 column to the right of month labels)
    # Data starts 2 rows below "Total Revenues" (1 row for sub-headers)
    data_start_row = row_idx + 2
    
    # Read all months with data
    for i in range(12):
        data_row = data_start_row + i
        if data_row >= len(df):
            break
        
        # Get month label from first column
        month_cell = df.iloc[data_row, col_idx] if pd.notna(df.iloc[data_row, col_idx]) else ''
        month_str = str(month_cell).strip()
        
        # Stop if we hit empty or another section
        if not month_str or 'bank' in month_str.lower() or 'deduction' in month_str.lower():
            break
        
        # Get revenue value from column to the right
        value_col = col_idx + 1
        if value_col < len(df.columns):
            value = df.iloc[data_row, value_col]
            revenue = parse_numeric(value)
            
            # Only add if there's actual data
            if revenue > 0:
                revenues[month_str] = revenue
                log.append(f"  {month_str}: ${revenue:,.2f}")
    
    log.append(f"Found {len(revenues)} months of total revenue data")
    return revenues


def parse_deductions(df: pd.DataFrame, log: List[str]) -> Dict[str, Any]:
    """Parse Deductions section for each bank account.
    
    Layout (user confirmed): Row 48, column 2
    Similar to bank accounts - header, then sub-headers, then data
    Account 2 deductions start at column 6
    """
    deductions = {}
    
    # Look for "Deductions" section headers
    deduction_locations = []
    for row_idx in range(len(df)):
        for col_idx in range(len(df.columns)):
            cell_value = df.iloc[row_idx, col_idx]
            cell_str = str(cell_value).lower() if pd.notna(cell_value) else ''
            # Look for standalone "Deductions" headers (not just the word in bank account headers)
            if cell_str.strip() == 'deductions' or 'deductions account' in cell_str or 'account' in cell_str and 'deduction' in cell_str:
                # Skip if this is part of bank account header row
                row_text = ' '.join([str(df.iloc[row_idx, c]).lower() for c in range(len(df.columns)) if pd.notna(df.iloc[row_idx, c])])
                if 'bank account' not in row_text and 'bank accoount' not in row_text:
                    section_name = str(cell_value).strip()
                    if not any(loc[2] == section_name for loc in deduction_locations):
                        deduction_locations.append((row_idx, col_idx, section_name))
    
    log.append(f"Found {len(deduction_locations)} deduction sections")
    
    # Also try finding by specific row if we didn't find any
    if len(deduction_locations) == 0:
        log.append("  Looking for deduction data around row 48...")
        # User said row 48 (0-indexed = 47)
        check_row = 47  # Row 48 in Excel (0-indexed)
        if check_row < len(df):
            for col_idx in range(len(df.columns)):
                cell_value = df.iloc[check_row, col_idx]
                if pd.notna(cell_value) and str(cell_value).strip():
                    cell_str = str(cell_value).strip()
                    log.append(f"    Row 48, col {col_idx+1}: '{cell_str}'")
                    if 'deduction' in cell_str.lower() or 'account' in cell_str.lower():
                        deduction_locations.append((check_row, col_idx, cell_str))
    
    for row_idx, col_idx, section_name in deduction_locations:
        log.append(f"Processing deductions: {section_name} at row {row_idx+1}, col {col_idx+1}")
        
        # Header row is 1 row below the section header
        header_row = row_idx + 1
        if header_row >= len(df):
            continue
        
        # Log header contents
        header_contents = []
        for c in range(col_idx, min(col_idx + 5, len(df.columns))):
            val = df.iloc[header_row, c] if pd.notna(df.iloc[header_row, c]) else ''
            header_contents.append(f"col{c+1}='{val}'")
        log.append(f"  Header row {header_row+1}: {', '.join(header_contents)}")
        
        # Find month and deduction columns
        month_col = None
        deduction_col = None
        
        for c in range(col_idx, min(col_idx + 5, len(df.columns))):
            cell = str(df.iloc[header_row, c]).lower() if pd.notna(df.iloc[header_row, c]) else ''
            if 'month' in cell and month_col is None:
                month_col = c
            elif 'deduction' in cell or 'amount' in cell:
                deduction_col = c
        
        # Default to adjacent columns if not found
        if month_col is None:
            month_col = col_idx
        if deduction_col is None:
            deduction_col = col_idx + 1
        
        # Read month data
        months_data = []
        data_row = header_row + 1
        
        while data_row < len(df) and len(months_data) < 12:
            month_cell = df.iloc[data_row, month_col] if pd.notna(df.iloc[data_row, month_col]) else ''
            month_str = str(month_cell).strip()
            
            if not month_str or not month_str.lower().startswith('month'):
                data_row += 1
                if not month_str:
                    break
                continue
            
            deduction_value = parse_numeric(df.iloc[data_row, deduction_col]) if deduction_col < len(df.columns) else 0.0
            
            months_data.append({
                'month': month_str,
                'deduction': deduction_value
            })
            log.append(f"    {month_str}: Deduction=${deduction_value:,.2f}")
            
            data_row += 1
        
        deductions[section_name] = {'months': months_data}
        log.append(f"  Found {len(months_data)} months of deduction data")
    
    return deductions


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
    
    lines.append("")
    lines.append("=" * 60)
    lines.append("💸 DEDUCTIONS (SEPARATE SECTION)")
    lines.append("=" * 60)
    deductions = data.get('deductions', {})
    if deductions:
        for section_name, section_data in deductions.items():
            lines.append(f"\n  {section_name}:")
            for month in section_data.get('months', []):
                lines.append(f"    {month['month']}: Deduction=${month['deduction']:,.2f}")
    else:
        lines.append("  (No separate deductions section found)")
    
    return "\n".join(lines)
