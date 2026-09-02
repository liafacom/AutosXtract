"""The contracts, checked against what ships — and against a fake that only obeys them.

An interface nobody verifies is a comment. This file is what makes
``autosxtract.interfaces`` load-bearing, and it does two different jobs:

**Conformance.** Every implementation the library ships must still satisfy the
protocol it claims, by ``isinstance`` and by signature. The drift this catches
is not hypothetical: the ``Engine`` protocol used to declare
``transcribe(pages, *, parallelism)`` while ``OCRStep`` had been passing
``force_parallelism`` for months. Nothing broke, because nothing looked — an
engine written to the published contract would have crashed on its first
document.

**Substitutability.** A hand-written fake that implements *only* the protocol —
no base class, no import of the concrete thing — has to work. That is the claim
the design makes ("a new engine is a class with one method"), and a claim about
extensibility is only true if somebody has extended it from the outside.

The fakes here inherit nothing on purpose. Deriving them from ``OCREngine``
would test the base class, which is not the same thing and is already covered.
"""

from __future__ import annotations

import importlib.util
import inspect
import pathlib
import sys
import types
from typing import Generic, Protocol

import pytest

from autosxtract import interfaces
from autosxtract.config import Config
from autosxtract.engines import registered
from autosxtract.engines.base import OCREngine, get
from autosxtract.interfaces import (
    DocumentContext,
    Engine,
    Gate,
    GateVerdict,
    InkSignals,
    LexiconLike,
    PageSource,
    Renderer,
    Scorer,
    StampStripper,
    Step,
    Tokenizer,
)
from autosxtract.pdf.profile import PageProfile
from autosxtract.types import Attempt, Candidate, Line, Page, Transcription

PROSE = (
    "O requerente vem respeitosamente a presenca de Vossa Excelencia nos "
    "autos do processo 0001234-56.2020.8.12.0001 requerer a citacao do "
    "requerido, tendo em vista a decisao proferida pela vara civel e a "
    "certidao do oficial de justica que instrui o presente pedido para que "
    "sejam produzidos os efeitos legais de direito."
)


# ── signature comparison ─────────────────────────────────────────────────


def _parameters(func) -> dict[str, inspect.Parameter]:
    return {n: p for n, p in inspect.signature(func).parameters.items() if n != "self"}


def _protocol_members(protocol: type) -> set[str]:
    """The names a protocol requires, read from the class bodies.

    ``__protocol_attrs__`` is the direct answer and exists only on CPython
    3.12+; on 3.11 the same set sits behind the private
    ``typing._get_protocol_attrs``. This suite runs on 3.11, 3.12 and 3.13, so
    a test that reaches for either is a test that passes on two interpreters
    out of three — and it failed on the one the project supports first.

    Walking the MRO is neither, and it is what the protocol actually declares:
    every public name in a class body, whether a method, a property or a bare
    annotation.
    """
    members: set[str] = set()
    for klass in protocol.__mro__:
        if klass in (object, Protocol, Generic):
            continue
        members.update(name for name in vars(klass) if not name.startswith("_"))
        members.update(
            name for name in getattr(klass, "__annotations__", {}) if not name.startswith("_")
        )
    return members


def _assert_signature(implementation, declared) -> None:
    """The implementation must accept everything the protocol promises callers.

    Extra parameters are allowed only when they have a default: a caller holding
    the protocol never passes them, so a required one would make the contract a
    lie in the direction that actually breaks — at the call site, not in the
    editor.
    """
    expected = _parameters(declared)
    actual = _parameters(implementation)
    for name, param in expected.items():
        assert name in actual, f"{implementation.__qualname__} does not accept {name!r}"
        assert actual[name].kind == param.kind, name
        if param.default is not inspect.Parameter.empty:
            assert actual[name].default is not inspect.Parameter.empty, name
    for name, param in actual.items():
        if name not in expected and param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            assert param.default is not inspect.Parameter.empty, (
                f"{implementation.__qualname__} requires {name!r}, which the protocol never sends"
            )


