"""The visual signature detector: inert by default, and for a good reason.

A model trained on a public signature dataset **did not transfer** to a legal
archive: 19% of pages with a detection, most of them false positives on
authenticity seals, stamps, logos, QR codes and coats of arms — while missing
the target case.
"""

from __future__ import annotations

from autosxtract.engines.signature import SignatureDetector


def test_with_no_model_it_stays_inert(tmp_path):
    d = SignatureDetector(tmp_path / "missing.onnx")
    ok, reason = d.available()
    assert not ok
    assert "missing" in reason


def test_detect_with_no_model_returns_empty(tmp_path):
    """An empty list is "I don't know", not "there is no signature" — which is
    why Layer 1 never concludes anything from the absence of boxes."""
    assert SignatureDetector(tmp_path / "x.onnx").detect(b"not an image") == []


def test_a_corrupt_model_does_not_raise(tmp_path):
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"this is not an onnx")
    d = SignatureDetector(bad)
    ok, reason = d.available()
    assert not ok
    assert "did not load" in reason
    assert d.detect(b"") == []


def test_off_by_default():
    from autosxtract import Config

    assert Config().signature_detector is None


def test_repr_does_not_hide_the_path(tmp_path):
    assert "sig.onnx" in repr(SignatureDetector(tmp_path / "sig.onnx"))
