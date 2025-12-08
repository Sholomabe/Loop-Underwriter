# Human-in-the-Loop Underwriting Platform

## Overview
This AI-powered underwriting platform automates document processing with human oversight and continuous learning. It uses **Koncile API** as the primary extraction engine for bank statements, with built-in verification to catch OCR errors. The platform detects duplicate submissions, verifies extracted data against bank statement summaries, and enhances accuracy through learning from human corrections. The goal is to streamline MCA underwriting, reduce manual effort, and improve decision-making accuracy.

## User Preferences
None specified yet.

## System Architecture
The platform utilizes a multi-page Streamlit application for the frontend and a Flask webhook server for backend email ingestion. PostgreSQL serves as the primary database, hosted on Replit. OpenAI's GPT-4o (Vision) and GPT-5 models are integrated via Replit AI for document analysis, summarization, and adversarial learning. Core document processing relies on libraries like PyPDF2, Pillow, and pytesseract.

### UI/UX Decisions
- **Streamlit Multi-page Application**: Provides a structured interface with dedicated pages for Dashboard, Inbox, Deal Details, Forensic Trainer, and Configuration.
- **Split-Screen UI**: The Forensic Trainer features a split-screen layout for side-by-side comparison of PDFs, AI reasoning logs, and truth forms, facilitating human corrections and adversarial training.
- **Dynamic Configuration**: UI allows for real-time adjustments of underwriting rules and system settings without code changes.

### Technical Implementations
- **Email Ingestion Pipeline**: A Flask webhook (`POST /incoming-email` on port 8080) processes email payloads, including PDF attachments, calculates SHA-256 hashes for duplicate detection, and initiates deal creation with Koncile extraction.
- **Koncile Extraction Flow**: 
  1. PDF uploaded to Koncile API
  2. Poll for completion (max 120 seconds)
  3. Parse General_fields (summary) and Line_fields (transactions)
  4. Auto-verify extracted transactions against bank summary
  5. Set deal status based on verification confidence
- **Statement Verification**: Compares extracted transactions against bank statement summary (deposits, withdrawals, checks, fees) with 1% tolerance. High-severity discrepancies (>$100) lower confidence score.
- **Multi-Account Intelligence**: Koncile extracts account numbers from PDFs, enabling automatic merging of related documents and flagging of unidentified sources.
- **Transfer Hunter Algorithm**: Detects inter-account transfers by matching debits and credits across accounts within a configurable time window, excluding them from revenue calculations.
- **Few-Shot Learning System**: The system dynamically incorporates human corrections from `TrainingExamples` into AI prompts for future analyses, improving model accuracy over time.
- **Forensic Trainer (Adversarial Training)**: A module designed for iterative AI improvement. Now uses **Koncile API** for extraction (same as production workflow) to ensure training matches real-world behavior. It compares Koncile output against human-provided truth data, generates specific error-based prompts for the AI to self-audit, and saves learned patterns to `GoldStandard_Rules`. This includes comprehensive comparison of all extracted metrics (info_needed, positions, bank accounts).
- **Pattern Memory (RAG)**: Stores and applies learned classification rules (`GoldStandard_Rules`) for transaction categorization, such as identifying specific Zelle payments as income.
- **Underwriting Logic**: Includes refined transfer logic to correctly identify revenue vs. internal transfers, debt identification using known lender keywords, and robust stacking logic for recurring positions.
- **AI Intelligence Improvements**: Incorporates critical rules for AI prompting, such as prioritizing 'type' fields for cash flow direction, ensuring all payment debits are included in total monthly payments, clustering positions by merchant with amount tolerance, and marking income metrics as "not computable" when no credit data exists.
- **Smart MCA Detection System** (`openai_integration.py`): 3-layer detection approach for identifying MCA positions:
  - **Layer 1 - Whitelist**: 50+ known MCA lenders including FORA FINANCIAL, SPARTAN CAP, EBF HOLDINGS, MCA SERVICING, ONDECK, CREDIBLY, HEADWAY, KALAMATA, etc. Always flagged as MCA.
  - **Layer 2 - Blacklist**: 60+ known false positives including CAPITAL ONE, INTUIT FINANCING, credit cards (AMEX, DISCOVER), insurance companies (PROGRESSIVE, STATE FARM), payroll (ADP, PAYCHEX), utilities. Never flagged as MCA.
  - **Layer 3 - Pattern Validation**: Generic keywords (CAPITAL, FUNDING, ADVANCE, FINANCING) only flag as MCA when transaction data validates the pattern (10+ payments, ±15% amount variance, $50-$5,000 range).
  - Key functions: `is_mca_whitelist()`, `is_mca_blacklist()`, `is_likely_mca_pattern()`, `get_mca_confidence()`
