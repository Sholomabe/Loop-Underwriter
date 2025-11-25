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
        
        # Parse Weekly Positions
        result['weekly_positions'] = parse_weekly_positions(df, result['parse_log'])
        
        # Parse Monthly Positions (non MCA)
        result['monthly_positions_non_mca'] = parse_monthly_positions_non_mca(df, result['parse_log'])
        
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
            
            # Debug: show what's in the row for this field
            row_values = []
            for c in range(col, min(col + 6, len(df.columns))):
                val = df.iloc[row, c] if pd.notna(df.iloc[row, c]) else ''
                row_values.append(f"col{c+1}='{val}'")
            log.append(f"  Row {row+1} for '{field_name}': {', '.join(row_values)}")
            
            # Get value at the specified column offset
            value = get_value_at_offset(df, row, col, 0, col_offset)
            if pd.isna(value) or value is None or str(value).strip() == '':
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
    
    # Override with fixed locations for specific fields (user confirmed exact positions)
    # Debug: Show what's in rows 16 and 17 around column 10
    log.append("--- FIXED LOCATION DEBUG ---")
    if len(df) > 16 and len(df.columns) > 12:
        # Show row 16 (0-indexed: 15)
        row16_values = []
        for c in range(max(0, 6), min(14, len(df.columns))):  # cols 7-14
            val = df.iloc[15, c]
            row16_values.append(f"col{c+1}='{val}' (type:{type(val).__name__})")
        log.append(f"Row 16: {', '.join(row16_values)}")
        
        # Show row 17 (0-indexed: 16)
        row17_values = []
        for c in range(max(0, 6), min(14, len(df.columns))):  # cols 7-14
            val = df.iloc[16, c]
            row17_values.append(f"col{c+1}='{val}' (type:{type(val).__name__})")
        log.append(f"Row 17: {', '.join(row17_values)}")
    
    # Holdback Percentage / Monthly Holdback: Scan columns 9-12 on row 16 (0-indexed: 15)
    # Handle compound strings like "10% / $4,500" or merged cells
    if len(df) > 15:
        log.append("Searching for Holdback values in row 16, cols 9-12...")
        for col_idx in range(8, min(13, len(df.columns))):  # cols 9-13 (0-indexed: 8-12)
            cell_val = df.iloc[15, col_idx]
            if pd.notna(cell_val):
                cell_str = str(cell_val).strip()
                log.append(f"  Col {col_idx+1}: '{cell_str}'")
                
                # Check for compound format with "/" separator (e.g., "10% / $4,500")
                if '/' in cell_str:
                    parts = cell_str.split('/')
                    for part in parts:
                        part = part.strip()
                        parsed_part = parse_numeric(part)
                        if parsed_part > 0:
                            # Determine if it's a percentage or dollar amount
                            if '%' in part or (parsed_part < 100 and '$' not in part):
                                if 0 < parsed_part < 1:
                                    info['holdback_percentage'] = parsed_part * 100
                                else:
                                    info['holdback_percentage'] = parsed_part
                                log.append(f"  Found holdback percentage: {info['holdback_percentage']}%")
                            elif '$' in part or parsed_part >= 100:
                                info['monthly_holdback'] = parsed_part
                                log.append(f"  Found monthly holdback: ${info['monthly_holdback']:,.2f}")
                else:
                    # Single value - determine if percentage or dollar amount
                    parsed_val = parse_numeric(cell_val)
                    if parsed_val > 0:
                        if 0 < parsed_val < 1:
                            info['holdback_percentage'] = parsed_val * 100
                            log.append(f"  Found holdback (converted decimal): {info['holdback_percentage']}%")
                        elif parsed_val < 100:
                            info['holdback_percentage'] = parsed_val
                            log.append(f"  Found holdback percentage: {parsed_val}%")
                        else:
                            info['monthly_holdback'] = parsed_val
                            log.append(f"  Found monthly holdback: ${parsed_val:,.2f}")
    
    # Monthly Payment to Income %: Scan columns 9-12 on row 17 (0-indexed: 16)
    if len(df) > 16:
        log.append("Searching for Payment to Income % in row 17, cols 9-12...")
        for col_idx in range(8, min(13, len(df.columns))):  # cols 9-13 (0-indexed: 8-12)
            cell_val = df.iloc[16, col_idx]
            if pd.notna(cell_val):
                cell_str = str(cell_val).strip()
                log.append(f"  Col {col_idx+1}: '{cell_str}'")
                
                parsed_val = parse_numeric(cell_val)
                if parsed_val > 0:
                    # Check if it's a decimal (like 0.25 for 25%)
                    if 0 < parsed_val < 1:
                        info['monthly_payment_to_income_pct'] = parsed_val * 100
                        log.append(f"  Found payment to income (converted decimal): {info['monthly_payment_to_income_pct']}%")
                        break
                    else:
                        info['monthly_payment_to_income_pct'] = parsed_val
                        log.append(f"  Found payment to income %: {parsed_val}%")
                        break
    
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


