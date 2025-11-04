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
from typing import Any, Dict, List

import fire
import fitz  # PyMuPDF
from bs4 import BeautifulSoup, Tag


def _merge_empty_consecutive(d: dict, is_empty: callable) -> dict:
    """
    Merge consecutive dict entries where first entry is empty.

    When two headers are next to each other and the first one has no content,
    they are merged by concatenating their names with a space.

    Parameters
    ----------
    d : dict
        Dictionary to clean
    is_empty : callable
        Function that returns True if a value is considered empty

    Returns
    -------
    dict
        New dict with empty entries merged
    """
    result = {}
    keys = list(d.keys())
    i = 0

    while i < len(keys):
        key = keys[i]
        value = d[key]

        # If this entry is empty and there's a next entry, merge them
        if is_empty(value) and i + 1 < len(keys):
            next_key = keys[i + 1]
            merged_key = f"{key} {next_key}"
            result[merged_key] = d[next_key]
            i += 2  # Skip both entries
        else:
            result[key] = value
            i += 1

    return result


def _merge_empty_headers(
    drug_dict: Dict[str, Dict[str, List[str]]],
) -> Dict[str, Dict[str, List[str]]]:
    """
    Merge consecutive headers that have no content.

    If two H1 or H2 headers are next to each other and the first one has no content,
    they are merged and their names concatenated with a space.

    Parameters
    ----------
    drug_dict : Dict[str, Dict[str, List[str]]]
        Hierarchical dict with H1 headers as keys

    Returns
    -------
    Dict[str, Dict[str, List[str]]]
        Cleaned dict with merged headers
    """
    # First merge H2 headers within each H1
    # H2 is empty if it has no content (empty list)
    h1_cleaned = {}
    for h1_key, h2_dict in drug_dict.items():
        h1_cleaned[h1_key] = _merge_empty_consecutive(h2_dict, lambda v: not v)

    # Then merge H1 headers
    # H1 is empty if it has no H2s or all H2s are empty
    result = _merge_empty_consecutive(
        h1_cleaned, lambda v: not v or all(not content for content in v.values())
    )

    return result


def parse_drug_pages(
    combined_soup: BeautifulSoup,
) -> Dict[str, Dict[str, List[str]]]:
    """
    Parse drug pages into hierarchical structure.

    H1 headers are identified by white text color (#ffffff), indicating colored background.
    H2 headers are identified by bold text with 10pt font size and dark text.
    Content under each H2 is stored as HTML strings.

    Parameters
    ----------
    combined_soup : BeautifulSoup
        BeautifulSoup object containing concatenated HTML from all drug pages

    Returns
    -------
    Dict[str, Dict[str, List[str]]]
        Hierarchical dict with H1 headers as keys, containing H2 headers
        and their HTML content as values
    """
    drug_dict: Dict[str, Dict[str, List[str]]] = {}

    # Find all paragraphs - these contain headers and content
    paragraphs = combined_soup.find_all("p")

    current_h1: str | None = None
    current_h2: str | None = None

    for p in paragraphs:
        # Look for span elements that might indicate headers
        span = p.find("span")
        if not span:
            continue

        style = span.get("style", "")

        # Check if this is an H1 header (white text color = colored background)
        if "color:#ffffff" in style.lower():
            # This is an H1 header
            current_h1 = span.get_text(strip=True)
            if current_h1 not in drug_dict:
                drug_dict[current_h1] = {}
            current_h2 = None
            continue

        # Check if this is an H2 header (bold, 10pt font, dark text)
        # H2 headers have bold tag and 10pt font size but NOT white color
        if "font-size:10.0pt" in style and p.find("b"):
            # This is an H2 header - extract just the bold text as the header
            bold_tag = p.find("b")
            h2_text = bold_tag.get_text(strip=True)

            # Skip if it's just whitespace or very short
            if h2_text and len(h2_text) > 1:
                current_h2 = h2_text
                if current_h1 and current_h2:
                    if current_h2 not in drug_dict[current_h1]:
                        drug_dict[current_h1][current_h2] = []

                    # Check if there's content after the bold tag in the same paragraph
                    # Create a copy and remove the bold tag to get remaining content
                    p_copy = BeautifulSoup(str(p), "html.parser").p
                    if p_copy and p_copy.find("b"):
                        p_copy.find("b").decompose()  # Remove the bold tag

                        # Check if there's any remaining text content
                        remaining_text = p_copy.get_text(strip=True)
                        if remaining_text:
                            # Add the modified paragraph (without header) as content
                            drug_dict[current_h1][current_h2].append(str(p_copy))
            continue

        # This is regular content - add to current section if we have both H1 and H2
        if current_h1 and current_h2:
            # Store the HTML content as a string
            drug_dict[current_h1][current_h2].append(str(p))

    # Merge consecutive headers where the first one has no content
    # This handles cases where headers appear back-to-back without content between them
    drug_dict = _merge_empty_headers(drug_dict)

    return drug_dict


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

    # Parse each drug's pages into hierarchical structure
    # The structure is: drug_name -> H1 header -> H2 header -> HTML content list
    # Concatenate all page HTML for each drug first to ensure coherent nesting across pages
    drug_content: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
    for drug_name, pages in drug_page.items():
        # Concatenate HTML from all pages for this drug
        combined_html = ""
        for page_soup in pages:
            combined_html += str(page_soup)

        # Parse the concatenated HTML as a single document
        combined_soup = BeautifulSoup(combined_html, "html.parser")

        # Parse the combined content
        drug_content[drug_name] = parse_drug_pages(combined_soup)

    # Create Anki cards from the parsed drug content
    # Each card has: Drug, Section (H1), Question (H2), Answer (concatenated H2 content), Tags
    cards: List[Dict[str, Any]] = []
    for drug_name, h1_dict in drug_content.items():
        for h1_header, h2_dict in h1_dict.items():
            for h2_header, content_list in h2_dict.items():
                # Verify content_list is a list, not a dict (would mean we missed a level)
                if not isinstance(content_list, list):
                    raise ValueError(
                        f"Expected list for content, got {type(content_list)} for "
                        f"{drug_name} -> {h1_header} -> {h2_header}"
                    )

                # Concatenate all HTML content into a single string
                combined_html = "".join(content_list)

                # Use BeautifulSoup to convert HTML to human-readable text
                soup = BeautifulSoup(combined_html, "html.parser")
                answer_text = soup.get_text(separator="\n", strip=True)

                # Create the card
                card = {
                    "Drug": drug_name,
                    "Section": h1_header,
                    "Question": h2_header,
                    "Answer": answer_text,
                    "Tags": [f"Stahl::{drug_name}::{h1_header}"],
                }
                cards.append(card)

    # Enter debugger to allow investigation of extracted data
    # Variables available for inspection:
    # - title: PDF title
    # - table_of_contents: List of TOC entries with level, title, and page
    # - page_contents: Dict of page numbers -> BeautifulSoup objects with HTML content
    # - pdf_data: Complete dict with all extracted information
    # - metadata: Full PDF metadata dict
    # - drug_page: Dict mapping drug names (uppercase) to list of BeautifulSoup page contents
    # - drug_content: Dict mapping drug names to hierarchical content structure (H1 -> H2 -> HTML)
    # - cards: List of dicts ready to be converted to Anki cards
    breakpoint()


def main() -> None:
    """
    Entry point for the CLI application.

    Uses Fire to automatically generate CLI interface from parse_pdf function.
    """
    fire.Fire(parse_pdf)


if __name__ == "__main__":
    main()
