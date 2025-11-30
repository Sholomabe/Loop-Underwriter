"""
Review Unknown Transactions Page

Allows users to categorize unrecognized recurring transactions
and add them to the KnownVendors database for future automatic matching.
"""

import streamlit as st
from datetime import datetime
from database import get_db
from models import UnknownTransaction, KnownVendor, Deal, Transaction
from sqlalchemy import desc

st.set_page_config(
    page_title="Review Transactions",
    page_icon="🔍",
    layout="wide"
)

st.title("🔍 Review Unknown Transactions")
st.markdown("Review and categorize recurring transactions that the system couldn't automatically identify.")

CATEGORY_OPTIONS = [
    "MCA",
    "Rent",
    "Payroll",
    "Insurance",
    "Utilities",
    "Equipment Lease",
    "Credit Card",
    "Loan Payment",
    "Vendor/Supplier",
    "Bank Fee",
    "Ignore"
]

MCA_CATEGORIES = ["MCA"]
FREQUENCY_OPTIONS = ["Daily", "Weekly", "Monthly", "One-time"]


def load_unknown_transactions():
    """Load pending unknown transactions from database."""
    with get_db() as db:
        unknowns = db.query(UnknownTransaction).filter(
            UnknownTransaction.status == "pending"
        ).order_by(desc(UnknownTransaction.occurrence_count)).all()
        
        result = []
        for u in unknowns:
            result.append({
                'id': u.id,
                'description': u.description,
                'normalized_name': u.normalized_name,
                'detected_frequency': u.detected_frequency,
                'average_amount': u.average_amount,
                'occurrence_count': u.occurrence_count,
                'sample_dates': u.sample_dates or [],
                'deal_id': u.deal_id
            })
        
        return result


def load_known_vendors():
    """Load all known vendors from database."""
    with get_db() as db:
        vendors = db.query(KnownVendor).order_by(KnownVendor.name).all()
        
        result = []
        for v in vendors:
            result.append({
                'id': v.id,
                'name': v.name,
                'category': v.category,
                'match_type': v.match_type,
                'is_mca_lender': v.is_mca_lender,
                'default_frequency': v.default_frequency,
                'times_matched': v.times_matched
            })
        
        return result


def save_vendor_classification(unknown_id: int, vendor_name: str, category: str, 
                               match_type: str = "fuzzy", is_mca: bool = False,
                               frequency: str = None):
    """Save a new vendor classification to KnownVendors and update unknown status."""
    with get_db() as db:
        existing = db.query(KnownVendor).filter(
            KnownVendor.name.ilike(f"%{vendor_name}%")
        ).first()
        
        if not existing:
            new_vendor = KnownVendor(
                name=vendor_name.upper(),
                category=category,
                match_type=match_type,
                is_mca_lender=is_mca,
                default_frequency=frequency,
                times_matched=1
            )
            db.add(new_vendor)
        else:
            existing.times_matched += 1
            existing.updated_at = datetime.utcnow()
        
        unknown = db.query(UnknownTransaction).filter(
            UnknownTransaction.id == unknown_id
        ).first()
        
        if unknown:
            unknown.status = "categorized"
            unknown.assigned_category = category
            unknown.reviewed_at = datetime.utcnow()
        
        db.commit()


def mark_as_ignored(unknown_id: int):
    """Mark an unknown transaction as ignored."""
    with get_db() as db:
        unknown = db.query(UnknownTransaction).filter(
            UnknownTransaction.id == unknown_id
        ).first()
        
        if unknown:
            unknown.status = "ignored"
            unknown.reviewed_at = datetime.utcnow()
            db.commit()


def delete_known_vendor(vendor_id: int):
    """Delete a known vendor from the database."""
    with get_db() as db:
        vendor = db.query(KnownVendor).filter(KnownVendor.id == vendor_id).first()
        if vendor:
            db.delete(vendor)
            db.commit()


def add_known_vendor_manually(name: str, category: str, match_type: str, 
                              is_mca: bool, frequency: str = None):
    """Manually add a known vendor."""
    with get_db() as db:
        new_vendor = KnownVendor(
            name=name.upper(),
            category=category,
            match_type=match_type,
            is_mca_lender=is_mca,
            default_frequency=frequency
        )
        db.add(new_vendor)
        db.commit()


tab1, tab2 = st.tabs(["📋 Review Queue", "📚 Known Vendors"])

