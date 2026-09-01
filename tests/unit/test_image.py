"""Dimensions from the header — no Pillow, no OpenCV.

This exists because the detailed contract has to turn a normalised coordinate
into a pixel, and on macOS the default install brings no imaging library: the
engine there reads the raw bytes.

What is unit-testable about it is the failure side: bytes that are not an image,
or an image cut short. The agreement with a real render needs a rendered page
and lives in ``integration/test_image_dimensions.py``.
"""

from __future__ import annotations

from autosxtract.image import dimensions


def test_an_unknown_format_returns_zero():
    """Zero is "I don't know" — the layers then do not classify margins,
    rather than classifying them wrongly."""
    assert dimensions(b"not an image") == (0.0, 0.0)
    assert dimensions(b"") == (0.0, 0.0)


def test_a_truncated_png_does_not_break():
    assert dimensions(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4) == (0.0, 0.0)


def test_a_jpeg_with_no_sof_does_not_break():
    assert dimensions(b"\xff\xd8" + b"\x00" * 40) == (0.0, 0.0)
