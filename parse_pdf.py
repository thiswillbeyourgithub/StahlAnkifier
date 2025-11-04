# /// script
# dependencies = [
#   "fire",
#   "pymupdf",
# ]
# ///

"""
PDF Parser Script

This script parses a PDF file and extracts metadata, table of contents, and content.
Uses PyMuPDF (fitz) for PDF parsing and Fire for CLI argument handling.

Created with assistance from aider.chat (https://github.com/Aider-AI/aider/)
"""

from pathlib import Path
from typing import Any

import fire
import fitz  # PyMuPDF


def parse_pdf(pdf_path: str) -> None:
    """
    Parse a PDF file and extract metadata, table of contents, and content.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file to parse.

    Notes
    -----
    This function extracts:
    - Title from metadata
    - Table of contents with section names and page numbers
    - Text content from each page
    
    After extraction, a breakpoint() is called to allow interactive investigation
    of the extracted data.
    """
    # Convert to Path object for better path handling
    pdf_file = Path(pdf_path)
    
    # Validate that the file exists and is a PDF
    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if pdf_file.suffix.lower() != '.pdf':
        raise ValueError(f"File must be a PDF, got: {pdf_file.suffix}")
    
    # Open the PDF document
    doc = fitz.open(pdf_path)
    
    # Extract metadata - title may be in metadata or empty
    metadata = doc.metadata
    title = metadata.get('title', '') or f"Untitled (from {pdf_file.name})"
    
    # Extract table of contents
    # fitz returns TOC as list of [level, title, page_num]
    toc_raw = doc.get_toc()
    table_of_contents = [
        {
            'level': level,
            'title': section_title,
            'page': page_num
        }
        for level, section_title, page_num in toc_raw
    ]
    
    # Extract text content from each page
    # Store as dict with page number as key for easy access
    page_contents = {}
    for page_num in range(len(doc)):
        page = doc[page_num]
        # Extract text from page - this gets all text in reading order
        page_text = page.get_text()
        page_contents[page_num + 1] = page_text  # Use 1-based indexing for readability
    
    # Store all extracted data for inspection
    pdf_data = {
        'title': title,
        'metadata': metadata,
        'table_of_contents': table_of_contents,
        'page_contents': page_contents,
        'total_pages': len(doc),
        'file_path': str(pdf_file.absolute())
    }
    
    # Close the document
    doc.close()
    
    # Enter debugger to allow investigation of extracted data
    # Variables available for inspection:
    # - title: PDF title
    # - table_of_contents: List of TOC entries with level, title, and page
    # - page_contents: Dict of page numbers -> text content
    # - pdf_data: Complete dict with all extracted information
    # - metadata: Full PDF metadata dict
    breakpoint()


def main() -> None:
    """
    Entry point for the CLI application.
    
    Uses Fire to automatically generate CLI interface from parse_pdf function.
    """
    fire.Fire(parse_pdf)


if __name__ == '__main__':
    main()
