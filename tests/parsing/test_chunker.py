from core.parsing.chunker import _plausible_next, chunk_pages
from core.parsing.pdf import PageText
from tests.parsing.samples import TENDER_PAGES


def _pages(texts: list[str]) -> list[PageText]:
    return [PageText(i, t) for i, t in enumerate(texts, start=1)]


def test_numbered_and_lettered_clauses_with_sections_and_pages() -> None:
    chunks = chunk_pages(_pages(TENDER_PAGES))
    by_no = {c.clause_no: c for c in chunks if c.clause_no}

    assert by_no["1.1"].section == "SECTION 3 - ELIGIBILITY CRITERIA"
    assert "8.30 lakh" in by_no["1.1"].text
    # An amount at the start of a line is not mistaken for clause "10.50".
    assert "10.50" not in by_no
    assert "10.50 lakh is the value" in by_no["1.1"].text
    assert by_no["1.2(a)"].text.startswith("(a) three similar works")
    assert by_no["1.2(c)"].page_start == 1
    # Clause 2 of the eligibility section continues on page 2.
    assert by_no["2"].page_start == 2 and "MSEs" in by_no["2"].text
    assert by_no["3"].text.startswith("3. Earnest money")


def test_page_number_lines_are_dropped() -> None:
    chunks = chunk_pages(_pages(TENDER_PAGES))
    assert not any("Page 2 of 3" in c.text for c in chunks)


def test_preamble_before_first_clause_is_kept() -> None:
    chunks = chunk_pages(_pages(TENDER_PAGES))
    assert any("Tender No. 55/EE(E)" in c.text for c in chunks)


def test_section_without_numbering_after_numbered_text() -> None:
    chunks = chunk_pages(_pages(TENDER_PAGES))
    annex = [c for c in chunks if c.section == "ANNEXURE A"]
    assert annex and "PAN card" in annex[0].text and annex[0].page_start == 3


def test_repeated_headers_are_removed() -> None:
    header = "Delhi Development Authority - Tender Document"
    pages = [f"{header}\n{i}. Clause number {i} text." for i in range(1, 6)]
    chunks = chunk_pages(_pages(pages))
    assert not any(header in c.text for c in chunks)
    assert [c.clause_no for c in chunks] == ["1", "2", "3", "4", "5"]


def test_fallback_paragraphs_without_numbering() -> None:
    text = "\n".join(f"This is sentence {i} of an unnumbered notice." for i in range(200))
    chunks = chunk_pages(_pages([text]), max_chars=1000)
    assert len(chunks) > 1
    assert all(c.clause_no is None for c in chunks)
    assert all(len(c.text) <= 1000 for c in chunks)


def test_long_clause_is_split_and_keeps_number() -> None:
    body = "\n".join("Detailed technical requirement line." for _ in range(300))
    chunks = chunk_pages(_pages([f"1. Scope of work\n{body}\n2. Next clause."]), max_chars=2000)
    ones = [c for c in chunks if c.clause_no == "1"]
    assert len(ones) > 1 and all(len(c.text) <= 2000 for c in ones)
    assert chunks[-1].clause_no == "2"


def test_plausible_next() -> None:
    assert _plausible_next([4, 2], [4, 2, 1], False)  # first child
    assert _plausible_next([4, 2, 3], [4, 3], False)  # back up a level
    assert _plausible_next([4, 2, 3], [5], False)
    assert _plausible_next([1, 1], [1, 2], False)
    assert not _plausible_next([1, 1], [10, 50], False)
    assert not _plausible_next([4, 2], [4, 9], False)  # too big a jump
    assert _plausible_next([7, 3], [1], True)  # restart after a section heading


def test_empty_input() -> None:
    assert chunk_pages([]) == []
