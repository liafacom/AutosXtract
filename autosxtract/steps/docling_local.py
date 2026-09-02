"""Docling running **inside the process** — no service, no network.

It is the same engine as ``DoclingStep``, differing in where it lives. Both
forms exist because the choice is not obvious:

    form     network   models        latency    when to choose
    -----------------------------------------------------------------------
    API      yes       on the server  + wire    several processes share one
                                                installation; the client stays
                                                light
    local    no        ~2 GB here     no wire   an isolated machine with no
                                                network egress, or a single
                                                process

Like every expensive step (~4 s per document), it **is not in the default
cascade**: whoever wants it instantiates it. And because it loads heavy models,
the instance should be **reused** — building one per document pays the whole
load on every file.

    from autosxtract import Cascade, NativeStep, OCRStep, get
    from autosxtract.steps.docling_local import LocalDoclingStep

    docling = LocalDoclingStep(workers=2)          # once
    cascade = Cascade(steps=[NativeStep(), OCRStep(get("paddle")), docling])

Requires ``pip install 'autosxtract[docling]'``.
"""

from __future__ import annotations

import contextlib
import os
import queue
import tempfile
import threading
import time

from autosxtract.interfaces import DocumentContext
from autosxtract.quality.scoring import score_text
from autosxtract.steps.base import StepResult
from autosxtract.types import Attempt, Candidate


class LocalDoclingStep:
    """Conversion through the ``docling`` library, with a pool of converters.

    The pool exists because ``DocumentConverter`` is **not thread-safe** and
    building one costs the model load. A ``queue.Queue`` hands one instance per
    worker: thread safety without an explicit lock, and the converter always
    returns to the pool in the ``finally`` — one that does not return silently
    removes capacity from the process until the pool empties and everything
    hangs on the timeout.

    Loading is **lazy**: instantiating this step loads no model at all. Without
    that, assembling a cascade only to discover the document is native would
    cost the ~2 GB for nothing.
    """

    name = "docling_local"
    #: Like every expensive step: the five vetoes run before, the replacement
    #: gate after.
    expensive = True

    def __init__(
        self,
        *,
        workers: int = 2,
        ocr: bool = True,
        table_structure: bool = True,
        ocr_engine: str = "rapidocr",
        languages: tuple[str, ...] = ("pt", "en"),
        timeout: float = 180.0,
    ) -> None:
        self.workers = max(1, workers)
        self.ocr = ocr
        self.table_structure = table_structure
        self.ocr_engine = ocr_engine
        self.languages = tuple(languages)
        self.timeout = timeout
        self._pool: queue.Queue | None = None
        self._reason = ""
        # ``extract_batch`` hands the SAME step object to every worker thread,
        # and ``run`` calls ``available`` once per document. Without this lock
        # the first N documents all see ``_pool is None`` and each builds its own
        # pool of converters — ~2 GB of models per pool, N-1 of them orphaned but
        # resident. ``OCREngine.model`` carries the same lock for the same
        # reason; this class was the one load path without it.
        self._load_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"LocalDoclingStep(workers={self.workers}, ocr_engine={self.ocr_engine!r})"

    # ── loading ──────────────────────────────────────────────────────────
    def _ocr_options(self):
        """The OCR engine options Docling will use internally.

        ``rapidocr`` is the default because it is the same engine as this
        library's cheap step — using two different engines for the same language
        would make the agreement gate compare readings that diverge by
        configuration rather than by page difficulty.
        """
        from docling.datamodel.pipeline_options import OcrAutoOptions, RapidOcrOptions

        try:
            from docling.datamodel.pipeline_options import EasyOcrOptions
        except ImportError:
            EasyOcrOptions = None

        languages = list(self.languages)
        if self.ocr_engine == "rapidocr":
            return RapidOcrOptions(lang=languages)
        if self.ocr_engine == "easyocr" and EasyOcrOptions is not None:
            return EasyOcrOptions(lang=languages)
        # "auto", or a requested engine that is unavailable: let Docling choose.
        return OcrAutoOptions(lang=languages)

    def _build_pool(self) -> queue.Queue | None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        ocr_options = self._ocr_options() if self.ocr else None
        pool: queue.Queue = queue.Queue()
        for _ in range(self.workers):
            pipeline = PdfPipelineOptions()
            pipeline.do_ocr = self.ocr
            pipeline.do_table_structure = self.table_structure
            if ocr_options is not None:
                pipeline.ocr_options = ocr_options
            pool.put(
                DocumentConverter(
                    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)}
                )
            )
        return pool

    def available(self) -> tuple[bool, str]:
        """``(can_run, reason)`` — never raises, like every engine in the library."""
        # Checked once outside the lock so the common case — the pool is already
        # there — costs nothing, and once more inside it, because between the two
        # another thread may have built it.
        if self._pool is not None:
            return True, f"local docling, {self.workers} worker(s)"
        if self._reason:
            return False, self._reason
        with self._load_lock:
            if self._pool is not None:
                return True, f"local docling, {self.workers} worker(s)"
            if self._reason:
                return False, self._reason
            try:
                self._pool = self._build_pool()
            except ImportError as exc:
                self._reason = (
                    f"docling missing ({exc}); install with pip install 'autosxtract[docling]'"
                )
                return False, self._reason
            except Exception as exc:
                self._reason = f"local docling did not load: {exc}"
                return False, self._reason
        return True, f"local docling, {self.workers} worker(s)"

    # ── running ──────────────────────────────────────────────────────────
    def run(self, ctx: DocumentContext) -> StepResult:
        t0 = time.perf_counter()
        ok, reason = self.available()
        if not ok:
            return StepResult(Attempt(self.name, False, reason, 0, 0.0))

        try:
            text = self._convert(ctx.pdf_bytes)
        except Exception as exc:
            # Like the remote ones: a failure becomes a reason in the
            # provenance, never an exception.
            ms = (time.perf_counter() - t0) * 1000
            return StepResult(Attempt(self.name, False, f"failed: {exc}"[:160], 0, ms))

        ms = (time.perf_counter() - t0) * 1000
        if not text.strip():
            return StepResult(Attempt(self.name, False, "empty conversion", 0, ms))
        ctx.record_reading(self.name, text)
        return StepResult(
            Attempt(self.name, True, "converted", len(text), ms),
            Candidate(self.name, text, score_text(text)["score"], ms),
        )

    def _convert(self, pdf_bytes: bytes) -> str:
        """Convert with a converter from the pool, always returning it at the end."""
        assert self._pool is not None  # guaranteed by ``available``
        path = None
        converter = None
        try:
            # Docling requires a file path, not bytes.
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                path = tmp.name
                tmp.write(pdf_bytes)
            try:
                converter = self._pool.get(timeout=self.timeout)
            except queue.Empty as exc:
                raise RuntimeError(
                    f"pool exhausted after {self.timeout:.0f}s (raise workers or the timeout)"
                ) from exc
            result = converter.convert(path)
            return result.document.export_to_markdown()
        finally:
            if converter is not None:
                self._pool.put(converter)
            if path:
                with contextlib.suppress(OSError):
                    os.remove(path)

    def close(self) -> None:
        """Empty the pool. The converters have no ``close`` of their own."""
        if self._pool is None:
            return
        while not self._pool.empty():
            try:
                self._pool.get_nowait()
            except queue.Empty:
                break
        self._pool = None
