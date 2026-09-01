"""Deterministic paper text extraction and claim-candidate discovery.

The core of this module intentionally depends only on the Python standard
library.  PDF support is an optional boundary: :func:`extract_pdf_pages`
imports PyMuPDF only when it is called.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib
import json
import math
from pathlib import Path
import re
from typing import Iterable, Mapping, Sequence


class PaperExtractionError(RuntimeError):
    """Raised when a paper cannot be converted into page text."""


class PDFDependencyError(PaperExtractionError):
    """Raised when PDF extraction is requested without PyMuPDF installed."""


@dataclass(frozen=True, slots=True)
class PageText:
    """Text extracted from one one-indexed paper page."""

    page_number: int
    text: str


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    """A source-compatible evidence record for a proposed claim value.

    These fields deliberately mirror the project's strict ``EvidenceSpec``
    schema so a draft can be promoted without renaming or discarding fields.
    """

    field: str
    quote: str
    page: int | None = None
    table: str | None = None
    cell: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ClaimDraft:
    """Unconfirmed values found near a user-supplied experiment hint."""

    hint: str
    candidate_values: tuple[float, ...]
    evidence: tuple[ClaimEvidence, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    """Internal ranked number paired with the exact evidence that produced it."""

    value: float
    raw: str
    evidence: ClaimEvidence
    score: float
    order: int


_NUMBER_RE = re.compile(
    r"(?<![\w.])"
    r"[-+]?"
    r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d*\.\d+|\d+)"
    r"(?:[eE][-+]?\d+)?"
    r"\s*%?"
    r"(?![\w.])"
)
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_TABLE_RE = re.compile(r"\b(?:table|tab\.)\s*([A-Za-z]?\d+[A-Za-z]?)\b", re.IGNORECASE)


def pages_from_text(text: str, *, page_separator: str = "\f") -> list[PageText]:
    """Split plain text into one-indexed pages.

    Form feed is the conventional page separator used by PDF-to-text tools.
    A string without form feeds becomes a single page, including an empty
    string.  This helper keeps tests and text-only workflows dependency-free.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not page_separator:
        raise ValueError("page_separator must not be empty")
    return [PageText(index, page) for index, page in enumerate(text.split(page_separator), 1)]


def extract_pdf_pages(path: str | Path) -> list[PageText]:
    """Extract page text from *path* using the optional PyMuPDF dependency.

    Install the project with ``pip install 'reproagent-lite[pdf]'`` when this
    feature is needed. Importing :mod:`reproagent_lite.paper` never requires
    PyMuPDF.
    """

    pdf_path = Path(path)
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Paper PDF does not exist: {pdf_path}")

    try:
        pymupdf = importlib.import_module("pymupdf")
    except ModuleNotFoundError as exc:
        if exc.name not in {"pymupdf", None}:
            raise
        raise PDFDependencyError(
            "PDF extraction requires the optional PyMuPDF dependency. "
            "Install it with: pip install 'reproagent-lite[pdf]'"
        ) from exc

    document = None
    try:
        document = pymupdf.open(str(pdf_path))
        if getattr(document, "needs_pass", False):
            raise PaperExtractionError(f"Paper PDF is encrypted: {pdf_path}")

        pages: list[PageText] = []
        for index, page in enumerate(document):
            page_text = page.get_text("text") or ""
            pages.append(PageText(page_number=index + 1, text=str(page_text)))
        return pages
    except PaperExtractionError:
        raise
    except Exception as exc:  # PyMuPDF exposes several version-specific errors.
        raise PaperExtractionError(f"Could not extract text from PDF {pdf_path}: {exc}") from exc
    finally:
        if document is not None:
            close = getattr(document, "close", None)
            if callable(close):
                close()


