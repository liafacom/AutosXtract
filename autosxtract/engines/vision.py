"""Apple Vision — step 2 on Apple hardware, **in this very process**.

It calls ``VNRecognizeTextRequest`` directly through pyobjc. No HTTP, no
worker, no tunnel: that is the central difference from the previous
architecture, where Vision lived on a Mac reached over a reverse SSH tunnel and
that worker going down silently degraded the whole extraction — measured on a
real incident, 488 documents re-extracted down the worse path, 19.5 min instead
of 4.9, and 28,239 characters lost.

Why it is the preferred step where it exists (measured on 60 audited documents,
the same sample for every engine):

    apple-vision      ~400 ms/page   words  92%   anchors 100%
    OnnxTR (mobile)    494 ms/page   words  53%   anchors  75%
    docTR PyTorch      816 ms/page        —       anchors  51%
    RapidOCR 1.x      1554 ms/page        —       anchors  58%

The model runs on-device, small and specialised, with hardware acceleration
that has no x86 equivalent. The known limit is throughput, not quality: the
Neural Engine is a single queue, so the ceiling sits at ~2.5 pages/s and does
**not** rise with threads — measured from 1 to 12 threads, constant throughput
and linearly growing latency. That is why a high ``page_parallelism`` here only
stacks waiting.

``correction`` deserves a conscious decision. Turning it off more than doubles
throughput (2.5 -> 5.4 pages/s), and even so the default is on: measured on 935
documents, turning it off made 102 documents fail the acceptance gate and fall
to worse engines, with a net -227 anchors and -4,981 characters. The three
worst-hit documents lost 93, 73 and 52 anchors — whole case numbers.
"""

from __future__ import annotations

import contextlib
import io

from autosxtract.engines.base import OCREngine, register
from autosxtract.image import dimensions
from autosxtract.types import Line, Page


