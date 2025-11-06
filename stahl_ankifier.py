# /// script
# dependencies = [
#   "pymupdf==1.26.4",
#   "beautifulsoup4==4.14.2",
#   "loguru==0.7.3",
#   "tqdm==4.67.1",
#   "genanki==0.13.1",
#   "Pillow==12.0.0",
# ]
# ///

"""
Stahl's Prescriber's Guide to Anki Converter

This script parses the PDF of Stahl's Essential Psychopharmacology: Prescriber's Guide
(8th Edition, ISBN: 9781009464772, DOI: https://doi.org/10.1017/9781009464772) and
converts it into Anki flashcards.

The script extracts the hierarchical structure of drug monographs and generates
flashcards organized by drug name, major sections (H1 headers), and specific topics
(H2 headers). Each card includes the question/topic, answer content with preserved
formatting, source page images for reference, and hierarchical tags.

Uses PyMuPDF (fitz) for PDF parsing and genanki for Anki package creation.

Created with assistance from aider.chat (https://github.com/Aider-AI/aider/)
"""

import argparse
import io
import re
import random
import shutil
import copy
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Literal

import fitz  # PyMuPDF
import genanki
from bs4 import BeautifulSoup, Tag
from loguru import logger
from PIL import Image
from tqdm import tqdm

# Version of the script
VERSION = "2.3.0"


def _clean_page_headers(soup: BeautifulSoup, drug_name: str) -> BeautifulSoup:
    """
    Remove page headers from the first 0-3 paragraphs.

    Headers to remove include:
    - Page numbers (just a number)
    - "(continued)" text
    - The drug name in uppercase
    - "Published online by Cambridge University Press"

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
        # 4. Cambridge University Press notice
        if (
            text.isdigit()
            or text.lower() == "(continued)"
            or text == drug_name
            or text == "Published online by Cambridge University Press"
        ):
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


def _merge_bullet_paragraphs(html_content: str) -> str:
    """
    Merge consecutive <p> tags that don't start with a bullet point (•).

    Paragraphs starting with • are kept separate as they mark the beginning
    of new bullet points. Paragraphs without • are merged with the previous
    paragraph to fix line wrapping issues in the PDF extraction.

    Parameters
    ----------
    html_content : str
        HTML content to process

    Returns
    -------
    str
        HTML with merged paragraphs
    """
    soup = BeautifulSoup(html_content, "html.parser")
    paragraphs = soup.find_all("p")

    if not paragraphs:
        return html_content

    # Group paragraphs - each group starts with a bullet point or is the first paragraph
    groups = []
    current_group = []

    for p in paragraphs:
        text = p.get_text(strip=True)

        # Check if this paragraph starts a new bullet point
        if text.startswith("•"):
            # Save the current group if it exists
            if current_group:
                groups.append(current_group)
            # Start a new group with this paragraph
            current_group = [p]
        else:
            # Add to current group (merge with previous)
            current_group.append(p)

    # Don't forget the last group
    if current_group:
        groups.append(current_group)

    # Merge each group into a single paragraph
    merged_paragraphs = []
    for group in groups:
        if len(group) == 1:
            # Single paragraph, keep as is
            merged_paragraphs.append(str(group[0]))
        else:
            # Multiple paragraphs, merge their content
            # Extract text from each paragraph and join with a space
            merged_text = " ".join(p.get_text(strip=True) for p in group)
            merged_paragraphs.append(f"<p>{merged_text}</p>")

    return "".join(merged_paragraphs)


def _remove_paragraph_tags(html_content: str) -> str:
    """
    Remove <p> tags while preserving their content and adding line breaks.

    This makes the content easier to edit in Anki by removing
    unnecessary paragraph wrapper tags. A line break is added after each
    paragraph to preserve visual separation when the <p> tag is removed,
    preventing the content from becoming an unformatted wall of text.

    Parameters
    ----------
    html_content : str
        HTML content to process

    Returns
    -------
    str
        HTML with <p> tags removed but content preserved with line breaks
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # Find all <p> tags and add a line break before unwrapping
    # This preserves visual separation between paragraphs (e.g., bullet points)
    for p in soup.find_all("p"):
        # Append a line break to the paragraph content before unwrapping
        br = soup.new_tag("br")
        p.append(br)
        p.unwrap()

    return str(soup).strip()