def find_claim_candidates(
    pages: Iterable[PageText | Mapping[str, object]],
    target_hint: str,
    *,
    context_chars: int = 280,
    max_candidates: int = 10,
) -> ClaimDraft:
    """Find numeric results close to *target_hint* and retain page evidence.

    The function is deliberately conservative: it only proposes numbers from
    pages where the hint's terms occur close together.  It does not guess a
    metric, silently normalize percentages, or declare any value correct.
    Candidates are ranked using transparent lexical heuristics; confirmation
    remains a human or optional model-assisted step.
    """

    hint = " ".join(str(target_hint).split())
    if not hint:
        raise ValueError("target_hint must not be empty")
    if context_chars < 40:
        raise ValueError("context_chars must be at least 40")
    if max_candidates < 1:
        raise ValueError("max_candidates must be positive")

    normalized_pages = [_coerce_page(page) for page in pages]
    tokens = _unique_tokens(hint)
    if not tokens:
        raise ValueError("target_hint must contain at least one letter or digit")

    proposed: list[_Candidate] = []
    fallback_evidence: list[ClaimEvidence] = []
    order = 0

    for page in normalized_pages:
        for region_start, region_end, coverage in _hint_regions(page.text, tokens):
            window_start = max(0, region_start - context_chars)
            window_end = min(len(page.text), region_end + context_chars)
            window = page.text[window_start:window_end]
            table = _nearest_table_label(page.text, region_start)

            fallback_evidence.append(
                ClaimEvidence(
                    field="target_hint",
                    quote=_clean_quote(window),
                    page=page.page_number,
                    table=table,
                    cell=None,
                    confidence=round(min(1.0, 0.55 + 0.4 * coverage), 3),
                )
            )

            for match in _NUMBER_RE.finditer(window):
                raw = match.group(0).strip()
                value = _parse_number(raw)
                if value is None or not math.isfinite(value):
                    continue

                absolute_start = window_start + match.start()
                absolute_end = window_start + match.end()
                distance = _distance_to_region(
                    absolute_start,
                    absolute_end,
                    region_start,
                    region_end,
                )
                score = _candidate_score(
                    raw=raw,
                    value=value,
                    page_text=page.text,
                    start=absolute_start,
                    end=absolute_end,
                    distance=distance,
                    context_chars=context_chars,
                    coverage=coverage,
                )
                quote_start = max(0, absolute_start - 150)
                quote_end = min(len(page.text), absolute_end + 150)
                confidence = round(max(0.05, min(0.99, score)), 3)
                evidence = ClaimEvidence(
                    field="reported_value",
                    quote=_clean_quote(page.text[quote_start:quote_end]),
                    page=page.page_number,
                    table=table,
                    cell=None,
                    confidence=confidence,
                )
                proposed.append(
                    _Candidate(
                        value=value,
                        raw=raw,
                        evidence=evidence,
                        score=score,
                        order=order,
                    )
                )
                order += 1

    ranked = sorted(proposed, key=lambda candidate: (-candidate.score, candidate.order))
    selected: list[_Candidate] = []
    seen: set[tuple[float, bool]] = set()
    for candidate in ranked:
        # Preserve the literal scale: 91.3% remains 91.3, with the percent sign
        # included in its quote.  Treat percent/non-percent spellings separately.
        key = (candidate.value, candidate.raw.rstrip().endswith("%"))
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= max_candidates:
            break

    if selected:
        return ClaimDraft(
            hint=hint,
            candidate_values=tuple(candidate.value for candidate in selected),
            evidence=tuple(candidate.evidence for candidate in selected),
        )

    # A matching passage with no number is still useful evidence: it tells the
    # caller where manual inspection should begin without inventing a value.
    return ClaimDraft(
        hint=hint,
        candidate_values=(),
        evidence=tuple(_dedupe_evidence(fallback_evidence)[:max_candidates]),
    )


def write_claim_draft(draft: ClaimDraft, path: str | Path) -> Path:
    """Write a claim draft as stable, UTF-8 JSON and return its path."""

    if not isinstance(draft, ClaimDraft):
        raise TypeError("draft must be a ClaimDraft")
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(draft)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _coerce_page(page: PageText | Mapping[str, object]) -> PageText:
    """Normalize the two supported page input forms."""

    if isinstance(page, PageText):
        return page
    if isinstance(page, Mapping):
        page_number = page.get("page_number", page.get("page"))
        text = page.get("text")
        if isinstance(page_number, int) and isinstance(text, str):
            return PageText(page_number=page_number, text=text)
    raise TypeError("pages must contain PageText objects or page/text mappings")


