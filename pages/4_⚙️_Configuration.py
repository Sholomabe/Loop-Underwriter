import streamlit as st
from database import get_db
from models import Setting
from datetime import datetime

st.set_page_config(page_title="Configuration", page_icon="⚙️", layout="wide")

st.title("⚙️ Configuration")

st.markdown("""
Manage underwriting rules and system settings. Changes here affect how deals are evaluated.
""")

st.divider()

# Load current settings
with get_db() as db:
    settings = db.query(Setting).all()
    
    # Convert to dictionaries to avoid detached instance errors
    settings_dicts = []
    for s in settings:
        settings_dicts.append({
            'id': s.id,
            'key': s.key,
            'value': s.value,
            'value_type': s.value_type,
            'description': s.description,
            'category': s.category
        })
    
    # Group by category
    settings_by_category = {}
    for setting_dict in settings_dicts:
        category = setting_dict['category'] or "General"
        if category not in settings_by_category:
            settings_by_category[category] = []
        settings_by_category[category].append(setting_dict)
    
    # If no settings exist, create defaults
    if not settings:
        default_settings = [
            {'key': 'min_annual_income', 'value': '100000', 'value_type': 'float', 'description': 'Minimum annual income required for approval', 'category': 'Underwriting Rules'},
            {'key': 'holdback_percentage', 'value': '10', 'value_type': 'float', 'description': 'Percentage holdback for underwriting', 'category': 'Underwriting Rules'},
            {'key': 'max_retry_attempts', 'value': '2', 'value_type': 'integer', 'description': 'Maximum retry attempts for AI extraction', 'category': 'System Config'},
            {'key': 'transfer_detection_window_days', 'value': '2', 'value_type': 'integer', 'description': 'Number of days to look for matching transfers', 'category': 'Transfer Detection'},
            {'key': 'max_nsf_count', 'value': '3', 'value_type': 'integer', 'description': 'Maximum acceptable NSF count', 'category': 'Underwriting Rules'},
            {'key': 'min_monthly_revenue', 'value': '20000', 'value_type': 'float', 'description': 'Minimum monthly revenue required', 'category': 'Underwriting Rules'},
            {'key': 'diesel_threshold', 'value': '5000', 'value_type': 'float', 'description': 'Minimum diesel payments for diesel-related businesses', 'category': 'Underwriting Rules'},
        ]
        
        for setting_data in default_settings:
            setting = Setting(**setting_data, created_at=datetime.utcnow())
            db.add(setting)
        
        db.commit()
        
        st.success("✅ Default settings initialized!")
        st.rerun()

# Display settings by category
for category, category_settings in settings_by_category.items():
    st.subheader(f"📁 {category}")
    
    with st.form(f"form_{category}"):
        settings_to_update = {}
        
        for setting in category_settings:
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # Display input based on value type
                if setting['value_type'] == 'integer':
                    new_value = st.number_input(
                        setting['key'].replace('_', ' ').title(),
                        value=int(setting['value']),
                        step=1,
                        help=setting['description'],
                        key=f"input_{setting['id']}"
                    )
                elif setting['value_type'] == 'float':
                    new_value = st.number_input(
                        setting['key'].replace('_', ' ').title(),
                        value=float(setting['value']),
                        step=0.01,
                        help=setting['description'],
                        key=f"input_{setting['id']}"
                    )
                elif setting['value_type'] == 'boolean':
                    new_value = st.checkbox(
                        setting['key'].replace('_', ' ').title(),
                        value=setting['value'].lower() == 'true',
                        help=setting['description'],
                        key=f"input_{setting['id']}"
                    )
                else:  # string
                    new_value = st.text_input(
                        setting['key'].replace('_', ' ').title(),
                        value=setting['value'],
                        help=setting['description'],
                        key=f"input_{setting['id']}"
                    )
                
                settings_to_update[setting['id']] = str(new_value)
            
            with col2:
                st.caption(f"**Type:** {setting['value_type']}")
                st.caption(f"**Current:** {setting['value']}")
        
        submit = st.form_submit_button("💾 Save Settings", type="primary")
        
        if submit:
            # Create a fresh database session for the update
            with get_db() as update_db:
                # Update settings in database
                for setting_id, new_value in settings_to_update.items():
                    setting = update_db.query(Setting).filter(Setting.id == setting_id).first()
                    if setting:
                        setting.value = new_value
                        setting.updated_at = datetime.utcnow()
                
                update_db.commit()
            
            st.success(f"✅ {category} settings updated!")
            st.rerun()
    
    st.divider()

# Add new setting
st.subheader("➕ Add New Setting")

with st.form("add_setting"):
    col1, col2 = st.columns(2)
    
    with col1:
        new_key = st.text_input("Setting Key", placeholder="e.g., max_debt_ratio")
        new_value = st.text_input("Value", placeholder="e.g., 0.5")
        new_category = st.text_input("Category", placeholder="e.g., Underwriting Rules")
    
    with col2:
        new_value_type = st.selectbox("Value Type", options=['string', 'integer', 'float', 'boolean'])
        new_description = st.text_area("Description", placeholder="What does this setting control?")
    
    submit_new = st.form_submit_button("Add Setting")
    
    if submit_new and new_key and new_value:
        with get_db() as db:
            # Check if key already exists
            existing = db.query(Setting).filter(Setting.key == new_key).first()
            
            if existing:
                st.error(f"Setting with key '{new_key}' already exists!")
            else:
                new_setting = Setting(
                    key=new_key,
                    value=new_value,
                    value_type=new_value_type,
                    description=new_description,
                    category=new_category or "General",
                    created_at=datetime.utcnow()
                )
                db.add(new_setting)
                db.commit()
                
                st.success(f"✅ Setting '{new_key}' added successfully!")
                st.rerun()

st.divider()

# Display all settings as reference
st.subheader("📊 All Settings Reference")

with get_db() as db:
    all_settings = db.query(Setting).order_by(Setting.category, Setting.key).all()
    
    if all_settings:
        import pandas as pd
        
        settings_data = [{
            'Category': s.category,
            'Key': s.key,
            'Value': s.value,
            'Type': s.value_type,
            'Description': s.description[:50] + '...' if len(s.description or '') > 50 else (s.description or '')
        } for s in all_settings]
        
        df = pd.DataFrame(settings_data)
        st.dataframe(df, use_container_width=True)
        
        # Export settings
        if st.button("📥 Export Settings as JSON"):
            import json
            export_data = {s.key: {'value': s.value, 'type': s.value_type, 'description': s.description} for s in all_settings}
            st.download_button(
                "Download settings.json",
                json.dumps(export_data, indent=2),
                file_name="underwriting_settings.json",
                mime="application/json"
            )
