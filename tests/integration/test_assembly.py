"""How a cascade gets assembled: which steps, in what order, with what options.

Nothing here extracts a document. What is under test is the seam where four
layers meet — the platform, the engine registry, the configuration and
``Cascade`` — and that seam is exactly where a shortened cascade hides. A
missing step does not announce itself: the extraction still succeeds, with worse
text, and the provenance is the only place the absence shows.

The individual pieces are answered in the unit slice (``test_platform``,
``test_config``, ``test_registry``). Here they are asked together.
"""

from __future__ import annotations

import pytest

from autosxtract.cascade import Cascade, engine_order
from autosxtract.config import Config

# ── the order of the steps ───────────────────────────────────────────────


def test_an_explicit_order_wins():
    """Naming an unavailable engine becomes a refused attempt, not an error."""
    assert engine_order(Config(engines=["vision"])) == ["vision"]


def test_the_cascade_always_starts_with_native():
    assert Cascade().names[0] == "native"


def test_native_can_be_turned_off():
    names = Cascade(Config(use_native=False, engines=[])).names
    assert "native" not in names


@pytest.mark.apple
def test_ocrmac_stays_out_when_vision_comes_in():
    """They are the same Apple engine; the second is the first's safety net.

    Marked ``apple`` because it can only conclude anything where Vision loads.
    Off Apple hardware ``vision`` is never in the order and the assertion below
    never runs — a test that passes by being inert, which is precisely what the
    marker exists to deselect on the Linux CI rather than count as green.
    """
    order = engine_order()
    if "vision" in order:
        assert "ocrmac" not in order


# ── the witness does not transcribe ──────────────────────────────────────


def test_the_veto_witness_stays_out_of_the_chain():
    """An engine cannot both produce a candidate and vouch for the others.

    The vetoes ask "does a DIFFERENT architecture also see text on this page?".
    An engine that answers about its own output answers nothing. And Tesseract
    in the chain would also enter the CONTEST, where at ~1.4 s/page it competes
    on volume against readings that are better and shorter.
    """
    order = engine_order(Config(veto_engine="tesseract"))
    assert "tesseract" not in order


def test_naming_the_witness_explicitly_wins():
    """``engines`` is the operator's choice, and silencing it would be worse."""
    order = engine_order(Config(engines=["tesseract"], veto_engine="tesseract"))
    assert order == ["tesseract"]


@pytest.mark.slow
def test_without_a_witness_every_engine_transcribes():
    """``veto_engine=None`` turns the three witness vetoes off — and then there
    is no reason to hold the engine back from the chain.

    Marked ``slow``: ``available()`` loads every compatible engine to find out.
    """
    from autosxtract.engines import base as engines

    available = {i.name for i in engines.available()}
    order = engine_order(Config(veto_engine=None))
    if "tesseract" in available:
        assert "tesseract" in order


# ── the options reach the engine the cascade built ───────────────────────


def test_engine_options_reach_the_assembled_cascade():
    """The field is worthless if the cascade does not pass it on — the defect
    it exists to fix was exactly a knob that nothing consulted."""
    order = engine_order(Config())
    if "paddle" not in order:
        pytest.skip("paddle is not available on this machine")

    cascade = Cascade(Config(engine_options={"paddle": {"det": "small", "threads": 3}}))
    paddle = next(s.engine for s in cascade.steps if getattr(s, "name", "") == "paddle")
    assert paddle.det == "small"
    assert paddle.threads == 3

    # E a cascata sem opções continua recebendo o motor compartilhado padrão.
    assert (
        next(s.engine for s in Cascade(Config()).steps if getattr(s, "name", "") == "paddle").det
        == "tiny"
    )


# ── the operator overrules the engine ────────────────────────────────────


def test_an_engine_that_declares_a_single_queue_can_be_overruled():
    """Registered engines are built by the registry with NO arguments, so
    without this there is no way at all to tune them — and the two Apple
    engines declare ``scales_with_threads = False``, pinning them to one page
    per document.

    That declaration is a good default: Apple's Neural Engine really does serve
    one request at a time, and whoever configures the cascade cannot see behind
    the engine. It is a bad law: it was measured on ONE machine.
    """
    from autosxtract.engines.base import OCREngine
    from autosxtract.steps.ocr import OCRStep

    class _SingleQueue(OCREngine):
        name = "single_queue"
        scales_with_threads = False

        def __init__(self):
            super().__init__()
            self.seen: list[int] = []

        def _load(self):
            return object()

        def transcribe(self, pages, *, parallelism=4, force_parallelism=False):
            self.seen.append(parallelism if (force_parallelism or self.scales_with_threads) else 1)
            return None

    engine = _SingleQueue()
    step = OCRStep(engine)

    ctx = _context(Config(page_parallelism=6))
    step.run(ctx)
    assert engine.seen[-1] == 1, "sem override, a declaração do motor vale"

    ctx = _context(Config(page_parallelism=6, engine_parallelism={"single_queue": 6}))
    step.run(ctx)
    assert engine.seen[-1] == 6, "com override, o operador vence"


def _context(config):
    from autosxtract.steps.base import Context

    ctx = Context(pdf_bytes=b"", config=config, identifier="x")
    ctx.images = lambda **kw: [b"pagina"]  # type: ignore[method-assign]
    return ctx
