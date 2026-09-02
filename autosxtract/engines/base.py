"""The OCR engine contract, and the registry that makes engines interchangeable.

**This is the library's extension point.** A new engine is a class with one
method — ``transcribe_page(image) -> (text, confidence)`` — plus the
``@register`` decorator. The cascade need not know it exists: it builds the
order from the registry, filtering by platform and by what is actually
installed.

    from autosxtract.engines.base import OCREngine, register

    @register(name="my_ocr", priority=25, extra="my-ocr")
    class MyOCR(OCREngine):
        def _load(self):
            import my_ocr
            return my_ocr.Reader()

        def transcribe_page(self, image: bytes) -> tuple[str, float]:
            r = self.model.read(image)
            return r.text, r.confidence * 100

Two rules the contract imposes, both of them measured:

**Confidence does not arbitrate quality.** Across 60 audited documents, engine
confidence did not separate a good reading from an unsafe one — there was an
unsafe document at 100. It enters only as a floor against degenerate output;
the gate is what decides.

**A missing engine is never an exception.** ``available()`` returns the reason
in words, the step goes inert and the cascade moves on. The absence of a tool
is not evidence about the document.

The contract itself is ``interfaces.Engine``, re-exported below. Inheriting
``OCREngine`` is the easy road and gives you the page sweep, the locked single
load and the witness reading for free — but it is a convenience, not the
requirement: ``OCRStep`` asks for the protocol, so an engine that shares nothing
with this base still descends the cascade.
"""

from __future__ import annotations

import platform
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from autosxtract.exceptions import UnknownEngine
from autosxtract.interfaces import Engine
from autosxtract.quality.vetoes import LocalReading
from autosxtract.types import Page, Transcription

#: The contract itself now lives in ``autosxtract.interfaces``, with every other
#: collaboration in the library, and is re-exported here because this is where
#: whoever writes an engine arrives. Moving it did not narrow anything: the
#: definition there is the one the code already required, ``force_parallelism``
#: and ``scales_with_threads`` included, which the copy that lived here had
#: quietly stopped describing.
__all__ = [
    "Engine",
    "EngineInfo",
    "OCREngine",
    "available",
    "compatible",
    "diagnose",
    "get",
    "register",
    "registered",
]


@dataclass(frozen=True)
class _Failed:
    """A page that RAISED, carrying why. Not a page that read nothing."""

    reason: str


