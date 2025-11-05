# /// script
# dependencies = [
#   "fire",
#   "pymupdf",
#   "beautifulsoup4",
#   "loguru",
#   "tqdm",
# ]
# ///

"""
PDF Parser Script

This script parses a PDF file and extracts metadata, table of contents, and content.
Uses PyMuPDF (fitz) for PDF parsing and Fire for CLI argument handling.

Created with assistance from aider.chat (https://github.com/Aider-AI/aider/)
"""

import random
from pathlib import Path
from typing import Any, Dict, List

import fire
import fitz  # PyMuPDF
from bs4 import BeautifulSoup, Tag
from loguru import logger
from tqdm import tqdm


def _clean_page_headers(soup: BeautifulSoup, drug_name: str) -> BeautifulSoup:
    """
    Remove page headers from the first 0-3 paragraphs.

    Headers to remove include:
    - Page numbers (just a number)
    - "(continued)" text
    - The drug name in uppercase

    This prevents these elements from appearing in Anki card answers.

    Parameters
    ----------
    soup : BeautifulSoup
        Page content to clean
    drug_name : str
        The drug name (in uppercase) to match against

    Returns
    -------
    BeautifulSoup
        Cleaned page content with headers removed
    """
    # Create a copy to avoid modifying the original
    soup_copy = BeautifulSoup(str(soup), "html.parser")

    # Find all paragraphs
    paragraphs = soup_copy.find_all("p")

    # Check first 0-3 paragraphs and remove if they match header patterns
    for i in range(min(3, len(paragraphs))):
        p = paragraphs[i]
        text = p.get_text(strip=True)

        # Check if this is a header we should remove:
        # 1. Just a number (page counter)
        # 2. "(continued)" indicator
        # 3. Drug name in uppercase
        if text.isdigit() or text.lower() == "(continued)" or text == drug_name:
            p.decompose()  # Remove this paragraph
        else:
            # Stop checking once we hit a non-header paragraph
            break

    return soup_copy