def parse_weekly_positions(df: pd.DataFrame, log: List[str]) -> List[Dict[str, Any]]:
    """Parse the Weekly Positions section.
    
    Layout (user confirmed): Same as Daily Positions
    Row 18: Weekly Positions | Name | Amount | Monthly Payment  (headers on SAME row)
    Row 19: Position 1       | John | 1000   | 500
    Row 20: Position 2       | Jane | 2000   | 600
    """
    positions = []
    
    # Find "Weekly Positions" header
    location = find_cell_location(df, ['weekly positions'])
    if not location:
        log.append("Could not find 'Weekly Positions' section")
        return positions
    
    header_row, start_col = location
    log.append(f"Found 'Weekly Positions' at row {header_row+1}, col {start_col+1}")
    
    # Headers are on the SAME row as "Weekly Positions", to the right
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
        log.append("Could not find 'Name' column in Weekly Positions row")
        return positions
    
    log.append(f"Weekly Positions columns (row {header_row+1}) - Name: col {name_col+1}, Amount: col {amount_col+1 if amount_col else 'N/A'}, Payment: col {payment_col+1 if payment_col else 'N/A'}")
    
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
        if any(term in first_col_value for term in ['bank account', 'bank accoount', 'total revenues', 'deduction']):
            break
        
        position = {
            'name': str(name_value).strip(),
            'amount': parse_numeric(df.iloc[data_row, amount_col]) if amount_col is not None else 0.0,
            'monthly_payment': parse_numeric(df.iloc[data_row, payment_col]) if payment_col is not None else 0.0
        }
        positions.append(position)
        log.append(f"  Position: {position['name']} - Amount: ${position['amount']:,.2f}, Payment: ${position['monthly_payment']:,.2f}")
        
        data_row += 1
    
    log.append(f"Found {len(positions)} weekly positions")
    return positions


