from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

class Deal(Base):
    __tablename__ = "deals"
    
    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String(255), nullable=False)
    subject = Column(String(500))
    email_body = Column(Text)
    status = Column(String(50), default="Pending")  # Pending Approval, Needs Human Review, Underwritten, Approved, Rejected, Duplicate
    extracted_data = Column(JSON)  # Stores all extracted financial metrics
    ai_summary = Column(Text)
    ai_reasoning_log = Column(Text)  # Detailed log of AI's decision-making process
    final_decision = Column(String(50))
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    duplicate_of_deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True)
    
    # Relationships
    pdf_files = relationship("PDFFile", back_populates="deal", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="deal", cascade="all, delete-orphan")

class PDFFile(Base):
    __tablename__ = "pdf_files"
    
    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), unique=True, index=True)  # SHA-256 hash
    account_number = Column(String(100))  # Extracted account number
    account_status = Column(String(50), default="Identified")  # Identified, Unknown Source, Manually Tagged
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    deal = relationship("Deal", back_populates="pdf_files")

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=False)
    source_account_id = Column(String(100))  # Which account this transaction belongs to
    transaction_date = Column(DateTime)
    description = Column(Text)
    amount = Column(Float)
    transaction_type = Column(String(50))  # Debit, Credit
    is_internal_transfer = Column(Boolean, default=False)
    matched_transfer_id = Column(Integer, ForeignKey("transactions.id"), nullable=True)  # Links to matching transfer
    category = Column(String(100))  # Diesel, Income, Expense, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    deal = relationship("Deal", back_populates="transactions")

class TrainingExample(Base):
    __tablename__ = "training_examples"
    
    id = Column(Integer, primary_key=True, index=True)
    original_financial_json = Column(JSON, nullable=False)  # Original extracted data
    user_corrected_summary = Column(Text, nullable=False)  # User's corrected version
    correction_details = Column(JSON)  # Details about what was corrected
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

class GoldStandardRule(Base):
    __tablename__ = "gold_standard_rules"
    
    id = Column(Integer, primary_key=True, index=True)
    rule_pattern = Column(Text, nullable=False)  # The pattern to match (e.g., "Zelle from John Doe")
    rule_type = Column(String(50), nullable=False)  # transfer_classification, income_classification, etc.
    original_classification = Column(String(100))  # What AI originally thought
    correct_classification = Column(String(100), nullable=False)  # What it should be
    confidence_score = Column(Float, default=1.0)
    times_applied = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    context_json = Column(JSON)  # Additional context about when to apply this rule
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Setting(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    value_type = Column(String(50), default="string")  # string, integer, float, boolean
    description = Column(Text)
    category = Column(String(100))  # Underwriting Rules, System Config, etc.
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class KnownVendor(Base):
    """
    Store known vendors/merchants for automatic categorization.
    Used by the Vendor Learning System for fuzzy matching.
    """
    __tablename__ = "known_vendors"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)  # Vendor name pattern
    category = Column(String(50), nullable=False)  # MCA, Rent, Payroll, Insurance, Utilities, Ignore, etc.
    match_type = Column(String(20), default="fuzzy")  # exact, fuzzy, contains
    is_mca_lender = Column(Boolean, default=False)  # True if this is an MCA/lending position
    default_frequency = Column(String(20))  # daily, weekly, monthly (for MCA positions)
    notes = Column(Text)  # Additional context
    times_matched = Column(Integer, default=0)  # Track usage for confidence
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UnknownTransaction(Base):
    """
    Review queue for unrecognized recurring transactions.
    When pattern detection finds unknown recurring payments, they go here for human review.
    """
    __tablename__ = "unknown_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=True)
    description = Column(Text, nullable=False)  # Original transaction description
    normalized_name = Column(String(255))  # Cleaned/normalized name
    detected_frequency = Column(String(20))  # daily, weekly, monthly
    average_amount = Column(Float)  # Average transaction amount
    occurrence_count = Column(Integer, default=1)  # How many times seen
    sample_dates = Column(JSON)  # Sample of dates when this appeared
    status = Column(String(20), default="pending")  # pending, categorized, ignored
    assigned_category = Column(String(50))  # Category assigned by user (if any)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    reviewed_at = Column(DateTime)  # When user reviewed this
