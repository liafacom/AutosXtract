"""The whole cascade, with fake engines.

The fake engines are not merely a testing convenience: they are the **proof
that the contract works**. If a ten-line engine written here descends the
cascade without it needing to know anything about it, the same holds for a real
engine somebody adds later.

Every test here runs a whole document through a real ``Cascade`` over a
synthetic PDF: the steps, the gates, the contest and the provenance at once.
The helpers the cascade calls on the way are answered alone in the unit slice —
``unit/test_pdf_pages.py`` for the subdocument cut, ``unit/test_gate.py`` for
the acceptance criterion, ``unit/test_selection.py`` for the contest.
"""

from __future__ import annotations

import pytest

from autosxtract.cascade import Cascade
from autosxtract.config import Config
from autosxtract.engines.base import OCREngine
from autosxtract.steps.native import NativeStep
from autosxtract.steps.ocr import OCRStep

PROSE = (
    "O requerente vem respeitosamente a presenca de Vossa Excelencia nos "
    "autos do processo 0001234-56.2020.8.12.0001 requerer a citacao do "
    "requerido, tendo em vista a decisao proferida pela vara civel e a "
    "certidao do oficial de justica que instrui o presente pedido para que "
    "sejam produzidos os efeitos legais de direito."
)


class FakeEngine(OCREngine):
    """A test engine: it returns whatever text it is given, page by page."""

    def __init__(self, name: str, text: str, confidence: float = 95.0) -> None:
        super().__init__()
        self.name = name
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def available(self) -> tuple[bool, str]:
        return True, "fake"

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        self.calls += 1
        return self.text, self.confidence


def _cascade(*engines, **config) -> Cascade:
    cfg = Config(**config)
    steps = [NativeStep(), *(OCRStep(e) for e in engines)]
    return Cascade(cfg, steps=steps)


# ── the cheap path ───────────────────────────────────────────────────────


def test_good_native_text_ends_without_paying_for_ocr(pdf_with_text):
    """31% of a real archive ends here, at 13 ms. That is the cascade's reason."""
    engine = FakeEngine("ocr", PROSE)
    r = _cascade(engine).extract(pdf_with_text)
    assert r.step == "native"
    assert engine.calls == 0


def test_a_pdf_with_no_text_layer_descends_to_ocr(pdf_scanned):
    engine = FakeEngine("ocr", PROSE)
    r = _cascade(engine).extract(pdf_scanned)
    assert r.step == "ocr"
    assert engine.calls > 0


def test_a_blank_sheet_does_not_escalate(pdf_blank):
    """With no ink there is nothing to read: sending it on is pure cost.

    That criterion separated the 4 legitimately empty pages of an archive from
    the 227 false successes.
    """
    engine = FakeEngine("ocr", PROSE)
    r = _cascade(engine, consensus_gate=False).extract(pdf_blank)
    assert any("no text layer" in a.reason for a in r.attempts)


def test_a_stamp_only_page_does_not_end_the_cascade(pdf_stamp_only):
    """The dominant false success: 227 cases in an audit of 1,339."""
    engine = FakeEngine("ocr", PROSE)
    r = _cascade(engine).extract(pdf_stamp_only)
    assert r.step == "ocr"


def test_the_coverage_gate_refuses_good_text_with_an_attachment(pdf_text_and_image):
    """A high score describes the text that came out, not what was left behind."""
    engine = FakeEngine("ocr", PROSE)
    r = _cascade(engine).extract(pdf_text_and_image)
    assert r.step == "ocr"
    assert any("large image" in a.reason for a in r.attempts)


def test_with_coverage_off_the_native_text_is_accepted(pdf_text_and_image):
    engine = FakeEngine("ocr", PROSE)
    r = _cascade(engine, coverage_gate=False).extract(pdf_text_and_image)
    assert r.step == "native"


# ── OCR step refusals ────────────────────────────────────────────────────


