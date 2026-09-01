"""Tesseract — the engine that exists to **disagree**, not to transcribe.

It is the worst of the three on quality and the slowest per page (~1.4 s), and
it still earns a place in the registry for one specific role: being the witness
for the vetoes that run before an expensive step.

The reasoning, measured: when an OCR reads the whole page in ~1 s and finds no
legible word, the conclusion stops being "the cheap layer failed" and becomes
"there is no text to recover". Across an archive of 489 documents the
separation is clean and roomy — everything Tesseract read with fewer than 3
reliable words yielded at most 124 real characters in the expensive step, and
everything it read with 7 or more yielded at least 257. The band between them
is empty.

Priority 90: it is never chosen to produce the document's text if any other
engine exists. The cascade consults it as a vote.

It is also the only engine that implements the **recovery track**: when the
first pass finds nothing, it pays for adaptive contrast (CLAHE) and Otsu
binarisation at double the resolution, because the page may be dense and
degraded rather than empty.
"""

from __future__ import annotations

import io

from autosxtract.engines.base import OCREngine, register
from autosxtract.pdf._mupdf import close, mupdf
from autosxtract.pdf.lock import pdf_lock
from autosxtract.quality.vetoes import LocalReading
from autosxtract.types import Line, Page

# Tesseract confidence above which a word counts as legible. The value is the
# engine's own (0-100); below it the reading is a guess over scanning noise.
MIN_WORD_CONFIDENCE = 70.0
# Resolution of the first pass. Measured: 150 DPI already finds every document
# that has content, and costs half of 300.
TRIAGE_DPI = 150
# Resolution of the recovery pass, applied only when the first found nothing.
# It is the track for the "degraded scan" class.
RECOVERY_DPI = 300


