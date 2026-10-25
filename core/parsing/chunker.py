"""Split tender text into clauses that citations can point to.

Strategy (CLAUDE.md, "Clause chunking"):
1. Drop page-number lines and headers/footers repeated on most pages.
2. Start a new clause at numbered headings (1., 1.1, 4.2.1, 3)) and lettered sub-clauses
   ((a), (ii), b)). A number only counts as a heading if it plausibly follows the previous
   one (next sibling, first child, or a restart after a new section), which filters out
   amounts and dates such as "10.50 lakh" at the start of a line.
3. Section headings (SECTION / CHAPTER / ANNEXURE ..., or short ALL-CAPS lines) set the
   `section` of the clauses that follow.
4. With no numbering at all, fall back to paragraph-sized chunks. Over-long clauses are split
   at line boundaries; the parts keep the same clause number.
Fixed-size token windows are never the primary strategy.
"""

import re
from collections import Counter
from dataclasses import dataclass

from core.parsing.pdf import PageText

MAX_CHARS = 4000  # ~1000 tokens
MAX_HEADING_TOP_LEVEL = 40  # "47. something" at the very start is more likely a quantity

_NUMBERED = re.compile(r"^(?P<no>\d{1,2}(?:\.\d{1,3}){1,4}|\d{1,2}[.)])\s+(?P<rest>\S.*)$")
_LETTERED = re.compile(r"^(?:\((?P<a>[a-z]|[ivx]{1,5})\)|(?P<b>[a-z])\))\s+(?P<rest>\S.*)$")
_SECTION_WORD = re.compile(
    r"^(SECTION|CHAPTER|PART|ANNEXURE|ANNEX|APPENDIX|SCHEDULE|FORM)\b[\s\-–:]*\S*", re.I
)
_PAGE_NO = re.compile(r"^(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?$", re.I)


@dataclass(frozen=True)
class Chunk:
    clause_no: str | None
    section: str | None
    page_start: int
    page_end: int
    text: str


@dataclass
class _Line:
    page: int
    text: str


def _parts(no: str) -> list[int]:
    return [int(p) for p in no.rstrip(".)").split(".")]


def _plausible_next(prev: list[int] | None, new: list[int], after_section: bool) -> bool:
    if prev is None or after_section:
        return new[0] <= MAX_HEADING_TOP_LEVEL and all(n <= 1 for n in new[1:])
    # first child: 4.2 -> 4.2.1
    if new == [*prev, 1]:
        return True
    # next sibling at some level (allow small gaps from missed lines): 4.2.3 -> 4.3 / 5
    for depth in range(len(prev)):
        if new[:depth] == prev[:depth] and len(new) == depth + 1:
            if prev[depth] < new[depth] <= prev[depth] + 3:
                return True
        # sibling with a first child: 4.2 -> 4.3.1
        if new[:depth] == prev[:depth] and len(new) == depth + 2:
            if prev[depth] < new[depth] <= prev[depth] + 3 and new[depth + 1] == 1:
                return True
    return False


def _is_section_heading(line: str) -> bool:
    if len(line) > 90 or line.startswith("|"):
        return False
    if _SECTION_WORD.match(line):
        return True
    letters = [c for c in line if c.isalpha()]
    words = line.split()
    return (
        len(letters) >= 6
        and all(c.isupper() for c in letters)
        and 1 <= len(words) <= 10
        and not line.endswith((",", ";"))
    )


def _clean_lines(pages: list[PageText]) -> list[_Line]:
    per_page = [
        (p.page_no, [ln.strip() for ln in p.text.splitlines() if ln.strip()]) for p in pages
    ]
    repeated: set[str] = set()
    if len(pages) >= 4:
        counts = Counter(ln for _, lines in per_page for ln in set(lines))
        repeated = {ln for ln, c in counts.items() if c >= 0.6 * len(pages) and len(ln) < 120}
    return [
        _Line(page, ln)
        for page, lines in per_page
        for ln in lines
        if ln not in repeated and not _PAGE_NO.match(ln)
    ]


