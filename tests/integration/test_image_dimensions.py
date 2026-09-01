"""The header reader against a page that was really rendered.

Two layers meet here: ``pdf/render.py`` produces the pixels and
``image.dimensions`` reads their size back out of the bytes without decoding
them. A header reader that drifts from the decoder is the kind of defect that
never raises — it moves every normalised coordinate the containment layers
compute, silently — so the check is against a real render and, where a decoder
is installed, against the decoder itself.
"""

from __future__ import annotations

import pytest

from autosxtract.image import dimensions
from autosxtract.pdf.render import render


@pytest.mark.parametrize("fmt", ["jpeg", "png"])
def test_matches_the_render(pdf_with_text, fmt):
    image = render(pdf_with_text, dpi=100, max_pages=1, fmt=fmt)[0]
    width, height = dimensions(image)
    assert width > 100
    assert height > width  # A4 portrait


def test_agrees_with_a_real_decoder(pdf_with_text):
    """Header reading must give the SAME number as decoding."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    image = render(pdf_with_text, dpi=100, max_pages=1)[0]
    arr = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    assert dimensions(image) == (float(arr.shape[1]), float(arr.shape[0]))
