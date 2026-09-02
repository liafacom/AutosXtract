"""The OCR engine is configurable — it is the model swap point.

The default is PP-OCRv6 tiny because, with the bottleneck in CPU, what decides
is throughput and not benchmark accuracy. But a default is a default: a
different archive wants a different model, and swapping it must not require
touching the cascade.

Constructor and configuration only — nothing here loads a model. The engine's
side of the detailed geometry contract is ``contract/test_geometry.py``; the
registry that builds it with these options is ``unit/test_registry.py``.
"""

from __future__ import annotations

import sys
import types

import pytest

from autosxtract.engines.paddle import TIERS, PaddleEngine


def test_the_default_is_tiny():
    e = PaddleEngine()
    assert e.det == "tiny"
    assert e.rec == "tiny"


def test_rec_follows_det_when_omitted():
    assert PaddleEngine(det="small").rec == "small"


def test_det_and_rec_are_independent():
    """Accuracy lives in the RECOGNISER: small det + large rec is the
    best-returning trade, and it requires two distinct parameters."""
    e = PaddleEngine(det="tiny", rec="medium")
    assert (e.det, e.rec) == ("tiny", "medium")
    assert "tiny/medium" in repr(e)


def test_an_invalid_tier_is_an_explicit_error():
    with pytest.raises(ValueError, match="invalid det"):
        PaddleEngine(det="gigantic")


def test_a_custom_directory_waives_the_tier():
    """A model fine-tuned on your archive has no official tier."""
    e = PaddleEngine(det="whatever", det_dir="/my/det")
    assert e.det_dir == "/my/det"


def test_a_finetuned_model_shows_in_the_repr():
    assert "/my/finetune" in repr(PaddleEngine(rec_dir="/my/finetune"))


def test_quantized_shows_in_the_repr():
    assert "INT8" in repr(PaddleEngine(quantized=True))


def test_the_official_tiers():
    assert TIERS == ("tiny", "small", "medium")


def test_preprocessing_is_optional():
    """Binarising helps a faded scan and HURTS a native document."""
    assert PaddleEngine().preprocess is None
    assert PaddleEngine(preprocess="otsu").preprocess == "otsu"


def test_providers_are_configurable():
    e = PaddleEngine(providers=["CoreMLExecutionProvider", "CPUExecutionProvider"])
    assert e._engine_config()["providers"][0] == "CoreMLExecutionProvider"


def test_threads_reach_the_engine():
    assert PaddleEngine(threads=8)._engine_config()["intra_op_num_threads"] == 8


# ── regression: the crop recogniser must not contaminate the main one ────


def test_the_cached_crop_recogniser_is_returned_as_is():
    """Once built, the crop recogniser is reused rather than rebuilt.

    This is the CACHE, not the isolation. It used to be the whole of the §16
    regression test, which was the defect: the test assigned ``_crop_rec``
    itself, so ``_recognizer`` returned on its first line and the branch that
    actually builds a separate instance never ran. Reusing the main object there
    kept every assertion green. The test below is the one that pins §16.
    """
    e = PaddleEngine()
    e._model = ("rapidocr", object())
    main = e.model[1]

    class FakeRec:
        def __call__(self, *a, **kw):
            return None

    e._crop_rec = FakeRec()
    assert e._recognizer() is not main
    assert e._recognizer() is e._crop_rec


@pytest.mark.parametrize("backend", ["rapidocr", "paddleocr"])
def test_the_crop_recogniser_is_BUILT_as_a_separate_instance(monkeypatch, backend):
    """Calling the main engine with ``use_det=False`` turns detection off
    PERMANENTLY on that object.

    Measured before the fix: the next whole-page read returned 1 line where it
    had returned 56, and the document came out with 1 character instead of
    3,900. The defect is of the worst kind — silent, order-dependent, and only
    visible from the second page of the batch onwards.

    So the assertion has to reach the CONSTRUCTION branch with ``_crop_rec``
    still unset, and check that what comes back is a NEW object rather than the
    one in ``self.model``. ``self._crop_rec = loaded[1]`` — the mutation that
    reintroduces the defect — fails here and passed everything before it.

    Both backends, because ``_recognizer`` has a branch per backend and pinning
    only ``rapidocr`` left the other free to borrow the main instance.
    """
    built: list[object] = []

    class FakeRecogniser:
        def __init__(self, *a, **kw):
            built.append(self)

        def __call__(self, *a, **kw):
            return None

    if backend == "rapidocr":
        module = types.ModuleType("rapidocr")
        module.RapidOCR = FakeRecogniser
        monkeypatch.setitem(sys.modules, "rapidocr", module)
    else:
        module = types.ModuleType("paddleocr")
        module.TextRecognition = FakeRecogniser
        monkeypatch.setitem(sys.modules, "paddleocr", module)

    e = PaddleEngine()
    main = FakeRecogniser()
    e._model = (backend, main)
    assert e._crop_rec is None

    crop = e._recognizer()
    assert crop is not None
    assert crop is not main, "the crop recogniser must not be the main instance"
    assert crop in built, "it has to be a freshly built object, not a borrowed one"
    # And it is cached: a second call does not build a third instance.
    assert e._recognizer() is crop


def test_an_unavailable_recogniser_does_not_retry():
    """``False`` marks "tried and it does not work" — otherwise every crop retries."""
    e = PaddleEngine()
    e._crop_rec = False
    assert e._recognizer() is None
