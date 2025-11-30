"""
Seed initial known vendors (MCA lenders) for the vendor learning system.
Run this once to populate the database with common MCA lenders.
"""

from database import get_db
from models import KnownVendor
from datetime import datetime


MCA_LENDERS = [
    ("CAN CAPITAL", "MCA", "contains", True, "daily"),
    ("ONDECK", "MCA", "contains", True, "daily"),
    ("CREDIBLY", "MCA", "contains", True, "daily"),
    ("KALAMATA CAPITAL", "MCA", "contains", True, "daily"),
    ("HEADWAY CAPITAL", "MCA", "contains", True, "weekly"),
    ("YELLOWSTONE CAPITAL", "MCA", "contains", True, "daily"),
    ("LIBERTAS FUNDING", "MCA", "contains", True, "daily"),
    ("CLEARVIEW FUNDING", "MCA", "contains", True, "daily"),
    ("RAPID FINANCE", "MCA", "contains", True, "daily"),
    ("BIZFUND", "MCA", "contains", True, "daily"),
    ("FORWARD FINANCING", "MCA", "contains", True, "daily"),
    ("KING COMMERCIAL", "MCA", "contains", True, "daily"),
    ("HUNTER CAROLINE", "MCA", "contains", True, "daily"),
    ("MERCHANT ADVANCE", "MCA", "contains", True, "daily"),
    ("CASH ADVANCE", "MCA", "contains", True, "daily"),
    ("DAILY ACH", "MCA", "contains", True, "daily"),
    ("WORLD BUSINESS LENDERS", "MCA", "contains", True, "weekly"),
    ("NEWTEK", "MCA", "contains", True, "monthly"),
    ("KABBAGE", "MCA", "contains", True, "weekly"),
    ("BLUEVINE", "MCA", "contains", True, "weekly"),
]

OPERATING_EXPENSES = [
    ("DISCOVER CARD", "Credit Card", "contains", False, None),
    ("AMEX", "Credit Card", "contains", False, None),
    ("AMERICAN EXPRESS", "Credit Card", "contains", False, None),
    ("CHASE CARD", "Credit Card", "contains", False, None),
    ("CAPITAL ONE CARD", "Credit Card", "contains", False, None),
    ("UTICA INSURANCE", "Insurance", "contains", False, None),
    ("PROGRESSIVE", "Insurance", "contains", False, None),
    ("STATE FARM", "Insurance", "contains", False, None),
    ("ALLSTATE", "Insurance", "contains", False, None),
    ("GEICO", "Insurance", "contains", False, None),
    ("LIBERTY MUTUAL", "Insurance", "contains", False, None),
    ("ADP PAYROLL", "Payroll", "contains", False, None),
    ("PAYCHEX", "Payroll", "contains", False, None),
    ("GUSTO", "Payroll", "contains", False, None),
    ("RENT PAYMENT", "Rent", "contains", False, None),
    ("COMMERCIAL RENT", "Rent", "contains", False, None),
    ("UTILITY BILL", "Utilities", "contains", False, None),
    ("ELECTRIC BILL", "Utilities", "contains", False, None),
    ("GAS BILL", "Utilities", "contains", False, None),
]


def seed_known_vendors():
    """Seed the known vendors database with initial data."""
    with get_db() as db:
        existing_count = db.query(KnownVendor).count()
        
        if existing_count > 0:
            print(f"Database already has {existing_count} vendors. Skipping seed.")
            return existing_count
        
        vendors_added = 0
        
        for name, category, match_type, is_mca, frequency in MCA_LENDERS:
            vendor = KnownVendor(
                name=name,
                category=category,
                match_type=match_type,
                is_mca_lender=is_mca,
                default_frequency=frequency
            )
            db.add(vendor)
            vendors_added += 1
        
        for name, category, match_type, is_mca, frequency in OPERATING_EXPENSES:
            vendor = KnownVendor(
                name=name,
                category=category,
                match_type=match_type,
                is_mca_lender=is_mca,
                default_frequency=frequency
            )
            db.add(vendor)
            vendors_added += 1
        
        db.commit()
        print(f"Successfully seeded {vendors_added} known vendors.")
        return vendors_added


if __name__ == "__main__":
    seed_known_vendors()
