"""
Regression tests for the HTML parsing helpers in stahl_ankifier.

These tests are self-contained: they build small synthetic HTML fragments that
mimic the relevant bits of PyMuPDF's extractHTML() output, so they need neither
the source PDF nor a test framework. Run directly with:

    python tests/test_parsing.py

They are also plain ``test_*`` functions, so ``pytest`` will collect them too.

Written with assistance from Claude Code.
"""

import sys
import tempfile
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup

# Allow running both as "python tests/test_parsing.py" and via pytest.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stahl_ankifier import (  # noqa: E402
    VERSION,
    _clean_page_headers,
    _output_filename,
    _reorder_reading_order,
    _write_deck,
    parse_drug_pages,
)


def _texts(soup):
    """Return the stripped text of each <p>, in document order."""
    return [p.get_text(strip=True) for p in soup.find_all("p")]


def test_clean_page_headers_removes_suffixed_drug_title():
    """A page title with a suffix (e.g. "AMPHETAMINE (D)") must be removed even
    though the TOC-derived drug_name is "AMPHETAMINE_D"."""
    html = (
        '<div style="width:391.2pt">'
        '<p><span>39</span></p>'  # page number
        '<p><span>AMPHETAMINE (D)</span></p>'  # running title, suffixed
        '<p><span>THERAPEUTICS</span></p>'  # real content / first header
        "</div>"
    )
    cleaned = _clean_page_headers(BeautifulSoup(html, "html.parser"), "AMPHETAMINE_D")
    remaining = _texts(cleaned)
    assert "AMPHETAMINE (D)" not in remaining, remaining
    assert "39" not in remaining, remaining
    assert "THERAPEUTICS" in remaining, remaining


def test_reorder_reading_order_fixes_scrambled_columns():
    """PyMuPDF may emit the right column (and a banner) before the left column;
    reorder must restore left-column-then-right-column reading order."""
    # Natural (scrambled) order: right-column H2 first, then left-column content,
    # then the left-column white H1 banner last (as seen for AMPHETAMINE).
    html = (
        '<div style="width:391.2pt">'
        '<p style="top:57.1pt;left:211.5pt"><span>If It Works</span></p>'
        '<p style="top:67.4pt;left:42.3pt"><span>Brands</span></p>'
        '<p style="top:53.5pt;left:87.4pt">'
        '<span style="color:#ffffff">THERAPEUTICS</span></p>'
        "</div>"
    )
    ordered = _reorder_reading_order(BeautifulSoup(html, "html.parser"))
    # Left column (THERAPEUTICS top 53, Brands top 67) before right column.
    assert _texts(ordered) == ["THERAPEUTICS", "Brands", "If It Works"], _texts(ordered)


def test_parse_drug_pages_content_under_h1_without_h2():
    """Content directly under an H1 banner with no H2 (e.g. depot property
    tables) must be attached to a synthetic H2 keyed by the H1 name."""
    html = (
        '<div>'
        '<p><span style="color:#ffffff">HALOPERIDOL DECANOATE</span></p>'
        '<p><span style="font-size:7.0pt">Haloperidol Decanoate Properties</span></p>'
        "</div>"
    )
    result = parse_drug_pages(BeautifulSoup(html, "html.parser"))
    assert list(result.keys()) == ["HALOPERIDOL DECANOATE"], result
    h2_dict = result["HALOPERIDOL DECANOATE"]
    assert list(h2_dict.keys()) == ["HALOPERIDOL DECANOATE"], h2_dict
    assert len(h2_dict["HALOPERIDOL DECANOATE"]) == 1, h2_dict


def test_parse_drug_pages_crashes_on_content_before_any_h1():
    """Content appearing before any H1 is a genuine parsing gap and must still
    raise, rather than being silently dropped or absorbed."""
    html = (
        '<div>'
        '<p><span style="font-size:8.5pt">orphan content before any header</span></p>'
        "</div>"
    )
    try:
        parse_drug_pages(BeautifulSoup(html, "html.parser"))
    except ValueError as exc:
        assert "no active H1" in str(exc), str(exc)
    else:
        raise AssertionError("expected ValueError for content before any H1")


def test_normal_two_column_order_is_preserved():
    """A page already in left-then-right order must be unchanged by reorder."""
    html = (
        '<div style="width:391.2pt">'
        '<p style="top:53.5pt;left:87.0pt">'
        '<span style="color:#ffffff">THERAPEUTICS</span></p>'
        '<p style="top:72.6pt;left:42.8pt"><span>Brands</span></p>'
        '<p style="top:58.1pt;left:243.9pt"><span>Best Augmenting</span></p>'
        "</div>"
    )
    ordered = _reorder_reading_order(BeautifulSoup(html, "html.parser"))
    assert _texts(ordered) == ["THERAPEUTICS", "Brands", "Best Augmenting"], _texts(ordered)


def test_output_filename_per_format():
    """basic keeps the bare name; cloze formats get a per-format suffix."""
    assert _output_filename("basic") == f"stahl_drugs_v{VERSION}.apkg"
    assert _output_filename("singlecloze") == f"stahl_drugs_v{VERSION}_singlecloze.apkg"
    assert _output_filename("onecloze") == f"stahl_drugs_v{VERSION}_onecloze.apkg"
    assert _output_filename("multicloze") == f"stahl_drugs_v{VERSION}_multicloze.apkg"


def test_write_deck_builds_valid_apkg_for_each_format():
    """_write_deck must produce a valid .apkg (a zip) for every card format,
    so a single parse can emit all formats."""
    cards = [
        {
            "Drug": "Aspirin",
            "Section": "Therapeutics",
            "Question": "Brands?",
            "Answer": "<p>First point</p><p>Second point</p>",
            "Tags": ["Stahl::aspirin::therapeutics"],
            "PageImages": "<div class='page-range'>Pages: 1-2</div>",
        }
    ]
    tmp = Path(tempfile.mkdtemp())
    try:
        for fmt in ("basic", "singlecloze", "onecloze", "multicloze"):
            out = tmp / f"deck_{fmt}.apkg"
            _write_deck(cards, [], fmt, str(out))
            assert out.exists(), f"{fmt}: no file written"
            assert zipfile.is_zipfile(out), f"{fmt}: not a valid apkg/zip"
    finally:
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
