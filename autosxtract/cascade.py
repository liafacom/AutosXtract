"""The cascade — the object you actually use.

Every document descends steps from the cheapest to the most expensive and
**stops at the first one that produces acceptable text**. That is the whole
idea, and it works because the distribution is uneven: measured across two real
archives, 31% of documents are resolved by the native text layer at 13 ms, and
only the rest pay for OCR.

    STEP                       COST/DOC     RESOLVES
    ---------------------------------------------------
    1. native (PyMuPDF)         13.4 ms      31%
    2. OCR                     ~500 ms       64%
    3. gates                    ~0           the remainder

Step 2 is chosen by the machine, and on Apple hardware there are two of them:
**Apple Vision** goes first (faster, and 100% preservation of numeric anchors at
the median) and **PP-OCRv6 tiny** sits underneath it, the step that runs when
Vision refuses the page. Off Apple the Vision layer simply is not there and
PP-OCRv6 becomes step 2 itself:

    macOS            native -> vision -> paddle
    Linux/Windows    native ->           paddle

Nothing about the cascade changes with the platform except that one missing
layer — same steps, same gates, same contest. Neither engine leaves the machine:
there is no worker, tunnel or remote endpoint anywhere.

The gates are what stop the cascade from spending the expensive step for
nothing:

``coverage``   does the native text cover the sheet, or did it leave the
               attachment out?
``agreement``  two engines read THE SAME THING -> the reading is complete
``consensus``  all of them read almost nothing -> the page is empty, it did not
               fail

And at the end, the **contest**: the candidate with the highest usefulness wins,
not the last one to run. Without that, a late step returning little erases the
text an earlier step had already extracted — measured, 12.7% of the documents
that fell through, 682 of them ending with zero characters.
"""

from __future__ import annotations

import time
from pathlib import Path

from autosxtract.config import Config
from autosxtract.engines import base as engines
from autosxtract.interfaces import Engine, Step
from autosxtract.quality.consensus import assess_agreement, assess_emptiness
from autosxtract.quality.prose import normalize
from autosxtract.quality.rejection import assess_replacement
from autosxtract.quality.selection import losers, pick
from autosxtract.quality.vetoes import LocalReading, assess_vetoes
from autosxtract.steps.base import Context, StepResult
from autosxtract.steps.native import NativeStep
from autosxtract.steps.ocr import OCRStep
from autosxtract.types import Attempt, Candidate, Result


def engine_order(config: Config | None = None) -> list[str]:
    """Which engines to use, on this machine, in this order.

    ``config.engines`` wins when filled in — including when naming an
    unavailable engine, in which case the step becomes a refused attempt with
    the reason rather than an error. Silencing the operator's choice would be
    worse.

    With no explicit choice, the order comes from the registry by priority,
    filtered by what loads here. Two common-sense rules apply:

    - ``ocrmac`` only enters if ``vision`` did not: they are the same Apple
      engine, and the second is the first's safety net (it pays the ~61 ms
      round-trip the direct path does not).
    - the **witness never transcribes**. ``config.veto_engine`` — Tesseract by
      default — is left out of the chain entirely. It exists to *disagree*, and
      an engine that both produces a candidate and vouches for the others is no
      independent evidence at all: the veto asks "does a DIFFERENT architecture
      also see text here?", and it cannot answer that about its own output. It
      would also enter the contest, where at ~1.4 s/page it competes on volume
      with readings that are better and shorter.

    ``config.engines`` overrides both rules. Naming the witness there is the
    operator saying they want it transcribing, and silencing that choice would
    be worse than honouring it.
    """
    config = config or Config()
    if config.engines is not None:
        return list(config.engines)

    chosen: list[str] = []
    for info in engines.compatible():
        if info.name == "ocrmac" and "vision" in chosen:
            continue
        if info.name == config.veto_engine:
            continue
        ok, _reason = engines.get(info.name).available()
        if ok:
            chosen.append(info.name)
    return chosen


