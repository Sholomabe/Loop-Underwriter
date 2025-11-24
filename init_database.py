"""
Initialize database with tables and default settings.
Run this script once to set up the database.
"""

from database import init_db, get_db
from models import Setting
from datetime import datetime

def initialize_default_settings():
    """Create default settings if they don't exist."""
    with get_db() as db:
        # Check if settings already exist
        existing_settings = db.query(Setting).count()
        
        if existing_settings > 0:
            print(f"Settings already initialized ({existing_settings} settings found)")
            return
        
        default_settings = [
            {
                'key': 'min_annual_income',
                'value': '100000',
                'value_type': 'float',
                'description': 'Minimum annual income required for approval',
                'category': 'Underwriting Rules'
            },
            {
                'key': 'holdback_percentage',
                'value': '10',
                'value_type': 'float',
                'description': 'Percentage holdback for underwriting',
                'category': 'Underwriting Rules'
            },
            {
                'key': 'max_retry_attempts',
                'value': '2',
                'value_type': 'integer',
                'description': 'Maximum retry attempts for AI extraction',
                'category': 'System Config'
            },
            {
                'key': 'transfer_detection_window_days',
                'value': '2',
                'value_type': 'integer',
                'description': 'Number of days to look for matching transfers',
                'category': 'Transfer Detection'
            },
            {
                'key': 'max_nsf_count',
                'value': '3',
                'value_type': 'integer',
                'description': 'Maximum acceptable NSF count',
                'category': 'Underwriting Rules'
            },
            {
                'key': 'min_monthly_revenue',
                'value': '20000',
                'value_type': 'float',
                'description': 'Minimum monthly revenue required',
                'category': 'Underwriting Rules'
            },
            {
                'key': 'diesel_threshold',
                'value': '5000',
                'value_type': 'float',
                'description': 'Minimum diesel payments for diesel-related businesses',
                'category': 'Underwriting Rules'
            },
            {
                'key': 'ai_model',
                'value': 'gpt-4o',
                'value_type': 'string',
                'description': 'OpenAI model for Vision API',
                'category': 'AI Config'
            },
            {
                'key': 'ai_summary_model',
                'value': 'gpt-5',
                'value_type': 'string',
                'description': 'OpenAI model for underwriting summaries',
                'category': 'AI Config'
            },
        ]
        
        for setting_data in default_settings:
            setting = Setting(**setting_data, created_at=datetime.utcnow())
            db.add(setting)
        
        db.commit()
        print(f"✅ Initialized {len(default_settings)} default settings")

def main():
    print("Initializing database...")
    
    # Create all tables
    init_db()
    print("✅ Database tables created")
    
    # Initialize default settings
    initialize_default_settings()
    
    print("✅ Database initialization complete!")

if __name__ == "__main__":
    main()
