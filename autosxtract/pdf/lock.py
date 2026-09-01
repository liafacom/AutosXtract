"""A process-wide lock for PyMuPDF access.

The library **crashes the process** when several threads use it at once. This
is not a hypothesis: captured with ``faulthandler``, the segfault comes out in
``page_get_textpage``, and it was reproduced on the bench with 489 archive PDFs
across 12 threads. ``try/except`` does not protect you — a segmentation fault is
not a Python exception, and the whole extraction dies mid-run.

The cost of serialising is close to zero, and that is measured: rendering 120
PDFs took 37.2 s with 4 threads and 38.6 s with 24. The library already
serialises internally, so the lock trades a crash for no practical loss of
throughput. The parallelism that matters — the OCR engines — happens OUTSIDE it.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

from autosxtract.pdf._mupdf import close, mupdf

_LOCK = threading.RLock()


@contextmanager
def pdf_lock():
    """Serialise a section that uses PyMuPDF.

    Reentrant on purpose: the cascade's entry points call each other (the
    quality analysis uses the page profile, which opens the document), and a
    plain ``Lock`` would deadlock the process against itself.
    """
    with _LOCK:
        yield


@contextmanager
def open_pdf(pdf_bytes: bytes):
    """Open the PDF under the lock and guarantee it is closed.

    Raises whatever PyMuPDF raises — the caller decides whether a failure to
    open is an error or merely "I don't know". The optional-signal modules
    treat it as "I don't know"; the cascade treats it as an error.
    """
    with pdf_lock():
        doc = mupdf().open(stream=pdf_bytes, filetype="pdf")
        try:
            yield doc
        finally:
            close(doc)
