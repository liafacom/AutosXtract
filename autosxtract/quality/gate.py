"""The acceptance gate — a SINGLE criterion for every step.

This is the heart of the cascade, and the reason it works: **one** notion of
"adequate extraction". Whoever decides the current step was enough and whoever
decides the next one is worth paying for ask the same question, with the same
code. Two competing criteria in one pipeline was the defect this function
exists to avoid repeating.

The criterion asks four questions, in this order:

1. **Is there anything to read?** A page with no visual content never escalates
   — a blank back page has no text to recover, and sending it to the expensive
   step is pure cost. That is what separated the 4 legitimately empty pages of
   an archive from the 227 false successes.
2. **Did any word survive outside the stamp?** Below the floor, what came back
   is the conformity banner, not the document.
3. **Is it text, or a glyph index?**
4. **Does the density match the size of the sheet?** A page of text yields
   hundreds of characters.

No I/O, no network, no global configuration: it takes the text, the page
profile and the thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass

from autosxtract.pdf.profile import PageProfile
from autosxtract.quality.stamp import default as default_stamp


@dataclass(frozen=True)
class Verdict:
    """The decision and the reason — the reason goes to logs and provenance."""

    escalate: bool
    reason: str

    @property
    def sufficient(self) -> bool:
        """Sugar for the happy path: the current step solved it."""
        return not self.escalate


def evaluate(
    text: str,
    profile: PageProfile,
    *,
    min_useful_words: int = 12,
    min_chars_per_page: int = 200,
    score: float | None = None,
    min_score: float = 0.35,
    glyph_index: float = 0.0,
    stamps: tuple[str, ...] | None = None,
) -> Verdict:
    """Decide whether the next step is worth paying for on this document."""
    if not profile.has_visual_content:
        return Verdict(False, "page with no visual content")

    stamp = default_stamp(stamps)
    body = stamp.strip(text)
    word_count = len(stamp.words(text))

    if word_count < min_useful_words:
        return Verdict(True, f"only {word_count} useful words outside the stamp")

    if glyph_index > 0.10:
        return Verdict(True, "text is a glyph index, not content")

    if score is not None and score < min_score:
        return Verdict(True, f"quality {score:.2f} below the minimum")

    density = len(body) / max(profile.pages, 1)
    if density < min_chars_per_page:
        return Verdict(True, f"density of {density:.0f} chars/page")

    return Verdict(False, "adequate extraction")
