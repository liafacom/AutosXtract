"""``Result.page_texts`` — the winning text, page by page.

``Result.text`` is one string per document, and it cannot be split back into
pages: a blank page leaves no separator behind, and a page's own text may
contain the blank line the join uses. The per-page view existed all along —
``read_native_text`` returns it, ``Transcription.page_texts`` carries it — and
stopped one object short of the caller. These tests pin the wiring from the
step that produced the text to the ``Result`` that leaves the cascade, for the
native step, for an OCR step, and across the per-page routing merge.

They live in the integration slice because every one of them runs a whole
``Cascade`` over a synthetic PDF: the field is a promise about what the cascade
RETURNS, and a test of ``Candidate`` alone would not say whether it arrives.
"""

from __future__ import annotations

import pymupdf

from autosxtract.cascade import Cascade
from autosxtract.config import Config
from autosxtract.engines.base import OCREngine
from autosxtract.steps.native import NativeStep
from autosxtract.steps.ocr import OCRStep

PAGE_ONE = (
    "PRIMEIRA PAGINA DO DOCUMENTO. O requerente vem respeitosamente a presenca "
    "de Vossa Excelencia nos autos do processo 0001234-56.2020.8.12.0001 "
    "requerer a citacao do requerido, tendo em vista a decisao proferida pela "
    "vara civel e a certidao do oficial de justica que instrui o presente pedido "
    "para que sejam produzidos os efeitos legais de direito."
)
PAGE_TWO = (
    "SEGUNDA PAGINA DO DOCUMENTO. Nestes termos, o exequente informa que a "
    "diligencia foi cumprida e que o mandado retornou devidamente cumprido, "
    "conforme certidao de folhas seguintes, razao pela qual pede deferimento "
    "do pedido formulado na forma da fundamentacao que segue e dos documentos "
    "anexos, para todos os efeitos de direito."
)


