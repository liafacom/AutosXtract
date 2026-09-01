"""Markers for unread passages, and why they do not count as content.

A vision model, when it cannot read a passage, is authorised by the prompt to
emit ``[ILLEGIBLE]``, ``[SIGNATURE]``, ``[STAMP]``. Those are legitimate in
small proportion — a signature in the middle of a certificate.

On a wholly illegible page the model **loops**: it repeats the marker until the
token budget runs out. Measured on a real archive, one document returned 6,281
characters of which 41 were real content, in 319 s — and the text was persisted
as if it were the document, inflating the "useful words" count and contaminating
everything downstream with noise that is not in the file.

Counting the raw text makes that loop look like the richest document in the
archive. So every measure of "how much content did this layer recover?" goes
through here.

WHICH markers count is data (``markers.unread``): the model is told in the
corpus language what to write when it cannot read, so the words it writes change
with the prompt, while the loop this module detects does not.
"""

from __future__ import annotations

from autosxtract import patterns

# Above this fraction of markers the text is a degenerate loop, not a
# transcription. The floor is high on purpose: markers are legitimate in
# smaller proportion.
MAX_MARKER_FRACTION = 0.80


def real_content(text: str) -> str:
    """The text without the unread-passage markers."""
    catalogue = patterns.default()
    without_markers = catalogue.regex("markers.unread").sub(" ", text or "")
    return catalogue.regex("markers.whitespace").sub(" ", without_markers).strip()


def marker_fraction(text: str) -> float:
    """Fraction of the text that is unread-passage marker, between 0 and 1."""
    raw = (text or "").strip()
    if not raw:
        return 0.0
    return 1.0 - len(real_content(raw)) / len(raw)


def is_degenerate_loop(text: str, threshold: float = MAX_MARKER_FRACTION) -> bool:
    """Did the model loop, repeating markers until the budget ran out?"""
    return marker_fraction(text) >= threshold
