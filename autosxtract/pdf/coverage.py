"""Does the text layer cover the whole page, or did it leave content behind?

The quality score describes the text that **came out**, not the fraction of the
page left out. In a filing that embeds an official letter as an image, the
native text is flawless and the attachment — which is the document's actual
content — is never read: high score, incomplete extraction.

This module answers a different question, then: is there a large image in a
region the text layer does not cover? ``True`` means "the native step cannot
end the cascade on its own".

An **additional** safety signal: any read failure returns ``False``, because
bringing the extraction down over it would trade a silent loss for a loud one.
"""

from __future__ import annotations

from autosxtract.pdf._mupdf import close, mupdf
from autosxtract.pdf.lock import pdf_lock

# Below this the image is a logo, a stamp or a rule — not the document's
# content, and demanding OCR because of it would escalate every letterheaded
# page.
MIN_PAGE_FRACTION = 0.15


def _area(rect) -> float:
    try:
        return abs(float(rect.width) * float(rect.height))
    except Exception:
        return 0.0


def has_image_without_text(pdf_bytes: bytes) -> bool:
    """Is there a large image in a page region with no line of text?"""
    with pdf_lock():
        try:
            pymupdf = mupdf()
        except ImportError:
            return False
        try:
            doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        except Exception:
            return False

        try:
            for page in doc:
                page_area = _area(page.rect)
                if page_area <= 0:
                    continue
                # Text blocks (``type`` 0) and image blocks (``type`` 1) come
                # from the SAME structured call.
                #
                # The per-image version (``get_image_rects``) **crashes the
                # process** under concurrency: captured with faulthandler, the
                # segfault happens in ``page_get_textpage``, inside
                # ``get_image_info``, with 24 documents in flight.
                # Sequentially the archive's 489 documents pass; concurrently
                # they kill the whole extraction. Besides not breaking, this is
                # cheaper: one traversal per page instead of one per image.
                blocks = page.get_text("dict").get("blocks") or []
                centres = [
                    ((b["bbox"][0] + b["bbox"][2]) / 2.0, (b["bbox"][1] + b["bbox"][3]) / 2.0)
                    for b in blocks
                    if b.get("type") == 0 and len(b.get("bbox") or ()) >= 4
                ]
                for block in blocks:
                    if block.get("type") != 1:
                        continue
                    box = tuple(block.get("bbox") or ())
                    if len(box) < 4:
                        continue
                    x1, y1, x2, y2 = box[:4]
                    if abs((x2 - x1) * (y2 - y1)) / page_area < MIN_PAGE_FRACTION:
                        continue
                    if not any(x1 <= x <= x2 and y1 <= y <= y2 for x, y in centres):
                        return True
            return False
        except Exception:
            return False
        finally:
            close(doc)
