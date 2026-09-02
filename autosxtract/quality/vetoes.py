"""The five vetoes that run before an expensive step.

Each answers a different question, and they all exist because the expensive
step costs tens of seconds per document. The order is by rising cost: the first
two are pixel statistics at 40 DPI (milliseconds); the third runs a real local
OCR (~1 s); the last two compare text that was already read (free).

    1. PAGE IS A PHOTOGRAPH   continuous tone and no text: nothing to read
    2. PAGE HAS NO INK        a blank sheet outside the stamp
    3. LOCAL OCR FINDS NO WORD  an engine read the page and found nothing legible
    4. SPARSE PAGE            legible, but with very little content
    5. READING CONFIRMED      two engines read THE SAME THING

The first two are only valid in conjunction with "the previous step extracted
no text" — on their own they would discard an old photocopy on dark paper,
which is continuous tone and carries thousands of legitimate characters.

The third is **the only one that measures instead of estimating**, and it is
what solved the case no pixel statistic could. Measured on 19 escalated
documents from an archive: it saves 27.2 minutes of the expensive step, and the
largest content lost is a 124-character stamp.

The fourth asks "is there anything to read?" where the third asks "can I read
it?". Without it, four "NOTICE OF INSPECTION" sheets paid for the expensive
step to yield 126 to 433 characters.

The fifth inverts the consensus asymmetry, deliberately: there one dissenting
vote is enough to escalate, because declaring a page with text empty destroys
information. Here the cost of being wrong is merely failing to marginally
improve a text both engines already read the same way — the document keeps what
it has.

**Not escalating is NOT discarding.** In all five cases the document keeps the
text the cheap layer already read.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from autosxtract.quality.consensus import assess_agreement
from autosxtract.quality.stamp import useful_words

if TYPE_CHECKING:
    from autosxtract.interfaces import InkSignals


def _default_ink() -> InkSignals:
    """``pdf.ink`` itself, imported here rather than at module scope.

    Two things follow from the placement. ``quality/`` keeps no import of
    ``pdf/`` for the callers that never ask for pixel signals, and the one
    branch that does open a PDF is reached through a name a test can replace.
    """
    from autosxtract.pdf import ink

    return ink


@dataclass(frozen=True)
class Veto:
    """A veto that fired, with its name and reason — it goes to provenance."""

    name: str
    reason: str
    evidence: str = ""


@dataclass(frozen=True)
class LocalReading:
    """What a local OCR managed to read, to serve as a witness.

    ``reliable_words`` is what separates "I cannot read it" from "there is
    nothing to read": the words the engine recognised above its own confidence
    floor.
    """

    text: str
    words: int = 0
    reliable_words: int = 0
    mean_confidence: float = 0.0
    track: str = ""
    pages_read: int = 0

    @property
    def empty(self) -> bool:
        return self.reliable_words == 0


def assess_vetoes(
    pdf_bytes: bytes,
    current_text: str,
    *,
    local_reading: LocalReading | Callable[[], LocalReading | None] | None = None,
    min_useful_words: int = 12,
    min_reliable_words: int = 3,
    min_agreement: float = 0.60,
    stamps: tuple[str, ...] | None = None,
    pixel_signals: bool = True,
    ink: InkSignals | None = None,
) -> Veto | None:
    """Should the expensive step be skipped? ``None`` means "go ahead".

    ``local_reading`` is the witness for vetoes 3 to 5. ``None`` means "I don't
    know" — the local engine is absent — and the three are skipped; it never
    becomes "there is no text", because the absence of a tool is not evidence
    about the document.

    Pass it as a **callable** to keep the declared cost order. The witness runs a
    real OCR (~1 s, and several seconds once the recovery track engages), while
    vetoes 1 and 2 are pixel statistics at 40 DPI. Handing this function an
    already-computed reading inverts that: Python evaluates the argument first,
    so a blank sheet paid for the whole witness before the cheapest veto that
    was written to reject it for free got to run. The callable is invoked at
    most once, and never when a pixel veto has already fired.
    """
    no_text = useful_words(current_text, stamps) < min_useful_words

    # ``and no_text`` is not an optimisation, it is the correctness condition.
    # On their own these two discard an old photocopy on dark paper — continuous
    # tone, thousands of legitimate characters (CLAUDE.md §13).
    if pixel_signals and no_text:
        signals = ink if ink is not None else _default_ink()
        if signals.is_photograph(pdf_bytes):
            return Veto("photograph", "page with no text and continuous tone — nothing to rescue")
        if signals.is_nearly_blank(pdf_bytes):
            return Veto("no_ink", "page with no text and almost no ink outside the stamp")

    # Only here — after the two cheap ones have had their chance.
    reading = local_reading() if callable(local_reading) else local_reading

    if reading is None:
        return None

    if reading.reliable_words < min_reliable_words:
        return Veto(
            "no_legible_word",
            "a local OCR read the page and found no legible word",
            f"{reading.reliable_words} reliable words, "
            f"mean confidence {reading.mean_confidence:.0f}, "
            f"track {reading.track}",
        )

    if useful_words(reading.text, stamps) < min_useful_words:
        return Veto(
            "sparse_page",
            "a local OCR read the whole page and it holds little content",
            f"{useful_words(reading.text, stamps)} useful words, floor {min_useful_words}",
        )

    if min_agreement > 0:
        agreement = assess_agreement(
            {"cheap": current_text, "local": reading.text},
            word_floor=min_useful_words,
            min_similarity=min_agreement,
            stamps=stamps,
        )
        if agreement.agree:
            return Veto(
                "reading_confirmed",
                "two independent engines read the same thing",
                agreement.evidence,
            )

    return None
