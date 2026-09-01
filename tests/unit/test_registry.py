"""The engine registry — the library's extension point.

If adding an engine required touching the cascade, the design would have
failed. These tests pin the opposite: a new engine enters through a decorator
and the cascade finds it on its own, carrying whatever options its constructor
declares.

Nothing here loads a model. Registration, lookup and the instance cache are
answerable from the registry alone; what the machine actually has installed is
``integration/test_shipped_engines.py``.
"""

from __future__ import annotations

import pytest

from autosxtract.engines import base as engines
from autosxtract.engines.base import OCREngine, register
from autosxtract.exceptions import UnknownEngine
from autosxtract.types import Transcription


def test_an_unknown_name_is_an_explicit_error():
    with pytest.raises(UnknownEngine, match="known"):
        engines.get("engine_that_does_not_exist")


def test_the_instance_is_shared():
    """The loaded model is the expensive resource; one per document wastes it."""
    assert engines.get("paddle") is engines.get("paddle")


def test_a_new_engine_enters_through_the_decorator():
    @register(name="test_engine", priority=50, description="for the test only")
    class TestEngine(OCREngine):
        def _load(self):
            return object()

        def transcribe_page(self, image: bytes) -> tuple[str, float]:
            return "text", 90.0

    try:
        assert "test_engine" in {i.name for i in engines.registered()}
        engine = engines.get("test_engine")
        assert engine.available()[0]
        assert isinstance(engine.transcribe([b"a", b"b"]), Transcription)
    finally:
        engines._REGISTRY.pop("test_engine", None)
        # A chave do cache é ``(nome, opções congeladas)``.
        for k in [k for k in engines._INSTANCES if k[0] == "test_engine"]:
            engines._INSTANCES.pop(k, None)


# ── per-engine configuration through the registry ────────────────────────


def test_the_registry_passes_options_to_the_constructor():
    """Engines were built by ``factory()`` with NO arguments, so everything
    their constructors accept — the tier, the INT8 flag, the thread count, the
    preprocessing — was unreachable from an assembled cascade.
    """
    from autosxtract.engines.paddle import PaddleEngine

    engine = engines.get("paddle", det="small", threads=4)
    assert isinstance(engine, PaddleEngine)
    assert engine.det == "small"
    assert engine.threads == 4


def test_different_options_are_a_different_engine():
    """Asking for INT8 must not hand back the FP32 model somebody built first.

    That would be the silent kind of wrong: the configuration is accepted, the
    measurement comes out unchanged, and nothing says why.
    """
    plain = engines.get("paddle")
    int8 = engines.get("paddle", quantized=True)
    assert plain is not int8
    assert engines.get("paddle") is plain  # e o cache continua valendo


def test_the_option_order_does_not_split_the_cache():
    """``{"a": 1, "b": 2}`` and ``{"b": 2, "a": 1}`` are the same engine —
    otherwise a dict literal written differently loads a second model."""
    a = engines.get("paddle", det="tiny", threads=2)
    b = engines.get("paddle", threads=2, det="tiny")
    assert a is b


def test_unhashable_options_do_not_break_the_cache():
    """``providers`` is a list, and a list cannot be a dictionary key."""
    a = engines.get("paddle", providers=["CPUExecutionProvider"])
    b = engines.get("paddle", providers=["CPUExecutionProvider"])
    assert a is b


@pytest.mark.paddle
def test_int8_that_is_not_on_disk_says_so_instead_of_running_fp32():
    """``quantized`` was read only by the paddleocr backend. With rapidocr it
    was accepted, reported as INT8 in the repr, and FP32 ran — a configuration
    that is accepted and does nothing is worse than one that is refused.

    Marked ``paddle``: the verdict is "INT8 is missing next to the FP32 weights
    that ARE here", so it only means anything where the PP-OCRv6 weights exist.
    """
    from autosxtract.engines import models
    from autosxtract.engines.paddle import PaddleEngine

    if models.int8_paths() is not None:
        pytest.skip("this machine has INT8 weights exported")
    engine = PaddleEngine(quantized=True)
    engine._rapidocr_params()
    assert "INT8 REQUESTED but not on disk" in engine.model_in_use