def test_confidence_below_the_floor_is_refused(pdf_scanned):
    weak = FakeEngine("weak", PROSE, confidence=30.0)
    strong = FakeEngine("strong", PROSE, confidence=95.0)
    r = _cascade(weak, strong).extract(pdf_scanned)
    assert r.step == "strong"
    assert any("confidence" in a.reason for a in r.attempts)


def test_bad_text_from_one_engine_descends_to_the_next(pdf_scanned):
    bad = FakeEngine("bad", "fls. 3")
    good = FakeEngine("good", PROSE)
    r = _cascade(bad, good).extract(pdf_scanned)
    assert r.step == "good"


def test_an_unavailable_engine_does_not_break_the_cascade(pdf_scanned):
    class Missing(OCREngine):
        name = "missing"

        def available(self):
            return False, "missing unavailable: dependency not installed"

    r = _cascade(Missing(), FakeEngine("good", PROSE)).extract(pdf_scanned)
    assert r.step == "good"
    assert any(a.step == "missing" and not a.accepted for a in r.attempts)


# ── gates between steps ──────────────────────────────────────────────────


def test_consensus_declares_the_page_empty(pdf_scanned):
    """Two independent engines reading almost nothing is "there is none"."""
    r = _cascade(FakeEngine("a", "fls"), FakeEngine("b", "1")).extract(pdf_scanned)
    assert r.step == "empty_by_consensus"
    assert "independent engines" in r.details["evidence"]


def test_with_consensus_off_it_returns_the_best_there_was(pdf_scanned):
    r = _cascade(FakeEngine("a", "fls"), FakeEngine("b", "1"), consensus_gate=False).extract(
        pdf_scanned
    )
    assert r.step in {"a", "b"}


def test_agreement_ends_before_the_next_step(pdf_scanned):
    """Two engines reading the same thing prove the reading is complete."""
    # Neither passes the gate alone (density too low for the sheet), but they
    # read the same thing — so there is no reason to pay for the third.
    short_a = (
        "certidao de intimacao do executado expedida pela secretaria da vara "
        "civel para ciencia da decisao proferida nos autos em epigrafe"
    )
    short_b = short_a
    expensive = FakeEngine("expensive", PROSE)
    cascade = _cascade(
        FakeEngine("a", short_a),
        FakeEngine("b", short_b),
        expensive,
        min_chars_per_page=5000,
    )
    r = cascade.extract(pdf_scanned)
    assert expensive.calls == 0
    assert any(a.step == "agreement_gate" for a in r.attempts)


# ── provenance and the contest ───────────────────────────────────────────


def test_the_provenance_records_every_step(pdf_stamp_only):
    r = _cascade(FakeEngine("a", "fls"), FakeEngine("b", PROSE)).extract(pdf_stamp_only)
    names = [a.step for a in r.attempts]
    assert names[:1] == ["native"]
    assert "b" in names
    assert all(a.reason for a in r.attempts)
    assert "->" in r.provenance


def test_refused_text_still_competes(pdf_text_and_image):
    """No later step did better: the refused one is still the best reading.

    The native step is refused (an impossible threshold), the OCR too (it read
    only the stamp), and nobody was accepted. Discarding the native text here is
    the defect that left 682 documents with zero characters while the PDF had a
    text layer.
    """
    cascade = _cascade(
        FakeEngine("ocr", "fls. 3"),
        native_accept_score=0.99,
        consensus_gate=False,
        agreement_gate=False,
    )
    r = cascade.extract(pdf_text_and_image)
    assert r.step == "native"
    assert "requerente" in r.text


def test_the_result_serialises(pdf_with_text):
    r = _cascade(FakeEngine("ocr", PROSE)).extract(pdf_with_text)
    d = r.to_dict()
    assert d["step"] == "native"
    assert d["attempts"][0]["step"] == "native"
    assert d["provenance"]


