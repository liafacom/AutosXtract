"""The OCR step — one, generic, for any engine.

**There is no step per engine.** Vision and PP-OCRv6 go down exactly the same
code: rasterise, transcribe, measure, decide. The only difference between them
is which object implements ``transcribe_page`` — which is the point of the
design, and what lets an engine be added without touching the cascade.

The criterion for "solved it" is the **same** ``quality.gate.evaluate`` that
decides the escalation ahead. Reusing it avoids two competing notions of
"adequate extraction" in one pipeline — which was the first version's defect,
where the step approved itself by one criterion and the cascade refused it by
another.

Three refusals before the gate, in order of cost:

1. **Confidence below the floor.** It does not arbitrate quality — measured on
   60 audited documents, OCR confidence does not separate a good reading from an
   unsafe one. It is only a floor against degenerate output.
2. **Incomplete reading.** ``pages_answered < pages_sent`` is a hole in the
   document: it passes any volume test and disappears without a trace.
3. **The acceptance gate.** The single criterion.

Every refusal records in the context what the engine read. It is free at the
point of decision, and it is what turns "I could not" (one engine) into "there
is none" (several).
"""

from __future__ import annotations

import time

from autosxtract.interfaces import DocumentContext, Engine, Gate, Scorer
from autosxtract.quality.gate import evaluate
from autosxtract.quality.metrics import glyph_index_ratio
from autosxtract.quality.scoring import score_text
from autosxtract.steps.base import StepResult
from autosxtract.types import Attempt, Candidate


