# Human-in-the-Loop Underwriting Platform

## Overview
A comprehensive AI-powered underwriting platform that combines automated document processing with human oversight and continuous learning. The system uses OpenAI's Vision API for document extraction, implements intelligent retry mechanisms, detects duplicate submissions, and learns from human corrections to improve over time.

## Architecture

### Tech Stack
- **Frontend**: Streamlit (Multi-page application)
- **Backend**: Flask (Webhook server for email ingestion)
- **Database**: PostgreSQL (Replit-hosted)
- **AI/ML**: OpenAI GPT-4o (Vision) and GPT-5 (via Replit AI Integrations)
- **Document Processing**: PyPDF2, Pillow, pytesseract

### Database Schema

#### Core Tables
1. **Deals** - Main deal records with status tracking
   - Stores extracted financial data (JSON)
   - Tracks AI reasoning logs
   - Links to duplicate deals
   - Status: Pending Approval, Needs Human Review, Underwritten, Approved, Rejected, Duplicate

2. **PDFFiles** - Uploaded bank statement PDFs
   - SHA-256 hash for duplicate detection
   - Account number extraction
   - Links to parent Deal

3. **Transactions** - Individual financial transactions
   - Multi-account support (source_account_id)
   - Transfer detection flags (is_internal_transfer)
   - Category classification (income, diesel, payment, etc.)

4. **TrainingExamples** - Human corrections for AI learning
   - Stores original AI output vs. corrected values
   - Used for few-shot learning in future analyses

5. **GoldStandard_Rules** - RAG-based pattern memory
   - Learned classification rules
   - Pattern matching for transaction categorization
   - Applied automatically to new deals

6. **Settings** - Dynamic configuration
   - Underwriting rules (min_annual_income, holdback_percentage, etc.)
   - System settings (max_retry_attempts, transfer_detection_window_days)
   - AI model configurations

## Key Features

### 1. Email Ingestion Pipeline
- **Endpoint**: `POST /incoming-email` (port 8080)
- Accepts JSON payloads with sender, subject, body, and PDF attachments
- Automatic SHA-256 hash calculation for duplicate detection
- Links duplicate submissions to original deals

### 2. Multi-Account Intelligence
- **Account Separator**: OCR scans top 20% of PDF to extract account numbers
- Automatically merges PDFs with matching account numbers
- Flags PDFs with no account number as "Unknown Source"
- Supports manual account tagging in UI

### 3. Transfer Hunter Algorithm
- Detects inter-account transfers using pattern matching:
  - Transaction A: Amount = -X, Date = T, Account = 1
  - Transaction B: Amount = +X, Date = T ±2 days, Account = 2
- Marks both transactions with `is_internal_transfer = True`
- Excludes internal transfers from revenue calculations
- Configurable detection window (default: 2 days)

### 4. Auto-Retry Verification Loop
- **Initial Extraction**: OpenAI Vision API extracts financial data
- **Math Verification**: Python validates sums match extracted totals
- **Intelligent Retry**: On failure, sends specific error feedback to AI
  - Example: "You extracted $50,000 but row sum is $48,500 - find the missing $1,500"
- **Max 2 Retries**: After 2 failed attempts, flags for human review
- Status outcomes: "Pending Approval" or "Needs Human Review"

### 5. Few-Shot Learning System
- Queries 3 most recent TrainingExamples before analysis
- Includes corrections in system prompt as examples
- AI learns from past mistakes automatically
- Improves accuracy over time

### 6. Forensic Trainer (Adversarial Training)
- **Split-Screen UI**:
  - Left: Uploaded PDFs (tabbed by account)
  - Center: AI reasoning log with exclusion explanations
  - Right: Truth form for correct values
- **Adversarial Feedback Loop**:
  1. Blind AI analysis
  2. Compare AI results vs. human truth
  3. Auto-generate interrogation prompt with specific errors
  4. AI conducts self-audit and generates correction report
- **Pattern Learning**: Save learned patterns to GoldStandard_Rules

### 7. Pattern Memory (RAG)
- Stores reusable classification rules
- Example: "Zelle from John Doe" → Income (not Transfer)
- Applied automatically to matching transactions in future deals
- Confidence scoring and success tracking

## Application Structure

### Streamlit Pages
1. **Home** (`app.py`) - Dashboard with quick stats and navigation
2. **Inbox** (`pages/1_📥_Inbox.py`) - Deal listing with status filters
3. **Deal Details** (`pages/2_📄_Deal_Details.py`) - Side-by-side PDF viewer and extracted data with correction interface
4. **Forensic Trainer** (`pages/3_🔬_Forensic_Trainer.py`) - Adversarial training system
5. **Configuration** (`pages/4_⚙️_Configuration.py`) - Dynamic rule management

### Core Modules
- `database.py` - SQLAlchemy connection and session management
- `models.py` - Database models and relationships
- `pdf_processor.py` - PDF hashing, OCR, account extraction
- `openai_integration.py` - Vision API, underwriting summaries, adversarial corrections
- `transfer_hunter.py` - Inter-account transfer detection
- `verification.py` - Auto-retry loop with math verification
- `webhook_server.py` - Flask email ingestion endpoint
- `init_database.py` - Database initialization script

## Running the Application

### Workflows
1. **Streamlit App** - Port 5000 (webview)
   - `streamlit run app.py --server.port 5000`
   
