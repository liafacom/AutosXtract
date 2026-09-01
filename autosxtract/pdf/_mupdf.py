"""A single place to import PyMuPDF.

The library changed names: the canonical module became ``pymupdf`` and the
historical ``fitz`` became a deprecated alias that warns on recent versions and
disappears on future ones. Old installations, though, only have ``fitz``.

Importing here and nowhere else means that transition is one line of code
rather than a sweep across the package.
"""

from __future__ import annotations

import contextlib
import functools


@functools.cache
def mupdf():
    """The PyMuPDF module, under either name.

    Raises ``ImportError`` when neither exists — callers decide whether that is
    "I don't know" (the optional signals) or an error (a cascade with no steps).
    """
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        import fitz  # old installation

        return fitz


def close(doc) -> None:
    """Close a document without letting the close error mask the real one.

    This shows up in every ``finally`` that opens a PDF: if the read already
    failed, an exception in ``close`` would replace the true diagnosis with a
    generic one.
    """
    with contextlib.suppress(Exception):
        doc.close()
