"""What the page **has** drawn on it, to compare against what was extracted.

No I/O and no network: just reading the PDF structure in memory. The profile is
what lets the acceptance gate tell "the extraction failed" from "there is
nothing on this sheet" — a blank back page has no text to recover, and sending
it to an expensive step is pure cost.
"""

from __future__ import annotations

from dataclasses import dataclass

from autosxtract.pdf._mupdf import close, mupdf
from autosxtract.pdf.lock import pdf_lock


@dataclass(frozen=True)
class PageProfile:
    """An inventory of what is drawn in the document."""

    pages: int = 1
    has_image: bool = False
    has_vector: bool = False

    @property
    def has_visual_content(self) -> bool:
        """Something is drawn on the sheet that an OCR could read."""
        return self.has_image or self.has_vector


def profile(pdf_bytes: bytes) -> PageProfile:
    """Read from the PDF structure what is drawn on the pages.

    A read failure returns a conservative profile **with** visual content: when
    in doubt, let the gate decide from the text. A file that will not even open
    is exactly the case where OCR may be the only way out.
    """
    with pdf_lock():
        try:
            pymupdf = mupdf()
        except ImportError:
            return PageProfile(has_image=True)

        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            return PageProfile(has_image=True)

        try:
            n = len(doc)
            has_image = has_vector = False
            for page in doc:
                if not has_image and page.get_images(full=True):
                    has_image = True
                if not has_vector and page.get_drawings():
                    has_vector = True
                if has_image and has_vector:
                    break
            return PageProfile(pages=max(n, 1), has_image=has_image, has_vector=has_vector)
        except Exception:
            return PageProfile(has_image=True)
        finally:
            close(doc)
