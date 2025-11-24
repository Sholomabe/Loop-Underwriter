import hashlib
import os
import re
from typing import Optional, Tuple
from PIL import Image
import pytesseract
from PyPDF2 import PdfReader
import io

def calculate_pdf_hash(pdf_path: str) -> str:
    """Calculate SHA-256 hash of a PDF file."""
    sha256_hash = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def extract_account_number_from_pdf(pdf_path: str) -> Tuple[Optional[str], str]:
    """
    Extract account number from the top 20% of the first page of a PDF.
    
    Returns:
        Tuple of (account_number, status)
        status can be: "Identified", "Unknown Source"
    """
    try:
        reader = PdfReader(pdf_path)
        if len(reader.pages) == 0:
            return None, "Unknown Source"
        
        first_page = reader.pages[0]
        
        # Extract text from first page
        text = first_page.extract_text()
        
        if not text or len(text.strip()) < 10:
            # If text extraction fails, we might need OCR
            # For now, mark as Unknown Source
            return None, "Unknown Source"
        
        # Take top 20% of text (rough approximation)
        lines = text.split('\n')
        top_20_percent_lines = lines[:max(1, len(lines) // 5)]
        top_text = '\n'.join(top_20_percent_lines)
        
        # Common account number patterns
        patterns = [
            r'(?:account|acct).*?(?:ending in|ending|#|number|no\.?)[\s:]*(\d{4,})',
            r'(?:ending in|ending)[\s:]*(\d{4,})',
            r'account\s*(?:number|#|no\.?)[\s:]*(\d{4,})',
            r'(\d{10,})',  # Long number sequences
        ]
        
        for pattern in patterns:
            match = re.search(pattern, top_text, re.IGNORECASE)
            if match:
                account_num = match.group(1)
                # If it's a long number, take last 4 digits
                if len(account_num) > 4:
                    account_num = account_num[-4:]
                return account_num, "Identified"
        
        return None, "Unknown Source"
        
    except Exception as e:
        print(f"Error extracting account number: {e}")
        return None, "Unknown Source"

def convert_pdf_to_images(pdf_path: str, max_pages: int = 10) -> list:
    """
    Convert PDF pages to images for Vision API processing.
    
    Returns list of PIL Image objects.
    """
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=200, first_page=1, last_page=max_pages)
        return images
    except ImportError:
        # pdf2image not installed, try alternative method
        print("pdf2image not available, using alternative method")
        return []
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return []

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract all text content from a PDF."""
    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        print(f"Error extracting text from PDF: {e}")
        return ""

def merge_pdfs_by_account(pdf_files: list) -> dict:
    """
    Group PDF files by account number.
    
    Args:
        pdf_files: List of dict with 'file_path' and 'account_number'
    
    Returns:
        Dict mapping account_number to list of file_paths
    """
    account_groups = {}
    
    for pdf_file in pdf_files:
        account = pdf_file.get('account_number', 'Unknown')
        if account not in account_groups:
            account_groups[account] = []
        account_groups[account].append(pdf_file['file_path'])
    
    return account_groups
