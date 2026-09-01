"""Stage 0 — is the file really a PDF?

It runs before anything else and almost always does nothing: on a real PDF it
costs the reading of 16 bytes. It exists for the cases where the extension
lies — in a real archive, 128 documents arrive as ``.pdf`` while being RTF, a
BRy envelope or PKCS#7, and PyMuPDF raises ``Failed to open stream`` on them.

When the unwrap produces **text**, the cascade stops here: there is no image to
recognise, and sending an RTF to OCR would be absurd. When it produces **bytes**
(a PDF that was inside a signed envelope), the step swaps the context's content
and lets the cascade carry on over the payload.
"""

from __future__ import annotations

import time

from autosxtract.formats import unwrap
from autosxtract.interfaces import DocumentContext
from autosxtract.quality.scoring import score_text
from autosxtract.steps.base import StepResult
from autosxtract.types import Attempt, Candidate


class UnwrapStep:
    """Detects the real format and peels the envelope layers off."""

    name = "unwrap"

    def run(self, ctx: DocumentContext) -> StepResult:
        t0 = time.perf_counter()
        result = unwrap(ctx.pdf_bytes)
        ms = (time.perf_counter() - t0) * 1000
        details = {"format": result.format.value}

        if result.is_plain_pdf:
            return StepResult(
                Attempt(self.name, False, "it is a PDF; the cascade continues", 0, ms, details)
            )

        if result.reason:
            return StepResult(Attempt(self.name, False, result.reason, 0, ms, details))

        if result.text.strip():
            text = result.text.strip()
            ctx.record_reading(self.name, text)
            return StepResult(
                Attempt(
                    self.name,
                    True,
                    f"text extracted from {result.format.value}",
                    len(text),
                    ms,
                    details,
                ),
                Candidate(
                    step=self.name,
                    text=text,
                    score=score_text(text)["score"],
                    ms=ms,
                    details=details,
                ),
            )

        if result.bytes_for_cascade is not None:
            # A binary document came out of the envelope. Swapping the context's
            # bytes is what makes the following steps see the payload instead of
            # the envelope — without it the unwrap would be pointless.
            if result.bytes_for_cascade != ctx.pdf_bytes:
                ctx.replace_bytes(result.bytes_for_cascade)
                return StepResult(
                    Attempt(
                        self.name,
                        False,
                        f"unwrapped from {result.format.value}; the cascade continues",
                        0,
                        ms,
                        details,
                    )
                )
            return StepResult(Attempt(self.name, False, "nothing to unwrap", 0, ms, details))

        return StepResult(Attempt(self.name, False, "unrecognised format", 0, ms, details))