@register(
    name="tesseract",
    priority=90,
    extra="veto",
    description="Local Tesseract — witness for the expensive step's vetoes",
)
class TesseractEngine(OCREngine):
    """A cheap local OCR, used as an independent vote."""

    def __init__(self, *, language: str = "por") -> None:
        super().__init__()
        self.language = language

    def _load(self):
        import pytesseract

        # This fails if the binary is not on the PATH — the Python package
        # alone is not enough, and discovering that only on the first page
        # would make the reason unreadable in the log.
        pytesseract.get_tesseract_version()
        return pytesseract

    # ── common contract ──────────────────────────────────────────────────
    def read_page(self, image: bytes) -> Page | None:
        """The page line by line, grouping Tesseract's words.

        ``image_to_data`` returns **word** by word; the layers reason about
        **lines**. The grouping uses ``block_num``/``par_num``/``line_num``,
        which is Tesseract's own segmentation — regrouping by geometric
        proximity would invent a line the engine never saw.

        Tesseract confidence comes in 0-100 and is divided here: the layer
        thresholds work in 0-1, and without the conversion every line would look
        perfect.
        """
        pytesseract = self.model
        if pytesseract is None:
            raise RuntimeError(self._reason or "pytesseract unavailable")
        from PIL import Image

        with Image.open(io.BytesIO(image)) as img:
            width, height = float(img.width), float(img.height)
            data = pytesseract.image_to_data(
                img, lang=self.language, output_type=pytesseract.Output.DICT
            )

        groups: dict[tuple, list[tuple]] = {}
        for i, raw in enumerate(data.get("text", [])):
            word = (raw or "").strip()
            if not word:
                continue
            try:
                confidence = float(data["conf"][i])
            except (TypeError, ValueError, KeyError, IndexError):
                continue
            if confidence < 0:
                continue
            key = (
                data.get("block_num", [0] * (i + 1))[i],
                data.get("par_num", [0] * (i + 1))[i],
                data.get("line_num", [0] * (i + 1))[i],
            )
            groups.setdefault(key, []).append(
                (
                    word,
                    confidence,
                    data["left"][i],
                    data["top"][i],
                    data["width"][i],
                    data["height"][i],
                )
            )

        lines: list[Line] = []
        for key in sorted(groups):
            items = groups[key]
            text = " ".join(w for w, *_ in items)
            score = sum(c for _w, c, *_ in items) / len(items) / 100.0
            x1 = min(x for *_a, x, _y, _w, _h in items)
            y1 = min(y for *_a, _x, y, _w, _h in items)
            x2 = max(x + w for *_a, x, _y, w, _h in items)
            y2 = max(y + h for *_a, _x, y, _w, h in items)
            lines.append(
                Line(
                    text=text,
                    score=round(score, 4),
                    poly=((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
                )
            )
        return Page(lines, width, height)

    @staticmethod
    def _words(pytesseract, image, language: str = "por"):
        data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
        words: list[str] = []
        confidences: list[float] = []
        for raw, conf in zip(data.get("text", []), data.get("conf", []), strict=False):
            word = (raw or "").strip()
            try:
                value = float(conf)
            except (TypeError, ValueError):
                continue
            if not word or value < 0:
                continue
            words.append(word)
            confidences.append(value)
        return words, confidences

    # ── witness role ─────────────────────────────────────────────────────
    def read_document(
        self,
        pdf_bytes: bytes,
        *,
        max_pages: int = 3,
        min_reliable_words: int = 3,
    ) -> LocalReading | None:
        """Read the document in two passes, to serve as a witness.

        The first is the cheap one. Only when it finds nothing does the second
        pay for contrast enhancement at double the resolution — because the page
        may be dense and degraded rather than empty.

        Returns ``None`` when the engine is unavailable, so the cascade carries
        on as before rather than treating the absence of a tool as the absence
        of text.
        """
        if self.model is None:
            return None

        pages = self._rasterise(pdf_bytes, TRIAGE_DPI, max_pages)
        if not pages:
            return None
        reading = self._measure(pages, f"{TRIAGE_DPI}/raw")
        if reading is None:
            return None
        if reading.reliable_words >= min_reliable_words:
            return reading

        enhanced = [self._enhance(p) for p in self._rasterise(pdf_bytes, RECOVERY_DPI, max_pages)]
        if enhanced:
            recovered = self._measure(enhanced, f"{RECOVERY_DPI}/enhanced")
            if recovered is not None and recovered.reliable_words > reading.reliable_words:
                return recovered
        return reading

    def _measure(self, pages, track: str) -> LocalReading | None:
        pytesseract = self.model
        from PIL import Image

        chunks: list[str] = []
        confidences: list[float] = []
        ran = False
        for page in pages:
            try:
                words, confs = self._words(pytesseract, Image.fromarray(page), self.language)
                ran = True
            except Exception:
                # A bad page does not bring the others down.
                continue
            if words:
                chunks.append(" ".join(words))
            confidences.extend(confs)
        # ``ran`` separates **a missing engine** from **a blank page**: both
        # return zero words, and confusing them is expensive in both directions.
        if not ran:
            return None
        return LocalReading(
            text="\n".join(chunks),
            words=len(confidences),
            reliable_words=sum(1 for c in confidences if c >= MIN_WORD_CONFIDENCE),
            mean_confidence=round(sum(confidences) / len(confidences), 1) if confidences else 0.0,
            track=track,
            pages_read=len(pages),
        )

    @staticmethod
    def _rasterise(pdf_bytes: bytes, dpi: int, max_pages: int):
        """Pages as greyscale arrays. Empty list if the PDF will not open."""
        with pdf_lock():
            try:
                import numpy as np
                from PIL import Image

                pymupdf = mupdf()
            except ImportError:
                return []
            try:
                doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
            except Exception:
                return []
            pages = []
            try:
                for i, page in enumerate(doc):
                    if i >= max_pages:
                        break
                    try:
                        pix = page.get_pixmap(dpi=dpi)
                        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
                        pages.append(np.array(img))
                    except Exception:
                        # A bad page does not bring the others down.
                        continue
            finally:
                close(doc)
            return pages

    @staticmethod
    def _enhance(grey):
        """Adaptive contrast plus binarisation — the degraded-scan track."""
        try:
            import cv2
        except ImportError:
            return grey
        enhanced = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(grey)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary
