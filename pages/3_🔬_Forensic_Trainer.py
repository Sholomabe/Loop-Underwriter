import streamlit as st
import json
import os
from database import get_db
from models import Deal, PDFFile, Transaction, TrainingExample, GoldStandardRule
from datetime import datetime
from openai_integration import adversarial_correction_prompt, validate_and_sanitize_transactions
from excel_parser import parse_underwriting_excel, format_extracted_data_for_display

st.set_page_config(page_title="Forensic Trainer", page_icon="🔬", layout="wide")

st.title("🔬 Forensic Trainer - Advanced AI Training")

st.markdown("""
This is the **Adversarial Training System** where you can:
1. Upload historical deals with known "truth" values
2. Let the AI analyze blindly
3. See where it went wrong
4. Teach the AI by showing it the exact errors
""")

st.divider()

# Upload Deal Section
st.subheader("📤 Upload Training Deal")

# Initialize session state for truth input method
if 'truth_input_method' not in st.session_state:
    st.session_state.truth_input_method = "✍️ Enter Manually"

# Radio button outside form to allow immediate re-render
st.subheader("📝 Enter Truth Values")
truth_input_method = st.radio(
    "How would you like to provide truth values?",
    options=["📊 Upload Excel File", "✍️ Enter Manually"],
    horizontal=True,
    key='truth_input_method'
)

# Initialize session state for truth values
if 'truth_annual_income' not in st.session_state:
    st.session_state.truth_annual_income = 0.0
if 'truth_monthly_income' not in st.session_state:
    st.session_state.truth_monthly_income = 0.0
if 'truth_revenues' not in st.session_state:
    st.session_state.truth_revenues = 0.0
if 'truth_payments' not in st.session_state:
    st.session_state.truth_payments = 0.0
if 'truth_diesel' not in st.session_state:
    st.session_state.truth_diesel = 0.0
if 'truth_nsf' not in st.session_state:
    st.session_state.truth_nsf = 0

# Initialize session state for full extracted data
if 'extracted_excel_data' not in st.session_state:
    st.session_state.extracted_excel_data = None

# Initialize session state for correction report (persists across reruns)
if 'last_correction_report' not in st.session_state:
    st.session_state.last_correction_report = None
if 'last_correction_timestamp' not in st.session_state:
    st.session_state.last_correction_timestamp = None
if 'last_correction_saved' not in st.session_state:
    st.session_state.last_correction_saved = False
if 'last_correction_id' not in st.session_state:
    st.session_state.last_correction_id = None
if '_auto_load_done' not in st.session_state:
    st.session_state._auto_load_done = False
if '_manual_load_active' not in st.session_state:
    st.session_state._manual_load_active = False

# AUTO-LOAD: Load the most recent audit from database ONLY on first session load
# Skip if: already auto-loaded, manual load active, or there's already a report in session
should_auto_load = (
    not st.session_state._auto_load_done and 
    not st.session_state._manual_load_active and
    st.session_state.last_correction_report is None
)

if should_auto_load:
    try:
        with get_db() as db:
            most_recent = db.query(TrainingExample).filter(
                TrainingExample.correction_details.isnot(None)
            ).order_by(TrainingExample.created_at.desc()).first()
            
            if most_recent and most_recent.correction_details:
                details = most_recent.correction_details
                if details.get('audit_type') == 'adversarial_self_audit':
                    st.session_state.last_correction_report = details.get('correction_report', {})
                    st.session_state.last_correction_timestamp = most_recent.created_at
                    st.session_state.last_correction_saved = True
                    st.session_state.last_correction_id = most_recent.id
        st.session_state._auto_load_done = True
    except Exception:
        st.session_state._auto_load_done = True  # Mark done even on error to prevent retries

