"""Rasterising PDF pages to images.

The module's only job: turn pages into image bytes that an OCR engine accepts.
It knows nothing about engines, cascades or storage — which is what lets the
engine behind it be swapped without touching this file.

The caps exist for the real case: a scanned page from an old case file becomes
an enormous image, and an engine handed a huge image either slows down or
refuses.
"""

from __future__ import annotations

from autosxtract.pdf._mupdf import mupdf
from autosxtract.pdf.lock import pdf_lock

# 72 pt = 1 in; the zoom converts the wanted DPI into a pixmap scale factor.
_PDF_BASE_DPI = 72.0
_MAX_SIDE_PX = 1800
_MAX_BYTES_PER_IMAGE = 1_500_000
_JPEG_QUALITY = 80


def _encode(pix, fmt: str) -> bytes:
    """JPEG (compact for scans), falling back to PNG on older PyMuPDF.

    ``fmt="png"`` encodes losslessly — heavier on the wire, but measured as
    *cheaper in CPU* when the pixmap is single-channel.
    """
    if fmt == "png":
        return pix.tobytes("png")
    try:
        return pix.tobytes("jpeg", jpg_quality=_JPEG_QUALITY)
    except TypeError:
        try:
            return pix.tobytes("jpeg")
        except Exception:
            return pix.tobytes("png")
    except Exception:
        return pix.tobytes("png")


def _pixmap(page, zoom: float, grayscale: bool):
    matrix = mupdf().Matrix(zoom, zoom)
    if grayscale:
        return page.get_pixmap(matrix=matrix, colorspace=mupdf().csGRAY)
    return page.get_pixmap(matrix=matrix)


def render(
    pdf_bytes: bytes,
    *,
    dpi: int = 150,
    max_pages: int = 64,
    grayscale: bool = True,
    fmt: str = "jpeg",
    indices: list[int] | None = None,
) -> list[bytes]:
    """Rasterise pages and return the image bytes, in document order.

    ``indices`` restricts to the given pages — that is how per-page routing
    avoids OCRing a sheet that already has native text. ``None`` rasterises
    from the first page up to ``max_pages``.

    Returns ``[]`` when there is nothing to rasterise or the PDF will not open.
    An empty list is a legitimate answer: the caller falls through to the next
    step.
    """
    with pdf_lock():
        if not pdf_bytes or max_pages <= 0 or dpi <= 0:
            return []

        images: list[bytes] = []
        try:
            with mupdf().open(stream=pdf_bytes, filetype="pdf") as doc:
                targets = (
                    [i for i in indices if 0 <= i < len(doc)][:max_pages]
                    if indices is not None
                    else list(range(min(len(doc), max_pages)))
                )
                for i in targets:
                    page = doc[i]
                    zoom = dpi / _PDF_BASE_DPI
                    longest = max(page.rect.width, page.rect.height) or 1.0
                    if longest * zoom > _MAX_SIDE_PX:
                        zoom = _MAX_SIDE_PX / longest
                    data = _encode(_pixmap(page, zoom, grayscale), fmt)
                    if len(data) > _MAX_BYTES_PER_IMAGE:
                        zoom *= 0.6
                        data = _encode(_pixmap(page, zoom, grayscale), fmt)
                    images.append(data)
        except Exception:
            # Unreadable PDF: the step is simply left with no pages.
            return []
        return images