def _unique_tokens(hint: str) -> list[str]:
    """Return case-folded hint terms in first-seen order without duplicates."""

    tokens: list[str] = []
    seen: set[str] = set()
    for match in _TOKEN_RE.finditer(hint.casefold()):
        token = match.group(0)
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def _hint_regions(text: str, tokens: Sequence[str]) -> list[tuple[int, int, float]]:
    """Find compact passages containing enough of the requested hint terms."""

    lowered = text.casefold()
    occurrences: dict[str, list[tuple[int, int]]] = {
        token: [(match.start(), match.end()) for match in re.finditer(re.escape(token), lowered)]
        for token in tokens
    }
    if not any(occurrences.values()):
        return []

    regions: list[tuple[int, int, float]] = []
    anchors = [item for values in occurrences.values() for item in values]
    radius = max(120, min(500, 70 * len(tokens)))
    for anchor_start, anchor_end in anchors:
        nearby: list[tuple[int, int]] = []
        matched = 0
        for token in tokens:
            token_hits = occurrences[token]
            if not token_hits:
                continue
            closest = min(
                token_hits,
                key=lambda hit: _distance_to_region(hit[0], hit[1], anchor_start, anchor_end),
            )
            if _distance_to_region(closest[0], closest[1], anchor_start, anchor_end) <= radius:
                nearby.append(closest)
                matched += 1
        coverage = matched / len(tokens)
        minimum_coverage = 1.0 if len(tokens) <= 2 else 0.67
        if coverage < minimum_coverage:
            continue
        start = min(hit[0] for hit in nearby)
        end = max(hit[1] for hit in nearby)
        if end - start <= radius * 2:
            regions.append((start, end, coverage))

    # Multiple token anchors usually describe the same local passage.
    regions.sort(key=lambda region: (region[0], region[1]))
    merged: list[tuple[int, int, float]] = []
    for region in regions:
        if merged and region[0] <= merged[-1][1] + 20:
            previous = merged[-1]
            merged[-1] = (
                min(previous[0], region[0]),
                max(previous[1], region[1]),
                max(previous[2], region[2]),
            )
        else:
            merged.append(region)
    return merged


def _parse_number(raw: str) -> float | None:
    """Parse a displayed number without silently converting percentage scale."""

    normalized = raw.strip().rstrip("%").strip().replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def _distance_to_region(start: int, end: int, region_start: int, region_end: int) -> int:
    """Measure the character gap between a number and its matched hint region."""

    if end < region_start:
        return region_start - end
    if start > region_end:
        return start - region_end
    return 0


def _candidate_score(
    *,
    raw: str,
    value: float,
    page_text: str,
    start: int,
    end: int,
    distance: int,
    context_chars: int,
    coverage: float,
) -> float:
    """Rank a candidate using explicit, reviewable lexical heuristics."""

    proximity = max(0.0, 1.0 - distance / max(context_chars, 1))
    score = 0.30 + 0.30 * coverage + 0.28 * proximity
    stripped = raw.strip()
    if "." in stripped or "e" in stripped.casefold():
        score += 0.08
    if stripped.endswith("%"):
        score += 0.08
    if 0.0 <= value <= 1.0:
        score += 0.05

    before = page_text[max(0, start - 16):start]
    after = page_text[end:min(len(page_text), end + 16)]
    if re.search(r"(?:±|\+/-)\s*$", before):
        score -= 0.22  # likely an uncertainty, not the central result
    if re.match(r"\s*(?:±|\+/-)", after):
        score += 0.10
    if re.search(r"(?:table|tab\.|figure|fig\.|page)\s*$", before, re.IGNORECASE):
        score -= 0.32
    if value.is_integer() and 1900 <= value <= 2100:
        score -= 0.55
    elif value.is_integer() and abs(value) < 20 and not stripped.endswith("%"):
        score -= 0.10
    return score


def _nearest_table_label(text: str, position: int) -> str | None:
    """Return the closest nearby table label when one is visible in text."""

    start = max(0, position - 500)
    matches = list(_TABLE_RE.finditer(text, start, min(len(text), position + 80)))
    if not matches:
        return None
    nearest = min(matches, key=lambda match: abs(match.start() - position))
    return f"Table {nearest.group(1)}"


def _clean_quote(text: str) -> str:
    """Collapse layout whitespace while retaining the quoted words and number."""

    return " ".join(text.split()).strip()


def _dedupe_evidence(evidence: Sequence[ClaimEvidence]) -> list[ClaimEvidence]:
    """Remove repeated page/quote pairs while preserving discovery order."""

    output: list[ClaimEvidence] = []
    seen: set[tuple[int | None, str]] = set()
    for item in evidence:
        key = (item.page, item.quote)
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


__all__ = [
    "ClaimDraft",
    "ClaimEvidence",
    "PDFDependencyError",
    "PageText",
    "PaperExtractionError",
    "extract_pdf_pages",
    "find_claim_candidates",
    "pages_from_text",
    "write_claim_draft",
]