def _clean_html_keep_formatting(html_content: str) -> str:
    """
    Clean HTML by removing most tags while preserving formatting tags.

    This removes structural tags like <div>, <span>, etc. but keeps
    formatting tags like <b>, <i>, <a> that are useful in Anki cards.
    Also removes all style attributes to eliminate positioning/layout styles
    while preserving semantic formatting from tags.

    Parameters
    ----------
    html_content : str
        HTML content to clean

    Returns
    -------
    str
        Cleaned HTML with only formatting tags preserved and no style attributes
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

    # Remove all style attributes from remaining tags
    # This eliminates positioning (top, left) and layout (line-height) styles
    # while preserving semantic formatting from tag types (<b>, <i>, etc.)
    for tag in soup.find_all():
        if tag.has_attr("style"):
            del tag["style"]

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


def parse_pdf(
    pdf_path: str,
    format: Literal["basic", "singlecloze", "onecloze", "multicloze"] = "basic",
    include_images: bool = True,
    debug: bool = False,
) -> None:
    """
    Parse Stahl's Prescriber's Guide PDF and convert to Anki flashcards.

    This function is specifically designed for the 8th Edition of Stahl's Essential
    Psychopharmacology: Prescriber's Guide (ISBN: 9781009464772).

    Parameters
    ----------
    pdf_path : str
        Path to the Prescriber's Guide PDF file (8th Edition).
    format : Literal["basic", "singlecloze", "onecloze", "multicloze"], optional
        Card format to use:
        - "basic": Basic Q&A cards with separate question and answer fields (default)
        - "singlecloze": Single cloze deletion wrapping the entire answer in {{c1::}}
        - "onecloze": Each paragraph in the answer becomes {{c1::paragraph}}
        - "multicloze": Each paragraph gets sequential cloze numbers {{c1::}}, {{c2::}}, etc.
    include_images : bool, optional
        Whether to include page images in the source field (default: True).
    debug : bool, optional
        Whether to enter debugger at the end for inspection (default: False).

    Notes
    -----
    This function is designed specifically for the structure of the 8th Edition
    Prescriber's Guide. It extracts:
    - Drug monographs with hierarchical sections (H1 and H2 headers)
    - Content with preserved formatting (bold, italic, links)
    - Source page images for visual reference
    - Hierarchical tags for organization in Anki

    The resulting Anki deck contains approximately 787 cards organized by drug
    name and section.
    """
    # Convert to Path object for better path handling
    pdf_file = Path(pdf_path)

    # Validate that the file exists and is a PDF
    if not pdf_file.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    if pdf_file.suffix.lower() != ".pdf":
        raise ValueError(f"File must be a PDF, got: {pdf_file.suffix}")

    # Validate format parameter
    valid_formats = ["basic", "singlecloze", "onecloze", "multicloze"]
    if format not in valid_formats:
        raise ValueError(f"Invalid format: {format}. Must be one of {valid_formats}")

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

        # Render page as JPEG image for visual reference
        # DPI=75 for compact file size, grayscale to reduce size further
        # JPEG with quality=75 provides good compression while maintaining readability
        pix = page.get_pixmap(colorspace=fitz.csGRAY, dpi=75)

        # Convert to JPEG using PIL for better compression
        img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
        img_bytes_io = io.BytesIO()
        img.save(img_bytes_io, format="JPEG", quality=75, optimize=True)
        img_bytes = img_bytes_io.getvalue()
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
    # Drug chapters are identified by format: number_pp_startpage_endpage_DRUGNAME
    # The page range starts at the item's page and ends at the next section's page
    # Example: '26.0_pp_125_128_BUSPIRONE' -> drug='BUSPIRONE'
    # Example: '90.0_pp_497_502_METHYLPHENIDATE_D' -> drug='METHYLPHENIDATE_D'
    # Pages are from item["page"] to next_item["page"] - 1
    logger.info("Identifying drug pages from table of contents...")
    drug_page = {}
    for idx, item in enumerate(table_of_contents):
        title_text = item["title"]

        # Look for _pp_ pattern to extract drug name
        if "_pp_" in title_text:
            # Split by _pp_ to get the part after
            after_pp = title_text.split("_pp_", 1)[1]
            # after_pp example: "497_502_METHYLPHENIDATE_D"

            # Split by underscore to get page numbers and drug name parts
            parts = after_pp.split("_")
            # parts example: ['497', '502', 'METHYLPHENIDATE', 'D']

            # Skip first two (page numbers) and join the rest as drug name
            if len(parts) >= 3:
                drug_name = "_".join(parts[2:])
                # drug_name example: "METHYLPHENIDATE_D"

                # Verify it's all uppercase (drug names are uppercase in TOC)
                if drug_name and drug_name.replace("_", "").isupper():
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

                    drug_page[drug_name] = pages_content

    logger.info(f"Found {len(drug_page)} drugs to process")

    # Build drug_images dict mapping drug names to their page images
    # Also track page ranges for each drug to display in source field
    # This allows including source pages as images in Anki cards for visual reference
    logger.info("Collecting page images and page ranges for each drug...")
    drug_images: Dict[str, List[bytes]] = {}
    drug_page_ranges: Dict[str, tuple[int, int]] = {}
    for idx, item in enumerate(table_of_contents):
        title_text = item["title"]

        # Look for _pp_ pattern to extract drug name (same logic as above)
        if "_pp_" in title_text:
            after_pp = title_text.split("_pp_", 1)[1]
            parts = after_pp.split("_")

            if len(parts) >= 3:
                drug_name = "_".join(parts[2:])

                if drug_name and drug_name.replace("_", "").isupper():
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

                    drug_images[drug_name] = images_for_drug
                    drug_page_ranges[drug_name] = (start_page, end_page)

    logger.info(f"Collected images and page ranges for {len(drug_images)} drugs")

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

    # Create temporary directory for image files
    # Images are written to disk so genanki can include them in the apkg package
    logger.info("Creating temporary directory for image files...")
    temp_dir = tempfile.mkdtemp()
    media_files = []  # Track all media file paths for genanki

    # Create Anki cards from the parsed drug content
    # Each card has: Drug, Section (H1), Question (H2), Answer (concatenated H2 content), Tags, PageImages
    logger.info("Creating Anki cards from parsed content...")
    cards: List[Dict[str, Any]] = []
    for drug_name, h1_dict in tqdm(drug_content.items(), desc="Creating cards"):
        # Get page range for this drug to display at top of source field
        page_range = drug_page_ranges.get(drug_name, (0, 0))
        page_range_text = f"<div style='font-weight: bold; margin-bottom: 10px;'>Pages: {page_range[0]}-{page_range[1]}</div>"

        # Write images for this drug to temp directory and create img tags
        # All cards for a drug will reference the same set of page images
        # Only include images if include_images is True
        page_images_html = page_range_text  # Always include page range
        if include_images:
            drug_name_for_file = drug_name.lower().replace(" ", "_")
            img_tags = []
            for page_idx, img_bytes in enumerate(drug_images.get(drug_name, [])):
                filename = f"{drug_name_for_file}_page_{page_idx}.jpg"
                filepath = Path(temp_dir) / filename
                filepath.write_bytes(img_bytes)
                media_files.append(str(filepath))
                img_tags.append(f'<img src="{filename}">')

            # Combine page range with img tags, separated by line breaks
            page_images_html = page_range_text + "<br>" + "<br>".join(img_tags)

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

                # Merge consecutive paragraphs that don't start with bullet points
                # Skip this for "Suggested Reading" sections which don't use bullets
                if h2_header.lower() != "suggested reading":
                    combined_html = _merge_bullet_paragraphs(combined_html)

                # Clean HTML to keep only formatting tags (bold, italic, links, etc.)
                # This preserves visual formatting while removing structural bloat
                answer_text = _clean_html_keep_formatting(combined_html)

                # Remove paragraph tags to make content easier to edit in Anki
                # This unwraps <p> tags while preserving their content and formatting
                answer_text = _remove_paragraph_tags(answer_text)

                # Create the card
                # Format drug name and section with title case for readability
                # Add question mark to question if not present
                question = h2_header if h2_header.endswith("?") else f"{h2_header}?"

                card = {
                    "Drug": drug_name.replace("_", " ").title(),
                    "Section": h1_header.title(),
                    "Question": question,
                    "Answer": answer_text,
                    "Tags": [
                        f"Stahl::{drug_name.lower().replace(' ', '_')}::{h1_header.lower().replace(' ', '_')}"
                    ],
                    "PageImages": page_images_html,
                }
                cards.append(card)

    logger.info(f"Created {len(cards)} Anki cards with {len(media_files)} media files")

    # Create genanki model (card template)
    # This defines the structure and layout of the cards
    # Multiple model types: basic Q&A or various cloze deletion formats
    logger.info("Creating Anki deck with genanki...")

    if format != "basic":
        # Cloze model: separate fields for drug, section, question+answer, and source images
        # Model ID varies by format to allow different deck types
        model_ids = {
            "singlecloze": 1607392320,
            "onecloze": 1607392321,
            "multicloze": 1607392322,
        }
        anki_model = genanki.Model(
            model_id=model_ids[format],
            name=f"Stahl Drug {format.title()}",
            fields=[
                {"name": "Drug"},
                {"name": "Section"},
                {"name": "Text"},
                {"name": "Source"},
                {"name": "Tags"},
            ],
            templates=[
                {
                    "name": "Cloze",
                    "qfmt": textwrap.dedent("""
                        <div style="font-size: 20px; margin-bottom: 10px;"><b>{{Drug}}</b></div>
                        <div style="font-size: 16px; margin-bottom: 15px;">{{Section}}</div>
                        <div style="font-size: 14px;">{{cloze:Text}}</div>
                    """),
                    "afmt": textwrap.dedent("""
                        <div style="font-size: 20px; margin-bottom: 10px;"><b>{{Drug}}</b></div>
                        <div style="font-size: 16px; margin-bottom: 15px;">{{Section}}</div>
                        <div style="font-size: 14px;">{{cloze:Text}}</div>
                        <hr>
                        <div style="margin-top: 15px;">
                            <details open>
                                <summary style="cursor: pointer; ">Source Pages</summary>
                                <div style="margin-top: 10px; text-align: center;">{{Source}}</div>
                            </details>
                        </div>
                    """),
                },
            ],
            css=textwrap.dedent("""
                .card {
                    font-family: arial;
                    font-size: 14px;
                    text-align: left;
                    color: black;
                    background-color: white;
                }
                img {
                    max-width: 100%;
                    height: auto;
                    margin: 10px 0;
                    border: 1px solid #ccc;
                }
                .cloze {
                    font-weight: bold;
                    color: blue;
                }
            """),
            model_type=genanki.Model.CLOZE,
        )
    else:
        # Basic Q&A model: separate fields for drug, section, question, answer
        anki_model = genanki.Model(
            model_id=1607392319,  # Random unique ID for this model
            name="Stahl Drug Card",
            fields=[
                {"name": "Drug"},
                {"name": "Section"},
                {"name": "Question"},
                {"name": "Answer"},
                {"name": "Tags"},
                {"name": "PageImages"},
            ],
            templates=[
                {
                    "name": "Card 1",
                    "qfmt": textwrap.dedent("""
                        <div style="font-size: 20px; margin-bottom: 10px;"><b>{{Drug}}</b></div>
                        <div style="font-size: 16px; margin-bottom: 15px;">{{Section}}</div>
                        <div style="font-size: 18px;">{{Question}}</div>
                    """),
                    "afmt": textwrap.dedent("""
                        {{FrontSide}}
                        <hr id="answer">
                        <div style="margin-top: 15px;">{{Answer}}</div>
                        <hr>
                        <div style="margin-top: 15px;">
                            <details open>
                                <summary style="cursor: pointer; ">Source Pages</summary>
                                <div style="margin-top: 10px; text-align: center;">{{PageImages}}</div>
                            </details>
                        </div>
                    """),
                },
            ],
            css=textwrap.dedent("""
                .card {
                    font-family: arial;
                    font-size: 14px;
                    text-align: left;
                    color: black;
                    background-color: white;
                }
                img {
                    max-width: 100%;
                    height: auto;
                    margin: 10px 0;
                    border: 1px solid #ccc;
                }
            """),
        )

    # Create deck and add notes
    anki_deck = genanki.Deck(
        deck_id=2059400110,  # Random unique ID for this deck
        name="Stahl Essential Psychopharmacology",
    )

    logger.info("Adding notes to deck...")
    for card in tqdm(cards, desc="Adding notes"):
        if format == "basic":
            # Basic Q&A cards: separate fields
            note = genanki.Note(
                model=anki_model,
                fields=[
                    card["Drug"],
                    card["Section"],
                    card["Question"],
                    card["Answer"],
                    ", ".join(card["Tags"]),
                    card["PageImages"],
                ],
                tags=card["Tags"],
            )
        else:
            # Cloze cards: format the answer based on cloze type
            answer_html = card["Answer"]
            original = copy.deepcopy(answer_html)

            # cleanup
            answer_html = answer_html.replace("<b><b/>", "")
            answer_html = answer_html.replace("<i><i/>", "")
            answer_html = answer_html.replace("<b/><b>", "")
            answer_html = answer_html.replace("<i/><i>", "")

            if format == "singlecloze":
                # Wrap entire answer in {{c1::}}
                cloze_answer = "{{c1::<br/>" + answer_html + "<br/>}}"
            elif format == "onecloze":
                # Wrap each <p> tag content in {{c1::}}
                soup = BeautifulSoup(answer_html, "html.parser")
                if soup.find_all("p"):
                    for p in soup.find_all("p"):
                        p_content = str(p)[3:-4]  # Remove <p> and </p>
                        p.string = "{{c1::" + p_content + "}}"
                    cloze_answer = str(soup)
                elif "<br/>" in str(soup):
                    cloze_answer = "{{c1::"
                    for br in str(soup).split("<br/>"):
                        cloze_answer += br
                        cloze_answer += "}}<br/>{{c1::"
                    cloze_answer += "}}"
                elif len(str(soup).strip().splitlines()) > 1:
                    cloze_answer = "{{c1::"
                    for br in str(soup).splitlines():
                        cloze_answer += br
                        cloze_answer += "}}<br/>{{c1::"
                    cloze_answer += "}}"
                else:
                    cloze_answer = "{{c1::" + str(soup) + "}}"

            elif format == "multicloze":
                # Wrap each <p> tag content in sequential cloze numbers
                soup = BeautifulSoup(answer_html, "html.parser")
                paragraphs = soup.find_all("p")
                if paragraphs:
                    for idx, p in enumerate(paragraphs, start=1):
                        p_content = str(p)[3:-4]  # Remove <p> and </p>
                        p.string = "{{c" + idx + "::" + p_content + "}}"
                    cloze_answer = str(soup)
                elif "<br/>" in str(soup):
                    cloze_answer = "{{c1::"
                    for ibr, br in enumerate(str(soup).split("<br/>")):
                        cloze_answer += br
                        cloze_answer += "}}<br/>{{c" + str(ibr + 1) + "::"
                    cloze_answer += "}}"
                elif len(str(soup).strip().splitlines()) > 1:
                    cloze_answer = "{{c1::"
                    for ibr, br in enumerate(str(soup).splitlines()):
                        cloze_answer += br
                        cloze_answer += "}}<br/>{{c" + str(ibr + 1) + "::"
                    cloze_answer += "}}"
                else:
                    cloze_answer = "{{c1::" + str(soup) + "}}"
            else:
                raise ValueError(format)

            cloze_answer = cloze_answer.replace("• ", "")
            cloze_answer = cloze_answer.replace("•", "")

            cloze_answer = re.sub(r"{{c\d*::\s*}}", "", cloze_answer).strip()

            # Remove trailing <br> and <br/> tags
            cloze_answer = re.sub(r"(<br\s*/?>)+$", "", cloze_answer)

            assert "{{c" in cloze_answer, (
                f"Answer is missing start of cloze: {cloze_answer}\n{original}"
            )
            assert "}}" in cloze_answer, (
                f"Answer is missing end of cloze: {cloze_answer}\n{original}"
            )

            # Format: Question followed by cloze-wrapped answer
            # Drug and Section are now separate fields
            text_content = (
                f"<div style='font-size: 18px; margin-bottom: 15px;'>{card['Question']}</div>"
                f"<div style='margin-top: 15px;'>{cloze_answer}</div>"
            )

            note = genanki.Note(
                model=anki_model,
                fields=[
                    card["Drug"],
                    card["Section"],
                    text_content,
                    card["PageImages"],
                    ", ".join(card["Tags"]),
                ],
                tags=card["Tags"],
            )
        anki_deck.add_note(note)

    # Create package with media files and write to disk
    logger.info("Writing Anki package to file...")
    anki_package = genanki.Package(anki_deck)
    anki_package.media_files = media_files
    output_file = f"stahl_drugs_v{VERSION}.apkg"
    anki_package.write_to_file(output_file)
    logger.info(f"Anki deck written to {output_file}")

    # Clean up temporary directory
    logger.info("Cleaning up temporary files...")
    shutil.rmtree(temp_dir)
    logger.info("Temporary files cleaned up")

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
    if debug:
        breakpoint()


def main() -> None:
    """
    Entry point for the CLI application.

    Uses argparse to provide CLI interface for parse_pdf function.
    """
    # Create argument parser with module docstring as description
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Add positional argument for PDF path
    parser.add_argument(
        "pdf_path",
        type=str,
        help="Path to the PDF file to parse.",
    )

    # Add format argument with choices
    parser.add_argument(
        "--format",
        type=str,
        default="basic",
        choices=["basic", "singlecloze", "onecloze", "multicloze"],
        help=(
            "Card format to use: "
            "'basic' for Q&A cards (default), "
            "'singlecloze' for single cloze wrapping entire answer, "
            "'onecloze' for each paragraph as c1, "
            "'multicloze' for sequential cloze numbers per paragraph."
        ),
    )

    # Add include_images flag
    parser.add_argument(
        "--include-images",
        dest="include_images",
        action="store_true",
        default=True,
        help="Include page images in the source field (default: True).",
    )

    parser.add_argument(
        "--no-include-images",
        dest="include_images",
        action="store_false",
        help="Do not include page images in the source field.",
    )

    # Add debug flag
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enter debugger at the end for inspection (default: False).",
    )

    # Parse arguments
    args = parser.parse_args()

    # Call parse_pdf with parsed arguments
    parse_pdf(
        pdf_path=args.pdf_path,
        format=args.format,
        include_images=args.include_images,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
