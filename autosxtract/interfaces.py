"""The contracts — every collaboration in the library, written down once.

A subsystem here talks to another through a name declared in this file, not
through an import of the class that happens to implement it today. That is the
whole difference between "the OCR step calls ``PaddleEngine``" and "the OCR step
calls something that reads pixels": only the second survives somebody adding an
engine, and only the second can be exercised on a machine where the engine is
not installed — which is every CI runner this project has.

Everything here is a ``typing.Protocol``, and structural on purpose: an
implementation does **not** inherit from these. A class satisfies a contract by
having the methods, which is what lets ``quality.stamp.Stamp`` — written long
before this file existed — be a ``StampStripper`` without one line of it
changing. Requiring inheritance would have made the same refactor a rewrite.

They are all ``@runtime_checkable`` so ``tests/contract/test_interfaces.py`` can assert
that every shipped implementation still satisfies the contract it claims. That
test is what makes the file worth anything: an interface nobody checks is a
comment, and this one had already drifted — the ``Engine`` protocol declared
``transcribe(pages, *, parallelism)`` while ``OCRStep`` had been passing
``force_parallelism`` for months. Nothing failed, because nothing looked.

The module imports **nothing at runtime**: every name it mentions arrives under
``TYPE_CHECKING``. Importing a contract therefore never drags in what implements
it, and the layering of CLAUDE.md §10 stays a fact rather than a convention —
``interfaces`` sits below all five layers and depends on none of them.

Where each contract is consumed:

    Renderer         ``Context.images``
    PageSource       anything that needs pixels and nothing else
    DocumentContext  every step's ``run``
    Engine           ``OCRStep``, ``steps.layers``
    Step             ``Cascade``
    Tokenizer        ``Context.record_reading``
    StampStripper    ``Tokenizer`` plus the stripping the gates measure through
    LexiconLike      ``steps.layers``, ``Config.lexicon``
    Scorer / Gate    ``OCRStep``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from autosxtract.config import Config
    from autosxtract.pdf.profile import PageProfile
    from autosxtract.quality.vetoes import LocalReading
    from autosxtract.steps.base import StepResult
    from autosxtract.types import Page, Transcription

__all__ = [
    "DocumentContext",
    "Engine",
    "Gate",
    "GateVerdict",
    "InkSignals",
    "LexiconLike",
    "PageSource",
    "Renderer",
    "Scorer",
    "StampStripper",
    "Step",
    "Tokenizer",
]


# ── the document, as the steps see it ────────────────────────────────────


@runtime_checkable
class Renderer(Protocol):
    """Turning a PDF into page images. Implemented by ``pdf.render.render``.

    The signature is the easy half of this contract; the promise is the other:
    **the same arguments give back the same pixels**. Two engines compared on
    one document have to receive identical images, otherwise the difference
    measured between them is preprocessing noise rather than evidence about the
    engines — and comparing engines is how every threshold in ``config`` was
    fixed. ``Context`` caches renders on that promise, so a renderer that
    quietly varies its output does not merely mislead, it poisons the cache.

    ``[]`` is a legitimate answer, not a failure: an unreadable PDF, or nothing
    left to rasterise. A renderer that raises instead turns a document the
    cascade could have degraded through into a traceback, which is the one
    outcome the library never produces.

    Injectable so a step can be driven over invented pixels without PyMuPDF
    opening anything — and PyMuPDF is precisely what cannot be run freely
    (CLAUDE.md §6).
    """

    def __call__(
        self,
        pdf_bytes: bytes,
        *,
        dpi: int = 150,
        max_pages: int = 64,
        grayscale: bool = True,
        indices: list[int] | None = None,
    ) -> list[bytes]: ...


@runtime_checkable
class InkSignals(Protocol):
    """The two pixel statistics the vetoes run before the expensive step.

    Satisfied by the ``pdf.ink`` MODULE itself — the two functions are its
    attributes, so there is no adapter class to keep in step with it.

    It exists for the same reason ``Renderer`` does. ``quality.vetoes`` used to
    call ``pdf.ink`` directly, which made ``quality/`` open a PDF (against
    CLAUDE.md §10) and left the two vetoes with no seam to test through: every
    unit test had to pass ``pixel_signals=False``, and lines 97-100 of
    ``vetoes.py`` were the only uncovered ones in the module.

    That gap was in the worst place. CLAUDE.md §13 warns that these two are
    **only valid together with "extracted no text"** — on their own they discard
    an old photocopy on dark paper, which is continuous tone and carries
    thousands of legitimate characters (measured: 0.99 / 0.99 / 0.83 mid-tone
    with 1,001, 2,612 and 632 characters). The branch that can throw a readable
    document away was the branch no test exercised.
    """

    def is_photograph(self, pdf_bytes: bytes) -> bool:
        """Continuous tone across the page — a photograph, not a scanned text."""
        ...

    def is_nearly_blank(self, pdf_bytes: bytes) -> bool:
        """Almost no ink outside the conformity stamp."""
        ...


@runtime_checkable
class PageSource(Protocol):
    """A document's bytes and its rasterised pages, paid for once.

    The narrow half of ``DocumentContext``, kept separate so that whatever needs
    only pixels can say so in its own signature. A collaborator asking for the
    whole context when it looks at nothing but images is how a helper silently
    acquires the right to read the configuration and record readings.

    ``images`` caches: rasterising is the second most expensive thing the
    cascade does after OCR itself, and every step of a document must be handed
    the same pixels rather than its own render.
    """

    @property
    def pdf_bytes(self) -> bytes: ...

    def images(self, *, indices: list[int] | None = None) -> list[bytes]: ...


@runtime_checkable
class DocumentContext(PageSource, Protocol):
    """Everything a step may rely on about the document — and nothing more.

    ``steps.base.Context`` implements it. A step should ask for **this**, because
    then a test can hand it thirty lines of fake instead of a real PDF, and a
    step written outside the library is told exactly what it is allowed to
    assume. The list is short on purpose: it is the audit of what the shipped
    steps actually touch, not a copy of ``Context``'s attributes.

    What is deliberately **absent** is as much of the contract as what is here.
    ``readings`` and ``texts`` are the blackboard the consensus and agreement
    gates read, and those gates belong to the cascade, not to a step. A step
    that reached into them would be deciding on evidence it did not gather, and
    the two gates would stop being answerable from one place.

    Two members mutate, and both earn it:

    ``record_reading``  is how a **refused** step still counts as a vote. The
        consensus gate only means "there is no text here" because every engine,
        including the ones that were turned down, left what it read. Free at the
        point of decision, and unavailable afterwards.
    ``replace_bytes``   is the unwrap step swapping an envelope for its payload.
        Without it the following steps would measure the wrapper — the whole
        point of stage 0 lost, and 128 documents of a real archive unreadable.
    """

    @property
    def config(self) -> Config: ...

    @property
    def profile(self) -> PageProfile: ...

    @property
    def pages_without_text(self) -> list[int] | None:
        """Pages with no native text; ``None`` when the structure is unreadable.

        ``None`` and ``[]`` are different answers and the routing depends on it:
        "I could not tell" must fall back to rasterising everything, while "no
        page is missing text" means there is nothing to OCR.
        """
        ...

    def best_text(self) -> str: ...

    def record_reading(self, engine: str, text: str) -> None: ...

    def replace_bytes(self, new_bytes: bytes) -> None: ...


# ── the two extension points ─────────────────────────────────────────────


@runtime_checkable
class Engine(Protocol):
    """What the cascade requires of an OCR engine — the first extension point.

    ``engines.base.OCREngine`` implements all of it, and inheriting from that
    base is the easy road: a subclass writes ``_load`` and one of the two
    reading methods. Inheritance is not required, though; this protocol is, and
    it is what ``OCRStep`` asks for.

    Two rules the contract carries, both measured:

    **Confidence does not arbitrate quality.** Across 60 audited documents,
    engine confidence did not separate a good reading from an unsafe one —
    there was an unsafe document at 100. It enters as a floor against degenerate
    output; the gate decides.

    **A missing engine is never an exception.** ``available`` returns
    ``(False, reason)`` in words, the step goes inert and the cascade moves on.
    The absence of a tool is not evidence about the document — treating "I have
    no OCR" as "the page is empty" switches the pipeline off in silence.

    ``read_page`` and ``recognize_crop`` may answer ``None``: that is the honest
    reply from an engine without geometry or without a detection-free path, and
    it blocks nothing. What it costs is the containment layers, the cheapest
    measured gain in the pipeline (entity recall 0.902 -> 0.921, and latency
    *falls* from 298 to 236 ms), so implement them when the backend exposes
    geometry.

    ``scales_with_threads`` and ``force_parallelism`` are on the contract rather
    than on the base class because ``OCRStep`` reads and passes them on every
    document. Leaving them off the protocol is how it came to describe an engine
    the library does not actually accept.
    """

    name: str
    #: Do threads add throughput here? ``False`` for a single hardware queue —
    #: Apple's Neural Engine served one request at a time while latency went
    #: from 430 ms to 3,492 ms across 1 to 12 threads, at constant throughput.
    #: The engine is the only party that knows this, so it is the one that says.
    scales_with_threads: bool

    def available(self) -> tuple[bool, str]:
        """``(can_run, reason)``. The reason is for logs, and it matters."""
        ...

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        """One page, image bytes -> ``(text, confidence 0-100)``."""
        ...

    def read_page(self, image: bytes) -> Page | None:
        """The same page, line by line. ``None`` = engine without geometry."""
        ...

    def recognize_crop(self, image: bytes) -> tuple[str, float] | None:
        """Recognise only, without detecting. ``None`` = engine without that path."""
        ...

    def transcribe(
        self,
        pages: list[bytes],
        *,
        parallelism: int = 4,
        force_parallelism: bool = False,
    ) -> Transcription | None:
        """The whole document, preserving page order.

        Order is part of the contract: reassembling in completion order
        scrambles the document, and nothing downstream can tell that it did.
        """
        ...

    def read_document(
        self,
        pdf_bytes: bytes,
        *,
        max_pages: int = 3,
        min_reliable_words: int = 3,
    ) -> LocalReading | None:
        """A witness reading, for the vetoes that run before an expensive step.

        ``None`` means "I don't know" and skips the vetoes that depend on it. It
        never becomes "there is no text".
        """
        ...


@runtime_checkable
class Step(Protocol):
    """One attempt at extraction, with a reason for whatever happens.

    The second extension point, and the smaller one: a name and a ``run``. It
    joins the cascade through ``Cascade(steps=[...])`` and nothing else changes,
    which is exactly what the fake engines in the test suite demonstrate.

    ``run`` returns a ``StepResult``, and the reason that type has two fields is
    the costliest defect this library has fixed: a step may have produced text
    **and** been refused, and the text still competes. Returning ``None`` for a
    refusal left 682 documents with zero characters while the PDF had a text
    layer.

    An optional ``expensive = True`` class attribute makes the cascade run the
    five vetoes before the step and submit its output to the replacement gate
    afterwards. It is read with ``getattr`` and stays off this protocol on
    purpose: making it mandatory would force every three-line step to declare
    that it is cheap.
    """

    name: str

    def run(self, ctx: DocumentContext) -> StepResult: ...


# ── text, and what judges it ─────────────────────────────────────────────


@runtime_checkable
class Tokenizer(Protocol):
    """The single answer to "what is a word here?".

    Whoever **counts** useful words and whoever **compares** two readings have
    to agree on this, or the two gates that depend on them diverge without ever
    disagreeing out loud: one engine's text passes the word floor and the same
    text fails the vocabulary overlap. That is why there is one tokeniser and
    not a regex per call site.

    ``quality.stamp.Stamp`` implements it, and the counting is what makes the
    numbers mean anything.
    """

    def words(self, text: str) -> list[str]: ...

    def count(self, text: str) -> int: ...

    def vocabulary(self, text: str) -> set[str]: ...


@runtime_checkable
class StampStripper(Tokenizer, Protocol):
    """A tokeniser that first removes the boilerplate banner off the page.

    Every digital case-file system prints a conformity stamp in the margin, in a
    font whose encoding survives when the body of the page produces nothing.
    That is 250 to 600 characters that sail past any size threshold: in an audit
    of 1,339 documents, 227 extractions looked successful and all there was, was
    the stamp. **Measuring an extraction without stripping is measuring the
    stamp.**

    This is also the library's adaptation seam. The shipped patterns are
    Brazilian court boilerplate; another corpus supplies its own through
    ``Config.stamps`` or its own implementation of this protocol, and no
    measurement code changes, because everyone measures through here.
    """

    def strip(self, text: str) -> str: ...


@runtime_checkable
class LexiconLike(Protocol):
    """The vocabulary a line is judged readable against.

    ``quality.lexicon.Lexicon`` implements it, and ``Config.lexicon`` accepts
    it — the field is typed loosely there for pydantic's sake, so this protocol
    is where the actual requirement is written down.

    It is injectable because the built-in word list is a floor, not a truth:
    anyone with a validated archive builds a measurably better one. And there is
    one failure mode worth stating before anybody does, since it points the
    wrong way round: **a lexicon that is too small makes correct text look like
    junk.** That error is the safe one — the line falls to ``suspect``, the text
    still passes, the page merely loses confidence — but a lexicon full of OCR
    errors is the unsafe one, which is why ``Lexicon.from_texts`` drops what
    appears fewer than three times.

    ``coverage`` must answer ``1.0`` for a line with no alphabetic token. A case
    number and a date are not words, and punishing them for being absent
    classifies exactly what matters most to preserve as junk.
    """

    def __contains__(self, word: str) -> bool: ...

    def coverage(self, text: str) -> float: ...

    def tokens(self, text: str) -> list[str]: ...


@runtime_checkable
class Scorer(Protocol):
    """Text -> a number between 0 and 1, with the reasons in words.

    ``quality.scoring.score_text`` implements it. The reasons are not decoration:
    the score alone is not auditable, and "why was this step refused?" has to be
    answerable from the result rather than from the source.

    The number settles the contest between candidates, so two properties are
    load-bearing. Empty text must score ``0.0`` explicitly — summing the
    degenerate-text penalties leaves an empty string at 0.15, competing with real
    text. And the scale must stay comparable across steps, because the native
    step and every OCR step put their candidates in the same contest.
    """

    def __call__(self, text: str, domain_patterns: list[str] | None = None) -> dict[str, Any]: ...


@runtime_checkable
class GateVerdict(Protocol):
    """A decision plus the sentence that justifies it.

    The reason travels into the provenance, which is the library's product as
    much as the text is: "the system extracted the text" is not an auditable
    answer, "the native step read 41 characters and was refused on density" is.
    A gate returning a bare ``bool`` would satisfy the cascade and destroy that.
    """

    @property
    def escalate(self) -> bool: ...

    @property
    def reason(self) -> str: ...


@runtime_checkable
class Gate(Protocol):
    """Is this text good enough to stop the cascade? Implemented by ``quality.gate.evaluate``.

    There is **one** acceptance criterion in this pipeline, and this protocol is
    a contract about that as much as about a signature: whoever decides the
    current step solved it and whoever decides the next one is worth paying for
    must ask the same question with the same code. Two competing notions of
    "adequate extraction" in one pipeline was the defect ``evaluate`` exists to
    stop repeating — the step approved itself by one criterion and the cascade
    refused it by another.

    So a replacement gate is a legitimate thing to inject; a **second** gate
    alongside the first is not. Note that the replacement gate of
    ``quality.rejection`` is deliberately not this contract: it compares against
    a concrete earlier text rather than a threshold, and what it refuses is
    discarded rather than left in the contest.

    It takes the text, the page profile and the thresholds. No I/O, no network,
    no global configuration — which is what lets it be called from both sides of
    the decision at no cost.
    """

    def __call__(
        self,
        text: str,
        profile: PageProfile,
        *,
        min_useful_words: int = 12,
        min_chars_per_page: int = 200,
        score: float | None = None,
        min_score: float = 0.35,
        glyph_index: float = 0.0,
        stamps: tuple[str, ...] | None = None,
    ) -> GateVerdict: ...