def test_every_protocol_is_runtime_checkable():
    """Otherwise this whole file could only assert that the names exist."""
    for name in interfaces.__all__:
        protocol = getattr(interfaces, name)
        assert getattr(protocol, "_is_runtime_protocol", False), name


def test_the_module_pulls_in_nothing_at_import_time():
    """The contracts sit below every layer, and importing one must prove it.

    If ``interfaces`` ever imported what implements it, the file would stop
    being a way to depend on a contract without depending on the code behind
    it — and the layering of CLAUDE.md section 10 would be a convention again.
    """
    # Checked by EXECUTING the module, not by reading its source.
    #
    # The substring version — splitting on ``if TYPE_CHECKING:`` and asserting
    # "import autosxtract" is absent from the head — had two holes wide enough
    # to drive the invariant through: a RELATIVE import (``from .config import
    # Config``) matches neither string, and anything placed after the
    # ``TYPE_CHECKING`` block is outside the text being inspected entirely.
    #
    # It is loaded BY PATH, under a name outside the package, so that importing
    # it does not run ``autosxtract/__init__.py`` — which imports the cascade and
    # would answer for the package's eagerness rather than for this module's.
    # That is exactly the property being pinned: ``interfaces`` has to be usable
    # without anything underneath it existing.
    path = pathlib.Path(inspect.getfile(interfaces))
    spec = importlib.util.spec_from_file_location("_isolated_interfaces", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)

    # The comparison CANNOT be a ``sys.modules`` diff: this very file does
    # ``from autosxtract import interfaces`` at the top, so the package and its
    # 49 submodules are already loaded before the snapshot is taken and an eager
    # absolute import could never show up in the difference. What is inspected
    # instead is what the module's own execution BOUND.
    sys.modules["_isolated_interfaces"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("_isolated_interfaces", None)

    bound_modules = sorted(
        name
        for name, value in vars(module).items()
        if isinstance(value, types.ModuleType) and value.__name__.startswith("autosxtract")
    )
    assert bound_modules == [], f"interfaces bound the module(s) {bound_modules}"

    # ``from autosxtract.config import Config`` binds a CLASS, not a module, so
    # the check above would not see it. Anything defined inside the package and
    # not part of the published contract is an eager import.
    leaked = sorted(
        name
        for name, value in vars(module).items()
        if not name.startswith("_")
        and getattr(value, "__module__", "").startswith("autosxtract")
        and name not in set(interfaces.__all__)
    )
    assert leaked == [], f"interfaces bound {leaked} from inside the package"

    # And the contracts really did load — otherwise the assertions above are
    # satisfied by a module that failed to define anything.
    assert set(interfaces.__all__) <= set(vars(module))


# ── engines ──────────────────────────────────────────────────────────────


def test_the_base_engine_satisfies_the_engine_contract():
    assert isinstance(OCREngine(), Engine)


@pytest.mark.parametrize("info", registered(), ids=lambda i: i.name)
def test_every_registered_engine_satisfies_the_engine_contract(info):
    """Instantiating is cheap: the model loads lazily and only when asked.

    An engine that cannot run here is still an ``Engine`` — that is the point of
    ``available()`` returning a reason instead of raising.
    """
    assert isinstance(get(info.name), Engine)


@pytest.mark.parametrize(
    "method",
    ["available", "transcribe_page", "read_page", "recognize_crop", "transcribe", "read_document"],
)
def test_the_base_engine_matches_the_declared_signatures(method):
    _assert_signature(getattr(OCREngine, method), getattr(Engine, method))


def test_the_engine_contract_names_what_the_ocr_step_actually_uses():
    """The regression that motivated moving this protocol into one file.

    ``OCRStep`` reads ``scales_with_threads`` and passes ``force_parallelism`` on
    every document. A protocol that omits them describes an engine the library
    does not accept.
    """
    assert "scales_with_threads" in Engine.__annotations__
    assert "force_parallelism" in _parameters(Engine.transcribe)


# ── steps ────────────────────────────────────────────────────────────────


def test_every_shipped_step_satisfies_the_step_contract():
    from autosxtract.steps import NativeStep, OCRStep, ScreeningStep, UnwrapStep

    for step in (NativeStep(), ScreeningStep(), UnwrapStep(), OCRStep(OCREngine())):
        assert isinstance(step, Step), step
        _assert_signature(type(step).run, Step.run)


def test_the_default_cascade_is_assembled_out_of_steps():
    from autosxtract.cascade import Cascade

    for step in Cascade(Config(engines=[])).steps:
        assert isinstance(step, Step), step


# ── the context handed to a step ─────────────────────────────────────────


def test_the_shipped_ink_module_satisfies_the_pixel_signal_contract():
    """The MODULE is the implementation — there is no adapter class.

    ``quality.vetoes`` used to import the two functions by name, which made
    ``quality/`` open a PDF and left the two pixel vetoes untestable. This is
    what stops that import coming back: the contract is the thing depended on,
    and ``pdf.ink`` has to keep satisfying it.
    """
    from autosxtract.pdf import ink

    assert isinstance(ink, InkSignals)


def test_the_real_context_satisfies_the_view_given_to_steps():
    from autosxtract.steps.base import Context

    ctx = Context(pdf_bytes=b"", config=Config())
    assert isinstance(ctx, PageSource)
    assert isinstance(ctx, DocumentContext)


def test_the_step_view_withholds_the_cascade_s_own_evidence():
    """``readings`` and ``texts`` are the gates' evidence, not a step's input.

    A step reading them would decide on what it did not gather, and the
    consensus and agreement gates would stop being answerable from one place.
    """
    members = _protocol_members(DocumentContext)

    # The anchor comes first: an empty set would satisfy both absences below
    # while proving nothing, and that is exactly how this test would rot into
    # a comment.
    assert {"config", "profile", "best_text", "record_reading"} <= members

    assert "readings" not in members
    assert "texts" not in members


# ── text, and what judges it ─────────────────────────────────────────────


def test_the_stamp_satisfies_the_stripping_and_tokenising_contracts():
    from autosxtract.quality.stamp import Stamp, default

    for stamp in (Stamp(), default(None)):
        assert isinstance(stamp, Tokenizer)
        assert isinstance(stamp, StampStripper)


def test_the_builtin_lexicon_satisfies_the_lexicon_contract():
    from autosxtract.quality.lexicon import Lexicon

    assert isinstance(Lexicon.builtin(), LexiconLike)


def test_the_scorer_matches_the_declared_contract():
    from autosxtract.quality.scoring import score_text

    assert isinstance(score_text, Scorer)
    _assert_signature(score_text, Scorer.__call__)


def test_the_renderer_matches_the_declared_contract():
    from autosxtract.pdf.render import render

    assert isinstance(render, Renderer)
    _assert_signature(render, Renderer.__call__)


def test_the_gate_matches_the_declared_contract():
    from autosxtract.quality.gate import evaluate

    assert isinstance(evaluate, Gate)
    _assert_signature(evaluate, Gate.__call__)


def test_the_gate_contract_repeats_no_threshold_of_its_own():
    """A protocol that restated a threshold would be a second place to change it.

    Every number in ``evaluate`` was measured. Copying them into the contract and
    letting the two drift is how a pipeline ends up with two notions of adequate
    extraction — the exact defect the single gate exists to prevent.
    """
    from autosxtract.quality.gate import evaluate

    declared = _parameters(Gate.__call__)
    for name, param in _parameters(evaluate).items():
        if param.default is not inspect.Parameter.empty and name in declared:
            assert declared[name].default == param.default, name


def test_a_verdict_is_a_decision_plus_its_reason():
    from autosxtract.quality.gate import evaluate

    verdict = evaluate("", PageProfile(pages=1, has_image=True))
    assert isinstance(verdict, GateVerdict)
    assert verdict.reason


# ── the fakes: implementing the contract and nothing else ────────────────


class FakeEngine:
    """An engine written from the protocol alone — no base class, no import.

    Ten lines, and the cascade must run it. If that fails, "a new engine is a
    class with one method" is marketing.
    """

    name = "fake"
    scales_with_threads = True

    def __init__(self, text: str = PROSE) -> None:
        self.text = text
        self.pages_seen = 0

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        self.pages_seen += 1
        return self.text, 95.0

    def read_page(self, image: bytes) -> Page | None:
        return None

    def recognize_crop(self, image: bytes) -> tuple[str, float] | None:
        return None

    def transcribe(
        self, pages: list[bytes], *, parallelism: int = 4, force_parallelism: bool = False
    ) -> Transcription | None:
        texts = [self.transcribe_page(p)[0] for p in pages]
        return Transcription(
            text="\n\n".join(texts),
            engine=self.name,
            pages_sent=len(pages),
            pages_answered=len(pages),
            mean_confidence=95.0,
        )

    def read_document(self, pdf_bytes: bytes, *, max_pages: int = 3, min_reliable_words: int = 3):
        return None


class FakeStep:
    """A step written from the protocol alone. It never opens the document."""

    name = "fake_step"

    def __init__(self, text: str = PROSE) -> None:
        self.text = text

    def run(self, ctx: DocumentContext):
        from autosxtract.steps.base import StepResult

        ctx.record_reading(self.name, self.text)
        return StepResult(
            Attempt(self.name, True, "fake", len(self.text), 0.0),
            Candidate(step=self.name, text=self.text, score=0.9),
        )


class FakeContext:
    """The whole of what a step is allowed to assume, in twenty lines.

    Its existence is the argument for the protocol: before it, exercising a step
    meant a real PDF, PyMuPDF and a profile read off disk.
    """

    def __init__(self, pdf_bytes: bytes = b"%PDF-fake", text: str = "") -> None:
        self.pdf_bytes = pdf_bytes
        self.config = Config()
        self.recorded: dict[str, str] = {}
        self._text = text
        # Empty = the orientation fix was never asked for. A step reads this to
        # report whether the page was turned before the engine saw it.
        self.orientation: dict = {}

    def images(self, *, indices: list[int] | None = None) -> list[bytes]:
        return [b"\x89PNG-one-page"]

    @property
    def profile(self) -> PageProfile:
        return PageProfile(pages=1, has_image=True)

    @property
    def pages_without_text(self) -> list[int] | None:
        return None

    def best_text(self) -> str:
        return self._text

    def record_reading(self, engine: str, text: str) -> None:
        self.recorded[engine] = text

    def replace_bytes(self, new_bytes: bytes) -> None:
        self.pdf_bytes = new_bytes


def test_the_fakes_satisfy_the_contracts_they_were_written_from():
    assert isinstance(FakeEngine(), Engine)
    assert isinstance(FakeStep(), Step)
    assert isinstance(FakeContext(), DocumentContext)


def test_a_step_runs_against_a_fake_context_with_no_pdf_at_all():
    """The payoff: a step exercised without a document, an engine or PyMuPDF."""
    from autosxtract.steps.screening import ScreeningStep

    ctx = FakeContext(text="CARTEIRA DE IDENTIDADE " + PROSE)
    result = ScreeningStep().run(ctx)
    assert result.attempt.step == "screening"


def test_an_ocr_step_drives_a_fake_engine_through_a_fake_context():
    from autosxtract.steps.ocr import OCRStep

    engine = FakeEngine()
    result = OCRStep(engine).run(FakeContext())
    assert engine.pages_seen == 1
    assert result.accepted
    assert result.candidate is not None
    assert result.candidate.text.startswith("O requerente")


def test_a_protocol_only_engine_descends_the_real_cascade(pdf_scanned):
    from autosxtract.cascade import Cascade
    from autosxtract.steps.ocr import OCRStep

    engine = FakeEngine()
    cascade = Cascade(Config(use_native=False), steps=[OCRStep(engine)])
    result = cascade.extract(pdf_scanned)
    assert result.step == "fake"
    assert engine.pages_seen > 0
    assert "O requerente" in result.text


def test_a_protocol_only_step_descends_the_real_cascade():
    from autosxtract.cascade import Cascade

    cascade = Cascade(Config(), steps=[FakeStep()])
    result = cascade.extract(b"not a pdf at all")
    assert result.step == "fake_step"
    assert result.text.startswith("O requerente")


def test_an_injected_renderer_replaces_pymupdf_entirely():
    """``Context`` asks for a ``Renderer``, so the pixels can be invented.

    The cache is part of the contract, not an implementation detail: two engines
    on one document must be handed the same pixels, or the difference measured
    between them is preprocessing noise.
    """
    from autosxtract.steps.base import Context

    calls: list[dict] = []

    def renderer(pdf_bytes, *, dpi=150, max_pages=64, grayscale=True, indices=None):
        calls.append({"dpi": dpi, "max_pages": max_pages, "grayscale": grayscale})
        return [b"page-one", b"page-two"]

    assert isinstance(renderer, Renderer)
    ctx = Context(pdf_bytes=b"not a pdf", config=Config(dpi=300), renderer=renderer)
    assert ctx.images() == [b"page-one", b"page-two"]
    assert ctx.images() == [b"page-one", b"page-two"]
    assert len(calls) == 1, "the second call must come from the cache"
    assert calls[0]["dpi"] == 300


def test_an_injected_tokenizer_decides_what_counts_as_a_word():
    """``record_reading`` is the consensus gate's vote, and it is counted here."""
    from autosxtract.steps.base import Context

    class EverySecondWord:
        def words(self, text: str) -> list[str]:
            return text.split()[::2]

        def count(self, text: str) -> int:
            return len(self.words(text))

        def vocabulary(self, text: str) -> set[str]:
            return set(self.words(text))

        def strip(self, text: str) -> str:
            return text

    tokenizer = EverySecondWord()
    assert isinstance(tokenizer, Tokenizer)
    assert isinstance(tokenizer, StampStripper)

    ctx = Context(pdf_bytes=b"", config=Config(), tokenizer=tokenizer)
    ctx.record_reading("fake", "um dois tres quatro")
    assert ctx.readings["fake"] == 2


def test_the_default_tokenizer_is_still_the_stamp_stripper():
    """No injection must change a single number the gates already measure."""
    from autosxtract.quality.stamp import default
    from autosxtract.steps.base import Context

    config = Config()
    ctx = Context(pdf_bytes=b"", config=config)
    ctx.record_reading("fake", PROSE)
    assert ctx.readings["fake"] == default(config.stamps).count(PROSE)


def test_a_lexicon_written_from_the_protocol_is_accepted_by_the_layers():
    """The adaptation seam: the built-in word list is a floor, not a truth."""
    from autosxtract.quality.lines import contain

    class KnowsEverything:
        def __contains__(self, word: str) -> bool:
            return True

        def coverage(self, text: str) -> float:
            return 1.0

        def tokens(self, text: str) -> list[str]:
            return text.lower().split()

    lexicon = KnowsEverything()
    assert isinstance(lexicon, LexiconLike)

    page = Page(
        lines=[
            Line(
                text="peticao inicial do requerente",
                score=0.95,
                poly=((10, 10), (300, 10), (300, 30), (10, 30)),
            )
        ],
        width=600.0,
        height=800.0,
    )
    containment = contain(page, lexicon=lexicon)
    assert "peticao inicial do requerente" in containment.text


def test_an_injected_gate_and_scorer_reach_the_ocr_step():
    """Injectable, and still one gate: what is passed here is what decides."""
    from autosxtract.quality.gate import Verdict
    from autosxtract.steps.ocr import OCRStep

    seen: list[str] = []

    def gate(text, profile, **kwargs) -> Verdict:
        seen.append(text)
        return Verdict(True, "refused by the injected gate")

    def scorer(text, domain_patterns=None):
        return {"score": 0.5, "label": "fair", "reasons": [], "metrics": {}}

    step = OCRStep(FakeEngine(), gate=gate, scorer=scorer)
    result = step.run(FakeContext())
    assert seen and not result.accepted
    assert result.attempt.reason == "refused by the injected gate"
    assert result.candidate is not None and result.candidate.score == 0.5
