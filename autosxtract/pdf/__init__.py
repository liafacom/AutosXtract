"""Reading and rasterising PDFs — the layer that only knows the file.

Nothing here knows what an OCR engine or a cascade is. That is the boundary
that lets everything above be swapped without touching the code that talks to
PyMuPDF.
"""

from autosxtract.pdf.coverage import has_image_without_text
from autosxtract.pdf.ink import ink_fraction, is_nearly_blank, is_photograph
from autosxtract.pdf.lock import open_pdf, pdf_lock
from autosxtract.pdf.pages import count, is_mixed, subdocument, without_text
from autosxtract.pdf.profile import PageProfile, profile
from autosxtract.pdf.render import render

__all__ = [
    "PageProfile",
    "count",
    "has_image_without_text",
    "ink_fraction",
    "is_mixed",
    "is_nearly_blank",
    "is_photograph",
    "open_pdf",
    "pdf_lock",
    "profile",
    "render",
    "subdocument",
    "without_text",
]