class Cascade:
    """Extracts text from PDFs by descending steps until one suffices.

    Reusable, and thread-safe where it matters: engines load once per process
    and PyMuPDF is serialised by a lock. Instantiate once and call ``extract``
    freely — instantiating per document throws away the model load cache, which
    is the dominant cost of the first call.

    ``steps`` is a list of ``interfaces.Step``, and that is the only thing the
    cascade knows about them: a name, a ``run``, and an optional ``expensive``
    marker read with ``getattr``. Nothing here imports a concrete step in order
    to run one — ``NativeStep`` and ``OCRStep`` are imported to *assemble* the
    default, which is a different job and the only place the two are named.

    The ``Context`` it builds stays concrete on purpose. The cascade owns the
    blackboard and writes to it; what it hands the steps is the narrower
    ``DocumentContext`` view, which withholds ``readings`` and ``texts``
    precisely because those are the evidence the gates below decide on.
    """

    def __init__(self, config: Config | None = None, steps: list[Step] | None = None) -> None:
        self.config = config or Config()
        self.steps = steps if steps is not None else self._assemble()

    # ── assembly ─────────────────────────────────────────────────────────
    def _assemble(self) -> list[Step]:
        """This machine's default cascade."""
        steps: list[Step] = []
        if self.config.use_native:
            steps.append(NativeStep())
        options = self.config.engine_options or {}
        for name in engine_order(self.config):
            steps.append(OCRStep(engines.get(name, **options.get(name, {}))))
        return steps

    @property
    def names(self) -> list[str]:
        """The assembled steps, in order — for logs and ``diagnose``."""
        return [s.name for s in self.steps]

    # ── running ──────────────────────────────────────────────────────────
    def extract(self, pdf_bytes: bytes, identifier: str = "") -> Result:
        """Extract the text of an in-memory PDF.

        It never raises because of a missing engine or an unreadable PDF: it
        returns an empty ``Result`` whose provenance says what happened at each
        step. Extraction is a process with an uncertain outcome, and an
        explained uncertain outcome is worth more than an exception.
        """
        t0 = time.perf_counter()
        ctx = Context(pdf_bytes=pdf_bytes, config=self.config, identifier=identifier)
        attempts: list[Attempt] = []
        candidates: list[Candidate] = []

        for step in self.steps:
            if getattr(step, "expensive", False):
                veto = self._veto(ctx)
                if veto is not None:
                    attempts.append(veto)
                    continue

            # The reference text has to be read BEFORE the step runs: the step
            # records its own reading in the context, and comparing afterwards
            # would compare the new text with itself — the anchor gate would
            # never fire.
            previous = ctx.best_text() if getattr(step, "expensive", False) else ""

            result = step.run(ctx)
            if getattr(step, "expensive", False) and result.candidate is not None:
                result = self._reject(ctx, result, previous)

            attempts.append(result.attempt)
            if result.candidate is not None:
                candidates.append(result.candidate)

            if result.accepted:
                return self._close(result.candidate, candidates, attempts, t0)

            agreed = self._agreement(ctx, attempts)
            if agreed is not None:
                return self._close(agreed, candidates, attempts, t0)

        empty = self._consensus(ctx, attempts, t0)
        if empty is not None:
            return empty

        return self._close(pick(candidates), candidates, attempts, t0)

    def extract_file(self, path: str | Path) -> Result:
        """Extract from a file on disk. The name becomes the identifier."""
        path = Path(path)
        return self.extract(path.read_bytes(), identifier=path.name)

    def extract_batch(
        self, paths: list[str | Path], *, parallelism: int | None = None
    ) -> dict[str, Result]:
        """Several files, in parallel per document.

        The useful parallelism is **per document**, not per page: PyMuPDF is
        serialised by a lock (it crashes the process under concurrency) and
        Apple's engine has a single hardware queue, so more threads inside one
        document only raise latency. Measured from 1 to 12 threads against
        Vision: constant throughput, linear latency.
        """
        from concurrent.futures import ThreadPoolExecutor

        documents, pages = self.config.batch_concurrency()
        n = parallelism or documents
        # The per-document pages in flight arrive already cut by the aggregate
        # cap. Without it, ``documents x pages`` grows unnoticed: 4 x 8 is 32
        # simultaneous pages, each holding a rendered image and the model's
        # activations.
        config = self.config.model_copy(update={"page_parallelism": pages})
        batch = Cascade(config, steps=self.steps)
        resolved = [Path(p) for p in paths]
        with ThreadPoolExecutor(max_workers=n) as pool:
            results = list(pool.map(batch.extract_file, resolved))
        return {p.name: r for p, r in zip(resolved, results, strict=True)}

    # ── gates ────────────────────────────────────────────────────────────
    def _agreement(self, ctx: Context, attempts: list[Attempt]) -> Candidate | None:
        """Did two engines read the same thing? Then the reading is complete.

        This gate answers a question none of the others does: the first four ask
        "is there text?"; this one asks "is the text we already have COMPLETE?" —
        which is the distinction between "the extraction failed" and "the
        document is short". No statistic separates the two; two engines of
        different architectures reading the same text do, because OCR errors do
        not correlate across distinct models.

        It costs nothing: at the point of decision the cascade already holds
        both readings. Measured on 935 documents: 23 vetoes, the expensive step
        fell from 25 to 16 calls, and real content went UP by 424 characters.
        """
        if not self.config.agreement_gate or len(ctx.texts) < 2:
            return None
        agreement = assess_agreement(
            ctx.texts,
            word_floor=self.config.min_useful_words,
            min_similarity=self.config.min_agreement,
            stamps=self.config.stamp_patterns(),
        )
        if not agreement.agree:
            return None
        best = _best_of_texts(ctx)
        if best is None:
            return None
        attempts.append(
            Attempt(
                "agreement_gate",
                True,
                f"reading confirmed ({agreement.similarity:.2f} shared vocabulary)",
                len(best.text),
                0.0,
                {"evidence": agreement.evidence},
            )
        )
        return best

    def _consensus(self, ctx: Context, attempts: list[Attempt], t0: float) -> Result | None:
        """Do all the engines agree there is no content?

        The asymmetry is deliberate: one dissenting engine is enough not to
        declare it empty. Declaring a page with text empty discards information;
        the reverse only wastes time.
        """
        if not self.config.consensus_gate:
            return None
        verdict = assess_emptiness(ctx.readings, word_floor=self.config.min_useful_words)
        if not verdict.empty:
            return None
        attempts.append(
            Attempt(
                "consensus_gate",
                True,
                "page with no textual content",
                0,
                0.0,
                {"evidence": verdict.evidence, "readings": verdict.readings},
            )
        )
        return Result(
            text="",
            step="empty_by_consensus",
            score=None,
            ms=(time.perf_counter() - t0) * 1000,
            attempts=attempts,
            details={"evidence": verdict.evidence},
        )

    # ── expensive-step gates ─────────────────────────────────────────────
    def _veto(self, ctx: Context) -> Attempt | None:
        """The five vetoes that run before a step declared expensive.

        The witness for vetoes 3 to 5 is a local engine **of another
        architecture** than those already run: a second engine of the same
        family is not independent evidence. With none available the three are
        skipped — and that shows in the provenance, because a veto that does not
        run is an expensive step paid where it need not have been.
        """
        if not self.config.expensive_step_vetoes:
            return None
        current = ctx.best_text()
        veto = assess_vetoes(
            ctx.pdf_bytes,
            current,
            local_reading=self._witness(ctx),
            min_useful_words=self.config.min_useful_words,
            min_reliable_words=self.config.min_reliable_words,
            min_agreement=self.config.min_agreement,
            stamps=self.config.stamp_patterns(),
        )
        if veto is None:
            return None
        return Attempt(
            f"veto:{veto.name}",
            False,
            veto.reason,
            len(current),
            0.0,
            {"evidence": veto.evidence} if veto.evidence else {},
        )

    def _witness(self, ctx: Context) -> LocalReading | None:
        """The local reading that supports vetoes 3 to 5, or ``None``.

        ``None`` means "I don't know" and never "there is no text": the absence
        of a tool is not evidence about the document.
        """
        name = self.config.veto_engine
        if not name:
            return None
        engine: Engine
        try:
            engine = engines.get(name, **(self.config.engine_options or {}).get(name, {}))
        except Exception:
            # A missing veto engine.
            return None
        if not engine.available()[0]:
            return None
        try:
            return engine.read_document(
                ctx.pdf_bytes,
                max_pages=self.config.veto_max_pages,
                min_reliable_words=self.config.min_reliable_words,
            )
        except Exception:
            # The witness never brings the cascade down.
            return None

    def _reject(self, ctx: Context, result: StepResult, previous: str) -> StepResult:
        """Decide whether the expensive step's text may REPLACE what exists.

        This is a different gate from the acceptance one, and it needs to be:
        that one asks "is this text good?", this one asks "is it better than what
        I already had, and did it lose nothing on the way?". Length alone gets
        both of the costliest cases wrong — partial coverage and digit
        corruption.
        """
        if not self.config.replacement_gate or result.candidate is None:
            return result
        if not previous:
            return result
        details = result.attempt.details
        verdict = assess_replacement(
            result.candidate.text,
            previous,
            document_pages=max(ctx.profile.pages, 1),
            pages_sent=details.get("pages_sent", 0),
            pages_answered=details.get("pages_answered", 0),
            failed_batches=details.get("failed_batches", 0),
            min_useful_words=self.config.min_useful_words,
        )
        extra = dict(details)
        if verdict.warnings:
            extra["warnings"] = verdict.warnings
        if verdict.accepted:
            return StepResult(
                Attempt(
                    result.attempt.step,
                    True,
                    result.attempt.reason,
                    result.attempt.chars,
                    result.attempt.ms,
                    extra,
                ),
                result.candidate,
            )
        # Here the candidate is DISCARDED, not merely refused — that is the
        # difference between this gate and the acceptance one, and it is
        # deliberate.
        #
        # The acceptance gate says "not good enough to stop the cascade", and
        # such a candidate may still be the best reading available: it stays in
        # the contest. This one has already COMPARED against the previous text
        # and concluded the new one is worse or dangerous — it corrupted a
        # digit, came back partial, is a marker loop. Letting it compete would
        # cancel the gate, because volume is usually on the wrong side: the
        # corrupted text is precisely the longest one.
        return StepResult(
            Attempt(
                result.attempt.step,
                False,
                verdict.reason or "refused",
                result.attempt.chars,
                result.attempt.ms,
                extra,
            )
        )

    # ── closing ──────────────────────────────────────────────────────────
    def _close(
        self,
        winner: Candidate | None,
        candidates: list[Candidate],
        attempts: list[Attempt],
        t0: float,
    ) -> Result:
        """Assemble the final result, with the contest already settled.

        This is where prose rebuilding happens, and only here: normalising
        earlier would make the gates measure one text and the output deliver
        another.
        """
        ms = (time.perf_counter() - t0) * 1000
        if winner is None:
            return Result(text="", step="none", score=None, ms=ms, attempts=attempts)
        text = normalize(winner.text) if self.config.rebuild_prose else winner.text
        return Result(
            text=text,
            step=winner.step,
            score=winner.score,
            ms=ms,
            attempts=attempts,
            discarded=losers(candidates, winner),
            details=dict(winner.details),
        )


def _best_of_texts(ctx: Context) -> Candidate | None:
    """The best among the texts already read, to close via the agreement gate.

    It rebuilds candidates from what is in the context rather than holding a
    reference: that way the gate works identically for any set of engines,
    including ones somebody adds later.
    """
    from autosxtract.quality.scoring import score_text

    rebuilt = [
        Candidate(step=engine, text=text, score=score_text(text)["score"])
        for engine, text in ctx.texts.items()
        if (text or "").strip()
    ]
    return pick(rebuilt)


def extract(pdf: bytes | str | Path, config: Config | None = None) -> Result:
    """A one-line shortcut for the simple case.

    It builds a fresh cascade on every call — convenient in a script, expensive
    in a loop: instantiate ``Cascade`` once to process many documents.
    """
    cascade = Cascade(config)
    if isinstance(pdf, bytes):
        return cascade.extract(pdf)
    return cascade.extract_file(pdf)
