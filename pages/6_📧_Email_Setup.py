import streamlit as st
import os

st.set_page_config(page_title="Email Setup", page_icon="📧", layout="wide")

st.title("📧 Email Integration Setup")
st.markdown("Connect your email to automatically process bank statements through Koncile.")

st.divider()

replit_url = os.environ.get('REPLIT_DEV_DOMAIN', 'your-app.replit.app')
webhook_url = f"https://{replit_url}/koncile-callback"

st.header("Koncile Email Integration")
st.markdown("""
This is the simplest way to process bank statements automatically:
1. Forward emails with bank statements to Koncile's email address
2. Koncile extracts the data
3. Results are automatically sent to your webhook
""")

st.subheader("Step 1: Get Your Webhook URL")
st.code(webhook_url, language="text")
st.caption("Copy this URL - you'll need it for the Koncile dashboard")

st.subheader("Step 2: Configure Koncile Dashboard")
st.markdown("""
1. Log into your [Koncile Dashboard](https://app.koncile.ai)
2. Go to **Settings** → **Webhooks** (or **Integrations**)
3. Paste your webhook URL from above
4. Save the configuration
5. Test the webhook using Koncile's test feature
""")

st.subheader("Step 3: Set Up Email Forwarding")
st.markdown("""
Configure your email to forward bank statement emails to Koncile:

**Option A: Gmail Filter (Recommended)**
1. In Gmail, go to **Settings** → **Filters and Blocked Addresses**
2. Create a filter for emails containing bank statements
3. Set action to **Forward to** your Koncile email address

**Option B: Manual Forward**
- Simply forward any email with bank statement PDFs to your Koncile intake email
""")

st.subheader("Step 4: How It Works")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("### 📨")
    st.markdown("**Email Arrives**")
    st.caption("Bank sends statement")

with col2:
    st.markdown("### 📤")
    st.markdown("**Forward to Koncile**")
    st.caption("Auto or manual")

with col3:
    st.markdown("### 🔍")
    st.markdown("**Koncile Extracts**")
    st.caption("OCR + AI parsing")

with col4:
    st.markdown("### ✅")
    st.markdown("**Deal Created**")
    st.caption("Ready for review")

st.divider()

st.header("Webhook Status")

if st.button("Test Webhook Connection"):
    import requests
    try:
        test_url = f"https://{replit_url}/health"
        response = requests.get(test_url, timeout=5)
        if response.status_code == 200:
            st.success("Webhook server is running and accessible!")
        else:
            st.warning(f"Server responded with status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        st.error(f"Could not reach webhook server: {str(e)}")

st.divider()

with st.expander("🔧 Technical Details"):
    st.markdown("### Webhook Endpoint")
    st.code(f"POST {webhook_url}", language="text")
    
    st.markdown("### Expected Payload from Koncile")
    st.code('''
{
    "task_id": "abc123",
    "status": "DONE",
    "general_fields": {
        "account_number": "1234567890",
        "bank_name": "Chase",
        "opening_balance": "5000.00",
        "closing_balance": "4500.00",
        "total_deposits": "2000.00",
        "total_withdrawals": "2500.00"
    },
    "repeated_fields": [
        {
            "date": "2024-01-15",
            "description": "DIRECT DEPOSIT",
            "amount": "2000.00",
            "type": "credit"
        }
    ]
}
''', language="json")
    
    st.markdown("### Response")
    st.code('''
{
    "status": "success",
    "deal_id": 123,
    "final_status": "Pending Approval",
    "verification_passed": true,
    "confidence_score": 0.95
}
''', language="json")

with st.expander("❓ Troubleshooting"):
    st.markdown("""
    **Webhook not receiving data?**
    - Verify the webhook URL is correctly configured in Koncile
    - Check that your app is published/deployed (not just running in dev)
    - Test the health endpoint: `GET /health`
    
    **Deals not appearing?**
    - Check the Flask Webhook Server logs for errors
    - Verify Koncile is sending "DONE" status (not "IN_PROGRESS")
    
    **Verification failing?**
    - This usually means extracted transactions don't match the summary
    - Review the deal in Deal Details to see specific discrepancies
    """)
