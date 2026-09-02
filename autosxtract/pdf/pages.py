"""Routing OCR per page rather than per document.

The cascade decides per document: if a document needs OCR, **all** its pages
pay for OCR. In a mixed PDF — part digitally generated, part scanned
attachment — that is straight waste.

Measured on a real case file: of the 419 pages that went through OCR, **54
(12.9%) already had native text**. A 39-page document with 29 native and 10
scanned pages ran OCR on all 39 — and it only reached OCR because of the 10.

Pure module: it only reads the PDF structure in memory.
"""

from __future__ import annotations

from autosxtract.pdf._mupdf import close, mupdf
from autosxtract.pdf.lock import pdf_lock

# Character floor for a page to count as "already has text". It is the CCpdf
# criterion (section 3.7: *Visible Text Length > 100*), whose measured
# precision was 93.15 with recall 43.31 — high confidence in what it asserts,
# conservative in what it lets through. Conservative is what you want here:
# wrongly saying a page needs OCR costs time; wrongly saying it does not loses
# text.
MIN_NATIVE_CHARS = 100


def without_text(pdf_bytes: bytes) -> list[int] | None:
    """Indices (0-based) of pages with no usable native text.

    ``None`` when the PDF could not be read — the caller treats that as "I
    don't know" and keeps the per-document behaviour.
    """
    with pdf_lock():
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
            return [
                i
                for i, page in enumerate(doc)
                if len((page.get_text() or "").strip()) < MIN_NATIVE_CHARS
            ]
        except Exception:
            return None
        finally:
            close(doc)


def count(pdf_bytes: bytes) -> int:
    """Number of pages; ``0`` when the PDF will not open."""
    with pdf_lock():
        try:
            doc = mupdf().open(stream=pdf_bytes, filetype="pdf")
            n = len(doc)
            doc.close()
            return n
        except Exception:
            # No PyMuPDF or an unreadable PDF: zero pages.
            return 0


def is_mixed(pdf_bytes: bytes) -> bool:
    """Does the document have native pages **and** pages without text?

    Only then does per-page routing save anything: in a fully scanned PDF there
    is nothing to spare, and in a fully native one OCR never runs.
    """
    missing = without_text(pdf_bytes)
    if missing is None:
        return False
    return 0 < len(missing) < count(pdf_bytes)


def subdocument(pdf_bytes: bytes, indices: list[int]) -> bytes | None:
    """A new PDF holding only the given pages, in the original order.

    This is what goes to a step that takes a **file** rather than an image —
    Docling, for instance — when the document is mixed. Rasterising only the
    missing pages solves the OCR case; for anything that converts the whole
    PDF, it has to be cut down first.

    ``None`` on any failure: the caller falls back to per-document behaviour.
    """
    with pdf_lock():
        if not indices:
            return None
        try:
            source = mupdf().open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            return None
        target = None
        try:
            target = mupdf().open()
            for i in sorted(indices):
                if 0 <= i < len(source):
                    target.insert_pdf(source, from_page=i, to_page=i)
            if not len(target):
                return None
            return target.tobytes()
        except Exception:
            return None
        finally:
            # BOTH documents, on every path. The early ``return None`` for an
            # empty target and a raising ``insert_pdf`` used to leave the target
            # open — the one ``finally`` in this package that did not cover
            # everything it had opened.
            close(source)
            if target is not None:
                close(target)
