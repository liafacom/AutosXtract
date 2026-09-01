"""OnnxTR — a local safety net, and honest about its own place.

Numbers from the same 60-document sample used for every engine:

    apple-vision      ~400 ms/page   words  92%   anchors 100%
    OnnxTR (mobile)    494 ms/page   words  53%   anchors  75%
    docTR PyTorch      816 ms/page        —       anchors  51%
    RapidOCR 1.x      1554 ms/page        —       anchors  58%

In other words: **it is neither faster nor better than Vision**, and it does not
deliver the ~170 ms/page the project advertises (that figure is from another
dataset on another processor). The ONNX conversion is still worth it — it is
1.65x faster than the same docTR in PyTorch.

Its role here is different: to be a second cheap engine of a **different
architecture**. Measured on the 17 documents Vision refused in a real archive:
it resolves 5 of them at ~0.5 s each. On the other 12 it does not read either —
and two independent engines agreeing that the page is sparse is far better
evidence than one alone.

Priority 30: it comes after Vision and Paddle, never in their place.
"""

from __future__ import annotations

from autosxtract.engines.base import OCREngine, register

# The combination measured as the best cost/quality ratio among those tested:
# swapping the recogniser for ``crnn_vgg16_bn`` cost 2.1x the time (1,054 ms
# against 494) and bought 2 anchor points (77% against 75%).
_DETECTOR = "db_mobilenet_v3_large"
_RECOGNISER = "crnn_mobilenet_v3_small"


@register(
    name="onnx",
    priority=30,
    extra="onnx",
    description="Local OnnxTR (docTR in ONNX) — a second cheap engine, different architecture",
)
class OnnxEngine(OCREngine):
    """Local OCR through ONNX, with no external dependency."""

    def __init__(self, *, detector: str = _DETECTOR, recogniser: str = _RECOGNISER) -> None:
        super().__init__()
        self.detector = detector
        self.recogniser = recogniser

    def _load(self):
        from onnxtr.models import ocr_predictor

        return ocr_predictor(det_arch=self.detector, reco_arch=self.recogniser)

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        model = self.model
        if model is None:
            raise RuntimeError(self._reason or "onnxtr unavailable")
        from onnxtr.io import DocumentFile

        # ``from_images`` takes image BYTES (or a path), not a numpy array —
        # passing an array returns "unsupported object type for argument 'file'"
        # and the transcription comes out empty with confidence 0, which looks
        # like "the page has no text" instead of "the call failed".
        result = model(DocumentFile.from_images([image]))
        lines: list[str] = []
        confidences: list[float] = []
        for page in result.pages:
            for block in page.blocks:
                for line in block.lines:
                    lines.append(" ".join(w.value for w in line.words))
                    confidences.extend(float(w.confidence) for w in line.words)
        mean = 100.0 * sum(confidences) / len(confidences) if confidences else 0.0
        return "\n".join(lines), round(mean, 1)
