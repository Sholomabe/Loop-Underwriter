import streamlit as st
import json
import os
import pandas as pd
from database import get_db
from models import Deal, PDFFile, Transaction, TrainingExample, GoldStandardRule
from datetime import datetime
from transfer_hunter import (
    calculate_revenue_with_overrides,
    detect_lender_positions,
    safe_float,
    KNOWN_LENDER_KEYWORDS
)
from openai_integration import MCA_KEYWORDS, OPERATING_EXPENSE_KEYWORDS, classify_position

st.set_page_config(page_title="Deal Details", page_icon="📄", layout="wide")

# ============================================
# SIDEBAR: Loan Simulator ("Diesel" Feature)
# ============================================
st.sidebar.header("🧮 Loan Simulator")
st.sidebar.caption("Calculate if merchant can afford a new loan")

loan_amount = st.sidebar.number_input(
    "Loan Amount ($)",
    min_value=0.0,
    value=50000.0,
    step=5000.0,
    format="%.2f"
)

factor_rate = st.sidebar.number_input(
    "Factor Rate",
    min_value=1.0,
    max_value=2.0,
    value=1.35,
    step=0.01,
    format="%.2f"
)

term_type = st.sidebar.radio(
    "Term Type",
    options=["Daily", "Weekly"],
    horizontal=True
)

term_length = st.sidebar.number_input(
    f"Term ({term_type} payments)",
    min_value=1,
    value=180 if term_type == "Daily" else 26,
    step=1
)

payback_amount = loan_amount * factor_rate
if term_type == "Daily":
    daily_payment = payback_amount / term_length
    weekly_payment = daily_payment * 5
    monthly_payment = daily_payment * 22
else:
    weekly_payment = payback_amount / term_length
    daily_payment = weekly_payment / 5
    monthly_payment = weekly_payment * 4.33

st.sidebar.divider()
st.sidebar.subheader("💰 Calculated Payments")
st.sidebar.metric("Total Payback", f"${payback_amount:,.2f}")
st.sidebar.metric("Daily Payment", f"${daily_payment:,.2f}")
st.sidebar.metric("Weekly Payment", f"${weekly_payment:,.2f}")
st.sidebar.metric("Monthly Payment", f"${monthly_payment:,.2f}")

st.session_state['simulated_diesel_monthly'] = monthly_payment

# ============================================
# MAIN PAGE
# ============================================
st.title("📄 Deal Details")

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

