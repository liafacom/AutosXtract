"""Who wins the contest between the steps that ran.

Without this layer the cascade uses **the last step that ran**, not the best
one: when the native text falls below the threshold, the pipeline calls OCR and
accepts its return without comparing. Measured on a real archive, that
discarded already-extracted text in 12.7% of the documents that fell through —
682 documents ended up with zero characters while having a text layer in the
PDF.

Pure module: no I/O, testable in isolation.
"""

from __future__ import annotations

from autosxtract.types import Candidate


def pick(candidates: list[Candidate]) -> Candidate | None:
    """The most useful candidate, or ``None`` if none has text.

    Rules, in this order:

    1. A candidate with no text never wins — it is discarded before the
       comparison. That was exactly the case leaving 682 documents empty.
    2. Among those with text, the highest ``usefulness`` wins
       (``quality x log(1 + volume)``).
    3. Ties go to entry order, which is cascade order (cheapest first) — that
       avoids switching engines for no gain.
    """
    with_text = [c for c in candidates if c.volume > 0]
    if not with_text:
        return None
    return max(with_text, key=lambda c: c.usefulness)


def losers(candidates: list[Candidate], winner: Candidate | None) -> list[Candidate]:
    """The ones that existed and lost — input to the provenance record."""
    return [c for c in candidates if c is not winner]
