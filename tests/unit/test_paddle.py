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


def test_the_crop_recogniser_is_a_separate_instance():
    """Calling the main engine with ``use_det=False`` turns detection off
    PERMANENTLY on that object.

    Measured before the fix: the next whole-page read returned 1 line where it
    had returned 56, and the document came out with 1 character instead of
    3,900. The defect is of the worst kind — silent, order-dependent, and only
    visible from the second page of the batch onwards.
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


def test_an_unavailable_recogniser_does_not_retry():
    """``False`` marks "tried and it does not work" — otherwise every crop retries."""
    e = PaddleEngine()
    e._crop_rec = False
    assert e._recognizer() is None
