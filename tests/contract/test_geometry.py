"""The detailed engine contract — the one the containment layers stand on.

``transcribe_page`` is the contract every engine owes; ``read_page`` is the
optional second level, line by line with a polygon and a score. Optional in the
protocol, mandatory in practice for the two engines that ARE step 2 — Vision on
Apple, PP-OCR everywhere else — because an engine without geometry means no
layers, and the layers are the cheapest measured gain in the pipeline.

Two obligations, and both are conformance questions rather than behaviour:
whether the shipped engines really override the detailed method, and whether the
score they hand over is on the scale the layers judge in.
"""

from __future__ import annotations

from autosxtract.engines.base import OCREngine
from autosxtract.quality.lines import contain
from autosxtract.types import Line, Page


def test_the_engines_that_expose_geometry():
    """Without the detailed contract there are no containment layers.

    Vision and PP-OCR must have it: they are the library's two step 2s, one per
    platform. Either without geometry would mean layers for only half the users.
    """
    from autosxtract.engines.paddle import PaddleEngine
    from autosxtract.engines.tesseract import TesseractEngine
    from autosxtract.engines.vision import VisionEngine

    base = OCREngine.read_page
    for cls in (PaddleEngine, VisionEngine, TesseractEngine):
        assert cls.read_page is not base, cls.__name__


def test_the_line_score_is_normalised():
    """The layer thresholds work in 0-1.

    Tesseract reports 0-100: without the conversion every line would look
    perfect and nothing would be contained.
    """
    page = Page(
        [
            Line(
                "xkqw zpmm bqrt zzxp lmnq wrtz",
                0.40,
                ((60, 100), (900, 100), (900, 130), (60, 130)),
            )
        ],
        1200,
        1700,
    )
    assert contain(page).n_illegible == 1