with get_db() as db:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    
    if not deal:
        st.error(f"Deal #{deal_id} not found")
        st.stop()
    
    # ============================================
    # SECTION 1: DEAL INFO (Top)
    # ============================================
    st.header("📋 Deal Info - Proposed Diesel Loan")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Deal #", deal.id)
        st.caption(f"From: {deal.sender}")
    
    with col2:
        status_colors = {
            'Pending Approval': '🟡',
            'Needs Human Review': '🟠',
            'Approved': '🟢',
            'Rejected': '🔴',
            'Duplicate': '⚫',
            'Training': '🔵',
            'Underwritten': '🟢'
        }
        st.metric("Status", f"{status_colors.get(deal.status, '⚪')} {deal.status}")
    
    with col3:
        data = deal.extracted_data or {}
        extraction_source = data.get('extraction_source', 'openai')
        if extraction_source == 'koncile':
            st.metric("Extraction", "📊 Koncile")
        else:
            st.metric("Extraction", "🤖 OpenAI")
    
    with col4:
        info_needed = data.get('info_needed', data)
        net_revenue = safe_float(info_needed.get('average_monthly_income', 0))
        current_payments = safe_float(info_needed.get('total_monthly_payments', 0))
        simulated_diesel = st.session_state.get('simulated_diesel_monthly', 0)
        
        projected_balance = net_revenue - current_payments - simulated_diesel
        
        if projected_balance >= 0:
            st.metric("Projected Balance", f"${projected_balance:,.2f}", delta="Affordable")
        else:
            st.metric("Projected Balance", f"${projected_balance:,.2f}", delta="Insufficient Cash Flow", delta_color="inverse")
    
    if projected_balance < 0:
        st.error("⚠️ **INSUFFICIENT CASH FLOW** - Projected balance is negative after adding simulated diesel payment.")
    
    verification_data = data.get('verification', {})
    if verification_data:
        ver_is_valid = verification_data.get('is_valid', True)
        ver_confidence = verification_data.get('confidence_score', 1.0)
        ver_discrepancies = verification_data.get('discrepancies', [])
        
        if ver_is_valid:
            st.success(f"✅ **Koncile Verification PASSED** - Confidence: {ver_confidence:.0%}")
        else:
            st.warning(f"⚠️ **Koncile Verification Found {len(ver_discrepancies)} Issues** - Confidence: {ver_confidence:.0%}")
            with st.expander("View Discrepancies", expanded=False):
                for d in ver_discrepancies:
                    severity_icon = "🔴" if d.get('severity') == 'high' else "🟡"
                    st.write(f"{severity_icon} **{d.get('field')}**: Expected ${d.get('summary_value', 0):,.2f}, Got ${d.get('calculated_value', 0):,.2f}")
    
    st.divider()
    
    # ============================================
    # SECTION 2: ACTIVE MCA POSITIONS (Middle)
    # ============================================
    st.header("🏦 Active MCA Positions")
    
    transactions = db.query(Transaction).filter(Transaction.deal_id == deal.id).all()
    
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
    
    detected_positions = detect_lender_positions(txn_list) if txn_list else []
    
    mca_positions = []
    other_liabilities = []
    
    for p in detected_positions:
        classification = classify_position(p['lender_name'])
        if classification == 'mca_position':
            mca_positions.append(p)
        else:
            other_liabilities.append({
                **p,
                'liability_type': 'operating_expense' if classification == 'operating_expense' else 'other'
            })
    
    data = deal.extracted_data or {}
    daily_positions = data.get('daily_positions', [])
    weekly_positions = data.get('weekly_positions', [])
    monthly_positions = data.get('monthly_positions_non_mca', [])
    ai_other_liabilities = data.get('other_liabilities', [])
    
    if daily_positions or weekly_positions or monthly_positions or mca_positions:
        col1, col2, col3 = st.columns(3)
        
        total_mca_monthly = 0
        
        with col1:
            st.subheader("📅 Daily Positions")
            if daily_positions:
                for pos in daily_positions:
                    name = pos.get('name', 'Unknown')
                    amount = safe_float(pos.get('amount', 0))
                    monthly = safe_float(pos.get('monthly_payment', amount * 22))
                    total_mca_monthly += monthly
                    st.markdown(f"**{name}**")
                    st.caption(f"${amount:,.2f}/day × 22 = ${monthly:,.2f}/mo")
            else:
                st.caption("No daily positions detected")
        
        with col2:
            st.subheader("📆 Weekly Positions")
            if weekly_positions:
                for pos in weekly_positions:
                    name = pos.get('name', 'Unknown')
                    amount = safe_float(pos.get('amount', 0))
                    monthly = safe_float(pos.get('monthly_payment', amount * 4.33))
                    total_mca_monthly += monthly
                    st.markdown(f"**{name}**")
                    st.caption(f"${amount:,.2f}/wk × 4.33 = ${monthly:,.2f}/mo")
            else:
                st.caption("No weekly positions detected")
        
        with col3:
            st.subheader("📆 Monthly Positions")
            if monthly_positions:
                for pos in monthly_positions:
                    name = pos.get('name', 'Unknown')
                    monthly = safe_float(pos.get('monthly_payment', 0))
                    total_mca_monthly += monthly
                    st.markdown(f"**{name}**")
                    st.caption(f"${monthly:,.2f}/mo")
            else:
                st.caption("No monthly positions detected")
        
        for p in mca_positions:
            total_mca_monthly += safe_float(p.get('monthly_payment', 0))
        
        st.divider()
        col1, col2, col3 = st.columns(3)
        with col1:
            position_count = len(daily_positions) + len(weekly_positions) + len(monthly_positions) + len(mca_positions)
            st.metric("Position Count", position_count)
        with col2:
            st.metric("Total MCA Payments/Mo", f"${total_mca_monthly:,.2f}")
        with col3:
            stacked = sum(1 for p in mca_positions if p.get('is_stacked', False))
            if stacked > 0:
                st.warning(f"⚠️ {stacked} stacked positions detected")
            else:
                st.success("No stacking detected")
    else:
        st.info("No MCA positions detected in this deal")
    
    st.divider()
    
    # ============================================
    # SECTION 3: BANK DATA (Bottom)
    # ============================================
    st.header("💵 Bank Data - Revenue & Income")
    
    info_needed = data.get('info_needed', data)
    bank_accounts = data.get('bank_accounts', {})
    total_revenues = data.get('total_revenues_by_month', {})
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        avg_income = info_needed.get('average_monthly_income', 0)
        if avg_income == 'not_computable':
            st.metric("Avg Monthly Income", "Not Computable")
        else:
            st.metric("Avg Monthly Income", f"${safe_float(avg_income):,.2f}")
    
    with col2:
        annual = info_needed.get('annual_income', 0)
        if annual == 'not_computable':
            st.metric("Annual Income", "Not Computable")
        else:
            st.metric("Annual Income", f"${safe_float(annual):,.2f}")
    
    with col3:
        st.metric("Total Monthly Payments", f"${safe_float(info_needed.get('total_monthly_payments', 0)):,.2f}")
    
    with col4:
        st.metric("NSF Count", data.get('nsf_count', 0))
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Diesel Payments", f"${safe_float(info_needed.get('diesel_total_monthly_payments', 0)):,.2f}")
    
    with col2:
        pmt_to_income = info_needed.get('monthly_payment_to_income_pct', 0)
        if pmt_to_income == 'not_computable':
            st.metric("Payment/Income %", "Not Computable")
        else:
            st.metric("Payment/Income %", f"{safe_float(pmt_to_income):.1f}%")
    
    with col3:
        holdback = info_needed.get('holdback_percentage', 0)
        if holdback == 'not_computable':
            st.metric("Holdback %", "Not Computable")
        else:
            st.metric("Holdback %", f"{safe_float(holdback):.1f}%")
    
    with col4:
        st.metric("Deal Length (Mo)", info_needed.get('length_of_deal_months', 'N/A'))
    
    if bank_accounts:
        st.subheader("📊 Bank Account Breakdown")
        for account_name, account_data in bank_accounts.items():
            with st.expander(f"🏦 {account_name}"):
                months = account_data.get('months', [])
                if months:
                    month_df = pd.DataFrame(months)
                    st.dataframe(month_df, use_container_width=True)
    
    if total_revenues:
        st.subheader("📈 Monthly Revenue Totals")
        revenue_df = pd.DataFrame([
            {'Month': month, 'Revenue': f"${amount:,.2f}"}
            for month, amount in total_revenues.items()
        ])
        st.dataframe(revenue_df, use_container_width=True)
    
    st.divider()
    
    # ============================================
    # SECTION 4: OTHER LIABILITIES (Separate from Positions)
    # ============================================
    if ai_other_liabilities or other_liabilities:
        st.header("📋 Other Liabilities (Non-MCA)")
        st.caption("Credit cards, insurance, and operating expenses - NOT counted in Position totals")
        
        all_liabilities = ai_other_liabilities + [
            {'name': p['lender_name'], 'type': p.get('liability_type', 'other'), 'monthly_payment': p['monthly_payment']}
            for p in other_liabilities
        ]
        
        if all_liabilities:
            liab_df = pd.DataFrame([
                {
                    'Creditor': l.get('name', 'Unknown'),
                    'Type': l.get('type', 'operating_expense').replace('_', ' ').title(),
                    'Monthly Payment': f"${safe_float(l.get('monthly_payment', 0)):,.2f}"
                }
                for l in all_liabilities
            ])
            st.dataframe(liab_df, use_container_width=True)
            
            total_other = sum(safe_float(l.get('monthly_payment', 0)) for l in all_liabilities)
            st.metric("Total Other Liabilities/Mo", f"${total_other:,.2f}")
    
    st.divider()
    
    # ============================================
    # SECTION 5: TRANSACTIONS & TRANSFER DETECTION
    # ============================================
    st.header("💸 Transactions & Transfer Detection")
    
    if transactions:
        if f'transfer_overrides_{deal.id}' not in st.session_state:
            st.session_state[f'transfer_overrides_{deal.id}'] = {}
        
        overrides = st.session_state[f'transfer_overrides_{deal.id}']
        revenue_result = calculate_revenue_with_overrides(txn_list, overrides)
        
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
        transfer_count = sum(1 for txn in transactions if txn.is_internal_transfer)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Transactions", len(transactions))
        with col2:
            st.metric("Internal Transfers", transfer_count)
        with col3:
            st.metric("Net Revenue", f"${revenue_result['total_revenue']:,.2f}")
        with col4:
            months = 4
            monthly_avg = revenue_result['total_revenue'] / months if months > 0 else 0
            st.metric("Monthly Average", f"${monthly_avg:,.2f}")
        
        st.dataframe(txn_df, use_container_width=True)
        
        st.subheader("💰 Revenue Breakdown")
        
        if revenue_result['breakdown']:
            st.markdown("**Excluded Transfers - Toggle to include in revenue:**")
            
            excluded_items = [item for item in revenue_result['breakdown'] if not item['included']]
            
            if excluded_items:
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
                        current_val = overrides.get(item['id'], False)
                        include = st.toggle(
                            "Include?",
                            value=current_val,
                            key=f"toggle_{deal.id}_{item['id']}"
                        )
                        
                        if include != current_val:
                            new_overrides[item['id']] = include
                            toggles_changed = True
                    
                    with col3:
                        if item['is_transfer']:
                            st.write("🔄 Transfer")
                        else:
                            st.write("📥 Deposit")
                    
                    st.divider()
                
                if st.button("🔄 Recalculate Revenue", key=f"recalc_{deal.id}"):
                    st.session_state[f'transfer_overrides_{deal.id}'] = new_overrides
                    st.rerun()
                
                if toggles_changed:
                    st.info("Click 'Recalculate Revenue' to update totals with your selections")
            else:
                st.success("No excluded transfers - all deposits are included in revenue")
            
            if revenue_result['included_transfers'] > 0:
                st.info(f"✅ {revenue_result['included_transfers']} transfers manually included in revenue by user")
        
        if transfer_count > 0:
            st.info(f"💡 {transfer_count} transactions identified as internal transfers. Use toggles above to override and recalculate revenue.")
    else:
        st.info("No transaction data available")
    
    st.divider()
    
    # ============================================
    # SECTION 5.5: AI VERIFICATION AGENT
    # ============================================
    st.header("🤖 AI Verification - Second Opinion")
    st.caption("AI reviews the calculated metrics and flags any anomalies")
    
    if 'ai_verification' not in st.session_state:
        st.session_state['ai_verification'] = None
    
    col1, col2 = st.columns([3, 1])
    
    with col2:
        if st.button("🔍 Get AI Verification", type="primary"):
            with st.spinner("AI is reviewing the underwriting metrics..."):
                try:
                    from ai_verification_agent import get_ai_verification, get_quick_validation
                    
                    calculated_metrics = {
                        'total_income': safe_float(info_needed.get('annual_income', 0)) / 12 if info_needed.get('annual_income', 0) != 'not_computable' else 0,
                        'net_revenue': safe_float(info_needed.get('average_monthly_income', 0)) if info_needed.get('average_monthly_income', 0) != 'not_computable' else 0,
                        'average_monthly_income': safe_float(info_needed.get('average_monthly_income', 0)) if info_needed.get('average_monthly_income', 0) != 'not_computable' else 0,
                        'annual_income': safe_float(info_needed.get('annual_income', 0)) if info_needed.get('annual_income', 0) != 'not_computable' else 0,
                        'months_analyzed': info_needed.get('length_of_deal_months', 0),
                        'total_monthly_payments': safe_float(info_needed.get('total_monthly_payments', 0)),
                        'diesel_total_monthly_payments': safe_float(info_needed.get('diesel_total_monthly_payments', 0)),
                        'total_monthly_payments_with_diesel': safe_float(info_needed.get('total_monthly_payments_with_diesel', 0)),
                        'payment_to_income_ratio': safe_float(info_needed.get('monthly_payment_to_income_pct', 0)) if info_needed.get('monthly_payment_to_income_pct', 0) != 'not_computable' else 0
                    }
                    
                    positions = daily_positions + weekly_positions + monthly_positions
                    
                    monthly_breakdown = [
                        {'month': month, 'revenue': amount}
                        for month, amount in total_revenues.items()
                    ]
                    
                    verification = get_ai_verification(
                        calculated_metrics=calculated_metrics,
                        positions=positions,
                        monthly_breakdown=monthly_breakdown,
                        raw_transaction_count=len(transactions),
                        detected_transfers=transfer_count
                    )
                    
                    st.session_state['ai_verification'] = verification
                    
                except Exception as e:
                    st.error(f"Error getting AI verification: {str(e)}")
    
    with col1:
        if st.session_state['ai_verification']:
            verification = st.session_state['ai_verification']
            
            if verification.get('success'):
                if verification.get('flags'):
                    critical_flags = [f for f in verification['flags'] if f.get('severity') == 'critical']
                    warning_flags = [f for f in verification['flags'] if f.get('severity') == 'warning']
                    
                    if critical_flags:
                        st.error(f"🚨 {len(critical_flags)} Critical Issue(s) Found")
                    elif warning_flags:
                        st.warning(f"⚠️ {len(warning_flags)} Warning(s) Found")
                    else:
                        st.success("✅ No Major Issues Detected")
                
                st.markdown("### AI Second Opinion")
                st.markdown(verification.get('ai_opinion', 'No opinion available'))
            else:
                st.warning(verification.get('ai_opinion', 'Unable to generate verification'))
        else:
            from ai_verification_agent import get_quick_validation
            
            avg_monthly = safe_float(info_needed.get('average_monthly_income', 0)) if info_needed.get('average_monthly_income', 0) != 'not_computable' else 0
            total_pmt = safe_float(info_needed.get('total_monthly_payments_with_diesel', info_needed.get('total_monthly_payments', 0)))
            position_count = len(daily_positions) + len(weekly_positions) + len(monthly_positions)
            months = info_needed.get('length_of_deal_months', 0)
            
            quick_check = get_quick_validation(avg_monthly, total_pmt, position_count, months)
            
            if quick_check['passed']:
                st.success(f"✅ Quick Check: {quick_check['summary']}")
            else:
                st.warning(f"⚠️ Quick Check: {quick_check['summary']}")
            
            for warning in quick_check.get('warnings', []):
                if warning['type'] == 'critical':
                    st.error(f"🚨 {warning['message']}")
                elif warning['type'] == 'warning':
                    st.warning(f"⚠️ {warning['message']}")
                else:
                    st.info(f"ℹ️ {warning['message']}")
            
            st.caption("Click 'Get AI Verification' for a detailed AI review")
    
    st.divider()
    
    # ============================================
    # SECTION 5B: STATEMENT VERIFICATION
    # ============================================
    st.header("📊 Statement Verification")
    st.caption("Compare extracted transactions against bank statement summary to catch data errors")
    
    with st.expander("🔍 Verify Statement Data", expanded=False):
        st.markdown("""
        **How it works:** When Koncile extracts transaction data, this tool compares the 
        individual transactions against the bank statement summary (totals, counts, balances) 
        to detect extraction errors.
        """)
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Bank Statement Summary")
            st.caption("Enter values from the bank statement summary page")
            
            summary_beginning_balance = st.number_input(
                "Beginning Balance ($)", 
                value=0.0, 
                step=100.0,
                key="verify_beginning"
            )
            summary_ending_balance = st.number_input(
                "Ending Balance ($)", 
                value=0.0, 
                step=100.0,
                key="verify_ending"
            )
            summary_deposits_total = st.number_input(
                "Total Deposits ($)", 
                value=0.0, 
                step=100.0,
                key="verify_deposits_total"
            )
            summary_deposits_count = st.number_input(
                "Deposits Count", 
                value=0, 
                step=1,
                key="verify_deposits_count"
            )
        
        with col2:
            st.subheader("​")
            st.caption("​")
            
            summary_withdrawals_total = st.number_input(
                "Total Withdrawals ($)", 
                value=0.0, 
                step=100.0,
                key="verify_withdrawals_total"
            )
            summary_withdrawals_count = st.number_input(
                "Withdrawals Count", 
                value=0, 
                step=1,
                key="verify_withdrawals_count"
            )
            summary_checks_total = st.number_input(
                "Total Checks ($)", 
                value=0.0, 
                step=100.0,
                key="verify_checks_total"
            )
            summary_fees_total = st.number_input(
                "Total Fees ($)", 
                value=0.0, 
                step=100.0,
                key="verify_fees_total"
            )
        
        if st.button("🔎 Run Verification", type="primary", key="run_verification"):
            transactions = db.query(Transaction).filter(Transaction.deal_id == deal.id).all()
            
            if transactions:
                from koncile_integration import verify_csv_against_summary, StatementVerifier
                
                txn_list = [{
                    'date': str(t.transaction_date),
                    'description': t.description or '',
                    'amount': float(t.amount or 0),
                    'type': t.transaction_type or 'unknown'
                } for t in transactions]
                
                summary_data = {
                    'beginning_balance': summary_beginning_balance,
                    'ending_balance': summary_ending_balance,
                    'deposits_total': summary_deposits_total,
                    'deposits_count': int(summary_deposits_count),
                    'withdrawals_total': summary_withdrawals_total,
                    'withdrawals_count': int(summary_withdrawals_count),
                    'checks_total': summary_checks_total,
                    'checks_count': 0,
                    'fees_total': summary_fees_total,
                    'fees_count': 0
                }
                
                result = verify_csv_against_summary(txn_list, summary_data)
                
                st.divider()
                
                if result.is_valid:
                    st.success(f"✅ VERIFICATION PASSED - Confidence: {result.confidence_score:.0%}")
                else:
                    st.error(f"⚠️ VERIFICATION FOUND {len(result.discrepancies)} DISCREPANCIES - Confidence: {result.confidence_score:.0%}")
                
                st.markdown("#### Summary vs Extracted Comparison")
                
                comparison_data = []
                categories = [
                    ('Deposits Total', 'deposits_total', True),
                    ('Deposits Count', 'deposits_count', False),
                    ('Withdrawals Total', 'withdrawals_total', True),
                    ('Withdrawals Count', 'withdrawals_count', False),
                ]
                
                for label, key, is_currency in categories:
                    summary_val = result.summary_totals.get(key, 0)
                    calc_val = result.calculated_totals.get(key, 0)
                    diff = calc_val - summary_val
                    
                    if is_currency:
                        match = "✅" if abs(diff) < 1.0 else "❌"
                        comparison_data.append({
                            'Category': label,
                            'Bank Statement': f"${summary_val:,.2f}",
                            'Extracted': f"${calc_val:,.2f}",
                            'Difference': f"${diff:,.2f}",
                            'Match': match
                        })
                    else:
                        match = "✅" if diff == 0 else "❌"
                        comparison_data.append({
                            'Category': label,
                            'Bank Statement': f"{int(summary_val)}",
                            'Extracted': f"{int(calc_val)}",
                            'Difference': f"{int(diff)}",
                            'Match': match
                        })
                
                st.dataframe(pd.DataFrame(comparison_data), use_container_width=True, hide_index=True)
                
                if result.discrepancies:
                    st.markdown("#### Discrepancy Details")
                    for d in result.discrepancies:
                        severity_icon = "🔴" if d['severity'] == 'high' else "🟡"
                        st.warning(f"{severity_icon} **{d['field']}**: Bank says ${d['summary_value']:,.2f}, Extracted shows ${d['calculated_value']:,.2f} (Diff: ${d['difference']:,.2f})")
                
                if result.warnings:
                    st.markdown("#### Warnings")
                    for w in result.warnings:
                        st.info(f"ℹ️ {w}")
                
                st.markdown("---")
                st.caption("**Note:** Discrepancies indicate potential OCR/extraction errors. Use the bank statement summary values for accurate underwriting.")
            else:
                st.info("No transactions found for this deal. Upload a bank statement first.")
    
    st.divider()
    
    # ============================================
    # SECTION 6: AI REASONING LOG
    # ============================================
    st.header("🧠 AI Reasoning Log")
    
    if deal.ai_reasoning_log:
        st.text_area("Reasoning", deal.ai_reasoning_log, height=200)
    else:
        st.info("No reasoning log available")
    
    st.divider()
    
    # ============================================
    # SECTION 7: PDF FILES
    # ============================================
    st.header("📁 Original PDFs")
    
    pdf_files = deal.pdf_files
    
    if pdf_files:
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
    
    st.divider()
    
    # ============================================
    # SECTION 8: CORRECTION MODE
    # ============================================
    st.header("✏️ Correction Mode")
    
    st.markdown("""
    If the AI misread any numbers, you can correct them here. Your corrections will be saved to the training database
    to improve future AI performance.
    """)
    
    with st.form("correction_form"):
        col1, col2 = st.columns(2)
        
        current_data = deal.extracted_data or {}
        info_data = current_data.get('info_needed', current_data)
        
        with col1:
            corrected_annual_income = st.number_input(
                "Annual Income",
                value=safe_float(info_data.get('annual_income', 0)),
                step=1000.0
            )
            
            corrected_monthly_income = st.number_input(
                "Avg Monthly Income",
                value=safe_float(info_data.get('average_monthly_income', info_data.get('avg_monthly_income', 0))),
                step=100.0
            )
            
            corrected_revenues = st.number_input(
                "Revenues (Last 4 Months)",
                value=safe_float(current_data.get('revenues_last_4_months', 0)),
                step=1000.0
            )
        
        with col2:
            corrected_payments = st.number_input(
                "Total Monthly Payments",
                value=safe_float(info_data.get('total_monthly_payments', 0)),
                step=100.0
            )
            
            corrected_diesel = st.number_input(
                "Diesel Payments",
                value=safe_float(info_data.get('diesel_total_monthly_payments', current_data.get('diesel_payments', 0))),
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
            corrected_data = {
                'annual_income': corrected_annual_income,
                'avg_monthly_income': corrected_monthly_income,
                'revenues_last_4_months': corrected_revenues,
                'total_monthly_payments': corrected_payments,
                'diesel_payments': corrected_diesel,
                'nsf_count': corrected_nsf
            }
            
            training_example = TrainingExample(
                original_financial_json=current_data,
                user_corrected_summary=json.dumps(corrected_data),
                correction_details={
                    'notes': correction_notes,
                    'corrected_fields': [k for k in corrected_data if corrected_data[k] != info_data.get(k, 0)]
                },
                deal_id=deal.id,
                created_at=datetime.utcnow()
            )
            db.add(training_example)
            
            deal.extracted_data = corrected_data
            deal.updated_at = datetime.utcnow()
            
            db.commit()
            
            st.success("✅ Corrections saved! AI will learn from this example.")
            st.rerun()