def _describe(exc: Exception) -> str:
    """A short, readable cause. Empty-message exceptions say only their type.

    ``ConnectionResetError()`` stringifies to ``""``, and a reason nobody can
    read is the same as no reason at all.
    """
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class OCREngine:
    """A base holding what every engine repeats: single load and page sweep.

    A subclass implements ``_load`` (once per process, under a lock) and
    ``transcribe_page``. The rest is inherited.
    """

    name: str = "engine"
    #: Systems where it makes sense to try. Empty = any.
    platforms: tuple[str, ...] = ()
    #: Name of the pip extra that installs it, quoted when it is missing.
    extra: str = ""
    #: Do threads add throughput on this engine?
    #:
    #: ``False`` for an engine with a single hardware queue — Apple's, whose
    #: Neural Engine serves one request at a time. Measured from 1 to 12
    #: threads: constant throughput at ~2.5 pages/s and latency from 430 ms to
    #: 3,492 ms. Asking for parallelism there is not bad optimisation, it is
    #: simply stacked waiting — and the engine that knows it is the one that
    #: should say so.
    scales_with_threads: bool = True

    def __init__(self) -> None:
        self._model = None
        self._load_lock = threading.Lock()
        self._reason = ""

    # ── loading ──────────────────────────────────────────────────────────
    def _load(self):
        """Build the model. Raising here means "engine unavailable"."""
        raise NotImplementedError

    @property
    def model(self):
        """The loaded model, or ``None`` if it will not load on this machine.

        Loading is expensive (tens to hundreds of ms) and happens once per
        process, under a lock — without it, four threads load four copies.
        """
        if self._model is not None or self._reason:
            return self._model
        with self._load_lock:
            if self._model is not None or self._reason:
                return self._model
            try:
                self._model = self._load()
            except Exception as exc:
                # Optional engine: a failure to load is unavailability.
                self._reason = str(exc)
                return None
            return self._model

    # ── availability ─────────────────────────────────────────────────────
    def available(self) -> tuple[bool, str]:
        """``(can_run, reason)`` — never raises."""
        if self.platforms and platform.system() not in self.platforms:
            return False, f"{self.name} requires {'/'.join(self.platforms)}"
        if self.model is None:
            hint = f"; install with pip install autosxtract[{self.extra}]" if self.extra else ""
            return False, f"{self.name} unavailable: {self._reason or 'did not load'}{hint}"
        return True, "ok"

    # ── transcription ────────────────────────────────────────────────────
    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        """The minimal contract: a page becomes ``(text, confidence)``.

        The default implementation derives it from the detailed contract when
        the engine offers one, so a subclass with geometry implements **one**
        method rather than two.
        """
        page = self.read_page(image)
        if page is None:
            raise NotImplementedError(
                f"{type(self).__name__} must implement transcribe_page or read_page"
            )
        return page.text, page.mean_confidence

    def read_page(self, image: bytes) -> Page | None:
        """The page line by line, with polygon and score — or ``None``.

        ``None`` is the honest answer from an engine that only returns running
        text, and it blocks nothing: the cascade falls back to the simple
        contract and the position-dependent layers are skipped, with the reason
        recorded.

        Implementing this enables the **containment layers**
        (``quality.lines``): measured on 895 pages, entity recall rises from
        0.902 to 0.921 and latency FALLS from 298 to 236 ms — but they only
        exist because someone knows where each line sits on the sheet.
        """
        return None

    def recognize_crop(self, image: bytes) -> tuple[str, float] | None:
        """Recognise a crop that **already is** a line, without running detection.

        This exists because of a measurement, not for elegance. Layer 2's
        re-reading calls it once per target; using the whole-page path instead,
        detection runs again on every crop and the layer goes from tens of
        milliseconds to ~3 s per document — from improvement to regression.

        ``None`` means the engine does not separate detection from recognition.
        Layer 2 then falls back to the full path, which works and is slow.
        """
        return None

    def transcribe(
        self,
        pages: list[bytes],
        *,
        parallelism: int = 4,
        force_parallelism: bool = False,
    ) -> Transcription | None:
        """Transcribe the pages **preserving the original order**.

        One page failing does not bring the others down — that page comes back
        empty and the caller sees ``pages_answered < pages_sent`` to decide
        whether the result is usable. Reassembling in completion order would
        scramble the document, so the parallel path uses ``map``, which
        preserves input order.
        """
        if not pages:
            return None

        # The engine has a say about its own parallelism, because whoever
        # configures the cascade does not know whether a hardware queue sits
        # behind it. ``force_parallelism`` is how the operator overrules that:
        # the declaration was measured on ONE machine, and a default that
        # nobody can lift stops being a measurement and becomes a law.
        effective = parallelism if (force_parallelism or self.scales_with_threads) else 1

        t0 = time.perf_counter()

        def _one(image: bytes):
            """One page. Returns the reading, or the REASON it could not be read.

            A bad page does not bring the document down — but the reason it went
            bad has to survive. Swallowing it makes an unreachable engine
            indistinguishable from a blank sheet, and only one of those is an
            emergency.
            """
            try:
                page = self.read_page(image)
            except Exception as exc:
                return _Failed(_describe(exc))
            if page is not None:
                return page.text, page.mean_confidence, page
            try:
                text, confidence = self.transcribe_page(image)
            except Exception as exc:
                return _Failed(_describe(exc))
            return text, confidence, None

        if effective > 1 and len(pages) > 1:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=effective) as pool:
                results = list(pool.map(_one, pages))
        else:
            results = [_one(p) for p in pages]

        parts: list[str] = []
        confidences: list[float] = []
        detailed: list[Page] = []
        failures: list[str] = []
        # One slot per page SENT, in order — a page that failed keeps its empty
        # slot instead of vanishing. ``results`` comes from ``map``, so it is
        # already aligned with ``pages``; that alignment is the whole value.
        page_texts: list[str] = []
        answered = 0
        for r in results:
            if isinstance(r, _Failed):
                if r.reason not in failures:
                    failures.append(r.reason)
                page_texts.append("")
                continue
            if r is None:
                page_texts.append("")
                continue
            text, confidence, page = r
            answered += 1
            if page is not None:
                detailed.append(page)
            if (text or "").strip():
                parts.append(text.strip())
                confidences.append(confidence)
                page_texts.append(text.strip())
            else:
                page_texts.append("")
        if answered == 0:
            if not failures:
                # Every page came back legitimately empty. That IS an answer.
                return None
            # Nothing was read AND every page raised: the engine is the problem,
            # not the document. Coming back as a Transcription rather than
            # ``None`` is what lets the step say so out loud.
            return Transcription(
                text="",
                engine=self.name,
                pages_sent=len(pages),
                pages_answered=0,
                ms=round((time.perf_counter() - t0) * 1000, 1),
                page_texts=page_texts,
                failures=failures,
            )
        return Transcription(
            text="\n\n".join(parts),
            engine=self.name,
            pages_sent=len(pages),
            pages_answered=answered,
            mean_confidence=(round(sum(confidences) / len(confidences), 1) if confidences else 0.0),
            ms=round((time.perf_counter() - t0) * 1000, 1),
            # Only when EVERY page answered in detail: a partial list would make
            # the layers operate on a different document from the one
            # transcribed, and the page index would stop lining up.
            #
            # The comparison is against the pages SENT, not against the ones that
            # answered. A page that RAISED is counted in neither ``detailed`` nor
            # ``answered``, so comparing the two let the equality survive a hole:
            # the list came back compacted, ``layers.apply`` pairs it positionally
            # against the images, and page 3's line geometry was cropped out of
            # page 2's image — silently, on the exact documents where an engine
            # is already misbehaving.
            pages=detailed if len(detailed) == len(pages) else [],
            page_texts=page_texts,
            failures=failures,
        )

    def read_document(
        self,
        pdf_bytes: bytes,
        *,
        max_pages: int = 3,
        min_reliable_words: int = 3,
    ) -> LocalReading | None:
        """A witness reading: what this engine can read from the document.

        It feeds the vetoes that run before an expensive step, and the question
        it answers is not "what is the text?" but "is there legible text here?".

        The generic implementation rasterises and transcribes.
        ``reliable_words`` comes from the engine's aggregate confidence, because
        the common contract does not expose PER-WORD confidence — whoever does
        (Tesseract) overrides this method and measures properly, which is why it
        is the preferred witness.

        ``None`` means "I don't know": a missing engine or an unreadable PDF. It
        never becomes "there is no text" — the absence of a tool is not evidence
        about the page.
        """
        from autosxtract.pdf.render import render
        from autosxtract.quality.stamp import useful_words

        if not self.available()[0]:
            return None
        images = render(pdf_bytes, dpi=150, max_pages=max_pages, grayscale=True)
        if not images:
            return None
        transcription = self.transcribe(images, parallelism=1)
        if transcription is None:
            return None
        useful = useful_words(transcription.text)
        return LocalReading(
            text=transcription.text,
            words=useful,
            # Without per-word confidence the honest approximation is
            # all-or-nothing: either the engine read above the floor, or it did
            # not read.
            reliable_words=useful if transcription.mean_confidence >= 70.0 else 0,
            mean_confidence=transcription.mean_confidence,
            track=f"{self.name}/generic",
            pages_read=transcription.pages_answered,
        )


