import streamlit as st
import json
import os
from database import get_db
from models import Deal, PDFFile, Transaction, TrainingExample, GoldStandardRule
from datetime import datetime
from transfer_hunter import (
    calculate_revenue_with_overrides,
    detect_lender_positions,
    safe_float,
    KNOWN_LENDER_KEYWORDS
)

st.set_page_config(page_title="Deal Details", page_icon="📄", layout="wide")

st.title("📄 Deal Details")

# Get selected deal ID from session state or selectbox
deal_id = st.session_state.get('selected_deal_id', None)

if not deal_id:
    st.warning("No deal selected. Please select a deal from the Inbox.")
    
    with get_db() as db:
        deals = db.query(Deal).order_by(Deal.created_at.desc()).limit(20).all()
        if deals:
            deal_options = {d.id: f"Deal #{d.id} - {d.sender} - {d.status}" for d in deals}
            selected = st.selectbox("Select a deal", options=list(deal_options.keys()), format_func=lambda x: deal_options[x])
            if st.button("Load Deal"):
                st.session_state['selected_deal_id'] = selected
                st.rerun()
    st.stop()

# Load deal details
with get_db() as db:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    
    if not deal:
        st.error(f"Deal #{deal_id} not found")
        st.stop()
    
    # Header
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        st.subheader(f"Deal #{deal.id}")
        st.caption(f"From: {deal.sender}")
    
    with col2:
        status_colors = {
            'Pending Approval': '🟡',
            'Needs Human Review': '🟠',
            'Approved': '🟢',
            'Rejected': '🔴',
            'Duplicate': '⚫'
        }
        st.metric("Status", f"{status_colors.get(deal.status, '⚪')} {deal.status}")
    
    with col3:
        st.metric("Retry Count", deal.retry_count)
    
    st.divider()
    
    # Main content area - Split screen
    left_col, right_col = st.columns([1, 1])
    
    with left_col:
        st.subheader("📁 Original PDFs")
        
        # Get PDF files
        pdf_files = deal.pdf_files
        
        if pdf_files:
            # Create tabs for each account
            account_groups = {}
            for pdf in pdf_files:
                account = pdf.account_number or "Unknown"
                if account not in account_groups:
                    account_groups[account] = []
                account_groups[account].append(pdf)
            
            if len(account_groups) > 1:
                tabs = st.tabs([f"Account {acc}" for acc in account_groups.keys()])
                
                for tab, (account, pdfs) in zip(tabs, account_groups.items()):
                    with tab:
                        for pdf in pdfs:
                            st.write(f"**File:** {os.path.basename(pdf.file_path)}")
                            st.caption(f"Account: {pdf.account_number or 'Unknown'} ({pdf.account_status})")
                            st.caption(f"Hash: {pdf.file_hash[:16]}...")
                            
                            if os.path.exists(pdf.file_path):
                                with open(pdf.file_path, 'rb') as f:
                                    st.download_button(
                                        "Download PDF",
                                        f,
                                        file_name=os.path.basename(pdf.file_path),
                                        mime="application/pdf"
                                    )
                            st.divider()
            else:
                # Single account
                for pdf in pdf_files:
                    st.write(f"**File:** {os.path.basename(pdf.file_path)}")
                    st.caption(f"Account: {pdf.account_number or 'Unknown'} ({pdf.account_status})")
                    st.caption(f"Hash: {pdf.file_hash[:16]}...")
                    
                    if os.path.exists(pdf.file_path):
                        with open(pdf.file_path, 'rb') as f:
                            st.download_button(
                                "Download PDF",
                                f,
                                file_name=os.path.basename(pdf.file_path),
                                mime="application/pdf",
                                key=f"download_{pdf.id}"
                            )
                    st.divider()
        else:
            st.info("No PDF files attached to this deal")
    
    with right_col:
        st.subheader("🤖 AI Extracted Data")
        
        if deal.extracted_data:
            # Display key metrics
            data = deal.extracted_data
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.metric("Annual Income", f"${data.get('annual_income', 0):,.0f}")
                st.metric("Avg Monthly Income", f"${data.get('avg_monthly_income', 0):,.0f}")
                st.metric("Total Monthly Payments", f"${data.get('total_monthly_payments', 0):,.0f}")
            
            with col2:
                st.metric("Revenues (4M)", f"${data.get('revenues_last_4_months', 0):,.0f}")
                st.metric("Diesel Payments", f"${data.get('diesel_payments', 0):,.0f}")
                st.metric("NSF Count", data.get('nsf_count', 0))
            
            st.divider()
            
            # Show raw data
            with st.expander("View Raw Extracted Data"):
                st.json(data)
        else:
            st.warning("No extracted data available")
    
    # AI Reasoning Log
    st.divider()
    st.subheader("🧠 AI Reasoning Log")
    
    if deal.ai_reasoning_log:
        st.text_area("Reasoning", deal.ai_reasoning_log, height=200)
    else:
        st.info("No reasoning log available")
    
    # Transactions and Transfers
    st.divider()
    st.subheader("💸 Transactions & Transfer Detection")
    
    transactions = db.query(Transaction).filter(Transaction.deal_id == deal.id).all()
    
    if transactions:
        import pandas as pd
        
        # Initialize override session state
        if f'transfer_overrides_{deal.id}' not in st.session_state:
            st.session_state[f'transfer_overrides_{deal.id}'] = {}
        
        overrides = st.session_state[f'transfer_overrides_{deal.id}']
        
        # Convert transactions to list of dicts for revenue calculation
        txn_list = []
        for txn in transactions:
            txn_list.append({
                'id': txn.id,
                'amount': txn.amount,
                'description': txn.description,
                'is_internal_transfer': txn.is_internal_transfer,
                'transaction_date': txn.transaction_date,
                'source_account_id': txn.source_account_id,
                'transaction_type': txn.transaction_type,
                'category': txn.category,
                'matched_transfer_id': txn.matched_transfer_id
            })
        
        # Calculate revenue with overrides
        revenue_result = calculate_revenue_with_overrides(txn_list, overrides)
        
        # Detect lender positions with stacking
        detected_positions = detect_lender_positions(txn_list)
        
        txn_data = []
        for txn in transactions:
            txn_data.append({
                'ID': txn.id,
                'Date': txn.transaction_date.strftime('%Y-%m-%d') if txn.transaction_date else 'N/A',
                'Account': txn.source_account_id or 'Unknown',
                'Description': txn.description[:50] + '...' if len(txn.description) > 50 else txn.description,
                'Amount': f"${txn.amount:,.2f}",
                'Type': txn.transaction_type,
                'Category': txn.category,
                'Transfer?': '✅' if txn.is_internal_transfer else '❌',
                'Matched With': txn.matched_transfer_id or '-'
            })
        
        txn_df = pd.DataFrame(txn_data)
        
        # Show revenue metrics with override support
        transfer_count = sum(1 for txn in transactions if txn.is_internal_transfer)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Transactions", len(transactions))
        with col2:
            st.metric("Internal Transfers", transfer_count)
        with col3:
            st.metric("Net Revenue", f"${revenue_result['total_revenue']:,.2f}")
        with col4:
            months = 4  # Approximate months in statement
            monthly_avg = revenue_result['total_revenue'] / months if months > 0 else 0
            st.metric("Monthly Average", f"${monthly_avg:,.2f}")
        
        st.dataframe(txn_df, use_container_width=True)
        
        # Revenue Breakdown with Toggle Switches
        st.divider()
        st.subheader("💰 Revenue Breakdown")
        
        if revenue_result['breakdown']:
            st.markdown("**Excluded Transfers - Toggle to include in revenue:**")
            
            # Get all excluded items (transfers and deposits marked as excluded)
            excluded_items = [item for item in revenue_result['breakdown'] if not item['included']]
            
            if excluded_items:
                # Track if any toggles changed
                toggles_changed = False
                new_overrides = overrides.copy()
                
                for item in excluded_items:
                    col1, col2, col3 = st.columns([3, 1, 1])
                    
                    with col1:
                        desc = item['description'][:60] + '...' if len(item['description']) > 60 else item['description']
                        st.write(f"**${item['amount']:,.2f}** - {desc}")
                        if item['reason']:
                            st.caption(f"Reason: {item['reason']}")
                    
                    with col2:
                        # Toggle switch for including in revenue
                        current_val = overrides.get(item['id'], False)
                        include = st.toggle(
                            "Include?",
                            value=current_val,
                            key=f"toggle_{deal.id}_{item['id']}"
                        )
                        
                        # Track changes
                        if include != current_val:
                            new_overrides[item['id']] = include
                            toggles_changed = True
                    
                    with col3:
                        if item['is_transfer']:
                            st.write("🔄 Transfer")
                        else:
                            st.write("📥 Deposit")
                    
                    st.divider()
                
                # Apply button to recalculate
                if st.button("🔄 Recalculate Revenue", key=f"recalc_{deal.id}"):
                    st.session_state[f'transfer_overrides_{deal.id}'] = new_overrides
                    st.rerun()
                
                if toggles_changed:
                    st.info("Click 'Recalculate Revenue' to update totals with your selections")
            else:
                st.success("No excluded transfers - all deposits are included in revenue")
            
            # Show included transfers (user overrides)
            if revenue_result['included_transfers'] > 0:
                st.info(f"✅ {revenue_result['included_transfers']} transfers manually included in revenue by user")
        
        # Detected Lender Positions with Stacking
        if detected_positions:
            st.divider()
            st.subheader("🏦 Detected Lender Positions")
            
            stacked_count = sum(1 for p in detected_positions if p.get('is_stacked', False))
            
            if stacked_count > 0:
                st.warning(f"⚠️ {stacked_count} positions show stacking (same lender, different amounts)")
            
            positions_df = pd.DataFrame([
                {
                    'Lender': p['lender_name'],
                    'Amount': f"${p['amount']:,.2f}",
                    'Frequency': p['frequency'].title(),
                    'Monthly Payment': f"${p['monthly_payment']:,.2f}",
                    'Occurrences': p['occurrence_count'],
                    'Stacked?': '⚠️ Yes' if p.get('is_stacked') else 'No'
                }
                for p in detected_positions
            ])
            
            st.dataframe(positions_df, use_container_width=True)
            
            st.caption(f"**Known Lender Keywords:** {', '.join(KNOWN_LENDER_KEYWORDS[:8])}...")
        
        # Highlight transfers
        if transfer_count > 0:
            st.info(f"💡 {transfer_count} transactions identified as internal transfers. Use toggles above to override and recalculate revenue.")
    else:
        st.info("No transaction data available")
    
    # Correction Interface
    st.divider()
    st.subheader("✏️ Correction Mode")
    
    st.markdown("""
    If the AI misread any numbers, you can correct them here. Your corrections will be saved to the training database
    to improve future AI performance.
    """)
    
    with st.form("correction_form"):
        col1, col2 = st.columns(2)
        
        current_data = deal.extracted_data or {}
        
        with col1:
            corrected_annual_income = st.number_input(
                "Annual Income",
                value=float(current_data.get('annual_income', 0)),
                step=1000.0
            )
            
            corrected_monthly_income = st.number_input(
                "Avg Monthly Income",
                value=float(current_data.get('avg_monthly_income', 0)),
                step=100.0
            )
            
            corrected_revenues = st.number_input(
                "Revenues (Last 4 Months)",
                value=float(current_data.get('revenues_last_4_months', 0)),
                step=1000.0
            )
        
        with col2:
            corrected_payments = st.number_input(
                "Total Monthly Payments",
                value=float(current_data.get('total_monthly_payments', 0)),
                step=100.0
            )
            
            corrected_diesel = st.number_input(
                "Diesel Payments",
                value=float(current_data.get('diesel_payments', 0)),
                step=100.0
            )
            
            corrected_nsf = st.number_input(
                "NSF Count",
                value=int(current_data.get('nsf_count', 0)),
                step=1
            )
        
        correction_notes = st.text_area("Correction Notes", placeholder="Explain what was wrong and what you corrected...")
        
        submit_correction = st.form_submit_button("💾 Save Corrections & Train AI", type="primary")
        
        if submit_correction:
            # Build corrected data
            corrected_data = {
                'annual_income': corrected_annual_income,
                'avg_monthly_income': corrected_monthly_income,
                'revenues_last_4_months': corrected_revenues,
                'total_monthly_payments': corrected_payments,
                'diesel_payments': corrected_diesel,
                'nsf_count': corrected_nsf
            }
            
            # Save to TrainingExamples
            training_example = TrainingExample(
                original_financial_json=current_data,
                user_corrected_summary=json.dumps(corrected_data),
                correction_details={
                    'notes': correction_notes,
                    'corrected_fields': [k for k in corrected_data if corrected_data[k] != current_data.get(k, 0)]
                },
                deal_id=deal.id,
                created_at=datetime.utcnow()
            )
            db.add(training_example)
            
            # Update deal with corrected data
            deal.extracted_data = corrected_data
            deal.updated_at = datetime.utcnow()
            
            db.commit()
            
            st.success("✅ Corrections saved! AI will learn from this example.")
            st.rerun()
