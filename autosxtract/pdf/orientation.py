"""Fixing page orientation before OCR.

A scanned document often arrives on its side or upside down — the operator put
the sheet in the scanner rotated. Every OCR engine reads far worse in that
state, and fixing it costs milliseconds against the cost of the bad reading.

Uses Tesseract's orientation detection (OSD), which is layout analysis rather
than full OCR. Without Tesseract or Pillow it degrades to "do not rotate" — it
never breaks the extraction over an optional dependency.

Off by default (``Config.fix_orientation``): the OSD pass costs per page and
only pays off on an archive known to be crooked.
"""

from __future__ import annotations

import io

# OSD is only trustworthy with a minimum number of characters on the page;
# below that it returns a random angle. Tesseract exposes that confidence, and
# we use it.
_MIN_CONFIDENCE = 1.0


def detect(image: bytes) -> int:
    """Degrees (0/90/180/270) the page must rotate to become readable.

    Returns 0 when it cannot be determined — including when the dependencies
    are not installed. Better to send the page as it is than to rotate it on a
    guess.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return 0

    try:
        with Image.open(io.BytesIO(image)) as img:
            osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
    except Exception:
        # OSD fails on a page with no text.
        return 0

    try:
        confidence = float(osd.get("orientation_conf", 0.0))
        degrees = int(osd.get("rotate", 0)) % 360
    except (TypeError, ValueError):
        return 0
    return degrees if confidence >= _MIN_CONFIDENCE else 0


def fix(image: bytes) -> tuple[bytes, int]:
    """``(image, degrees_applied)`` with the page upright.

    With no rotation to apply — or no way to apply it — it returns the original
    bytes untouched, so the caller need not tell the cases apart.
    """
    degrees = detect(image)
    if not degrees:
        return image, 0
    try:
        from PIL import Image
    except ImportError:
        return image, 0
    try:
        with Image.open(io.BytesIO(image)) as img:
            # OSD reports how far to turn clockwise; Pillow rotates
            # anticlockwise, hence the negative sign.
            rotated = img.rotate(-degrees, expand=True)
            buffer = io.BytesIO()
            fmt = "PNG" if image.startswith(b"\x89PNG") else "JPEG"
            if fmt == "JPEG" and rotated.mode not in ("RGB", "L"):
                rotated = rotated.convert("RGB")
            rotated.save(buffer, format=fmt)
            return buffer.getvalue(), degrees
    except Exception:
        return image, 0