def _split_long(chunk: Chunk, lines: list[_Line], max_chars: int) -> list[Chunk]:
    if len(chunk.text) <= max_chars:
        return [chunk]
    out: list[Chunk] = []
    buf: list[_Line] = []
    size = 0
    for ln in lines:
        if buf and size + len(ln.text) > max_chars:
            out.append(_make(chunk.clause_no, chunk.section, buf))
            buf, size = [], 0
        # A single enormous line (e.g. a giant table row) is hard-split.
        while len(ln.text) > max_chars:
            out.append(_make(chunk.clause_no, chunk.section, [_Line(ln.page, ln.text[:max_chars])]))
            ln = _Line(ln.page, ln.text[max_chars:])
        buf.append(ln)
        size += len(ln.text) + 1
    if buf:
        out.append(_make(chunk.clause_no, chunk.section, buf))
    return out


def _make(clause_no: str | None, section: str | None, lines: list[_Line]) -> Chunk:
    return Chunk(
        clause_no=clause_no,
        section=section,
        page_start=lines[0].page,
        page_end=lines[-1].page,
        text="\n".join(ln.text for ln in lines),
    )


def _paragraph_chunks(lines: list[_Line], max_chars: int) -> list[Chunk]:
    """Fallback for documents without clause numbering."""
    chunks: list[Chunk] = []
    section: str | None = None
    buf: list[_Line] = []
    size = 0
    for ln in lines:
        if _is_section_heading(ln.text):
            if buf:
                chunks.append(_make(None, section, buf))
                buf, size = [], 0
            section = ln.text
            continue
        ends_sentence = ln.text.endswith((".", ":", ";"))
        buf.append(ln)
        size += len(ln.text) + 1
        if size >= max_chars // 2 and ends_sentence:
            chunks.append(_make(None, section, buf))
            buf, size = [], 0
    if buf:
        chunks.append(_make(None, section, buf))
    out: list[Chunk] = []
    for c in chunks:
        out.extend(_split_long(c, [_Line(c.page_start, t) for t in c.text.splitlines()], max_chars))
    return out


def chunk_pages(pages: list[PageText], max_chars: int = MAX_CHARS) -> list[Chunk]:
    lines = _clean_lines(pages)
    if not lines:
        return []

    groups: list[tuple[str | None, str | None, list[_Line]]] = []
    section: str | None = None
    prev_no: list[int] | None = None
    parent_no: str | None = None
    after_section = False
    current: tuple[str | None, str | None, list[_Line]] = (None, None, [])
    found_numbering = False

    def flush() -> None:
        if current[2]:
            groups.append(current)

    for ln in lines:
        numbered = _NUMBERED.match(ln.text)
        if numbered:
            parts = _parts(numbered["no"])
            if _plausible_next(prev_no, parts, after_section):
                flush()
                found_numbering = True
                prev_no, after_section = parts, False
                parent_no = ".".join(str(p) for p in parts)
                rest = numbered["rest"].strip()
                # "4. ELIGIBILITY CRITERIA": a numbered heading also names the section.
                if _is_section_heading(rest):
                    section = rest
                current = (parent_no, section, [ln])
                continue
        lettered = _LETTERED.match(ln.text)
        if lettered and (parent_no is not None or found_numbering):
            flush()
            letter = lettered["a"] or lettered["b"]
            current = (f"{parent_no}({letter})" if parent_no else f"({letter})", section, [ln])
            continue
        if _is_section_heading(ln.text) and not numbered:
            flush()
            section, after_section = ln.text, True
            parent_no = None
            current = (None, section, [])
            continue
        current[2].append(ln)
    flush()

    if not found_numbering:
        return _paragraph_chunks(lines, max_chars)

    chunks: list[Chunk] = []
    for clause_no, sec, group_lines in groups:
        # Drop heading-only clauses ("4. ELIGIBILITY CRITERIA" followed directly by 4.1);
        # the heading survives as the section of the clauses below it.
        if (
            len(group_lines) == 1
            and clause_no
            and sec == _NUMBERED.sub(r"\g<rest>", group_lines[0].text)
        ):
            continue
        chunk = _make(clause_no, sec, group_lines)
        chunks.extend(_split_long(chunk, group_lines, max_chars))
    return chunks