# Helper function to display a correction report (reusable)
def display_correction_report(correction_report, show_save_button=True, key_prefix=""):
    """Display a correction report in a user-friendly format."""
    # Display errors found
    if 'errors_found' in correction_report and correction_report['errors_found']:
        st.markdown("### ❌ Errors Identified")
        for i, error in enumerate(correction_report['errors_found'], 1):
            st.error(f"{i}. {error}")
    else:
        st.info("No specific errors identified")
    
    # Display missed transactions
    if 'missed_transactions' in correction_report and correction_report['missed_transactions']:
        st.markdown("### 🔍 Missed Transactions")
        for txn in correction_report['missed_transactions']:
            desc = txn.get('description', 'N/A')
            amt = txn.get('amount', 0)
            why = txn.get('why_missed', 'N/A')
            st.warning(f"**{desc}**: ${amt:,.2f} - *{why}*")
    
    # Display miscategorized transactions
    if 'miscategorized_transactions' in correction_report and correction_report['miscategorized_transactions']:
        st.markdown("### 🔄 Miscategorized Transactions")
        for txn in correction_report['miscategorized_transactions']:
            desc = txn.get('description', 'N/A')
            was_cat = txn.get('was_categorized_as', 'N/A')
            should_be = txn.get('should_be', 'N/A')
            st.warning(f"**{desc}**: Was '{was_cat}' → Should be '{should_be}'")
    
    # Display correction explanation
    if 'correction_explanation' in correction_report and correction_report['correction_explanation']:
        st.markdown("### 📖 Detailed Explanation")
        st.info(correction_report['correction_explanation'])
    
    # Display root cause analysis if present
    if 'root_cause' in correction_report and correction_report['root_cause']:
        st.markdown("### 🔬 Root Cause Analysis")
        st.write(correction_report['root_cause'])
    
    # Display recommendations if present
    if 'recommendations' in correction_report and correction_report['recommendations']:
        st.markdown("### 💡 Recommendations for Improvement")
        for rec in correction_report['recommendations']:
            st.write(f"• {rec}")
    
    # Display learned pattern and save option
    if 'learned_pattern' in correction_report and correction_report['learned_pattern'] and show_save_button:
        st.divider()
        st.subheader("💾 Save to Memory Bank (RAG)")
        st.code(correction_report['learned_pattern'], language='text')
        
        if st.button("Save Learned Pattern to GoldStandard_Rules", key=f"{key_prefix}save_pattern_btn"):
            with get_db() as db:
                rule = GoldStandardRule(
                    rule_pattern=correction_report['learned_pattern'],
                    rule_type='general_correction',
                    original_classification='error',
                    correct_classification='corrected',
                    confidence_score=1.0,
                    context_json=correction_report,
                    created_at=datetime.utcnow()
                )
                db.add(rule)
                db.commit()
            st.success("✅ Pattern saved to memory bank! AI will apply this learning to future deals.")
    
    # Show raw JSON for debugging
    with st.expander("🔧 View Raw Correction Report JSON"):
        st.json(correction_report)