# ── registry ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EngineInfo:
    """A registry entry: how to build the engine and when to prefer it."""

    name: str
    factory: Callable[[], OCREngine]
    priority: int
    platforms: tuple[str, ...]
    extra: str
    description: str


_REGISTRY: dict[str, EngineInfo] = {}
#: Keyed by ``(name, frozen options)`` — see ``get``.
_INSTANCES: dict[tuple, OCREngine] = {}
_LOCK = threading.Lock()


def _first_line(doc: str | None) -> str:
    """The first non-empty line of a docstring, or ``""``.

    Never raises: a registry that refuses an engine because its author did not
    write a docstring is a registry that fails on the extension point it exists
    to offer.
    """
    for line in (doc or "").strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def register(
    *,
    name: str,
    priority: int,
    platforms: tuple[str, ...] = (),
    extra: str = "",
    description: str = "",
):
    """A decorator that puts an engine in the registry.

    ``priority`` is preference order, **lowest first**, and the default numbers
    come from comparative measurement on the same 60-document sample:

        10  Apple Vision   ~400 ms/page   92% of words, 100% of anchors
        20  PP-OCRv6 tiny  ~500 ms/page   the off-Apple candidate
        90  Tesseract      ~1.4 s/page    veto only; it does not persist text

    An engine that cannot run on the current platform is filtered out before it
    is instantiated, so declaring ``platforms`` avoids importing what is not
    there.
    """

    def decorator(cls):
        cls.name = name
        cls.platforms = platforms
        cls.extra = extra
        _REGISTRY[name] = EngineInfo(
            name=name,
            factory=cls,
            priority=priority,
            platforms=platforms,
            extra=extra,
            # ``splitlines()[0]`` on a class with no docstring is an IndexError
            # on an empty list — and this is the library's advertised extension
            # point, whose own worked example declares an engine with neither a
            # docstring nor a ``description``. It also took the whole package
            # down under ``python -OO``, where every ``__doc__`` is None.
            description=description or _first_line(cls.__doc__),
        )
        return cls

    return decorator


