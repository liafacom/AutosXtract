"""Pixel signals: does the sheet have ink? is it a photograph or a document?

These are the two cheapest vetoes before an expensive step, and they ship with
a warning built in: **neither is valid on its own.** Nine families of pixel
statistics were tested to tell "blank page" from "dense but faded page", and
all of them failed for the same reason — the two cases produce identical
statistics.

What survived were these two, and only in conjunction with "the previous step
extracted no text". An old photocopy on dark paper reaches 0.99 continuous-tone
and still carries thousands of legitimate characters — measured on three
archive documents (0.99 / 0.99 / 0.83, with 1,001, 2,612 and 632 characters).
On its own, the visual signal would discard them.

Any read failure returns "I don't know" (``False``/``None``): when in doubt the
cascade proceeds and pays for the step.
"""

from __future__ import annotations

from autosxtract.pdf._mupdf import close, mupdf
from autosxtract.pdf.lock import pdf_lock

# Above this fraction of mid-tone pixels the page is a continuous-tone image (a
# photograph) rather than a scanned document.
MAX_DOCUMENT_MIDTONE = 0.45
# The grey band that is neither paper nor ink.
_INK_FLOOR = 60
_PAPER_CEILING = 230
# The metric is a proportion, so a low DPI is enough and the cost stays in the
# low milliseconds.
_SAMPLE_DPI = 40

# Fraction of the sheet covered in ink below which there is nothing to
# transcribe. Calibrated against the visual audit verdicts of 20 escalations in
# a real case file: at 1% it avoids 2 of the 11 escalations judged useless and
# **loses none** of the 9 judged useful. Deliberately conservative — at 3% it
# would avoid 9 useless ones but discard 5 useful, a bad trade for a step whose
# error costs content.
MIN_INK_TO_TRANSCRIBE = 0.01
# The conformity stamp occupies the top band of the sheet and exists on every
# page of a digital case file. Counting it as content would make an empty page
# look filled — which is exactly what we are trying to detect.
_STAMP_BAND = 0.12
# A pixel below this counts as ink. Looser than ``_INK_FLOOR``, which separates
# ink from mid-tone: the question here is "is anything written on the sheet?",
# and an old scan has greyish ink that a strict cut would exclude.
_INK_THRESHOLD = 200


def _sample(pdf_bytes: bytes):
    """A greyscale pixmap of the first page, or ``None`` if unreadable."""
    try:
        pymupdf = mupdf()
    except ImportError:
        return None
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        # Optional signal: it never brings the cascade down.
        return None
    try:
        if not len(doc):
            return None
        return doc[0].get_pixmap(dpi=_SAMPLE_DPI, colorspace=pymupdf.csGRAY)
    except Exception:
        return None
    finally:
        close(doc)


def is_photograph(pdf_bytes: bytes) -> bool:
    """Is the first page a photograph rather than a document?

    Used to **avoid** paying for the expensive step on a document with no text
    to extract — a portrait, a photo of a person, an image attached as visual
    evidence. With no textual content, the expensive step only produces
    ``[SIGNATURE]`` and ``[ILLEGIBLE]``.

    Use **in conjunction with** "the previous step extracted no text". The
    conjunction of both conditions produced no false positive across the 489
    audited documents; the signal alone produced three.
    """
    with pdf_lock():
        pix = _sample(pdf_bytes)
        if pix is None:
            return False
        try:
            pixels = pix.samples
            if not pixels:
                return False
            midtone = sum(1 for p in pixels if _INK_FLOOR < p < _PAPER_CEILING) / len(pixels)
            return midtone > MAX_DOCUMENT_MIDTONE
        except Exception:
            return False


def ink_fraction(pdf_bytes: bytes) -> float | None:
    """Fraction of the first page covered in ink, outside the stamp band.

    ``None`` on any failure — callers treat it as "I don't know".
    """
    with pdf_lock():
        pix = _sample(pdf_bytes)
        if pix is None:
            return None
        try:
            pixels = pix.samples
            if not pixels:
                return None
            body = pixels[int(pix.height * _STAMP_BAND) * pix.width :]
            if not body:
                return None
            return sum(1 for p in body if p < _INK_THRESHOLD) / len(body)
        except Exception:
            return None


def is_nearly_blank(pdf_bytes: bytes) -> bool:
    """There is not enough ink on the sheet to hold text worth transcribing."""
    ink = ink_fraction(pdf_bytes)
    return ink is not None and ink < MIN_INK_TO_TRANSCRIBE
