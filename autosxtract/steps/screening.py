"""Dropping documents with no textual value — deliberate, with evidence attached.

Placed **after** the cheap steps and **before** the expensive one, which is
where it saves: a document's declared type does not distinguish the ID card
attached to a filing — the description covers the whole filing. Only the text
already extracted reveals the card.

Dropping has double value: it spares the expensive step *and* keeps tax
numbers, parentage and place of birth out of the output corpus.

The original text is **not** deleted from the source file; what this step does
is replace the content with an auditable notice. Reprocessing is simply a matter
of taking the step out of the cascade.
"""

from __future__ import annotations

import time

from autosxtract.interfaces import DocumentContext
from autosxtract.quality import screening
from autosxtract.steps.base import StepResult
from autosxtract.types import Attempt, Candidate

NOTICE = (
    "[DOCUMENT NOT EXTRACTED — identity document]\n"
    "Detected by physical card markers (ID / tax card / driving licence / "
    "vehicle registration). The original file is untouched; to reprocess, "
    "simply remove the screening step from the cascade."
)


class ScreeningStep:
    """Drops an already-transcribed identity or vehicle document."""

    name = "screening"

    def __init__(self, *, label: str | None = None, notice: str = NOTICE) -> None:
        #: The document's declared description, when the integrator has it. It
        #: is the third detection path, and the only one that catches a card the
        #: OCR read as loose names and codes with no printed label at all.
        self.label = label
        self.notice = notice

    def run(self, ctx: DocumentContext) -> StepResult:
        t0 = time.perf_counter()
        text = ctx.best_text()
        if not text:
            return StepResult(Attempt(self.name, False, "nothing extracted yet", 0, 0.0))

        verdict = screening.assess(text, self.label)
        ms = (time.perf_counter() - t0) * 1000
        if not verdict.drop:
            return StepResult(Attempt(self.name, False, verdict.reason, len(text), ms))

        details = {"reason": verdict.reason, "evidence": verdict.evidence}
        return StepResult(
            Attempt(self.name, True, f"dropped: {verdict.reason}", 0, ms, details),
            Candidate(step=self.name, text=self.notice, score=0.0, ms=ms, details=details),
        )