# STANDALONE SECTION: Display most recent self-audit from session (independent of training_result)
if st.session_state.last_correction_report:
    st.divider()
    st.subheader("📝 Most Recent Self-Audit Report")
    if st.session_state.last_correction_timestamp:
        st.caption(f"Generated: {st.session_state.last_correction_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    if st.session_state.last_correction_saved:
        st.success(f"✅ This report has been saved to the database (ID: {st.session_state.last_correction_id})")
    
    display_correction_report(st.session_state.last_correction_report, show_save_button=True, key_prefix="recent_")
    
    # Clear button
    if st.button("🗑️ Clear This Report", key="clear_recent_report_btn"):
        st.session_state.last_correction_report = None
        st.session_state.last_correction_timestamp = None
        st.session_state.last_correction_saved = False
        st.session_state.last_correction_id = None
        st.session_state._manual_load_active = False  # Reset manual load flag
        st.session_state._auto_load_done = False  # Allow auto-load again
        st.rerun()
    st.divider()

# Excel upload section OR manual entry preview (outside form for immediate feedback)
excel_file = None
if truth_input_method == "📊 Upload Excel File":
    st.markdown("Upload an Excel file with the **underwriting** sheet containing truth values")
    st.info("📖 The parser will look for sheet named 'underwriting' (or use the second sheet)")
    
    excel_file = st.file_uploader(
        "Upload Truth Values Excel",
        type=['xlsx', 'xls'],
        help="Excel should have an 'underwriting' sheet with: Info Needed section, Daily Positions, Bank Account data, and Total Revenues",
        key='excel_uploader'
    )
    
    if excel_file:
        try:
            # Use the comprehensive parser
            extracted_data = parse_underwriting_excel(excel_file)
            st.session_state.extracted_excel_data = extracted_data
            
            st.success("✅ Excel file parsed successfully!")
            
            # Show parse log PROMINENTLY for debugging
            st.markdown("### 🔍 Parse Log (What the parser found)")
            for log_entry in extracted_data.get('parse_log', []):
                if 'ERROR' in log_entry or 'Could not find' in log_entry:
                    st.error(log_entry)
                elif 'Found' in log_entry:
                    st.success(log_entry)
                else:
                    st.info(log_entry)
            
            # Show raw preview
            with st.expander("📊 Raw Excel Preview (First 30 Rows)", expanded=True):
                st.text(extracted_data.get('raw_preview', 'No preview available'))
            
            # Display all extracted data in organized sections
            st.markdown("---")
            st.subheader("📋 Extracted Data from 'underwriting' Sheet")
            
            # INFO NEEDED SECTION
            info = extracted_data.get('info_needed', {})
            st.markdown("### 📝 Info Needed Section")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric("Total Monthly Payments", f"${info.get('total_monthly_payments', 0):,.2f}")
                st.metric("Average Monthly Income", f"${info.get('average_monthly_income', 0):,.2f}")
                st.metric("Annual Income", f"${info.get('annual_income', 0):,.2f}")
            
            with col2:
                st.metric("Diesel's Total Monthly Payments", f"${info.get('diesel_total_monthly_payments', 0):,.2f}")
                st.metric("Total w/ Diesel's New Deal", f"${info.get('total_monthly_payments_with_diesel', 0):,.2f}")
                st.metric("Length of Deal (months)", f"{info.get('length_of_deal_months', 0)}")
            
            with col3:
                st.metric("Holdback Percentage", f"{info.get('holdback_percentage', 0):.2f}%")
                st.metric("Monthly Holdback", f"${info.get('monthly_holdback', 0):,.2f}")
                st.metric("Payment to Income %", f"{info.get('monthly_payment_to_income_pct', 0):.2f}%")
            
            st.metric("Original Balance to Annual Income %", f"{info.get('original_balance_to_annual_income_pct', 0):.2f}%")
            
            # DAILY POSITIONS SECTION
            st.markdown("### 📊 Daily Positions")
            positions = extracted_data.get('daily_positions', [])
            if positions:
                import pandas as pd
                pos_df = pd.DataFrame(positions)
                pos_df.columns = ['Name', 'Amount', 'Monthly Payment']
                pos_df['Amount'] = pos_df['Amount'].apply(lambda x: f"${x:,.2f}")
                pos_df['Monthly Payment'] = pos_df['Monthly Payment'].apply(lambda x: f"${x:,.2f}")
                st.dataframe(pos_df, use_container_width=True, hide_index=True)
            else:
                st.info("No Daily Positions found in the spreadsheet")
            
            # WEEKLY POSITIONS SECTION
            st.markdown("### 📅 Weekly Positions")
            weekly_positions = extracted_data.get('weekly_positions', [])
            if weekly_positions:
                import pandas as pd
                weekly_df = pd.DataFrame(weekly_positions)
                weekly_df.columns = ['Name', 'Amount', 'Monthly Payment']
                weekly_df['Amount'] = weekly_df['Amount'].apply(lambda x: f"${x:,.2f}")
                weekly_df['Monthly Payment'] = weekly_df['Monthly Payment'].apply(lambda x: f"${x:,.2f}")
                st.dataframe(weekly_df, use_container_width=True, hide_index=True)
            else:
                st.info("No Weekly Positions found in the spreadsheet")
            
            # MONTHLY POSITIONS (NON MCA) SECTION
            st.markdown("### 📆 Monthly Positions (non MCA)")
            monthly_non_mca = extracted_data.get('monthly_positions_non_mca', [])
            if monthly_non_mca:
                import pandas as pd
                monthly_df = pd.DataFrame(monthly_non_mca)
                monthly_df = monthly_df[['name', 'monthly_payment']]  # Only show name and payment
                monthly_df.columns = ['Name', 'Monthly Payment']
                monthly_df['Monthly Payment'] = monthly_df['Monthly Payment'].apply(lambda x: f"${x:,.2f}")
                st.dataframe(monthly_df, use_container_width=True, hide_index=True)
            else:
                st.info("No Monthly Positions (non MCA) found in the spreadsheet")
            
            # BANK ACCOUNTS SECTION
            st.markdown("### 🏦 Bank Account Data")
            bank_accounts = extracted_data.get('bank_accounts', {})
            if bank_accounts:
                # Create tabs for each bank account
                account_names = list(bank_accounts.keys())
                if account_names:
                    tabs = st.tabs(account_names)
                    for idx, account_name in enumerate(account_names):
                        with tabs[idx]:
                            account_data = bank_accounts[account_name]
                            months_data = account_data.get('months', [])
                            if months_data:
                                import pandas as pd
                                months_df = pd.DataFrame(months_data)
                                months_df.columns = ['Month', 'Total Income', 'Deductions', 'Net Revenue']
                                months_df['Total Income'] = months_df['Total Income'].apply(lambda x: f"${x:,.2f}")
                                months_df['Deductions'] = months_df['Deductions'].apply(lambda x: f"${x:,.2f}")
                                months_df['Net Revenue'] = months_df['Net Revenue'].apply(lambda x: f"${x:,.2f}")
                                st.dataframe(months_df, use_container_width=True, hide_index=True)
                            else:
                                st.info(f"No monthly data found for {account_name}")
            else:
                st.info("No Bank Account data found in the spreadsheet")
            
            # TOTAL REVENUES SECTION
            st.markdown("### 📈 Total Revenues by Month")
            revenues = extracted_data.get('total_revenues_by_month', {})
            if revenues:
                import pandas as pd
                rev_df = pd.DataFrame(list(revenues.items()), columns=['Month', 'Total Revenue'])
                rev_df['Total Revenue'] = rev_df['Total Revenue'].apply(lambda x: f"${x:,.2f}")
                st.dataframe(rev_df, use_container_width=True, hide_index=True)
            else:
                # Calculate from bank accounts if available
                if bank_accounts:
                    st.info("Total Revenues calculated from Bank Account Net Revenues:")
                    total_by_month = {}
                    for account_name, account_data in bank_accounts.items():
                        for month_entry in account_data.get('months', []):
                            month = month_entry['month']
                            if month not in total_by_month:
                                total_by_month[month] = 0
                            total_by_month[month] += month_entry['net_revenue']
                    if total_by_month:
                        import pandas as pd
                        rev_df = pd.DataFrame(list(total_by_month.items()), columns=['Month', 'Total Net Revenue'])
                        rev_df['Total Net Revenue'] = rev_df['Total Net Revenue'].apply(lambda x: f"${x:,.2f}")
                        st.dataframe(rev_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No Total Revenues data found")
            
            # Update session state with key values for the form
            st.session_state.truth_annual_income = info.get('annual_income', 0)
            st.session_state.truth_monthly_income = info.get('average_monthly_income', 0)
            st.session_state.truth_payments = info.get('total_monthly_payments', 0)
            st.session_state.truth_diesel = info.get('diesel_total_monthly_payments', 0)
            
            # Calculate total revenues from bank accounts for the last 4 months
            total_revenue_4m = 0
            if bank_accounts:
                for account_data in bank_accounts.values():
                    months_data = account_data.get('months', [])
                    # Take last 4 months with data
                    for month_entry in months_data[-4:]:
                        total_revenue_4m += month_entry.get('net_revenue', 0)
            st.session_state.truth_revenues = total_revenue_4m
            st.session_state.truth_nsf = 0  # Not in this format
            
            st.markdown("---")
            st.success(f"""
            **Key Values Saved for Training:**
            - Annual Income: ${st.session_state.truth_annual_income:,.2f}
            - Avg Monthly Income: ${st.session_state.truth_monthly_income:,.2f}
            - Total Monthly Payments: ${st.session_state.truth_payments:,.2f}
            - Diesel's Total Payments: ${st.session_state.truth_diesel:,.2f}
            - Revenues (Last 4M Net): ${st.session_state.truth_revenues:,.2f}
            """)
            
        except Exception as e:
            st.error(f"❌ Error parsing Excel file: {str(e)}")
            import traceback
            with st.expander("🔍 Error Details"):
                st.code(traceback.format_exc())
    
    # Show current saved values if no new file uploaded
    if excel_file is None and st.session_state.extracted_excel_data is not None:
        st.success("📂 Using previously loaded Excel data (upload a new file to replace)")
        info = st.session_state.extracted_excel_data.get('info_needed', {})
        st.info(f"""
        **Previously Loaded Key Values:**
        - Annual Income: ${st.session_state.truth_annual_income:,.2f}
        - Avg Monthly Income: ${st.session_state.truth_monthly_income:,.2f}
        - Total Monthly Payments: ${st.session_state.truth_payments:,.2f}
        - Diesel's Total Payments: ${st.session_state.truth_diesel:,.2f}
        """)
else:
    # Manual entry mode - show instructions
    st.markdown("Enter the **correct** values in the form below (what the AI should have extracted)")
    st.info("👇 Scroll down to the form below to enter PDF files and truth values manually")

st.divider()

with st.form("upload_training_deal"):
    col1, col2 = st.columns(2)
    
    with col1:
        sender_email = st.text_input("Sender Email", value="training@example.com")
        deal_subject = st.text_input("Subject", value="Training Deal")
    
    with col2:
        uploaded_pdfs = st.file_uploader(
            "Upload PDF Bank Statements",
            type=['pdf'],
            accept_multiple_files=True,
            key='pdf_uploader'
        )
    
    # Show manual input fields if manual entry is selected
    if truth_input_method == "✍️ Enter Manually":
        st.markdown("Enter the **correct** values for this deal (what the AI should have extracted)")
        
        col1, col2 = st.columns(2)
        
        with col1:
            truth_annual_income = st.number_input("Truth: Annual Income", value=st.session_state.truth_annual_income, step=1000.0, key='form_annual_income')
            truth_monthly_income = st.number_input("Truth: Avg Monthly Income", value=st.session_state.truth_monthly_income, step=100.0, key='form_monthly_income')
            truth_revenues = st.number_input("Truth: Revenues (4M)", value=st.session_state.truth_revenues, step=1000.0, key='form_revenues')
        
        with col2:
            truth_payments = st.number_input("Truth: Monthly Payments", value=st.session_state.truth_payments, step=100.0, key='form_payments')
            truth_diesel = st.number_input("Truth: Diesel Payments", value=st.session_state.truth_diesel, step=100.0, key='form_diesel')
            truth_nsf = st.number_input("Truth: NSF Count", value=int(st.session_state.truth_nsf), step=1, key='form_nsf')
    else:
        # Excel mode - display read-only summary using session state
        st.info(f"""
        **Using Excel Values:**
        - Annual Income: ${st.session_state.truth_annual_income:,.2f}
        - Monthly Income: ${st.session_state.truth_monthly_income:,.2f}
        - Revenues (4M): ${st.session_state.truth_revenues:,.2f}
        - Monthly Payments: ${st.session_state.truth_payments:,.2f}
        - Diesel Payments: ${st.session_state.truth_diesel:,.2f}
        - NSF Count: {st.session_state.truth_nsf}
        """)
    
    submit_training = st.form_submit_button("🧪 Run Adversarial Training", type="primary")
    
    if submit_training and uploaded_pdfs:
        with st.spinner("Processing training deal..."):
            # Get truth values from appropriate source
            # If manual mode, use form values; if Excel mode, use session state
            if truth_input_method == "✍️ Enter Manually":
                # Use form values (already defined in manual mode)
                final_truth_annual = truth_annual_income
                final_truth_monthly = truth_monthly_income
                final_truth_revenues = truth_revenues
                final_truth_payments = truth_payments
                final_truth_diesel = truth_diesel
                final_truth_nsf = truth_nsf
            else:
                # Use session state values (from Excel upload)
                final_truth_annual = st.session_state.truth_annual_income
                final_truth_monthly = st.session_state.truth_monthly_income
                final_truth_revenues = st.session_state.truth_revenues
                final_truth_payments = st.session_state.truth_payments
                final_truth_diesel = st.session_state.truth_diesel
                final_truth_nsf = st.session_state.truth_nsf
            
            # Save uploaded PDFs
            upload_dir = "uploads"
            os.makedirs(upload_dir, exist_ok=True)
            
            saved_paths = []
            for uploaded_file in uploaded_pdfs:
                file_path = os.path.join(upload_dir, uploaded_file.name)
                with open(file_path, 'wb') as f:
                    f.write(uploaded_file.getbuffer())
                saved_paths.append(file_path)
            
            # Create a training deal
            with get_db() as db:
                from pdf_processor import calculate_pdf_hash, extract_account_number_from_pdf
                from verification import auto_retry_extraction_with_verification
                from transfer_hunter import find_inter_account_transfers
                
                # Create deal
                training_deal = Deal(
                    sender=sender_email,
                    subject=f"[TRAINING] {deal_subject}",
                    email_body="Forensic training deal",
                    status="Training",
                    created_at=datetime.utcnow()
                )
                db.add(training_deal)
                db.flush()
                
                # Process PDFs
                all_transactions = []
                
                for pdf_path in saved_paths:
                    # Calculate hash
                    pdf_hash = calculate_pdf_hash(pdf_path)
                    account_number, account_status = extract_account_number_from_pdf(pdf_path)
                    
                    # Check if PDF with same hash already exists
                    existing_pdf = db.query(PDFFile).filter(PDFFile.file_hash == pdf_hash).first()
                    
                    if existing_pdf:
                        # PDF already processed before - create unique hash for training
                        # Truncate original hash and add short suffix to stay within 64 chars
                        unique_hash = pdf_hash[:50] + f"_t{training_deal.id}"[:14]
                        pdf_file = PDFFile(
                            deal_id=training_deal.id,
                            file_path=pdf_path,
                            file_hash=unique_hash,
                            account_number=account_number,
                            account_status=account_status,
                            created_at=datetime.utcnow()
                        )
                        db.add(pdf_file)
                    else:
                        # New PDF - save with original hash
                        pdf_file = PDFFile(
                            deal_id=training_deal.id,
                            file_path=pdf_path,
                            file_hash=pdf_hash,
                            account_number=account_number,
                            account_status=account_status,
                            created_at=datetime.utcnow()
                        )
                        db.add(pdf_file)
                    
                    # Extract data (blind run)
                    extracted_data, reasoning_log, retry_count, final_status = auto_retry_extraction_with_verification(
                        pdf_path,
                        account_number
                    )
                    
                    transactions = extracted_data.get('transactions', [])
                    # Validate and sanitize transactions using the utility function
                    valid_transactions = validate_and_sanitize_transactions(transactions)
                    all_transactions.extend(valid_transactions)
                
                # Run transfer hunter on all transactions
                if all_transactions:
                    # Double-check all transactions are dicts before assignment
                    all_transactions = [t for t in all_transactions if isinstance(t, dict)]
                    for txn in all_transactions:
                        txn['deal_id'] = training_deal.id
                    
                    all_transactions = find_inter_account_transfers(all_transactions)
                    
                    # Save transactions
                    for txn in all_transactions:
                        transaction = Transaction(
                            deal_id=training_deal.id,
                            source_account_id=txn.get('source_account_id'),
                            transaction_date=datetime.strptime(txn.get('date', '2024-01-01'), '%Y-%m-%d'),
                            description=txn.get('description', ''),
                            amount=txn.get('amount', 0),
                            transaction_type=txn.get('type', 'unknown'),
                            is_internal_transfer=txn.get('is_internal_transfer', False),
                            matched_transfer_id=txn.get('matched_transfer_id'),
                            category=txn.get('category', 'other'),
                            created_at=datetime.utcnow()
                        )
                        db.add(transaction)
                
                # Update deal with AI's results
                training_deal.extracted_data = extracted_data
                training_deal.ai_reasoning_log = reasoning_log
                training_deal.retry_count = retry_count
                
                db.commit()
                
                # Now compare AI results vs truth
                # Handle both old flat format and new nested format from AI
                ai_info = extracted_data.get('info_needed', extracted_data)
                
                ai_result = {
                    'info_needed': {
                        'total_monthly_payments': ai_info.get('total_monthly_payments', 0),
                        'diesel_total_monthly_payments': ai_info.get('diesel_total_monthly_payments', ai_info.get('diesel_payments', 0)),
                        'total_monthly_payments_with_diesel': ai_info.get('total_monthly_payments_with_diesel', 0),
                        'average_monthly_income': ai_info.get('average_monthly_income', ai_info.get('avg_monthly_income', 0)),
                        'annual_income': ai_info.get('annual_income', 0),
                        'length_of_deal_months': ai_info.get('length_of_deal_months', 0),
                        'holdback_percentage': ai_info.get('holdback_percentage', 0),
                        'monthly_holdback': ai_info.get('monthly_holdback', 0),
                        'monthly_payment_to_income_pct': ai_info.get('monthly_payment_to_income_pct', 0),
                        'original_balance_to_annual_income_pct': ai_info.get('original_balance_to_annual_income_pct', 0),
                    },
                    'daily_positions': extracted_data.get('daily_positions', []),
                    'weekly_positions': extracted_data.get('weekly_positions', []),
                    'monthly_positions_non_mca': extracted_data.get('monthly_positions_non_mca', []),
                    'bank_accounts': extracted_data.get('bank_accounts', {}),
                    'total_revenues_by_month': extracted_data.get('total_revenues_by_month', {}),
                    'deductions': extracted_data.get('deductions', {}),
                    'nsf_count': extracted_data.get('nsf_count', 0)
                }
                
                # Get full truth data from Excel if available, otherwise use manual values
                if truth_input_method == "📊 Upload Excel File" and st.session_state.extracted_excel_data:
                    human_truth = st.session_state.extracted_excel_data
                else:
                    # Manual entry - create compatible structure
                    human_truth = {
                        'info_needed': {
                            'total_monthly_payments': final_truth_payments,
                            'diesel_total_monthly_payments': final_truth_diesel,
                            'total_monthly_payments_with_diesel': final_truth_payments + final_truth_diesel,
                            'average_monthly_income': final_truth_monthly,
                            'annual_income': final_truth_annual,
                            'length_of_deal_months': 0,
                            'holdback_percentage': 0,
                            'monthly_holdback': 0,
                            'monthly_payment_to_income_pct': 0,
                            'original_balance_to_annual_income_pct': 0,
                        },
                        'daily_positions': [],
                        'weekly_positions': [],
                        'monthly_positions_non_mca': [],
                        'bank_accounts': {},
                        'total_revenues_by_month': {},
                        'deductions': {},
                        'nsf_count': final_truth_nsf
                    }
                
                # Store in session state for display
                st.session_state['training_result'] = {
                    'deal_id': training_deal.id,
                    'ai_result': ai_result,
                    'human_truth': human_truth,
                    'transactions': all_transactions,
                    'full_extracted_data': extracted_data
                }
                
                st.success(f"✅ Training deal created! Deal ID: {training_deal.id}")
                st.rerun()

# Display training results
if 'training_result' in st.session_state:
    st.divider()
    st.subheader("📊 Training Results - Comprehensive Comparison")
    
    result = st.session_state['training_result']
    ai_result = result['ai_result']
    human_truth = result['human_truth']
    
    # Helper function for safe numeric comparison
    def safe_float_val(val, default=0.0):
        if val is None:
            return default
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            cleaned = val.replace('$', '').replace(',', '').replace('%', '').strip()
            if cleaned == '' or cleaned == '-':
                return default
            try:
                return float(cleaned)
            except:
                return default
        return default
    
    # INFO NEEDED COMPARISON
    st.markdown("### 📝 Info Needed Metrics Comparison")
    
    ai_info = ai_result.get('info_needed', ai_result)
    human_info = human_truth.get('info_needed', human_truth)
    
    info_fields = [
        ('total_monthly_payments', 'Total Monthly Payments', '$'),
        ('diesel_total_monthly_payments', "Diesel's Total Monthly Payments", '$'),
        ('total_monthly_payments_with_diesel', 'Total w/ Diesel', '$'),
        ('average_monthly_income', 'Avg Monthly Income', '$'),
        ('annual_income', 'Annual Income', '$'),
        ('length_of_deal_months', 'Length of Deal (months)', ''),
        ('holdback_percentage', 'Holdback %', '%'),
        ('monthly_holdback', 'Monthly Holdback', '$'),
        ('monthly_payment_to_income_pct', 'Payment to Income %', '%'),
        ('original_balance_to_annual_income_pct', 'Orig Balance to Annual Income %', '%'),
    ]
    
    differences = []
    for field_key, field_name, symbol in info_fields:
        ai_val = safe_float_val(ai_info.get(field_key, 0))
        human_val = safe_float_val(human_info.get(field_key, 0))
        diff = human_val - ai_val
        
        if symbol == '$':
            ai_display = f"${ai_val:,.2f}"
            human_display = f"${human_val:,.2f}"
            diff_display = f"${diff:,.2f}"
        elif symbol == '%':
            ai_display = f"{ai_val:.2f}%"
            human_display = f"{human_val:.2f}%"
            diff_display = f"{diff:.2f}%"
        else:
            ai_display = f"{ai_val:.0f}"
            human_display = f"{human_val:.0f}"
            diff_display = f"{diff:.0f}"
        
        match_status = "✅" if abs(diff) < 0.01 else "❌"
        differences.append({
            'Field': field_name,
            'AI': ai_display,
            'Truth': human_display,
            'Diff': diff_display,
            'Match': match_status
        })
    
    import pandas as pd
    diff_df = pd.DataFrame(differences)
    st.dataframe(diff_df, use_container_width=True, hide_index=True)
    
    # Count matches vs mismatches
    matches = sum(1 for d in differences if d['Match'] == '✅')
    total = len(differences)
    if matches == total:
        st.success(f"✅ Perfect match on all {total} Info Needed metrics!")
    else:
        st.warning(f"⚠️ {matches}/{total} metrics match. {total - matches} differences found.")
    
    # POSITIONS COMPARISON
    st.markdown("### 📊 Positions Comparison")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**Daily Positions**")
        ai_daily = ai_result.get('daily_positions', [])
        human_daily = human_truth.get('daily_positions', [])
        st.write(f"AI found: {len(ai_daily)} | Truth: {len(human_daily)}")
        if len(ai_daily) != len(human_daily):
            st.error(f"❌ Mismatch in count")
        else:
            st.success("✅ Count matches")
    
    with col2:
        st.markdown("**Weekly Positions**")
        ai_weekly = ai_result.get('weekly_positions', [])
        human_weekly = human_truth.get('weekly_positions', [])
        st.write(f"AI found: {len(ai_weekly)} | Truth: {len(human_weekly)}")
        if len(ai_weekly) != len(human_weekly):
            st.error(f"❌ Mismatch in count")
        else:
            st.success("✅ Count matches")
    
    with col3:
        st.markdown("**Monthly (non MCA) Positions**")
        ai_monthly = ai_result.get('monthly_positions_non_mca', [])
        human_monthly = human_truth.get('monthly_positions_non_mca', [])
        st.write(f"AI found: {len(ai_monthly)} | Truth: {len(human_monthly)}")
        if len(ai_monthly) != len(human_monthly):
            st.error(f"❌ Mismatch in count")
        else:
            st.success("✅ Count matches")
    
    # BANK ACCOUNTS COMPARISON
    st.markdown("### 🏦 Bank Accounts Comparison")
    ai_accounts = ai_result.get('bank_accounts', {})
    human_accounts = human_truth.get('bank_accounts', {})
    st.write(f"AI found: {len(ai_accounts)} accounts | Truth: {len(human_accounts)} accounts")
    
    # Show detailed comparison in expanders
    with st.expander("🔍 View Detailed AI Results"):
        st.json(ai_result)
    
    with st.expander("🔍 View Detailed Truth Data"):
        st.json(human_truth)
    
    # Run adversarial correction
    if differences:
        st.divider()
        st.subheader("🔍 The Interrogation - AI Self-Audit")
        
        if st.button("🚀 Run Adversarial Correction", type="primary"):
            with st.spinner("AI is auditing itself..."):
                correction_report_json = adversarial_correction_prompt(
                    ai_result,
                    human_truth,
                    result['transactions']
                )
                
                try:
                    correction_report = json.loads(correction_report_json)
                    
                    # Store in session state so it persists across reruns
                    st.session_state.last_correction_report = correction_report
                    st.session_state.last_correction_timestamp = datetime.utcnow()
                    st.session_state.last_correction_saved = False
                    st.session_state.last_correction_id = None
                    
                    # Auto-save to database with error handling
                    try:
                        with get_db() as db:
                            training_example = TrainingExample(
                                original_financial_json=ai_result,
                                user_corrected_summary=f"Self-Audit Report - {len(correction_report.get('errors_found', []))} errors found",
                                correction_details={
                                    'correction_report': correction_report,
                                    'human_truth': human_truth,
                                    'differences_count': len(differences),
                                    'audit_type': 'adversarial_self_audit'
                                },
                                created_at=datetime.utcnow()
                            )
                            db.add(training_example)
                            db.commit()
                            db.refresh(training_example)
                            st.session_state.last_correction_saved = True
                            st.session_state.last_correction_id = training_example.id
                    except Exception as db_error:
                        st.warning(f"⚠️ Could not save to database: {str(db_error)}")
                        st.session_state.last_correction_saved = False
                    
                    st.success("✅ AI has completed its self-audit!")
                    st.rerun()
                    
                except json.JSONDecodeError:
                    st.error("Error parsing AI's correction report")
                    st.text(correction_report_json)
        
        # Note: The correction report display is now handled by the standalone section at the top
        if st.session_state.last_correction_report:
            st.info("📝 See the 'Most Recent Self-Audit Report' section above for the detailed results")

st.divider()

# Show existing training examples
st.subheader("📚 Training History & Self-Audit Results")

with get_db() as db:
    training_examples = db.query(TrainingExample).order_by(TrainingExample.created_at.desc()).limit(20).all()
    
    if training_examples:
        # Count self-audits
        audit_count = sum(1 for ex in training_examples if ex.correction_details and ex.correction_details.get('audit_type') == 'adversarial_self_audit')
        st.info(f"📊 Found {len(training_examples)} training examples ({audit_count} self-audits)")
        
        for example in training_examples:
            # Determine if this is a self-audit
            is_self_audit = example.correction_details and example.correction_details.get('audit_type') == 'adversarial_self_audit'
            icon = "🔬" if is_self_audit else "📝"
            label = "Self-Audit" if is_self_audit else "Training Example"
            
            with st.expander(f"{icon} {label} #{example.id} - {example.created_at.strftime('%Y-%m-%d %H:%M')} - {example.user_corrected_summary}"):
                
                if is_self_audit and example.correction_details:
                    # Display self-audit results in a user-friendly format
                    correction_report = example.correction_details.get('correction_report', {})
                    
                    # Add "Load in Viewer" button to view this audit in the top viewer
                    if st.button(f"📤 Load in Main Viewer", key=f"load_audit_{example.id}"):
                        st.session_state.last_correction_report = correction_report
                        st.session_state.last_correction_timestamp = example.created_at
                        st.session_state.last_correction_saved = True
                        st.session_state.last_correction_id = example.id
                        st.session_state._manual_load_active = True  # Prevent auto-load from overwriting
                        st.success("✅ Loaded! Scroll up to see the 'Most Recent Self-Audit Report' section")
                        st.rerun()
                    
                    st.markdown("### 📊 Audit Summary")
                    col1, col2 = st.columns(2)
                    with col1:
                        errors_count = len(correction_report.get('errors_found', []))
                        missed_count = len(correction_report.get('missed_transactions', []))
                        st.metric("Errors Found", errors_count)
                    with col2:
                        miscat_count = len(correction_report.get('miscategorized_transactions', []))
                        st.metric("Miscategorized", miscat_count)
                    
                    # Display errors
                    if correction_report.get('errors_found'):
                        st.markdown("### ❌ Errors Identified")
                        for i, error in enumerate(correction_report['errors_found'], 1):
                            st.error(f"{i}. {error}")
                    
                    # Display missed transactions
                    if correction_report.get('missed_transactions'):
                        st.markdown("### 🔍 Missed Transactions")
                        for txn in correction_report['missed_transactions']:
                            desc = txn.get('description', 'N/A')
                            amt = txn.get('amount', 0)
                            why = txn.get('why_missed', 'N/A')
                            st.warning(f"**{desc}**: ${amt:,.2f} - *{why}*")
                    
                    # Display miscategorized
                    if correction_report.get('miscategorized_transactions'):
                        st.markdown("### 🔄 Miscategorized Transactions")
                        for txn in correction_report['miscategorized_transactions']:
                            desc = txn.get('description', 'N/A')
                            was_cat = txn.get('was_categorized_as', 'N/A')
                            should_be = txn.get('should_be', 'N/A')
                            st.warning(f"**{desc}**: Was '{was_cat}' → Should be '{should_be}'")
                    
                    # Display explanation
                    if correction_report.get('correction_explanation'):
                        st.markdown("### 📖 Detailed Explanation")
                        st.info(correction_report['correction_explanation'])
                    
                    # Display root cause if present
                    if correction_report.get('root_cause'):
                        st.markdown("### 🔬 Root Cause")
                        st.write(correction_report['root_cause'])
                    
                    # Display recommendations if present
                    if correction_report.get('recommendations'):
                        st.markdown("### 💡 Recommendations")
                        for rec in correction_report['recommendations']:
                            st.write(f"• {rec}")
                    
                    # Display learned pattern if present
                    if correction_report.get('learned_pattern'):
                        st.markdown("### 🧠 Learned Pattern")
                        st.code(correction_report['learned_pattern'], language='text')
                    
                    # Raw data expanders
                    with st.expander("🔧 View Raw Correction Report"):
                        st.json(correction_report)
                    
                    with st.expander("🔧 View Human Truth Data"):
                        human_truth = example.correction_details.get('human_truth', {})
                        st.json(human_truth)
                
                else:
                    # Regular training example display
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        st.markdown("**Original AI Data:**")
                        st.json(example.original_financial_json)
                    
                    with col2:
                        st.markdown("**Corrected Summary:**")
                        st.text(example.user_corrected_summary)
                    
                    if example.correction_details:
                        st.markdown("**Correction Details:**")
                        st.json(example.correction_details)
    else:
        st.info("No training examples yet. Upload a deal and run a self-audit to start training the AI!")
