import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_db
from models import Deal, PDFFile
import json

st.set_page_config(page_title="Inbox", page_icon="📥", layout="wide")

st.title("📥 Deals Inbox")

# Status filter
st.sidebar.header("Filters")
status_options = ["All", "Pending Approval", "Needs Human Review", "Underwritten", "Approved", "Rejected", "Duplicate"]
selected_status = st.sidebar.multiselect(
    "Filter by Status",
    status_options,
    default=["Pending Approval", "Needs Human Review"]
)

# Date filter
date_filter = st.sidebar.date_input(
    "Filter by Date Range",
    value=None
)

# Fetch deals from database
with get_db() as db:
    query = db.query(Deal)
    
    # Apply status filter
    if "All" not in selected_status and selected_status:
        query = query.filter(Deal.status.in_(selected_status))
    
    deals = query.order_by(Deal.created_at.desc()).all()
    
    # Convert to DataFrame for display
    deals_data = []
    for deal in deals:
        # Get PDF count
        pdf_count = len(deal.pdf_files)
        
        # Extract key metrics
        extracted = deal.extracted_data or {}
        annual_income = extracted.get('annual_income', 0)
        revenues = extracted.get('revenues_last_4_months', 0)
        
        deals_data.append({
            'ID': deal.id,
            'Sender': deal.sender,
            'Subject': deal.subject,
            'Status': deal.status,
            'PDFs': pdf_count,
            'Annual Income': f"${annual_income:,.0f}" if annual_income else "N/A",
            'Revenue (4M)': f"${revenues:,.0f}" if revenues else "N/A",
            'Retry Count': deal.retry_count,
            'Created': deal.created_at.strftime('%Y-%m-%d %H:%M') if deal.created_at else 'N/A',
            'Duplicate Of': deal.duplicate_of_deal_id if deal.duplicate_of_deal_id else '-'
        })
    
    df = pd.DataFrame(deals_data)
    
    st.subheader(f"Found {len(df)} deals")
    
    if len(df) > 0:
        # Display table with status colors
        def color_status(val):
            colors = {
                'Pending Approval': 'background-color: #ffc107',
                'Needs Human Review': 'background-color: #fd7e14; color: white',
                'Approved': 'background-color: #28a745; color: white',
                'Rejected': 'background-color: #dc3545; color: white',
                'Duplicate': 'background-color: #6c757d; color: white',
                'Underwritten': 'background-color: #17a2b8; color: white'
            }
            return colors.get(val, '')
        
        # Apply styling
        styled_df = df.style.applymap(color_status, subset=['Status'])
        
        st.dataframe(
            styled_df,
            use_container_width=True,
            height=400
        )
        
        # Deal selection
        st.divider()
        st.subheader("Quick Actions")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            selected_deal_id = st.selectbox(
                "Select a deal to view details",
                options=df['ID'].tolist(),
                format_func=lambda x: f"Deal #{x} - {df[df['ID']==x]['Sender'].values[0]} - {df[df['ID']==x]['Status'].values[0]}"
            )
        
        with col2:
            if st.button("View Deal Details", type="primary"):
                st.session_state['selected_deal_id'] = selected_deal_id
                st.switch_page("pages/2_📄_Deal_Details.py")
        
        # Show summary of selected deal
        if selected_deal_id:
            selected_deal = next((d for d in deals if d.id == selected_deal_id), None)
            if selected_deal:
                st.divider()
                st.subheader(f"Deal #{selected_deal_id} - Quick Preview")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.metric("Status", selected_deal.status)
                    st.metric("Retry Count", selected_deal.retry_count)
                
                with col2:
                    if selected_deal.extracted_data:
                        st.metric("Annual Income", f"${selected_deal.extracted_data.get('annual_income', 0):,.0f}")
                        st.metric("NSF Count", selected_deal.extracted_data.get('nsf_count', 0))
                
                with col3:
                    if selected_deal.extracted_data:
                        st.metric("Revenues (4M)", f"${selected_deal.extracted_data.get('revenues_last_4_months', 0):,.0f}")
                        st.metric("Diesel Payments", f"${selected_deal.extracted_data.get('diesel_payments', 0):,.0f}")
                
                # Show AI reasoning snippet
                if selected_deal.ai_reasoning_log:
                    with st.expander("AI Reasoning Log (Preview)"):
                        st.text(selected_deal.ai_reasoning_log[:500] + "..." if len(selected_deal.ai_reasoning_log) > 500 else selected_deal.ai_reasoning_log)
    else:
        st.info("No deals found with the selected filters.")
        
    # Stats
    st.divider()
    st.subheader("📊 Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        pending_count = len([d for d in deals if d.status in ["Pending Approval", "Needs Human Review"]])
        st.metric("Pending Review", pending_count)
    
    with col2:
        duplicate_count = len([d for d in deals if d.status == "Duplicate"])
        st.metric("Duplicates Detected", duplicate_count)
    
    with col3:
        avg_retry = sum(d.retry_count for d in deals) / len(deals) if deals else 0
        st.metric("Avg Retry Count", f"{avg_retry:.1f}")
    
    with col4:
        needs_review = len([d for d in deals if d.status == "Needs Human Review"])
        st.metric("Needs Human Review", needs_review)