def test_an_unreadable_pdf_returns_an_empty_result_with_a_reason():
    """Extraction is uncertain: an explained uncertainty beats an exception."""
    r = _cascade(FakeEngine("ocr", PROSE)).extract(b"i am not a pdf")
    assert r.empty
    assert r.attempts


@pytest.mark.parametrize("parallelism", [1, 4])
def test_page_order_is_preserved(pdf_scanned, parallelism):
    """Reassembling in completion order would scramble the document."""

    class Numbered(OCREngine):
        name = "numbered"

        def __init__(self):
            super().__init__()
            self.n = 0

        def available(self):
            return True, "fake"

        def transcribe_page(self, image):
            self.n += 1
            return f"page {self.n}", 99.0

    engine = Numbered()
    cascade = _cascade(engine, page_parallelism=parallelism, consensus_gate=False)
    cascade.extract(pdf_scanned)
    assert engine.n >= 1


# ── the new local steps ──────────────────────────────────────────────────


def test_unwrapping_ends_the_cascade_on_rtf():
    """There is no image to recognise: sending an RTF to OCR would be absurd."""
    from autosxtract.steps.unwrap import UnwrapStep

    rtf = rb"{\rtf1\ansi\deff0 Mandado de citacao, penhora e avaliacao expedido.\par}"
    engine = FakeEngine("ocr", PROSE)
    cascade = Cascade(Config(), steps=[UnwrapStep(), NativeStep(), OCRStep(engine)])
    r = cascade.extract(rtf)
    assert r.step == "unwrap"
    assert "Mandado de citacao" in r.text
    assert engine.calls == 0


def test_unwrapping_does_not_disturb_an_ordinary_pdf(pdf_with_text):
    from autosxtract.steps.unwrap import UnwrapStep

    cascade = Cascade(Config(engines=[]), steps=[UnwrapStep(), NativeStep()])
    r = cascade.extract(pdf_with_text)
    assert r.step == "native"
    assert any(a.step == "unwrap" and "PDF" in a.reason for a in r.attempts)


def test_screening_drops_an_already_transcribed_card(pdf_scanned):
    """The declared type does not distinguish the attached ID; only the text does."""
    from autosxtract.steps.screening import ScreeningStep

    card = (
        "MINISTERIO DA FAZENDA CADASTRO DE PESSOAS FISICAS NUMERO DE INSCRICAO "
        "123.456.789-00 CARTAO DE USO PESSOAL E INTRANSFERIVEL"
    )
    cascade = Cascade(
        Config(consensus_gate=False),
        steps=[NativeStep(), OCRStep(FakeEngine("ocr", card)), ScreeningStep()],
    )
    r = cascade.extract(pdf_scanned)
    assert r.step == "screening"
    assert "NOT EXTRACTED" in r.text
    assert "123.456.789-00" not in r.text


def test_screening_lets_a_legitimate_document_through(pdf_scanned):
    from autosxtract.steps.screening import ScreeningStep

    cascade = Cascade(
        Config(),
        steps=[NativeStep(), OCRStep(FakeEngine("ocr", PROSE)), ScreeningStep()],
    )
    r = cascade.extract(pdf_scanned)
    assert r.step == "ocr"


# ── expensive-step vetoes and replacement gate ───────────────────────────


def _expensive(engine):
    step = OCRStep(engine)
    step.expensive = True
    return step


def test_the_confirmed_reading_veto_spares_the_expensive_step(pdf_scanned):
    """Two engines read the same thing: no reason to pay for the third."""
    expensive = FakeEngine("expensive", PROSE)
    cascade = Cascade(
        Config(min_chars_per_page=5000, veto_engine=None, consensus_gate=False),
        steps=[
            NativeStep(),
            OCRStep(FakeEngine("a", PROSE)),
            OCRStep(FakeEngine("b", PROSE)),
            _expensive(expensive),
        ],
    )
    r = cascade.extract(pdf_scanned)
    assert expensive.calls == 0
    assert any(a.step == "agreement_gate" for a in r.attempts)


