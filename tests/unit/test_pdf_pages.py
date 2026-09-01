"""Cutting a document down to the pages a step asked for.

This is the helper behind page routing: a step that takes a FILE rather than an
image — docling, a VLM served a PDF — is handed a subdocument of the pages the
cascade still wants read, never the whole filing. The synthetic PDF is parsed,
not rendered, so the test stays in the unit slice.
"""

from __future__ import annotations

from autosxtract.pdf.pages import count, subdocument


def test_subdocument_cuts_the_requested_pages(pdf_with_text):
    """This is what goes to a step that takes a FILE rather than an image."""
    assert count(pdf_with_text) == 2
    cut = subdocument(pdf_with_text, [1])
    assert cut is not None
    assert count(cut) == 1


def test_subdocument_with_no_pages_returns_none(pdf_with_text):
    assert subdocument(pdf_with_text, []) is None