- **Loan Simulator ("Diesel" Feature)**: Sidebar widget on Deal Details page that calculates affordability for new loans. Inputs: Loan Amount, Factor Rate, Term (Daily/Weekly). Outputs: Daily/Weekly/Monthly Payment, Total Payback, and Projected Balance with red warning if cash flow is insufficient.
- **PDF Chunking for Large Documents**: Large PDF text (>50k characters) is split into overlapping chunks, processed separately through OpenAI, and intelligently merged. Uses max-value deduplication for revenues by month and preserves AI-calculated metrics from each chunk.
- **Logic Engine** (`logic_engine.py`): Core calculation module that processes transaction data to compute:
  - Income & Revenue metrics (total income, deductions, net revenue, averages)
  - Monthly revenue breakdown tables
  - MCA position detection (daily/weekly payments with frequency analysis)
  - Diesel payment detection and projections
  - Underwriting ratios (payment-to-income, available capacity)
  - Complete positions table generation
- **Pattern Recognizer** (`logic_engine.py:PatternRecognizer`): Advanced pattern detection for:
  - Internal transfer detection using 2-day window matching across accounts
  - Recurring payment pattern analysis (daily/weekly frequency detection)
  - Stop/start pattern detection (paused/resumed payments, refinancing)
- **Vendor Learning System**: Machine learning for transaction categorization:
  - `KnownVendor` table stores recognized vendors with categories (MCA, Insurance, Payroll, etc.)
  - Fuzzy matching (fuzzywuzzy) to match transactions against known vendors
  - Review Unknown Transactions page (`pages/5_🔍_Review_Transactions.py`) for human categorization
  - Learning from human input to improve future matching
  - Seeded with 39 known vendors (20 MCA lenders, 19 operating expenses)
- **AI Verification Agent** (`ai_verification_agent.py`): LLM-powered second opinion system:
  - Quick validation for basic sanity checks (payment ratios, position counts)
  - Full AI verification using OpenAI for anomaly detection
  - Integrated into Deal Details page showing AI opinion alongside underwriter metrics
  - Flags critical issues, warnings, and provides detailed analysis
- **Koncile Integration** (`koncile_integration.py`): Bank statement extraction via Koncile API:
  - Connects to Koncile API for automated document extraction
  - Pulls both General_fields (summary) and Line_fields (transactions)
  - Statement Verification feature compares extracted transactions against bank summary
  - Detects OCR/extraction errors by checking deposits, withdrawals, checks, and fees match
  - Confidence scoring based on discrepancy severity
  - Integrated verification panel in Deal Details page

### Feature Specifications
- **Dynamic Configuration**: Manages underwriting rules (e.g., `min_annual_income`, `holdback_percentage`) and system settings (e.g., `max_retry_attempts`, `transfer_detection_window_days`).
- **Data Security**: Implements SHA-256 hashing for PDF files to prevent duplicates and ensures database security by not exposing credentials.

### System Design Choices
- **Database Schema**: Structured around `Deals`, `PDFFiles`, `Transactions`, `TrainingExamples`, `GoldStandard_Rules`, and `Settings` tables, designed for comprehensive tracking and AI learning.
- **Modularity**: Codebase is organized into distinct modules for database interaction (`database.py`, `models.py`), PDF processing (`pdf_processor.py`), AI integration (`openai_integration.py`), and core business logic (`transfer_hunter.py`, `verification.py`, `webhook_server.py`).

## External Dependencies
- **Koncile API**: Primary extraction engine for bank statements. Extracts both summary data (General_fields) and transaction details (Line_fields) with confidence scoring.
- **OpenAI GPT-4o**: Used for AI verification (second opinion), adversarial corrections, and pattern learning. No longer used for primary extraction.
- **PostgreSQL**: The relational database management system used for storing all application data, hosted on Replit.
- **Streamlit**: Python framework for building the interactive web application frontend.
- **Flask**: Python micro-framework used for the backend webhook server handling email ingestion.
- **PyPDF2**: Python library for working with PDF documents.
- **Pillow (PIL Fork)**: Python Imaging Library used for image processing.
- **Pytesseract**: Python wrapper for Google's Tesseract-OCR Engine, used for fallback OCR if needed.