def _freeze(options: dict) -> tuple:
    """A hashable form of the options, for the instance cache key.

    Lists and dicts arrive here (``providers=["CPUExecutionProvider"]``) and
    cannot be dictionary keys. Sorting keeps ``{"a": 1, "b": 2}`` and
    ``{"b": 2, "a": 1}`` the same engine rather than two loaded models.
    """

    def norm(v):
        if isinstance(v, dict):
            return tuple(sorted((k, norm(x)) for k, x in v.items()))
        if isinstance(v, (list, tuple, set)):
            return tuple(norm(x) for x in v)
        return v

    return tuple(sorted((k, norm(v)) for k, v in options.items()))


def get(name: str, **options) -> OCREngine:
    """The shared instance of an engine, by name **and by options**.

    Shared on purpose: the loaded model is the expensive resource, and one
    instance per document would defeat the load cache.

    ``options`` go straight to the engine's constructor, and this is the only
    way to reach them: the registry builds engines with no arguments, so
    ``PaddleEngine``'s tier, INT8 flag, thread count and preprocessing were
    unreachable for anyone using the assembled cascade. A knob that exists in
    the constructor and cannot be turned from outside is not a knob.

        get("paddle", quantized=True)      # INT8 weights
        get("paddle", det="small", rec="medium")

    Different options are a DIFFERENT engine and get their own instance. Asking
    for INT8 must not hand back the FP32 model that somebody built first —
    that would be the silent kind of wrong, where the configuration is accepted
    and the measurement comes out unchanged.
    """
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY)) or "none"
        raise UnknownEngine(f"engine '{name}' is not registered; known: {known}")
    key = (name, _freeze(options))
    with _LOCK:
        if key not in _INSTANCES:
            _INSTANCES[key] = _REGISTRY[name].factory(**options)
        return _INSTANCES[key]


def registered() -> list[EngineInfo]:
    """Everything in the registry, most preferred first."""
    return sorted(_REGISTRY.values(), key=lambda i: (i.priority, i.name))


def compatible() -> list[EngineInfo]:
    """Those that make sense on **this** platform — without trying to load them."""
    system = platform.system()
    return [i for i in registered() if not i.platforms or system in i.platforms]


def available() -> list[EngineInfo]:
    """Those that actually load here and now. Costs each one's load."""
    ready = []
    for info in compatible():
        ok, _reason = get(info.name).available()
        if ok:
            ready.append(info)
    return ready


def diagnose() -> list[tuple[str, bool, str]]:
    """``(name, available, reason)`` for every registered engine.

    This is what the CLI prints for ``diagnose``: the question "why did the
    cascade pick this step?" must be answerable without reading code.
    """
    rows = []
    for info in registered():
        engine = get(info.name)
        ok, reason = engine.available()
        rows.append((info.name, ok, reason))
    return rows