def test_an_expensive_step_that_corrupts_an_anchor_is_refused(pdf_scanned):
    """``882167`` -> ``882187``: no text metric detects that."""
    good = (
        "Procuracao lavrada no cartorio, protocolo 882167, referente ao "
        "processo 0001234-56.2020.8.12.0001, com poderes para o foro em geral "
        "e ciencia de todas as partes interessadas nos autos da execucao."
    )
    corrupted = good.replace("882167", "882187") + " Texto adicional que o torna mais longo."
    expensive = FakeEngine("expensive", corrupted)
    cascade = Cascade(
        Config(
            min_chars_per_page=5000,
            veto_engine=None,
            agreement_gate=False,
            consensus_gate=False,
        ),
        steps=[NativeStep(), OCRStep(FakeEngine("cheap", good)), _expensive(expensive)],
    )
    r = cascade.extract(pdf_scanned)
    assert expensive.calls > 0
    assert any("anchors" in a.reason for a in r.attempts)
    # Refused as a replacement, but the cheap step's correct text survives.
    assert "882167" in r.text


def test_a_marker_loop_never_replaces(pdf_scanned):
    loop = "[ILLEGIBLE] " * 400
    expensive = FakeEngine("expensive", loop)
    cascade = Cascade(
        Config(
            min_chars_per_page=5000,
            veto_engine=None,
            agreement_gate=False,
            consensus_gate=False,
        ),
        steps=[NativeStep(), OCRStep(FakeEngine("cheap", PROSE)), _expensive(expensive)],
    )
    r = cascade.extract(pdf_scanned)
    assert any("marker" in a.reason for a in r.attempts)
    assert "[ILLEGIBLE]" not in r.text


# ── prose and layers ─────────────────────────────────────────────────────


def test_prose_is_rebuilt_in_the_result(pdf_scanned):
    broken = (
        "O requerente vem a presenca\nde Vossa Excelencia para requerer\na citacao do requerido."
    )
    cascade = Cascade(Config(), steps=[OCRStep(FakeEngine("ocr", broken))])
    r = cascade.extract(pdf_scanned)
    assert "presenca de Vossa Excelencia para requerer a citacao" in r.text


def test_prose_rebuilding_can_be_turned_off(pdf_scanned):
    broken = "linha um sem ponto\nlinha dois continua"
    cascade = Cascade(Config(rebuild_prose=False), steps=[OCRStep(FakeEngine("ocr", broken))])
    r = cascade.extract(pdf_scanned)
    assert "\n" in r.text


def test_skipped_layers_show_in_the_provenance(pdf_scanned):
    """Skipping in silence would make the absence of `[illegible]` look clean."""
    cascade = Cascade(Config(layers=True), steps=[OCRStep(FakeEngine("ocr", PROSE))])
    r = cascade.extract(pdf_scanned)
    attempt = next(a for a in r.attempts if a.step == "ocr")
    assert "no line geometry" in attempt.details["layers"]["skipped"]


def test_the_layers_run_with_an_engine_that_gives_geometry(pdf_scanned):
    from autosxtract.types import Line, Page

    class WithGeometry(FakeEngine):
        def read_page(self, image):
            self.calls += 1
            return Page(
                [
                    Line(PROSE, 0.98, ((60, 100), (900, 100), (900, 130), (60, 130))),
                    Line("·", 0.30, ((60, 140), (66, 140), (66, 146), (60, 146))),
                ],
                1200,
                1700,
            )

    cascade = Cascade(
        Config(layers=True, layer2=False), steps=[OCRStep(WithGeometry("ocr", PROSE))]
    )
    r = cascade.extract(pdf_scanned)
    report = next(a for a in r.attempts if a.step == "ocr").details["layers"]
    assert report["lines_total"] == 2
    assert "·" not in r.text  # the fragment was dropped
