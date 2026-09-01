"""Synthetic fixtures — no real document enters the repository.

The PDFs are generated on the fly by PyMuPDF, with invented text. That is what
lets the suite run in CI without carrying a private archive, and what guarantees
a failing test points at the code rather than at one specific file (CLAUDE.md
section 9).

This is the ONLY conftest in the suite, and deliberately so. The four slices —
``unit``, ``integration``, ``contract``, ``packaging`` — differ in what they are
allowed to touch, not in what they are handed, so a per-directory conftest would
either duplicate a fixture that is already here or hide one slice's setup from
another. A new fixture earns a directory conftest only when one slice needs it
and the others must not have it; see ``tests/README.md``.

Every fixture below returns BYTES, never a path and never an open document. A
fixture that owned a file would make the tests share state through the
filesystem, and a synthetic corpus is cheap enough to rebuild per test.
"""

from __future__ import annotations

import pytest


def _grey_image(width: int = 400, height: int = 300) -> bytes:
    """Any image, so it becomes an image block inside the PDF.

    It has to be a real image (a ``type == 1`` block), not a vector rectangle:
    the coverage gate asks about a large image in a region with no text, and a
    vector drawing is not an image — that is what made the first version of
    these tests pass by accident.
    """
    import pymupdf

    pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, width, height))
    pix.set_rect(pix.irect, (210,))
    for y in range(20, height - 20, 24):
        pix.set_rect(pymupdf.IRect(20, y, width - 20, y + 6), (40,))
    return pix.tobytes("png")


def _pdf(pages: list[str], *, with_image: bool = False) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    image = _grey_image() if with_image else None
    for text in pages:
        page = doc.new_page()
        if text:
            # Text only in the top half: the bottom is left for the attachment,
            # which is the real arrangement of a filing with a scanned document
            # embedded.
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 380), text, fontsize=11)
        if image is not None:
            page.insert_image(pymupdf.Rect(60, 400, 540, 740), stream=image)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def pdf_with_text() -> bytes:
    """A legitimate digital filing: prose and domain vocabulary."""
    body = (
        "EXCELENTISSIMO SENHOR DOUTOR JUIZ DE DIREITO DA VARA CIVEL\n\n"
        "O requerente, nos autos do processo 0001234-56.2020.8.12.0001, vem "
        "respeitosamente a presenca de Vossa Excelencia expor e ao final "
        "requerer o que segue. A decisao proferida nestes autos determinou a "
        "intimacao da parte executada para que se manifestasse no prazo legal, "
        "sob pena de preclusao. O exequente informa que a diligencia foi "
        "cumprida e que o mandado retornou devidamente cumprido em "
        "17/03/2005, conforme certidao de folhas seguintes.\n\n"
        "Nestes termos, pede deferimento."
    )
    return _pdf([body, body])


@pytest.fixture
def pdf_stamp_only() -> bytes:
    """The classic false success: only the conformity banner survived."""
    return _pdf(
        [
            "Este documento e copia do original assinado digitalmente por "
            "FULANO DE TAL. Para conferir o original acesse o site do "
            "tribunal e informe o codigo de verificacao 8A2F91C. fls. 42"
        ],
        with_image=True,
    )


@pytest.fixture
def pdf_blank() -> bytes:
    """A genuinely blank sheet — no text and no ink.

    There is nothing to extract, and escalating is pure cost: the gate never
    sends a page like this onwards.
    """
    return _pdf([""])


@pytest.fixture
def pdf_scanned() -> bytes:
    """A page with ink and no text layer — the OCR case.

    This is the fixture most cascade tests want: there is something to read, so
    the acceptance gate actually judges what the engine returned rather than
    accepting anything for want of an alternative.
    """
    return _pdf([""], with_image=True)


@pytest.fixture
def pdf_text_and_image() -> bytes:
    """Flawless text with a large attachment the text layer does not cover."""
    body = (
        "Peticao inicial nos autos do processo 0001234-56.2020.8.12.0001, em "
        "tramite perante a vara civel, em que o requerente pede a citacao do "
        "requerido na forma da decisao anterior, bem como a juntada dos "
        "documentos que seguem em anexo neste mesmo arquivo e cujo teor "
        "integra o pedido para todos os efeitos de direito. O exequente "
        "esclarece que a diligencia anterior restou infrutifera e que o "
        "oficial de justica certificou nos autos a impossibilidade de "
        "cumprimento, razao pela qual se requer nova tentativa no endereco "
        "indicado no documento anexo, que e parte integrante desta peticao."
    )
    return _pdf([body], with_image=True)
