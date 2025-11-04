# /// script
# dependencies = [
#   "fire",
#   "pymupdf",
#   "beautifulsoup4",
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
from bs4 import BeautifulSoup


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
    if pdf_file.suffix.lower() != ".pdf":
        raise ValueError(f"File must be a PDF, got: {pdf_file.suffix}")

    # Open the PDF document
    doc = fitz.open(pdf_path)

    # Extract metadata - title may be in metadata or empty
    metadata = doc.metadata
    title = metadata.get("title", "") or f"Untitled (from {pdf_file.name})"

    # Extract table of contents
    # fitz returns TOC as list of [level, title, page_num]
    toc_raw = doc.get_toc()
    table_of_contents = [
        {"level": level, "title": section_title, "page": page_num}
        for level, section_title, page_num in toc_raw
    ]

    # Extract HTML content from each page using get_textpage().extractHTML()
    # This preserves more structural information than plain text extraction
    # Store as dict with page number as key for easy access
    page_contents = {}
    for page_num in range(len(doc)):
        page = doc[page_num]
        # Extract HTML from page - this preserves formatting and structure
        textpage = page.get_textpage()
        html_content = textpage.extractHTML()
        # Parse HTML with BeautifulSoup for easier manipulation
        soup = BeautifulSoup(html_content, "html.parser")
        page_contents[page_num + 1] = soup  # Use 1-based indexing for readability

    # Store all extracted data for inspection
    pdf_data = {
        "title": title,
        "metadata": metadata,
        "table_of_contents": table_of_contents,
        "page_contents": page_contents,
        "total_pages": len(doc),
        "file_path": str(pdf_file.absolute()),
    }

    # Close the document
    doc.close()

    # Extract drug pages from table of contents
    # Drug chapters are identified by titles ending with an uppercase word
    # The page range starts at the item's page and ends at the next section's page
    # Example: '26.0_pp_125_128_BUSPIRONE' -> drug='BUSPIRONE'
    # Pages are from item["page"] to next_item["page"] - 1
    drug_page = {}
    for idx, item in enumerate(table_of_contents):
        title_text = item["title"]
        # Split by underscore to get segments
        segments = title_text.split("_")
        if segments:
            last_segment = segments[-1]
            # Check if the last segment is all uppercase and not empty
            # This indicates a drug name (e.g., BUSPIRONE, ASPIRIN, etc.)
            if last_segment and last_segment.isupper():
                # Start page is from the current TOC item
                start_page = item["page"]

                # End page is the page before the next TOC item, or total pages if this is the last item
                if idx + 1 < len(table_of_contents):
                    end_page = table_of_contents[idx + 1]["page"] - 1
                else:
                    end_page = pdf_data["total_pages"]

                # Collect content from all pages in the range
                pages_content = []
                for page_num in range(start_page, end_page + 1):
                    # page_contents uses 1-based indexing
                    if page_num in page_contents:
                        pages_content.append(page_contents[page_num])

                drug_page[last_segment] = pages_content

    # Enter debugger to allow investigation of extracted data
    # Variables available for inspection:
    # - title: PDF title
    # - table_of_contents: List of TOC entries with level, title, and page
    # - page_contents: Dict of page numbers -> BeautifulSoup objects with HTML content
    # - pdf_data: Complete dict with all extracted information
    # - metadata: Full PDF metadata dict
    # - drug_page: Dict mapping drug names (uppercase) to list of BeautifulSoup page contents
    breakpoint()


def main() -> None:
    """
    Entry point for the CLI application.

    Uses Fire to automatically generate CLI interface from parse_pdf function.
    """
    fire.Fire(parse_pdf)


if __name__ == "__main__":
    main()
