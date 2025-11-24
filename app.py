import streamlit as st
import os
from database import init_db

# Initialize database on startup
init_db()

# Page configuration
st.set_page_config(
    page_title="Underwriting Platform",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .status-badge {
        padding: 0.25rem 0.75rem;
        border-radius: 0.25rem;
        font-weight: bold;
        font-size: 0.875rem;
    }
    .status-pending { background-color: #ffc107; color: #000; }
    .status-approved { background-color: #28a745; color: #fff; }
    .status-rejected { background-color: #dc3545; color: #fff; }
    .status-review { background-color: #fd7e14; color: #fff; }
    .status-duplicate { background-color: #6c757d; color: #fff; }
</style>
""", unsafe_allow_html=True)

# Main app
st.markdown('<div class="main-header">🏦 Human-in-the-Loop Underwriting Platform</div>', unsafe_allow_html=True)

st.markdown("""
Welcome to the AI-powered underwriting platform with continuous learning capabilities.

**Features:**
- 📧 **Email Ingestion**: Automatic processing of bank statements via webhook
- 🔍 **Duplicate Detection**: SHA-256 hash-based duplicate prevention
- 🏦 **Multi-Account Support**: Intelligent account separation and transfer detection
- 🤖 **AI Extraction**: OpenAI Vision API with auto-retry verification
- 📊 **Human-in-the-Loop Training**: Learn from corrections
- 🧠 **Pattern Memory**: RAG-based rule learning

**Navigation:**
Use the sidebar to navigate between different sections of the platform.
""")

st.divider()

# Quick stats
from database import get_db
from models import Deal

with get_db() as db:
    total_deals = db.query(Deal).count()
    pending_deals = db.query(Deal).filter(Deal.status.in_(["Pending Approval", "Needs Human Review"])).count()
    approved_deals = db.query(Deal).filter(Deal.status == "Approved").count()
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Deals", total_deals)
    
    with col2:
        st.metric("Pending Review", pending_deals)
    
    with col3:
        st.metric("Approved", approved_deals)
    
    with col4:
        st.metric("Success Rate", f"{(approved_deals/total_deals*100) if total_deals > 0 else 0:.1f}%")

st.divider()

# Instructions
st.subheader("📖 Quick Start Guide")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    **For Underwriters:**
    1. Check the **Inbox** for pending deals
    2. Review AI-extracted data in **Deal Details**
    3. Correct any errors and click **Train** to improve AI
    4. Use **Forensic Trainer** for batch training
    """)

with col2:
    st.markdown("""
    **For Administrators:**
    1. Configure underwriting rules in **Configuration**
    2. Monitor AI learning progress
    3. Review transfer detection accuracy
    4. Manage duplicate detection settings
    """)

st.info("💡 **Tip**: The AI learns from every correction you make. The more you train it, the more accurate it becomes!")

# Webhook information
st.divider()
st.subheader("🔗 Webhook Configuration")

st.code(f"""
POST /incoming-email

Payload:
{{
    "sender": "sender@example.com",
    "subject": "Bank Statement",
    "body": "Email body text",
    "attachments": [
        {{
            "filename": "statement.pdf",
            "content": "<base64 encoded PDF>"
        }}
    ]
}}
""", language="json")

st.caption("Configure your email provider (SendGrid, Mailgun, etc.) to send webhooks to this endpoint.")