2. **Flask Webhook Server** - Port 8080 (console)
   - `python webhook_server.py`

### Initial Setup
```bash
# Initialize database (run once)
python init_database.py
```

## API Endpoints

### Webhook Endpoint
```
POST http://localhost:8080/incoming-email

Payload:
{
  "sender": "sender@example.com",
  "subject": "Bank Statement",
  "body": "Email body text",
  "attachments": [
    {
      "filename": "statement.pdf",
      "content": "<base64 encoded PDF>"
    }
  ]
}

Response:
{
  "status": "success|duplicate",
  "deal_id": 123,
  "final_status": "Pending Approval|Needs Human Review",
  "retry_count": 0,
  "account_number": "1234"
}
```

### Health Check
```
GET http://localhost:8080/health

Response:
{
  "status": "healthy",
  "service": "underwriting-webhook"
}
```

## Configuration Settings

### Underwriting Rules
- `min_annual_income`: Minimum annual income threshold (default: $100,000)
- `holdback_percentage`: Percentage holdback (default: 10%)
- `max_nsf_count`: Maximum NSF count allowed (default: 3)
- `min_monthly_revenue`: Minimum monthly revenue (default: $20,000)
- `diesel_threshold`: Diesel payment threshold (default: $5,000)

### System Configuration
- `max_retry_attempts`: Maximum AI retry attempts (default: 2)
- `transfer_detection_window_days`: Days to search for matching transfers (default: 2)
- `ai_model`: Vision API model (default: gpt-4o)
- `ai_summary_model`: Summary generation model (default: gpt-5)

## Workflow Examples

### Deal Processing Flow
1. Email arrives at webhook endpoint
2. PDF hash calculated, checked for duplicates
3. Account number extracted from PDF
4. OpenAI Vision extracts financial data
5. Math verification checks accuracy
6. If fails: Retry with specific error feedback (max 2x)
7. Transfer Hunter identifies inter-account transfers
8. Status set to "Pending Approval" or "Needs Human Review"
9. Deal appears in Inbox dashboard

### Human Correction Flow
1. Underwriter reviews deal in Deal Details page
2. Identifies AI error and corrects values
3. Clicks "Save Corrections & Train AI"
4. Correction saved to TrainingExamples table
5. AI uses this example in future few-shot learning

### Adversarial Training Flow
1. Upload historical deal with known truth values
2. AI analyzes blindly
3. System compares AI vs. truth
4. Generate adversarial prompt: "You said X, human says Y - find the error"
5. AI conducts self-audit
6. Save learned pattern to GoldStandard_Rules
7. Pattern automatically applied to future deals

## AI Integration Details

### OpenAI Models Used
- **GPT-4o**: Vision API for PDF document extraction
  - Supports both text and image analysis
  - Returns structured JSON with financial metrics
  
- **GPT-5**: Underwriting summaries and adversarial corrections
  - Incorporates few-shot examples from TrainingExamples
  - Applies patterns from GoldStandard_Rules
  - Generates detailed reasoning logs

### Replit AI Integrations
- No OpenAI API key required
- Charges billed to Replit credits
- Fully compatible OpenAI SDK interface

## Data Security

### Duplicate Prevention
- SHA-256 hashing of all PDF files
- Database-level unique constraint on file_hash
- Automatic linking to original deal when duplicate detected

### Database Management
- Development database accessible via tools
- Production database requires manual management via Replit UI
- Never expose DATABASE_URL or credentials

## Future Enhancements

### Suggested Next Steps (from Architect Review)
1. **Automated Tests**: Add unit and integration tests for webhook, transfer detection, and retry loop
2. **Enhanced Logging**: Improve error handling and observability for OpenAI and PDF processing
3. **Demo Data**: Seed example deals for demonstration purposes
4. **Advanced Transfer Patterns**: Detect partial matches, recurring transfers, split transactions
5. **Analytics Dashboard**: Track AI accuracy metrics and improvement trends

### Potential Features
- Bulk processing for multiple email submissions
- Role-based access control
- Export functionality (PDF reports)
- Collaborative review workflow
- Additional document types (tax returns, invoices)

## Recent Changes
- **2024-11-24**: Initial implementation of complete platform
  - Database schema with all 6 tables
  - Flask webhook server with duplicate detection
  - Multi-account support and transfer detection
  - Auto-retry verification loop (max 2 retries)
  - Streamlit 4-page dashboard
  - Forensic Trainer with adversarial feedback
  - RAG-based pattern memory system
  - Dynamic configuration management
  
- **2024-11-24**: Bug fixes and feature additions
  - Fixed file upload 403 errors by configuring Streamlit properly (maxUploadSize, maxMessageSize)
  - Fixed SQLAlchemy DetachedInstanceError in Configuration page with fresh session per save
  - Added Excel file upload for truth values in Forensic Trainer (.xlsx/.xls support)
  - Implemented intelligent column name matching for Excel (case-insensitive, flexible)
  - Fixed radio button UX - moved outside form for immediate mode switching
  - Maintained security by keeping XSRF and CORS protection enabled

## User Preferences
None specified yet.

## Notes
- The platform is fully functional and ready for testing
- Both workflows (Streamlit + Flask) must run concurrently
- Database must be initialized before first use
- OpenAI integration uses Replit AI Integrations (no API key needed)
