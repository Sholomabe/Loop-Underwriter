import streamlit as st
import json
import os
from database import get_db
from models import Deal, PDFFile, Transaction, TrainingExample, GoldStandardRule
from datetime import datetime
from openai_integration import adversarial_correction_prompt
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
                    
                    # Save PDF record
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
                    all_transactions.extend(transactions)
                
                # Run transfer hunter on all transactions
                if all_transactions:
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
                ai_result = {
                    'annual_income': extracted_data.get('annual_income', 0),
                    'avg_monthly_income': extracted_data.get('avg_monthly_income', 0),
                    'revenues_last_4_months': extracted_data.get('revenues_last_4_months', 0),
                    'total_monthly_payments': extracted_data.get('total_monthly_payments', 0),
                    'diesel_payments': extracted_data.get('diesel_payments', 0),
                    'nsf_count': extracted_data.get('nsf_count', 0)
                }
                
                human_truth = {
                    'annual_income': final_truth_annual,
                    'avg_monthly_income': final_truth_monthly,
                    'revenues_last_4_months': final_truth_revenues,
                    'total_monthly_payments': final_truth_payments,
                    'diesel_payments': final_truth_diesel,
                    'nsf_count': final_truth_nsf
                }
                
                # Store in session state for display
                st.session_state['training_result'] = {
                    'deal_id': training_deal.id,
                    'ai_result': ai_result,
                    'human_truth': human_truth,
                    'transactions': all_transactions
                }
                
                st.success(f"✅ Training deal created! Deal ID: {training_deal.id}")
                st.rerun()

# Display training results
if 'training_result' in st.session_state:
    st.divider()
    st.subheader("📊 Training Results - The Diff Check")
    
    result = st.session_state['training_result']
    ai_result = result['ai_result']
    human_truth = result['human_truth']
    
    # Split screen comparison
    left_col, center_col, right_col = st.columns(3)
    
    with left_col:
        st.markdown("### 🤖 AI's Analysis")
        st.json(ai_result)
    
    with center_col:
        st.markdown("### ❌ Differences")
        
        differences = []
        for key in human_truth:
            if key in ai_result:
                diff = human_truth[key] - ai_result[key]
                if abs(diff) > 0.01:
                    differences.append({
                        'Field': key.replace('_', ' ').title(),
                        'AI': f"${ai_result[key]:,.2f}" if isinstance(ai_result[key], (int, float)) else str(ai_result[key]),
                        'Truth': f"${human_truth[key]:,.2f}" if isinstance(human_truth[key], (int, float)) else str(human_truth[key]),
                        'Diff': f"${diff:,.2f}" if isinstance(diff, (int, float)) else str(diff)
                    })
        
        if differences:
            import pandas as pd
            diff_df = pd.DataFrame(differences)
            st.dataframe(diff_df, use_container_width=True)
        else:
            st.success("✅ Perfect match! No errors found.")
    
    with right_col:
        st.markdown("### ✅ Human Truth")
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
                    
                    st.success("✅ AI has completed its self-audit!")
                    
                    # Display correction report
                    st.subheader("📝 AI's Correction Report")
                    
                    if 'errors_found' in correction_report:
                        st.markdown("**Errors Identified:**")
                        for error in correction_report['errors_found']:
                            st.write(f"- {error}")
                    
                    if 'missed_transactions' in correction_report:
                        st.markdown("**Missed Transactions:**")
                        for txn in correction_report['missed_transactions']:
                            st.write(f"- {txn.get('description', 'N/A')}: ${txn.get('amount', 0):,.2f} - {txn.get('why_missed', 'N/A')}")
                    
                    if 'miscategorized_transactions' in correction_report:
                        st.markdown("**Miscategorized Transactions:**")
                        for txn in correction_report['miscategorized_transactions']:
                            st.write(f"- {txn.get('description', 'N/A')}: Was '{txn.get('was_categorized_as', 'N/A')}', Should be '{txn.get('should_be', 'N/A')}'")
                    
                    if 'correction_explanation' in correction_report:
                        st.markdown("**Detailed Explanation:**")
                        st.write(correction_report['correction_explanation'])
                    
                    # Save learned pattern to GoldStandard_Rules
                    if 'learned_pattern' in correction_report and correction_report['learned_pattern']:
                        st.divider()
                        st.subheader("💾 Save to Memory Bank (RAG)")
                        
                        if st.button("Save Learned Pattern to GoldStandard_Rules"):
                            with get_db() as db:
                                # Create a new gold standard rule
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
                
                except json.JSONDecodeError:
                    st.error("Error parsing AI's correction report")
                    st.text(correction_report_json)

st.divider()

# Show existing training examples
st.subheader("📚 Training History")

with get_db() as db:
    training_examples = db.query(TrainingExample).order_by(TrainingExample.created_at.desc()).limit(10).all()
    
    if training_examples:
        for example in training_examples:
            with st.expander(f"Training Example #{example.id} - {example.created_at.strftime('%Y-%m-%d %H:%M')}"):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**Original Data:**")
                    st.json(example.original_financial_json)
                
                with col2:
                    st.markdown("**Corrected Summary:**")
                    st.text(example.user_corrected_summary)
                
                if example.correction_details:
                    st.markdown("**Correction Details:**")
                    st.json(example.correction_details)
    else:
        st.info("No training examples yet. Start training the AI to improve its accuracy!")