@register(
    name="vision",
    priority=10,
    platforms=("Darwin",),
    extra="apple",
    description="Apple Vision on-device (VNRecognizeTextRequest), no network",
)
class VisionEngine(OCREngine):
    """Apple Vision on-device, inside the library's own process."""

    #: The Neural Engine is a single-server queue: requests line up and are
    #: served one at a time. Measured from 1 to 12 threads, constant throughput
    #: at ~2.5 pages/s with linearly growing latency (430 ms to 3,492 ms). The
    #: useful parallelism here is PER DOCUMENT, never per page.
    scales_with_threads = False

    def __init__(
        self,
        *,
        language: str = "pt-BR",
        level: str = "accurate",
        correction: bool = True,
        vocabulary: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__()
        self.language = language
        # ``fast`` was rejected on quality — the author of the public benchmark
        # comparing Vision and ML Kit reached the same conclusion and carried
        # on comparing only ``accurate``.
        self.level = level
        self.correction = correction
        self.vocabulary = tuple(vocabulary or ())
        self._languages: set[str] | None = None

    def _load(self):
        """Load the pyobjc bundles. There is no model to instantiate.

        Returns the ``Vision`` module as the "model" to reuse the base class's
        semantics: ``None`` means unavailable.
        """
        import Vision

        try:
            from Foundation import NSData
        except ImportError:
            # pyobjc packages NSData in more than one bundle.
            from AppKit import NSData  # noqa: F401
        return Vision

    # ── Apple API details ────────────────────────────────────────────────
    def _supported_languages(self, req) -> set[str]:
        if self._languages is None:
            try:
                self._languages = set(req.supportedRecognitionLanguagesAndReturnError_(None)[0])
            except Exception:
                # Without the list we simply do not filter.
                self._languages = set()
        return self._languages

    @staticmethod
    def _text_of(obs) -> str:
        """The text of a ``VNRecognizedTextObservation``.

        ``topCandidates:`` is the documented API, stable since macOS 10.15;
        ``.text()`` is a convenience of recent versions. We try the documented
        one first — without that, a pyobjc version difference would bring down
        every page at once.
        """
        try:
            candidates = obs.topCandidates_(1)
            if candidates and len(candidates):
                return candidates[0].string()
        except Exception:
            # Fall through to the convenience API.
            pass
        try:
            return obs.text()
        except Exception:
            # An unreadable observation: ignored.
            return ""

    def read_page(self, image: bytes) -> Page | None:
        """One page, line by line, with box and confidence.

        ``VNImageRequestHandler`` decodes PNG/JPEG natively, so we hand it the
        raw bytes — no PIL on the hot path. The dimensions come from the image
        header (``autosxtract.image``) for the same reason: on macOS the default
        install brings neither Pillow nor OpenCV.

        Without this method there would be no containment layers on macOS —
        which is the platform the preferred engine runs on.
        """
        Vision = self.model
        if Vision is None:
            raise RuntimeError(self._reason or "Vision unavailable")

        import objc

        try:
            from Foundation import NSData
        except ImportError:
            from AppKit import NSData

        with objc.autorelease_pool():
            req = Vision.VNRecognizeTextRequest.alloc().init()
            req.setRecognitionLevel_(1 if self.level == "fast" else 0)
            req.setUsesLanguageCorrection_(bool(self.correction))
            if self.correction and self.vocabulary:
                # Missing selector on an older macOS: carry on without the
                # vocabulary bias.
                with contextlib.suppress(Exception):
                    req.setCustomWords_(list(self.vocabulary))
            if self.language and self.language in self._supported_languages(req):
                req.setRecognitionLanguages_([self.language])

            nsdata = NSData.dataWithBytes_length_(image, len(image))
            handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(nsdata, None)
            result = handler.performRequests_error_([req], None)
            ok = result[0] if isinstance(result, tuple) else bool(result)
            if not ok:
                raise RuntimeError("VNImageRequestHandler refused the image")

            lines: list[Line] = []
            width, height = dimensions(image)
            for obs in req.results() or []:
                text = self._text_of(obs)
                if not (text or "").strip():
                    continue
                lines.append(
                    Line(
                        text=text,
                        score=float(obs.confidence()),
                        poly=self._polygon(obs, width, height),
                    )
                )

        return Page(lines, width, height)

    @staticmethod
    def _polygon(obs, width: float, height: float):
        """A normalised ``boundingBox`` -> a pixel polygon, origin at the top.

        Vision returns the box **normalised and with its origin at the bottom
        left**. Mixing the two axes up puts every footer stamp in the header,
        and the margin classifier starts failing exactly where it should
        succeed.

        ``None`` when the dimensions could not be read: without them the
        conversion would be a guess, and a wrong polygon is worse than none.
        """
        if width <= 0 or height <= 0:
            return None
        try:
            box = obs.boundingBox()
            x = float(box.origin.x) * width
            w = float(box.size.width) * width
            h = float(box.size.height) * height
            y = (1.0 - float(box.origin.y) - float(box.size.height)) * height
        except Exception:
            # An observation with no geometry: the line goes in without a position.
            return None
        return ((x, y), (x + w, y), (x + w, y + h), (x, y + h))


@register(
    name="ocrmac",
    priority=15,
    platforms=("Darwin",),
    extra="apple",
    description="Apple Vision through the ocrmac library — a safety net for the direct path",
)
class OcrmacEngine(OCREngine):
    """The same Apple engine, through the ``ocrmac`` library.

    It exists as a safety net: an incomplete pyobjc breaks the direct path, and
    it is better to pay the library round-trip's extra ~61 ms than to fall to an
    engine of a different quality. Priority 15 guarantees it only comes in after
    ``vision``.
    """

    #: Same hardware, same queue.
    scales_with_threads = False

    def _load(self):
        from ocrmac import ocrmac  # only exists on macOS

        return ocrmac

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        ocrmac = self.model
        if ocrmac is None:
            raise RuntimeError(self._reason or "ocrmac unavailable")
        from PIL import Image

        with Image.open(io.BytesIO(image)) as img:
            found = ocrmac.OCR(
                img, language_preference=["pt-BR"], recognition_level="accurate"
            ).recognize()
        lines = [t for t, _c, _b in found if (t or "").strip()]
        confidences = [float(c) for t, c, _b in found if (t or "").strip()]
        mean = 100.0 * sum(confidences) / len(confidences) if confidences else 0.0
        return "\n".join(lines), round(mean, 1)