def parse_monthly_positions_non_mca(df: pd.DataFrame, log: List[str]) -> List[Dict[str, Any]]:
    """Parse the Monthly Positions (non MCA) section.
    
    Layout (user confirmed):
    Row 26: Monthly Positions (non MCA) | [headers if any]
    Row 27+: Data rows with columns 3-4 as name, column 5 as monthly payment
    
    Note: This section may have headers on row 26 or start data on row 27
    Column 2 = section label area
    Columns 3-4 = Name (may span 2 columns)
    Column 5 = Monthly Payment
    """
    positions = []
    log.append("--- MONTHLY POSITIONS (NON MCA) PARSING ---")
    
    # Debug: Show what's in row 26 (0-indexed: 25) to help find the section
    if len(df) > 25:
        row26_preview = []
        for c in range(min(8, len(df.columns))):
            val = df.iloc[25, c] if pd.notna(df.iloc[25, c]) else ''
            row26_preview.append(f"col{c+1}='{val}'")
        log.append(f"Row 26 preview: {', '.join(row26_preview)}")
    
    # Try multiple search terms
    search_terms = ['monthly positions', 'monthly (non', 'non mca', 'monthly pos']
    location = None
    for term in search_terms:
        location = find_cell_location(df, [term])
        if location:
            log.append(f"Found section using search term: '{term}'")
            break
    
    # Fallback: Check fixed row 26, col 2 (0-indexed: row 25, col 1)
    if not location and len(df) > 25 and len(df.columns) > 1:
        cell_val = df.iloc[25, 1]  # Row 26, Col 2
        if pd.notna(cell_val):
            cell_str = str(cell_val).strip().lower()
            log.append(f"Checking fixed location row 26, col 2: '{cell_val}'")
            if 'monthly' in cell_str or 'position' in cell_str or 'non' in cell_str:
                location = (25, 1)
                log.append(f"Using fixed location row 26, col 2")
    
    if not location:
        log.append("Could not find 'Monthly Positions (non MCA)' section")
        return positions
    
    header_row, start_col = location
    log.append(f"Found 'Monthly Positions (non MCA)' at row {header_row+1}, col {start_col+1}")
    
    # Debug: Show what's in the header row
    row_preview = []
    for c in range(max(0, start_col), min(start_col + 8, len(df.columns))):
        val = df.iloc[header_row, c] if pd.notna(df.iloc[header_row, c]) else ''
        row_preview.append(f"col{c+1}='{val}'")
    log.append(f"  Header row content: {', '.join(row_preview)}")
    
    # Per user: columns 3-4 = name, column 5 = monthly payment (0-indexed: cols 2-3 = name, col 4 = payment)
    # But we need to adjust based on where the section header is found
    name_col_1 = 2  # Column 3 (0-indexed: 2)
    name_col_2 = 3  # Column 4 (0-indexed: 3)
    payment_col = 4  # Column 5 (0-indexed: 4)
    
    log.append(f"  Using fixed columns: Name cols {name_col_1+1}-{name_col_2+1}, Payment col {payment_col+1}")
    
    # Data starts on row BELOW the header
    data_row = header_row + 1
    
    # Debug: Show first data row
    if data_row < len(df):
        data_row_preview = []
        for c in range(max(0, name_col_1), min(payment_col + 2, len(df.columns))):
            val = df.iloc[data_row, c] if pd.notna(df.iloc[data_row, c]) else ''
            data_row_preview.append(f"col{c+1}='{val}'")
        log.append(f"  First data row ({data_row+1}) content: {', '.join(data_row_preview)}")
    
    while data_row < len(df):
        # Get name from columns 3-4 (concatenate if both have values)
        name_part1 = df.iloc[data_row, name_col_1] if name_col_1 < len(df.columns) and pd.notna(df.iloc[data_row, name_col_1]) else ''
        name_part2 = df.iloc[data_row, name_col_2] if name_col_2 < len(df.columns) and pd.notna(df.iloc[data_row, name_col_2]) else ''
        
        name_part1 = str(name_part1).strip() if name_part1 else ''
        name_part2 = str(name_part2).strip() if name_part2 else ''
        
        # Combine name parts
        if name_part1 and name_part2:
            name_value = f"{name_part1} {name_part2}"
        elif name_part1:
            name_value = name_part1
        elif name_part2:
            name_value = name_part2
        else:
            name_value = ''
        
        # Stop if name is empty
        if not name_value:
            break
        
        # Stop if we hit another section
        first_col_value = str(df.iloc[data_row, start_col]).lower() if pd.notna(df.iloc[data_row, start_col]) else ''
        if any(term in first_col_value for term in ['bank account', 'bank accoount', 'total revenues', 'deduction']):
            break
        
        # Get monthly payment from column 5
        monthly_payment = parse_numeric(df.iloc[data_row, payment_col]) if payment_col < len(df.columns) else 0.0
        
        position = {
            'name': name_value,
            'amount': 0.0,  # No amount column for this section
            'monthly_payment': monthly_payment
        }
        positions.append(position)
        log.append(f"  Position: {position['name']} - Monthly Payment: ${position['monthly_payment']:,.2f}")
        
        data_row += 1
    
    log.append(f"Found {len(positions)} monthly (non MCA) positions")
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
    
    Layout (user confirmed): Grid/matrix layout
    Row 22: Month 1 (col 7), Month 2 (col 8), Month 3 (col 9), Month 4 (col 10)
    Row 23: $value    $value       $value       $value
    Row 24: Month 5 (col 7), Month 6 (col 8), Month 7 (col 9), Month 8 (col 10)
    Row 25: $value    $value       $value       $value
    ...
    """
    revenues = {}
    
    # Look for "Total Revenues" or similar section header first
    location = find_cell_location(df, ['total revenues', 'revenues total', 'monthly revenue'])
    
    if location:
        log.append(f"Found 'Total Revenues' header at row {location[0]+1}, col {location[1]+1}")
    
    # User said: Row 22 (0-indexed = 21) is where month headers start at column 7 (0-indexed = 6)
    # Let's scan for month headers in the grid layout
    log.append("Scanning for monthly revenue grid layout...")
    
    # Look for "Month 1", "Month 2", etc. as column headers
    month_locations = []  # (row, col, month_number)
    
    for row_idx in range(len(df)):
        for col_idx in range(len(df.columns)):
            cell_value = df.iloc[row_idx, col_idx]
            if pd.notna(cell_value):
                cell_str = str(cell_value).strip().lower()
                # Look for "month X" pattern
                if cell_str.startswith('month'):
                    # Extract month number
                    parts = cell_str.split()
                    if len(parts) >= 2:
                        try:
                            month_num = int(parts[1])
                            month_locations.append((row_idx, col_idx, month_num, str(cell_value).strip()))
                        except ValueError:
                            pass
    
    log.append(f"Found {len(month_locations)} month headers in grid")
    
    # For each month header, get the value from the row below
    for row_idx, col_idx, month_num, month_label in month_locations:
        # Value should be directly below the month header
        value_row = row_idx + 1
        if value_row < len(df):
            value = df.iloc[value_row, col_idx]
            revenue = parse_numeric(value)
            
            # Only add if there's actual data and we don't already have this month
            if revenue > 0 and month_label not in revenues:
                revenues[month_label] = revenue
                log.append(f"  {month_label} (row {row_idx+1}, col {col_idx+1}): ${revenue:,.2f}")
    
    # Sort by month number for display
    log.append(f"Found {len(revenues)} months of total revenue data")
    return revenues


def parse_deductions(df: pd.DataFrame, log: List[str]) -> Dict[str, Any]:
    """Parse Deductions section for each bank account.
    
    Layout (user confirmed): Months are COLUMNS, data is in rows below
    Row 48: Header row (maybe "Deductions - Bank Account 1" etc)
    Row 49: Month 1 (col 2) | Month 2 (col 3) | Month 3 (col 4) | Month 4 (col 5) | Month 1 (col 6) | ...
    Row 50: $value         | $value          | $value          | $value          | $value          | ...
    
    Account 1: Columns 2-5 (0-indexed: 1-4)
    Account 2: Columns 6-9 (0-indexed: 5-8)
    Account 3: Columns 10+ (0-indexed: 9+)
    """
    deductions = {}
    
    log.append("Looking for Deductions section...")
    
    # User confirmed: Row 48 has header, Row 49 has month labels as columns
    header_row = 47  # Row 48 in Excel (0-indexed)
    month_header_row = 48  # Row 49 in Excel (0-indexed)
    data_row = 49  # Row 50 in Excel (0-indexed)
    
    # Log what's in rows 48-50
    for check_row in [header_row, month_header_row, data_row]:
        if check_row < len(df):
            row_contents = []
            for col_idx in range(min(12, len(df.columns))):
                cell_value = df.iloc[check_row, col_idx]
                if pd.notna(cell_value) and str(cell_value).strip():
                    row_contents.append(f"col{col_idx+1}='{cell_value}'")
            log.append(f"  Row {check_row+1} contents: {', '.join(row_contents) if row_contents else '(empty)'}")
    
    # Define account column ranges based on user's description
    # Account 1: cols 2-5 (0-indexed: 1-4)
    # Account 2: cols 6-9 (0-indexed: 5-8)  
    # Account 3: cols 10-13 (0-indexed: 9-12)
    account_ranges = [
        ('Deductions - Bank Account 1', 1, 5),   # cols 2-5
        ('Deductions - Bank Account 2', 5, 9),   # cols 6-9
        ('Deductions - Bank Account 3', 9, 13),  # cols 10-13
    ]
    
    for account_name, start_col, end_col in account_ranges:
        if start_col >= len(df.columns):
            continue
            
        months_data = []
        
        # Read each column as a month
        for col_idx in range(start_col, min(end_col, len(df.columns))):
            # Get month label from the month header row
            if month_header_row < len(df):
                month_cell = df.iloc[month_header_row, col_idx]
                month_label = str(month_cell).strip() if pd.notna(month_cell) else ''
            else:
                month_label = ''
            
            # Get deduction value from the data row
            if data_row < len(df):
                value_cell = df.iloc[data_row, col_idx]
                deduction_value = parse_numeric(value_cell)
            else:
                deduction_value = 0.0
            
            # Only add if we have a month label
            if month_label and month_label.lower().startswith('month'):
                months_data.append({
                    'month': month_label,
                    'deduction': deduction_value
                })
                log.append(f"  {account_name} - {month_label} (col {col_idx+1}): ${deduction_value:,.2f}")
        
        if months_data:
            deductions[account_name] = {'months': months_data}
            log.append(f"  Found {len(months_data)} months for {account_name}")
    
    # Also try to find section headers dynamically if the fixed positions don't work
    if not deductions:
        log.append("  Fixed positions didn't find data, searching for deduction headers...")
        for row_idx in range(len(df)):
            for col_idx in range(len(df.columns)):
                cell_value = df.iloc[row_idx, col_idx]
                if pd.notna(cell_value):
                    cell_str = str(cell_value).strip().lower()
                    if 'deduction' in cell_str and ('account' in cell_str or 'bank' in cell_str):
                        log.append(f"    Found header: '{cell_value}' at row {row_idx+1}, col {col_idx+1}")
    
    log.append(f"Total deduction sections found: {len(deductions)}")
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
    lines.append("📅 WEEKLY POSITIONS")
    lines.append("=" * 60)
    weekly_positions = data.get('weekly_positions', [])
    if weekly_positions:
        for pos in weekly_positions:
            lines.append(f"  {pos['name']}: Amount=${pos['amount']:,.2f}, Monthly=${pos['monthly_payment']:,.2f}")
    else:
        lines.append("  (No weekly positions found)")
    
    lines.append("")
    lines.append("=" * 60)
    lines.append("📆 MONTHLY POSITIONS (NON MCA)")
    lines.append("=" * 60)
    monthly_non_mca = data.get('monthly_positions_non_mca', [])
    if monthly_non_mca:
        for pos in monthly_non_mca:
            lines.append(f"  {pos['name']}: Monthly=${pos['monthly_payment']:,.2f}")
    else:
        lines.append("  (No monthly non-MCA positions found)")
    
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
