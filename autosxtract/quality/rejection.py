"""When NOT to accept an expensive step's text, even though it ran.

The naive rule is ``len(new) > len(previous)``, and length gets both of the
costliest cases wrong:

- **Coverage.** A document transcribed up to page 10 of 15 is still longer than
  a bad extraction of all 15, and it silently replaced it. That is how a power
  of attorney lost three notarial acts.
- **Fidelity.** The expensive step rewrites with better layout and corrupts
  digits the previous step had read correctly. Length and text score are blind
  to that: ``9XXYZ3ZE...`` scores exactly like ``9XXYZ32E...``.

The gate is only valid while the previous text is a **trustworthy reference**.
When it is degenerate — the previous step collapsed and read almost nothing —
there is nothing to check against, and partial text beats nothing. That
exemption is what stops the gate from becoming a no-op against itself.

Pure module: it takes the two texts and the coverage figures, and returns the
refusal reason or ``None`` to accept.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autosxtract.quality.anchors import lost
from autosxtract.quality.markers import (
    MAX_MARKER_FRACTION,
    marker_fraction,
    real_content,
)
from autosxtract.quality.stamp import useful_words

# How many times denser the new text must be for "partial" to stop being a
# defect and become the best available reading. Measured on the 15-page power
# of attorney: 52 chars/page against 3,422 — a 66x difference, and in that
# regime the partial one is unambiguously better.
PARTIAL_DENSITY_FACTOR = 10.0


@dataclass(frozen=True)
class Rejection:
    """The verdict on the expensive step's text, with any warnings."""

    reason: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.reason is None


def assess_replacement(
    new_text: str,
    previous_text: str,
    *,
    document_pages: int,
    pages_sent: int = 0,
    pages_answered: int = 0,
    failed_batches: int = 0,
    min_useful_words: int = 12,
    trustworthy_reference: bool = True,
) -> Rejection:
    """May the new text replace the previous one?

    ``trustworthy_reference=False`` turns off the gates that compare against the
    previous text. Use it when the previous one is known in advance to be bad
    for that class of document — otherwise the gate rejects exactly the
    document the expensive step exists to rescue.
    """
    warnings: list[str] = []

    # Degenerate loop: long text, 99% markers, persisted as if it were the
    # document. It comes first because it is the only case where the new text
    # is worse than nothing, and no other check catches it.
    if marker_fraction(new_text) >= MAX_MARKER_FRACTION:
        real = len(real_content(new_text))
        return Rejection(
            f"transcription is {100 * marker_fraction(new_text):.0f}% unread-passage "
            f"marker ({real} characters of real content)"
        )

    previous_degenerate = useful_words(previous_text) < min_useful_words
    exempt = previous_degenerate or not trustworthy_reference
    truncation_accepted = False

    # Density measured over REAL CONTENT (markers excluded), so a loop cannot
    # declare itself "richer". The calculation lives out here rather than inside
    # the truncation branch because the question "is the new one incomparably
    # better?" applies to both paths. Keeping it inside made the page-ceiling
    # fix REINTRODUCE the very defect it was meant to correct.
    previous_density = len(real_content(previous_text)) / max(document_pages, 1)
    new_density = len(real_content(new_text)) / max(
        pages_answered or pages_sent or document_pages, 1
    )
    much_richer = new_density >= PARTIAL_DENSITY_FACTOR * max(previous_density, 1.0)

    if pages_sent and document_pages > pages_sent:
        # A page ceiling cut the document short. Refusing outright would trade a
        # rich, incomplete text for a poor, complete one.
        if not previous_degenerate and not much_richer:
            return Rejection(f"partial transcription: {pages_sent} of {document_pages} pages")
        # Accepted — but never in silence. Without this warning the power of
        # attorney lost three notarial acts leaving no trace.
        truncation_accepted = True
        warnings.append(
            f"truncation accepted: {pages_sent} of {document_pages} pages, "
            f"density {previous_density:.0f} -> {new_density:.0f} chars/page"
        )

    if failed_batches and not previous_degenerate:
        return Rejection(
            f"{failed_batches} batch(es) failed ({pages_answered} of {pages_sent} pages answered)"
        )

    # The anchor gate guards against CORRUPTING digits the previous step read
    # correctly — and that premise requires comparable texts. It stands down in
    # four situations, each of them measured:
    #
    # - previous degenerate: there is no reference.
    # - untrustworthy reference: the previous text is known to be bad for the class.
    # - truncation accepted: the density gate has just decided to keep the
    #   partial text, and the anchor gate would then reject it for not
    #   containing what is on the pages that were KNOWINGLY not transcribed.
    #   Counting that absence twice cancels the decision.
    # - much richer: this is not the same reading with swapped digits, it is a
    #   reading of the document against a reading of the header. Measured:
    #   51,440 characters rejected for "losing" protocols present in the
    #   previous step's 774 characters of header.
    if not (exempt or truncation_accepted or much_richer):
        missing = lost(previous_text, new_text)
        if missing:
            return Rejection(
                "loses anchors from the previous step: " + ", ".join(sorted(missing)[:5])
            )
    elif much_richer and not exempt:
        # Accepted on richness, but never in silence.
        missing = lost(previous_text, new_text)
        if missing:
            warnings.append("anchors lost but accepted: " + ", ".join(sorted(missing)[:5]))

    # Length, too, only decides when there is something to compare against. The
    # archive's dominant pattern (227 of 1,339 documents) is a page whose only
    # surviving text is the stamp — 250 to 600 characters — and the real
    # content is often SHORTER than that: a notice of expiry, a one-line
    # ruling, a filing receipt. Comparing by size against a stamp discarded the
    # correct rescue.
    if len(new_text) <= len(previous_text) and not exempt:
        return Rejection("does not beat the previous text", warnings)

    return Rejection(None, warnings)