with tab1:
    st.subheader("Pending Review")
    
    unknown_txns = load_unknown_transactions()
    
    if not unknown_txns:
        st.info("🎉 No unknown transactions pending review. The system has either categorized everything or there are no recurring patterns detected yet.")
        st.markdown("""
        **How it works:**
        1. When deals are processed, the system detects recurring payment patterns
        2. If a pattern doesn't match any known vendor, it goes into this review queue
        3. You categorize it here, and the system learns for next time
        """)
    else:
        st.write(f"Found **{len(unknown_txns)}** unknown recurring transactions to review.")
        
        for idx, txn in enumerate(unknown_txns):
            with st.expander(
                f"📌 {txn['normalized_name'] or txn['description'][:50]} "
                f"(${txn['average_amount']:,.2f} avg, {txn['occurrence_count']}x)",
                expanded=idx == 0
            ):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.markdown(f"**Description:** `{txn['description']}`")
                    st.markdown(f"**Detected Frequency:** {txn['detected_frequency'] or 'Unknown'}")
                    st.markdown(f"**Average Amount:** ${txn['average_amount']:,.2f}")
                    st.markdown(f"**Occurrences:** {txn['occurrence_count']}")
                    
                    if txn['sample_dates']:
                        st.markdown(f"**Sample Dates:** {', '.join(txn['sample_dates'][:3])}")
                
                with col2:
                    st.markdown("**Categorize this transaction:**")
                    
                    category = st.selectbox(
                        "Category",
                        options=CATEGORY_OPTIONS,
                        key=f"cat_{txn['id']}"
                    )
                    
                    is_mca = category in MCA_CATEGORIES
                    
                    if is_mca:
                        frequency = st.selectbox(
                            "Payment Frequency",
                            options=FREQUENCY_OPTIONS,
                            key=f"freq_{txn['id']}"
                        )
                    else:
                        frequency = None
                    
                    match_type = st.selectbox(
                        "Match Type",
                        options=["fuzzy", "contains", "exact"],
                        help="How should the system match this vendor? Fuzzy allows for variations.",
                        key=f"match_{txn['id']}"
                    )
                    
                    col_a, col_b = st.columns(2)
                    
                    with col_a:
                        if st.button("✅ Save", key=f"save_{txn['id']}", type="primary"):
                            vendor_name = txn['normalized_name'] or txn['description'][:50]
                            save_vendor_classification(
                                unknown_id=txn['id'],
                                vendor_name=vendor_name,
                                category=category,
                                match_type=match_type,
                                is_mca=is_mca,
                                frequency=frequency.lower() if frequency else None
                            )
                            st.success(f"Saved as {category}!")
                            st.rerun()
                    
                    with col_b:
                        if st.button("🚫 Ignore", key=f"ignore_{txn['id']}"):
                            mark_as_ignored(txn['id'])
                            st.info("Marked as ignored")
                            st.rerun()

with tab2:
    st.subheader("Known Vendors Database")
    
    col1, col2 = st.columns([3, 1])
    
    with col2:
        with st.expander("➕ Add New Vendor"):
            new_name = st.text_input("Vendor Name", key="new_vendor_name")
            new_category = st.selectbox("Category", options=CATEGORY_OPTIONS, key="new_vendor_cat")
            new_match_type = st.selectbox("Match Type", options=["fuzzy", "contains", "exact"], key="new_vendor_match")
            new_is_mca = new_category in MCA_CATEGORIES
            
            if new_is_mca:
                new_frequency = st.selectbox("Frequency", options=FREQUENCY_OPTIONS, key="new_vendor_freq")
            else:
                new_frequency = None
            
            if st.button("Add Vendor", type="primary"):
                if new_name:
                    add_known_vendor_manually(
                        name=new_name,
                        category=new_category,
                        match_type=new_match_type,
                        is_mca=new_is_mca,
                        frequency=new_frequency.lower() if new_frequency else None
                    )
                    st.success(f"Added {new_name}!")
                    st.rerun()
                else:
                    st.error("Please enter a vendor name")
    
    known_vendors = load_known_vendors()
    
    with col1:
        if not known_vendors:
            st.info("No known vendors in the database yet. Add them manually or categorize unknown transactions.")
        else:
            st.write(f"**{len(known_vendors)}** vendors in database")
            
            filter_category = st.selectbox(
                "Filter by Category",
                options=["All"] + CATEGORY_OPTIONS,
                key="filter_cat"
            )
            
            filtered_vendors = known_vendors
            if filter_category != "All":
                filtered_vendors = [v for v in known_vendors if v['category'] == filter_category]
            
            for vendor in filtered_vendors:
                with st.container():
                    cols = st.columns([3, 1, 1, 1, 0.5])
                    
                    with cols[0]:
                        mca_badge = "🏦 " if vendor['is_mca_lender'] else ""
                        st.markdown(f"**{mca_badge}{vendor['name']}**")
                    
                    with cols[1]:
                        st.markdown(f"`{vendor['category']}`")
                    
                    with cols[2]:
                        st.markdown(f"{vendor['match_type']}")
                    
                    with cols[3]:
                        if vendor['default_frequency']:
                            st.markdown(f"{vendor['default_frequency']}")
                    
                    with cols[4]:
                        if st.button("🗑️", key=f"del_{vendor['id']}", help="Delete"):
                            delete_known_vendor(vendor['id'])
                            st.rerun()
                    
                    st.markdown("---")


with st.sidebar:
    st.markdown("### Quick Stats")
    
    unknown_count = len(load_unknown_transactions())
    vendor_count = len(load_known_vendors())
    
    st.metric("Pending Review", unknown_count)
    st.metric("Known Vendors", vendor_count)
    
    st.markdown("---")
    
    st.markdown("### Bulk Actions")
    
    if st.button("🔄 Refresh Data"):
        st.rerun()
    
    st.markdown("---")
    
    st.markdown("""
    ### How Matching Works
    
    **Exact:** Must match exactly (case-insensitive)
    
    **Contains:** Vendor name must be contained in transaction description
    
    **Fuzzy:** Allows for spelling variations and partial matches (80% threshold)
    """)
