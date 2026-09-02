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
        text, report, contained = self._layers(ctx, images, transcription, text)
        # What the ENGINE read, before anything native is merged into it. This is
        # the reading that goes on the blackboard: the agreement and consensus
        # gates ask whether INDEPENDENT engines saw the same thing, and an
        # engine whose reading has the text layer spliced into it agrees with the
        # native step by construction. That is the same "the witness has to be of
        # another architecture" rule as §13, applied to the other gate — and it
        # ended the cascade on self-agreement before the second engine ran.
        reading = text
        # Per-page routing sent only the pages WITHOUT native text, so what the
        # engine read is half the document. The other half is in the text layer
        # and has to go back into place before anything judges this step.
        merge: dict = {}
        covered = transcription.pages_sent
        if indices is not None:
            text, merge, covered = self._merge_native(ctx, text, transcription, contained, indices)
        details = {
            "confidence": transcription.mean_confidence,
            "pages": transcription.pages_answered,
            # The replacement gate reads these two names, and only the remote
            # steps used to write them — so its truncation branch was
            # unreachable from any OCR step somebody marked expensive. An
            # unwritten key between two modules is a wiring break that no test
            # of either module alone can see.
            #
            # ``pages_sent`` there means HOW MUCH OF THE DOCUMENT THIS TEXT
            # COVERS, not how many images the engine was handed — `remote.py`
            # writes it from a render of the whole document. Under per-page
            # routing those are different numbers, and writing the routed count
            # made `document_pages > pages_sent` true on every mixed PDF: the
            # gate called it a partial transcription and DISCARDED the candidate,
            # throwing away the very attachment the merge had just recovered.
            "pages_sent": covered,
            "pages_answered": transcription.pages_answered,
            **({"parallelism": effective} if effective != requested else {}),
            **({"ocr_pages": indices} if indices is not None else {}),
            **({"layers": report} if report else {}),
            # Whether the page was turned before the engine saw it, or why it
            # could not be. Empty on an upright document that asked for nothing,
            # which is the common case and writes no key at all.
            **({"orientation": dict(ctx.orientation)} if ctx.orientation else {}),
            **merge,
        }

        if transcription.mean_confidence < ctx.config.min_confidence:
            ctx.record_reading(self.name, reading)
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
            ctx.record_reading(self.name, reading)
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

        # The score goes INTO the gate, not only into the candidate. Computing it
        # for the contest and withholding it from the decision left the gate's
        # quality branch unreachable in production: text that cleared the word
        # floor and the density floor stopped the cascade whatever its quality,
        # and the better engine underneath never ran.
        score = self.scorer(text)["score"]
        verdict = self.gate(
            text,
            ctx.profile,
            min_useful_words=ctx.config.min_useful_words,
            min_chars_per_page=ctx.config.min_chars_per_page,
            score=score,
            min_score=ctx.config.min_score,
            glyph_index=glyph_index_ratio(text),
            stamps=ctx.config.stamp_patterns(),
        )
        ctx.record_reading(self.name, reading)
        candidate = self._candidate(text, ms, details, score=score)
        if verdict.escalate:
            return StepResult(
                Attempt(self.name, False, verdict.reason, len(text), ms, details), candidate
            )
        return StepResult(
            Attempt(self.name, True, verdict.reason, len(text), ms, details), candidate
        )

    def _layers(self, ctx: DocumentContext, images, transcription, text: str):
        """Contain stamps, signatures and junk — when the engine gives geometry.

        Returns ``(text, report, page_texts)``. Without geometry the text passes
        untouched, the report comes back empty and there are no per-page texts:
        the layers are a gain, not a requirement, and an engine that only returns
        a string is still a valid engine.

        The report enters provenance whole. It is what says where the holes are
        and whether the page calls for a more expensive step — information the
        text alone does not carry.
        """
        if not ctx.config.layers:
            return text, {}, []
        if not transcription.pages:
            # Skipping in silence is the antipattern this library fights:
            # whoever reads the provenance needs to know containment did NOT
            # run, and why — otherwise the absence of `[illegible]` looks like a
            # clean page.
            return text, {"skipped": f"{self.engine.name} exposes no line geometry"}, []
        from autosxtract.steps import layers

        try:
            contained, report, per_page = layers.apply(
                self.engine, images, transcription, ctx.config
            )
        except Exception as exc:
            # A layer is an improvement: if it fails, the engine's text still
            # stands — but the failure shows.
            return text, {"skipped": f"layer failure: {exc}"[:120]}, []
        if not contained.strip():
            return text, report, []
        return contained.strip(), report, per_page

    def _merge_native(
        self,
        ctx: DocumentContext,
        text: str,
        transcription,
        contained: list[str],
        indices: list[int],
    ) -> tuple[str, dict, int]:
        """Return each OCR'd page to its position among the native ones.

        Per-page routing is an economy, not a decision about what the document
        is: the pages it declines to rasterise already have their text, and
        returning only what the engine read drops them. Measured on the shape
        this library was built for — a 39-page filing with 29 native pages and a
        10-page scanned attachment — the coverage gate refuses the native step
        *because of* the attachment, OCR runs on the 10, the acceptance gate
        passes on a density computed over all 39, and 29 pages of text leave the
        result without a word in the provenance about it.

        Concatenating the two halves is not enough either: in a PDF where native
        and scanned pages alternate, a wrong order is worse than a wasted
        conversion. The alignment comes from the per-page lists, never from
        splitting the joined text — a blank page leaves no separator behind.

        Returns ``(text, details, pages_covered)``. The third value is what the
        replacement gate calls ``pages_sent``: how much of the DOCUMENT the text
        now covers, which after a merge is the whole of it and not the handful
        of pages the engine was handed.
        """
        if not ctx.config.use_native:
            # The operator switched the text layer off. Reading it here anyway,
            # to splice it into another step's candidate, would be this step
            # deciding to overrule that.
            return text, {"native_merge": "skipped: use_native is off"}, transcription.pages_sent

        from autosxtract.steps.native import read_native_text

        # The contained pages are preferred: they are what the layers produced
        # for the pages that went through OCR. Without geometry there are none,
        # and the engine's own per-page list serves.
        per_page = contained or list(transcription.page_texts)
        if len(per_page) != len(indices):
            # No alignment, no merge — and it is said out loud. Guessing the
            # order would reintroduce the defect this method exists to remove,
            # and dropping the native pages in silence is the defect itself.
            return (
                text,
                {"native_merge": f"skipped: {len(per_page)} page texts for {len(indices)} pages"},
                transcription.pages_sent,
            )
        _, native = read_native_text(ctx.pdf_bytes)
        if not native:
            return (
                text,
                {"native_merge": "skipped: the text layer could not be read"},
                transcription.pages_sent,
            )
        ocr_by_page = {page: per_page[n] for n, page in enumerate(indices) if per_page[n].strip()}
        out: list[str] = []
        merged = 0
        for i, page in enumerate(native):
            if i in ocr_by_page:
                out.append(ocr_by_page[i])
            elif page["text"].strip():
                out.append(page["text"].strip())
                merged += 1
        if not out:
            return text, {"native_merge": "skipped: nothing to assemble"}, transcription.pages_sent
        # The merged text spans the whole document, so that is what it covers.
        # Reporting the routed page count here made the replacement gate read
        # `document_pages > pages_sent`, call a complete document a partial
        # transcription, and discard it.
        return (
            "\n\n".join(out),
            {"native_pages_merged": merged, "native_merge": "merged"},
            len(native),
        )

    def _candidate(
        self, text: str, ms: float, details: dict, *, score: float | None = None
    ) -> Candidate:
        return Candidate(
            step=self.name,
            text=text,
            score=self.scorer(text)["score"] if score is None else score,
            ms=ms,
            details=details,
        )
