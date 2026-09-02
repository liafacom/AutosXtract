"""Fixing page orientation before OCR.

A scanned document often arrives on its side or upside down — the operator put
the sheet in the scanner rotated. Every OCR engine reads far worse in that
state, and fixing it costs milliseconds against the cost of the bad reading.

Uses Tesseract's orientation detection (OSD), which is layout analysis rather
than full OCR. Without Tesseract or Pillow it degrades to "do not rotate" — it
never breaks the extraction over an optional dependency.

On by default (``Config.fix_orientation``). It was off, and being off was not
the problem: a page that arrives sideways is read badly by every engine, and
everything downstream — the acceptance gate, the score, the vetoes — then judges
a bad reading caused by an input defect it cannot see. That is a document
problem the pipeline had no answer for.

What it costs is an OSD pass per **rasterised** page, so a document resolved by
the native text layer pays nothing. The pass has not been measured on this
project's archive; see ``Config.fix_orientation``.

Two rules this module follows, and both are section 3 of ``CLAUDE.md``: it never
breaks the extraction over an optional dependency, and it never goes missing in
silence. ``available()`` is how the absence reaches ``autosxtract diagnose`` and
the provenance, and ``fix`` returns the degrees it applied so a rotation that
DID happen is recorded too. A correction nobody can see in the record is
indistinguishable from one that never ran.
"""

from __future__ import annotations

import io

# OSD is only trustworthy with a minimum number of characters on the page;
# below that it returns a random angle. Tesseract exposes that confidence, and
# we use it.
_MIN_CONFIDENCE = 1.0


def available() -> tuple[bool, str]:
    """``(can_run, reason)`` — the same contract an engine answers with.

    It exists because ``fix_orientation=True`` on a machine without Tesseract
    used to be a **silent no-op**: ``detect`` returned 0 on ``ImportError`` and
    nothing anywhere said the correction had not run. A run with the OSD working
    and a run without it were byte-for-byte identical in the record, which is
    the failure mode section 3 forbids — degrading without breaking is right,
    degrading without warning is not.
    """
    try:
        import pytesseract
    except ImportError:
        return False, "pytesseract is not installed; install with pip install 'autosxtract[veto]'"
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return False, "Pillow is not installed; install with pip install 'autosxtract[veto]'"
    try:
        # The Python package alone is not enough — the binary has to be on the
        # PATH, and discovering that one page at a time makes the reason
        # unreadable in the log.
        pytesseract.get_tesseract_version()
    except Exception as exc:
        return False, f"the tesseract binary is not on the PATH: {exc}"[:160]
    return True, "tesseract OSD"


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
