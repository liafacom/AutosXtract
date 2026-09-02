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

from autosxtract.interfaces import DocumentContext, Gate
from autosxtract.pdf._mupdf import close, mupdf
from autosxtract.pdf.coverage import has_image_without_text
from autosxtract.pdf.lock import pdf_lock
from autosxtract.quality.gate import evaluate
from autosxtract.quality.metrics import glyph_index_ratio, normalize
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
    """Reads the text layer and decides whether it ends the cascade.

    The decision is ``quality.gate.evaluate``'s — the SAME function ``OCRStep``
    calls and the same one that judges whether the next step is worth paying
    for. Two refusals run before it, and they are refusals this step alone can
    make: a structural score below the floor, and a large image sitting in a
    region the text layer does not cover.

    It used to end on its own criterion — ``score_structure`` against
    ``native_accept_score`` — and never consulted the gate at all. The two
    disagreed on exactly the input the gate was written for: a page whose text
    layer is only the conformity stamp scores 0.90 as *structure* (it is
    well-formed text) while the gate escalates it for holding ten useful words.
    Of 1,339 documents in the archive this was measured on, 403 had text that
    looked fine and was only the signature stamp. That is the defect
    ``evaluate`` exists to stop repeating, and it was living in this file.
    """

    name = "native"

    def __init__(self, *, gate: Gate = evaluate) -> None:
        # A parameter for the same reason ``OCRStep`` has one: so the acceptance
        # criterion stays visibly ONE object that a caller can replace on both
        # sides at once. Passing a second gate here while the cascade keeps the
        # first is the defect above with a constructor argument.
        self.gate = gate

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

        # ``score=`` is deliberately NOT passed. The gate's ``min_score`` is
        # documented and measured against ``score_text``; what this step has is
        # ``score_structure``, a different function with a density family
        # ``score_text`` does not have. Both land in 0-1, which is exactly what
        # makes the mix-up cheap to write and invisible to read. The score
        # dimension is already covered here by ``native_accept_score``, above,
        # and at a stricter floor (0.75 against 0.35) — so passing it would be
        # inert today and a scale confusion the day somebody lowers it.
        verdict = self.gate(
            text,
            ctx.profile,
            min_useful_words=ctx.config.min_useful_words,
            min_chars_per_page=ctx.config.min_chars_per_page,
            glyph_index=glyph_index_ratio(text),
            stamps=ctx.config.stamp_patterns(),
        )
        if verdict.escalate:
            return StepResult(Attempt(self.name, False, verdict.reason, len(text), ms), candidate)
        # On acceptance the gate's own reason can be a statement about the SHEET
        # rather than about the text — "page with no visual content" is how a
        # born-digital filing passes, since it has neither image nor vector — and
        # printing that as the provenance of a good extraction is a false
        # sentence in the one record that is supposed to be auditable.
        return StepResult(Attempt(self.name, True, "adequate extraction", len(text), ms), candidate)