def _merge_empty_consecutive(d: dict, is_empty: callable) -> dict:
    """
    Merge consecutive dict entries where first entry is empty.

    When two headers are next to each other and the first one has no content,
    they are merged by concatenating their names with a space.
    This process repeats iteratively until no more merges are possible,
    handling cases where multi-line headers are split into 3+ separate entries.

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
    # Keep merging until no more changes occur
    # This handles cases like multi-line headers split into 3+ parts
    changed = True
    result = d.copy()

    while changed:
        changed = False
        new_result = {}
        keys = list(result.keys())
        i = 0

        while i < len(keys):
            key = keys[i]
            value = result[key]

            # If this entry is empty and there's a next entry, merge them
            if is_empty(value) and i + 1 < len(keys):
                next_key = keys[i + 1]
                merged_key = f"{key} {next_key}"
                new_result[merged_key] = result[next_key]
                i += 2  # Skip both entries
                changed = True  # Mark that we made a change
            else:
                new_result[key] = value
                i += 1

        result = new_result

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


def _clean_html_keep_formatting(html_content: str) -> str:
    """
    Clean HTML by removing most tags while preserving formatting tags.

    This removes structural tags like <div>, <span>, etc. but keeps
    formatting tags like <b>, <i>, <a> that are useful in Anki cards.

    Parameters
    ----------
    html_content : str
        HTML content to clean

    Returns
    -------
    str
        Cleaned HTML with only formatting tags preserved
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Tags to keep - these preserve useful formatting for Anki
    # Bold/strong, italic/emphasis, underline, links, line breaks, paragraphs
    allowed_tags = {"b", "strong", "i", "em", "u", "a", "br", "p", "ul", "ol", "li"}

    # Remove all tags except the allowed ones
    # unwrap() removes the tag but keeps its content
    for tag in soup.find_all():
        if tag.name not in allowed_tags:
            tag.unwrap()

    return str(soup)


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
    logger.warning("Opening PDF file")
    doc = fitz.open(pdf_path)
    logger.info(f"PDF opened successfully: {pdf_file.name}")

    # Extract metadata - title may be in metadata or empty
    logger.info("Extracting metadata and table of contents...")
    metadata = doc.metadata
    title = metadata.get("title", "") or f"Untitled (from {pdf_file.name})"

    # Extract table of contents
    # fitz returns TOC as list of [level, title, page_num]
    toc_raw = doc.get_toc()
    table_of_contents = [
        {"level": level, "title": section_title, "page": page_num}
        for level, section_title, page_num in toc_raw
    ]
    logger.info(f"Found {len(table_of_contents)} TOC entries")

    # Extract HTML content and images from each page
    # HTML uses get_textpage().extractHTML() to preserve formatting and structure
    # Images are rendered as PNG using get_pixmap() for visual reference in Anki cards
    # Store as dict with page number as key for easy access
    logger.info(f"Extracting HTML content and images from {len(doc)} pages...")
    page_contents = {}
    page_images: Dict[int, bytes] = {}
    for page_num in tqdm(range(len(doc)), desc="Extracting pages"):
        page = doc[page_num]
        # Extract HTML from page - this preserves formatting and structure
        textpage = page.get_textpage()
        html_content = textpage.extractHTML()
        # Parse HTML with BeautifulSoup for easier manipulation
        soup = BeautifulSoup(html_content, "html.parser")
        page_contents[page_num + 1] = soup  # Use 1-based indexing for readability

        # Render page as PNG image for visual reference
        # DPI=150 balances quality and file size (typical range is 150-300)
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        page_images[page_num + 1] = img_bytes  # Store as bytes for flexibility

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
    logger.info("Identifying drug pages from table of contents...")
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

    logger.info(f"Found {len(drug_page)} drugs to process")

    # Build drug_images dict mapping drug names to their page images
    # This allows including source pages as images in Anki cards for visual reference
    logger.info("Collecting page images for each drug...")
    drug_images: Dict[str, List[bytes]] = {}
    for idx, item in enumerate(table_of_contents):
        title_text = item["title"]
        segments = title_text.split("_")
        if segments:
            last_segment = segments[-1]
            if last_segment and last_segment.isupper():
                # Get page range for this drug
                start_page = item["page"]
                if idx + 1 < len(table_of_contents):
                    end_page = table_of_contents[idx + 1]["page"] - 1
                else:
                    end_page = pdf_data["total_pages"]

                # Collect images for all pages in this drug's range
                images_for_drug = []
                for page_num in range(start_page, end_page + 1):
                    if page_num in page_images:
                        images_for_drug.append(page_images[page_num])

                drug_images[last_segment] = images_for_drug

    logger.info(f"Collected images for {len(drug_images)} drugs")

    # Parse each drug's pages into hierarchical structure
    # The structure is: drug_name -> H1 header -> H2 header -> HTML content list
    # Concatenate all page HTML for each drug first to ensure coherent nesting across pages
    logger.info("Parsing drug content into hierarchical structure...")
    drug_content: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
    for drug_name, pages in tqdm(drug_page.items(), desc="Parsing drugs"):
        # Concatenate HTML from all pages for this drug
        # Clean page headers first to avoid them appearing in answers
        combined_html = ""
        for page_soup in pages:
            cleaned_soup = _clean_page_headers(page_soup, drug_name)
            combined_html += str(cleaned_soup)

        # Parse the concatenated HTML as a single document
        combined_soup = BeautifulSoup(combined_html, "html.parser")

        # Parse the combined content
        drug_content[drug_name] = parse_drug_pages(combined_soup)

    # Create Anki cards from the parsed drug content
    # Each card has: Drug, Section (H1), Question (H2), Answer (concatenated H2 content), Tags
    logger.info("Creating Anki cards from parsed content...")
    cards: List[Dict[str, Any]] = []
    for drug_name, h1_dict in tqdm(drug_content.items(), desc="Creating cards"):
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

                # Clean HTML to keep only formatting tags (bold, italic, links, etc.)
                # This preserves visual formatting while removing structural bloat
                answer_text = _clean_html_keep_formatting(combined_html)

                # Create the card
                # Format drug name and section with title case for readability
                # Add question mark to question if not present
                question = h2_header if h2_header.endswith("?") else f"{h2_header}?"

                card = {
                    "Drug": drug_name.title(),
                    "Section": h1_header.title(),
                    "Question": question,
                    "Answer": answer_text,
                    "Tags": [
                        f"Stahl::{drug_name.replace(' ', '_')}::{h1_header.replace(' ', '_')}"
                    ],
                }
                cards.append(card)

    logger.info(f"Created {len(cards)} Anki cards")

    # Check for cards with empty answer fields
    logger.info("Checking for cards with empty answers...")
    empty_answer_indices = []
    for idx, card in enumerate(cards):
        if not card["Answer"] or not card["Answer"].strip():
            empty_answer_indices.append(idx)
            logger.warning(
                f"Card {idx} has empty answer: "
                f"Drug={card['Drug']}, Section={card['Section']}, Question={card['Question']}"
            )

    if empty_answer_indices:
        logger.warning(
            f"Found {len(empty_answer_indices)} cards with empty answers: {empty_answer_indices}"
        )
    else:
        logger.info("All cards have non-empty answers")

    # Local function to display random cards in Anki-like layout
    def r(k: int = 5) -> None:
        """
        Print k random cards in Anki-like layout.

        Parameters
        ----------
        k : int, optional
            Number of random cards to display, by default 5
        """
        sample_size = min(k, len(cards))
        sample_cards = random.sample(cards, sample_size)

        for idx, card in enumerate(sample_cards, 1):
            print(f"\n{'=' * 80}")
            print(f"Card {idx}/{sample_size}")
            print(f"{'=' * 80}")
            print(f"Drug: {card['Drug']}")
            print(f"Section: {card['Section']}")
            print(f"\nQuestion: {card['Question']}")
            print(f"\n{'-' * 80}")
            print(f"Answer:\n{card['Answer']}")
            print(f"\nTags: {', '.join(card['Tags'])}")
            print(f"{'=' * 80}")

    # Enter debugger to allow investigation of extracted data
    # Variables available for inspection:
    # - title: PDF title
    # - table_of_contents: List of TOC entries with level, title, and page
    # - page_contents: Dict of page numbers -> BeautifulSoup objects with HTML content
    # - page_images: Dict of page numbers -> PNG image bytes
    # - pdf_data: Complete dict with all extracted information
    # - metadata: Full PDF metadata dict
    # - drug_page: Dict mapping drug names (uppercase) to list of BeautifulSoup page contents
    # - drug_images: Dict mapping drug names to list of PNG image bytes (one per page)
    # - drug_content: Dict mapping drug names to hierarchical content structure (H1 -> H2 -> HTML)
    # - cards: List of dicts ready to be converted to Anki cards
    # - r: Function to display random cards (call r() or r(k=10))
    breakpoint()


def main() -> None:
    """
    Entry point for the CLI application.

    Uses Fire to automatically generate CLI interface from parse_pdf function.
    """
    fire.Fire(parse_pdf)


if __name__ == "__main__":
    main()
