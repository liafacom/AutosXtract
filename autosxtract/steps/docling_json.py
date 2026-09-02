"""Recovering Docling's orphaned text, and its reading order.

This exists because of a measured defect in ``docling-serve``: on a scanned
document ``md_content`` comes back empty — or holding only ``<!-- image -->`` —
while the structured document (``json_content``) carries the complete OCR text.
Without this reassembly those documents end up with zero characters while the
text sits right there, in the same payload.

The reassembly **only kicks in when the markdown has no real content**. A
document that already comes out correct does not change: that is the criterion
stopping recovery from becoming a silent reprocessing of everything.

Reading order matters and is not the array's order. Two rules, both from real
cases:

- **Frame goes last.** Repeated headers and footers, interleaved in the body,
  chop the sentence.
- **A 90-degree-rotated box goes last.** A case-file side stamp and a notary
  label are narrow and tall; interleaving them scrambles the reading — the same
  defect PyMuPDF's ``sort=True`` produces.

Pure module: dictionaries only, no network.
"""

from __future__ import annotations

import re
from typing import Any

_IMAGE_MARKER = re.compile(r"<!--\s*image\s*-->", re.IGNORECASE)

# Below this the markdown has no real content. Scanned documents come back with
# a handful of image markers and nothing else, and still hold the full text in
# the structured document.
EMPTY_MARKDOWN_THRESHOLD = 40

# Labels Docling uses for the page frame.
_FRAME = frozenset({"page_header", "page_footer"})
# A box far taller than it is wide is 90-degree-rotated text.
_SIDEWAYS_RATIO = 3.0
_SIDEWAYS_WIDTH = 40.0


def strip_image_markers(md: str) -> str:
    """Remove the ``<!-- image -->`` markers and collapse the blank lines left."""
    if not md:
        return ""
    return re.sub(r"\n{3,}", "\n\n", _IMAGE_MARKER.sub("", md))


def markdown_is_empty(md: str, threshold: int = EMPTY_MARKDOWN_THRESHOLD) -> bool:
    """Does the markdown hold no real content, discounting the markers?"""
    return len(strip_image_markers(md).strip()) < threshold


def _first_prov(item: dict[str, Any]) -> dict[str, Any] | None:
    prov = item.get("prov")
    if isinstance(prov, list) and prov:
        return prov[0] if isinstance(prov[0], dict) else None
    return None


def _is_sideways(bbox: dict[str, Any] | None) -> bool:
    """A 90-degree-rotated box: narrow and tall."""
    if not bbox:
        return False
    try:
        width = abs(float(bbox["r"]) - float(bbox["l"]))
        height = abs(float(bbox["t"]) - float(bbox["b"]))
    except (KeyError, TypeError, ValueError):
        return False
    if width <= 0:
        return False
    return width < _SIDEWAYS_WIDTH and height > width * _SIDEWAYS_RATIO


def _reading_key(index: int, item: dict[str, Any]) -> tuple:
    """Page, body before frame, top to bottom, left to right.

    Docling's ``coord_origin`` is ``BOTTOMLEFT``, so a **larger** ``t`` is
    higher on the page — hence the negative sign.
    """
    prov = _first_prov(item)
    if not prov:
        # With no position there is no way to order: keep the input order, last.
        return (10**6, 2, 0.0, 0.0, index)

    bbox = prov.get("bbox") or {}
    after = 1 if (item.get("label") in _FRAME or _is_sideways(bbox)) else 0
    # ``page_no`` is the PRIMARY sort key and it came off the wire unguarded
    # while ``t``/``l`` were defended — so one item with a string page number
    # made ``sorted`` raise ``TypeError`` comparing str with int. ``DoclingStep``
    # caught it and reported the whole conversion as failed, which is the worst
    # place to lose it: this module exists BECAUSE the markdown came back empty
    # and the structured document is the only copy of the text.
    try:
        page = int(prov.get("page_no") or 0)
    except (TypeError, ValueError):
        page = 0
    try:
        top = -float(bbox.get("t", 0.0))
        left = float(bbox.get("l", 0.0))
    except (TypeError, ValueError):
        top, left = 0.0, 0.0
    return (page, after, top, left, index)


def _ordered_items(json_content: dict[str, Any] | None) -> list[tuple[int, dict]]:
    if not isinstance(json_content, dict):
        return []
    items = json_content.get("texts")
    if not isinstance(items, list):
        return []
    valid = [
        (i, it)
        for i, it in enumerate(items)
        if isinstance(it, dict) and (it.get("text") or "").strip()
    ]
    valid.sort(key=lambda pair: _reading_key(pair[0], pair[1]))
    return valid


def text_from_json(json_content: dict[str, Any] | None) -> str:
    """Reassemble the orphaned items' text, in reading order.

    An empty string when there is nothing usable — never ``None``, so the
    caller can compare lengths without an extra check.
    """
    return "\n".join(item["text"].strip() for _, item in _ordered_items(json_content))


def text_by_page(json_content: dict[str, Any] | None) -> dict[int, str]:
    """The reconstructed text, grouped by page (``page_no``, 1-based).

    It serves per-page routing: when only part of the document is scanned, the
    step runs on a subdocument and the result has to return to each page's
    original position. Without it the reassembly would be a concatenation, which
    scrambles the order in a PDF where native and scanned pages alternate — and
    a wrong order is worse than a wasted OCR.
    """
    by_page: dict[int, list[str]] = {}
    for _, item in _ordered_items(json_content):
        prov = _first_prov(item) or {}
        # Same guard as ``_reading_key``: a page number the server typed as a
        # string must not cost the whole reassembly (see the note there).
        try:
            page = int(prov.get("page_no") or 1)
        except (TypeError, ValueError):
            page = 1
        by_page.setdefault(page, []).append(item["text"].strip())
    return {p: "\n".join(lines) for p, lines in by_page.items()}


def final_text(md: str, json_content: dict[str, Any] | None) -> tuple[str, bool]:
    """``(text, recovered)`` — choose between the markdown and the reassembly.

    The reassembly only kicks in when the markdown has no real content. A
    document that already comes out correct **does not change**.
    """
    if not markdown_is_empty(md):
        return md, False
    recovered = text_from_json(json_content)
    if not recovered:
        return md, False
    return recovered, True
