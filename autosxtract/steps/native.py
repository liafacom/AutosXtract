"""Step 1 — the text layer already inside the PDF.

This is not OCR, it is reading. It costs ~13 ms per document (median 12.2 ms,
maximum 30.2 ms measured) against ~400 ms for any OCR engine, and it resolves
**31% of a real archive** on its own. That is why the cascade exists: a single
model for everything would charge OCR on those 31% of pages that already have
the text ready.

    935 pages / 2.5 pages/s = 6.2 min   against 4.44 min for the cascade

The step has one specific trap, and the coverage gate exists because of it: the
score describes the text that **came out**, not the fraction of the page left
behind. In a filing that embeds an official letter as an image, the native text
is flawless and the attachment — the document's actual content — is never read.
"""

from __future__ import annotations

import time
from typing import Any

from autosxtract.interfaces import DocumentContext
from autosxtract.pdf._mupdf import close, mupdf
from autosxtract.pdf.coverage import has_image_without_text
from autosxtract.pdf.lock import pdf_lock
from autosxtract.quality.metrics import normalize
from autosxtract.quality.scoring import score_structure
from autosxtract.steps.base import StepResult
from autosxtract.types import Attempt, Candidate


def read_native_text(pdf_bytes: bytes) -> tuple[str, list[dict[str, Any]]]:
    """``(text, per-page statistics)`` from the text layer.

    Returns ``("", [])`` when the PDF will not open — the step becomes a refused
    attempt and the cascade moves on.
    """
    with pdf_lock():
        try:
            pymupdf = mupdf()
        except ImportError:
            return "", []
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            return "", []
        try:
            pages: list[dict[str, Any]] = []
            parts: list[str] = []
            for i in range(len(doc)):
                page = doc[i]
                # ``sort=True`` reorders by position on the sheet: without it,
                # a PDF from certain producers returns the text in the order it
                # was written into the file, which is not reading order.
                text = normalize(page.get_text("text", sort=True))
                pages.append(
                    {
                        "page": i + 1,
                        "text": text,
                        "chars": len(text),
                        "lines": len([ln for ln in text.splitlines() if ln.strip()]),
                        "blocks": len(page.get_text("blocks")),
                        "words": len(page.get_text("words")),
                    }
                )
                parts.append(text)
            return "\n\n".join(parts).strip(), pages
        except Exception:
            return "", []
        finally:
            close(doc)


class NativeStep:
    """Reads the text layer and decides whether it ends the cascade."""

    name = "native"

    def run(self, ctx: DocumentContext) -> StepResult:
        t0 = time.perf_counter()
        text, pages = read_native_text(ctx.pdf_bytes)
        ms = (time.perf_counter() - t0) * 1000

        if not text.strip():
            return StepResult(Attempt(self.name, False, "no text layer", 0, ms))

        assessment = score_structure(text, pages)
        score = assessment["score"]
        candidate = Candidate(
            step=self.name,
            text=text,
            score=score,
            ms=ms,
            details={"label": assessment["label"], "reasons": assessment["reasons"]},
        )
        ctx.record_reading(self.name, text)

        if score < ctx.config.native_accept_score:
            return StepResult(
                Attempt(
                    self.name,
                    False,
                    f"quality {score:.2f} below {ctx.config.native_accept_score:.2f}",
                    len(text),
                    ms,
                    {"reasons": assessment["reasons"]},
                ),
                candidate,
            )

        # A high score is not enough: it cannot see what was left out of the layer.
        if ctx.config.coverage_gate and has_image_without_text(ctx.pdf_bytes):
            return StepResult(
                Attempt(self.name, False, "large image in a region with no text", len(text), ms),
                candidate,
            )

        return StepResult(Attempt(self.name, True, "adequate extraction", len(text), ms), candidate)