class OCRStep:
    """Wraps an engine and applies the cascade's gates to what it read.

    ``engine`` is asked for by contract (``interfaces.Engine``), not by base
    class. Inheriting ``OCREngine`` remains the easy road and every shipped
    engine takes it, but nothing here requires it — which is what makes "there
    is no step per engine" a structural fact rather than a habit.

    ``scorer`` and ``gate`` default to the two functions this step has always
    called. They are parameters so that a caller measuring an alternative
    criterion does not have to fork the step — and, more to the point, so that
    the acceptance gate stays visibly **one** object. Passing a second gate here
    while the cascade keeps the first is the defect of two competing notions of
    "adequate extraction" in one pipeline, only now it has a name and a
    constructor argument instead of a duplicated threshold.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        name: str | None = None,
        scorer: Scorer = score_text,
        gate: Gate = evaluate,
    ) -> None:
        self.engine = engine
        self.name = name or engine.name
        self.scorer = scorer
        self.gate = gate

    def _pages(self, ctx: DocumentContext) -> tuple[list[bytes], list[int] | None]:
        """The images to transcribe, and which pages they are.

        With per-page routing only the pages without native text are
        rasterised: measured on a real case file, of the 419 pages that went
        through OCR, 54 (12.9%) already had text. On a 39-page document with 29
        native pages, OCR ran on all 39.

        Routing is abandoned when **every** page lacks text (there is nothing to
        spare) or when the structure could not be read.
        """
        if not ctx.config.per_page_routing:
            return ctx.images(), None
        missing = ctx.pages_without_text
        if not missing:
            return ctx.images(), None
        from autosxtract.pdf.pages import count

        if len(missing) >= count(ctx.pdf_bytes):
            return ctx.images(), None
        return ctx.images(indices=missing), missing

    def run(self, ctx: DocumentContext) -> StepResult:
        t0 = time.perf_counter()
        ok, reason = self.engine.available()
        if not ok:
            return StepResult(Attempt(self.name, False, reason, 0, 0.0))

        images, indices = self._pages(ctx)
        if not images:
            return StepResult(Attempt(self.name, False, "no page rasterised", 0, 0.0))

        requested = ctx.config.pages_in_flight()
        # The effective value may be lower than requested — a single-queue
        # engine uses 1. Recording the difference is what prevents the surprise
        # of configuring 8 and measuring the time of 1 without understanding why.
        # Order matters: the operator's explicit number wins over the engine's
        # own statement about itself. The engine knows its hardware; it does not
        # know the hardware it was NOT measured on.
        override = (ctx.config.engine_parallelism or {}).get(self.name)
        if override is not None:
            effective = max(1, override)
        else:
            effective = requested if self.engine.scales_with_threads else 1
        transcription = self.engine.transcribe(
            images, parallelism=effective, force_parallelism=override is not None
        )
        ms = (time.perf_counter() - t0) * 1000
        if transcription is None or transcription.empty:
            # "Read nothing" and "could not be reached" are different facts, and
            # the provenance has to keep them apart. A worker that is down looks
            # exactly like a blank sheet in the text — that resemblance is how
            # the previous architecture lost 28,239 characters without anyone
            # noticing, because the step that failed reported the DOCUMENT as
            # empty instead of reporting ITSELF as unavailable.
            failures = getattr(transcription, "failures", []) if transcription else []
            if failures:
                reason = f"engine failed on every page: {'; '.join(failures[:2])}"
            else:
                reason = "engine returned no text"
            return StepResult(Attempt(self.name, False, reason, 0, ms))

        text = transcription.text.strip()
        text, report = self._layers(ctx, images, transcription, text)
        details = {
            "confidence": transcription.mean_confidence,
            "pages": transcription.pages_answered,
            **({"parallelism": effective} if effective != requested else {}),
            **({"ocr_pages": indices} if indices is not None else {}),
            **({"layers": report} if report else {}),
        }

        if transcription.mean_confidence < ctx.config.min_confidence:
            ctx.record_reading(self.name, text)
            return StepResult(
                Attempt(
                    self.name,
                    False,
                    f"confidence {transcription.mean_confidence:.0f} below "
                    f"{ctx.config.min_confidence:.0f}",
                    len(text),
                    ms,
                    details,
                ),
                self._candidate(text, ms, details),
            )

        if not transcription.complete:
            ctx.record_reading(self.name, text)
            return StepResult(
                Attempt(
                    self.name,
                    False,
                    f"incomplete reading: {transcription.pages_answered} of "
                    f"{transcription.pages_sent} pages",
                    len(text),
                    ms,
                    details,
                ),
                self._candidate(text, ms, details),
            )

        verdict = self.gate(
            text,
            ctx.profile,
            min_useful_words=ctx.config.min_useful_words,
            min_chars_per_page=ctx.config.min_chars_per_page,
            glyph_index=glyph_index_ratio(text),
            stamps=ctx.config.stamp_patterns(),
        )
        ctx.record_reading(self.name, text)
        candidate = self._candidate(text, ms, details)
        if verdict.escalate:
            return StepResult(
                Attempt(self.name, False, verdict.reason, len(text), ms, details), candidate
            )
        return StepResult(
            Attempt(self.name, True, verdict.reason, len(text), ms, details), candidate
        )

    def _layers(self, ctx: DocumentContext, images, transcription, text: str):
        """Contain stamps, signatures and junk — when the engine gives geometry.

        Returns ``(text, report)``. Without geometry the text passes untouched
        and the report comes back empty: the layers are a gain, not a
        requirement, and an engine that only returns a string is still a valid
        engine.

        The report enters provenance whole. It is what says where the holes are
        and whether the page calls for a more expensive step — information the
        text alone does not carry.
        """
        if not ctx.config.layers:
            return text, {}
        if not transcription.pages:
            # Skipping in silence is the antipattern this library fights:
            # whoever reads the provenance needs to know containment did NOT
            # run, and why — otherwise the absence of `[illegible]` looks like a
            # clean page.
            return text, {"skipped": f"{self.engine.name} exposes no line geometry"}
        from autosxtract.steps import layers

        try:
            contained, report = layers.apply(self.engine, images, transcription, ctx.config)
        except Exception as exc:
            # A layer is an improvement: if it fails, the engine's text still
            # stands — but the failure shows.
            return text, {"skipped": f"layer failure: {exc}"[:120]}
        return (contained.strip() or text), report

    def _candidate(self, text: str, ms: float, details: dict) -> Candidate:
        return Candidate(
            step=self.name,
            text=text,
            score=self.scorer(text)["score"],
            ms=ms,
            details=details,
        )