def _pdf(pages: list[str]) -> bytes:
    """A born-digital PDF with one text box per page — the 31% case."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 700), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


class FakeEngine(OCREngine):
    """Returns a DIFFERENT text per page, so alignment can be checked."""

    def __init__(self, name: str, texts: list[str], confidence: float = 95.0) -> None:
        super().__init__()
        self.name = name
        self.texts = texts
        self.confidence = confidence
        self.calls = 0

    def available(self) -> tuple[bool, str]:
        return True, "fake"

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        text = self.texts[self.calls % len(self.texts)]
        self.calls += 1
        return text, self.confidence


# ── the native step ──────────────────────────────────────────────────────


def test_a_two_page_native_pdf_returns_one_entry_per_page():
    """The case the field exists for: two pages, two strings, in order."""
    from autosxtract import extract

    r = extract(_pdf([PAGE_ONE, PAGE_TWO]), Config(engines=[]))

    assert r.step == "native"
    assert len(r.page_texts) == 2
    assert "PRIMEIRA PAGINA" in r.page_texts[0]
    assert "SEGUNDA PAGINA" in r.page_texts[1]
    # And each page holds ONLY its own text: an alignment off by one would put
    # the second page's marker in the first slot.
    assert "SEGUNDA PAGINA" not in r.page_texts[0]
    assert "PRIMEIRA PAGINA" not in r.page_texts[1]


def test_a_blank_page_in_the_middle_keeps_its_slot():
    """Dropping the empty page is how every page after it shifts by one."""
    cascade = Cascade(Config(engines=[]), steps=[NativeStep()])
    r = cascade.extract(_pdf([PAGE_ONE, "", PAGE_TWO]))

    assert r.step == "native"
    assert len(r.page_texts) == 3
    assert r.page_texts[1] == ""
    assert "SEGUNDA PAGINA" in r.page_texts[2]


def test_the_pages_receive_the_same_treatment_as_the_text():
    """``text`` and ``page_texts`` are two views of ONE output, not two outputs."""
    cascade = Cascade(Config(engines=[]), steps=[NativeStep()])
    r = cascade.extract(_pdf([PAGE_ONE, PAGE_TWO]))

    # Every page's text is somewhere in the joined text, after the same prose
    # rebuilding — a line broken in one and joined in the other would fail this.
    for page in r.page_texts:
        assert page in r.text


# ── the OCR step ─────────────────────────────────────────────────────────


def test_an_ocr_step_carries_the_engine_pages_in_order():
    """Without routing every page is rasterised; the engine's list is the document's."""
    from autosxtract.steps.base import Context

    scanned = _scanned_pdf(2)
    config = Config(consensus_gate=False, rebuild_prose=False)
    engine = FakeEngine("ocr", [PAGE_ONE, PAGE_TWO])
    cascade = Cascade(config, steps=[NativeStep(), OCRStep(engine)])
    # The fake hands texts out in CALL order; below two pages the engine takes
    # the sequential branch, so call order is page order and the check holds.
    assert len(Context(pdf_bytes=scanned, config=config).images()) == 2

    r = cascade.extract(scanned)

    assert r.step == "ocr"
    assert r.page_texts == [PAGE_ONE, PAGE_TWO]


def test_routing_puts_the_ocr_page_back_at_its_index(pdf_mixed):
    """Pages 0, 1 and 3 have a text layer; page 2 is scanned. The per-page list
    has to span the whole document, with the OCR'd text at index 2 — not a
    one-element list of what the engine was handed."""
    marker = "MARCADOR DA PAGINA DIGITALIZADA que so o motor de OCR pode ler"
    engine = FakeEngine("ocr", [marker])
    cascade = Cascade(
        Config(per_page_routing=True, coverage_gate=False, consensus_gate=False),
        steps=[NativeStep(), OCRStep(engine)],
    )
    r = cascade.extract(pdf_mixed)

    assert r.step == "ocr"
    assert len(r.page_texts) == 4
    assert marker in r.page_texts[2]
    assert "Pagina 1." in r.page_texts[0]
    assert "Pagina 2." in r.page_texts[1]
    assert "Pagina 4." in r.page_texts[3]


def test_an_engine_with_no_per_page_view_yields_no_page_texts(pdf_mixed):
    """No alignment means an EMPTY list, never a guess: a per-page list that
    does not span the document would be read as one that does."""

    class NoAlignment(FakeEngine):
        def transcribe(self, pages, *, parallelism=4, force_parallelism=False):
            from autosxtract.types import Transcription

            return Transcription(
                text=self.texts[0],
                engine=self.name,
                pages_sent=len(pages),
                pages_answered=len(pages),
                mean_confidence=95.0,
            )

    engine = NoAlignment("ocr", ["texto sem alinhamento nenhum por pagina"])
    cascade = Cascade(
        Config(per_page_routing=True, coverage_gate=False, consensus_gate=False),
        steps=[NativeStep(), OCRStep(engine)],
    )
    r = cascade.extract(pdf_mixed)

    if r.step == "ocr":
        assert r.page_texts == []


# ── serialisation stays backward compatible ──────────────────────────────


def test_to_dict_carries_the_pages_only_when_there_are_any():
    """A result with no per-page view serialises exactly as before the field."""
    from autosxtract.types import Result

    with_pages = Result(text="a\n\nb", step="native", score=0.9, ms=1.0, page_texts=["a", "b"])
    assert with_pages.to_dict()["page_texts"] == ["a", "b"]

    without = Result(text="", step="none", score=None, ms=1.0)
    assert "page_texts" not in without.to_dict()


def test_an_empty_result_has_no_pages():
    r = Cascade(Config(engines=[]), steps=[NativeStep()]).extract(b"i am not a pdf")
    assert r.empty
    assert r.page_texts == []


# ── helpers ──────────────────────────────────────────────────────────────


def _scanned_pdf(pages: int) -> bytes:
    """Pages with ink and no text layer, each with a different image."""
    doc = pymupdf.open()
    for index in range(pages):
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 400, 300))
        pix.set_rect(pix.irect, (210,))
        offset = (index * 7) % 24
        for y in range(20 + offset, 280, 24):
            pix.set_rect(pymupdf.IRect(20 + offset, y, 380, y + 6), (40,))
        page = doc.new_page()
        page.insert_image(pymupdf.Rect(60, 400, 540, 740), stream=pix.tobytes("png"))
    data = doc.tobytes()
    doc.close()
    return data
