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

import hashlib
import re
import time

import pytest

from autosxtract.cascade import Cascade
from autosxtract.config import Config
from autosxtract.engines.base import OCREngine
from autosxtract.steps.base import Context
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


def _rendered_pages(pdf_bytes: bytes, config: Config) -> list[bytes]:
    """The very images the cascade will hand the engine, in document order.

    Built through ``Context`` rather than by calling ``render`` directly, so the
    DPI, the greyscale flag and the orientation fix are whatever the cascade
    itself would apply — otherwise the bytes a test hashes are not the bytes the
    engine is handed.
    """
    return Context(pdf_bytes=pdf_bytes, config=config).images()


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
def test_page_order_is_preserved(pdf_scanned_multipage, parallelism):
    """Reassembling in completion order would scramble the document.

    Two things this test needs in order to prove anything, and the version it
    replaces had neither. The fixture must have SEVERAL pages — ``transcribe``
    takes the sequential branch below two, so the ``parallelism=4`` case never
    reached the code it was parametrised to exercise, and order cannot be wrong
    in a one-page document. And the assertion has to look at the TEXT: the old
    one was ``engine.n >= 1``, which a reassembly by completion order satisfies
    just as well as one by input order.

    The engine labels each page by the image it was handed, not by call order —
    a counter would only record the order the threads happened to start in.
    """

    class Numbered(OCREngine):
        name = "numbered"

        def __init__(self):
            super().__init__()
            self.seen: list[bytes] = []

        def available(self):
            return True, "fake"

        def transcribe_page(self, image):
            # Slow the FIRST page down so completion order and input order
            # genuinely differ under threads. Without this the parallel path can
            # finish in input order by luck and the test proves nothing.
            if not self.seen:
                time.sleep(0.05)
            self.seen.append(image)
            marker = hashlib.sha1(image).hexdigest()[:8]
            return f"conteudo da pagina com marcador {marker} nos autos", 99.0

    engine = Numbered()
    cascade = _cascade(engine, page_parallelism=parallelism, consensus_gate=False)
    images = _rendered_pages(pdf_scanned_multipage, cascade.config)
    assert len(images) >= 4, "the fixture must be multi-page for this test to mean anything"
    # And the pages must be DISTINGUISHABLE, or every order satisfies the
    # assertion below. This guard is the one that catches a fixture regression.
    assert len({hashlib.sha1(i).hexdigest() for i in images}) == len(images)

    r = cascade.extract(pdf_scanned_multipage)

    expected = [hashlib.sha1(image).hexdigest()[:8] for image in images]
    found = re.findall(r"marcador ([0-9a-f]{8})", r.text)
    assert found == expected


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


# ── the vetoes, reached THROUGH the cascade (CLAUDE.md §13) ──────────────
#
# `tests/unit/test_vetoes.py` answers `assess_vetoes` as a pure function, and
# answers it well. What had no test at all was the WIRING: every cascade test
# with an expensive step switched the vetoes off (`veto_engine=None` or
# `expensive_step_vetoes=False`), so `cascade._veto` and the whole of
# `cascade._witness` were never executed. Deleting the veto block from
# `extract` left the suite green and the 27.2 minutes per document that §13
# claims to save silently stopped being saved.


class _Witness:
    """A local engine of another architecture, standing in for Tesseract."""

    name = "witness"

    def __init__(self, reading=None, *, ok=True, reason="fake", raises=False) -> None:
        self.reading = reading
        self.ok = ok
        self.reason = reason
        self.raises = raises
        self.calls = 0

    def available(self):
        return self.ok, self.reason

    def read_document(self, pdf_bytes, *, max_pages=3, min_reliable_words=3):
        self.calls += 1
        if self.raises:
            raise RuntimeError("the witness fell over")
        return self.reading


def _with_witness(monkeypatch, witness):
    """Point `config.veto_engine` at a fake through the registry lookup."""
    from autosxtract import cascade as cascade_module

    def fake_get(name, **options):
        if name == "witness":
            return witness
        raise LookupError(name)

    monkeypatch.setattr(cascade_module.engines, "get", fake_get)


def test_a_veto_skips_the_expensive_step_and_says_so(monkeypatch, pdf_scanned):
    """The blocking half: the step does not run, and the provenance carries why."""
    from autosxtract.quality.vetoes import LocalReading

    witness = _Witness(LocalReading(text="", words=0, reliable_words=0, track="direct"))
    _with_witness(monkeypatch, witness)
    expensive = FakeEngine("expensive", PROSE)
    cascade = Cascade(
        Config(
            min_chars_per_page=5000,
            veto_engine="witness",
            expensive_step_vetoes=True,
            consensus_gate=False,
            agreement_gate=False,
        ),
        steps=[NativeStep(), OCRStep(FakeEngine("cheap", "")), _expensive(expensive)],
    )
    r = cascade.extract(pdf_scanned)

    assert expensive.calls == 0, "the veto has to stop the expensive step running"
    assert any(a.step == "veto:no_legible_word" for a in r.attempts)
    assert "veto:no_legible_word" in r.provenance


def test_the_cheap_pixel_vetoes_run_BEFORE_the_witness(monkeypatch, pdf_blank):
    """§13's cost order: pixel statistics at 40 DPI (ms), THEN a real OCR (~1 s).

    The witness used to be evaluated as an argument to ``assess_vetoes``, so
    Python ran it first: a blank sheet paid for a full local OCR — with its
    300 DPI recovery track — before the veto written to reject it for free got
    to run. Passing a callable is what keeps the declared order honest, and this
    asserts the witness was never asked at all.
    """
    witness = _Witness(None)
    _with_witness(monkeypatch, witness)
    expensive = FakeEngine("expensive", PROSE)
    cascade = Cascade(
        Config(
            min_chars_per_page=5000,
            veto_engine="witness",
            expensive_step_vetoes=True,
            consensus_gate=False,
            agreement_gate=False,
        ),
        steps=[NativeStep(), OCRStep(FakeEngine("cheap", "")), _expensive(expensive)],
    )
    r = cascade.extract(pdf_blank)

    assert any(a.step.startswith("veto:") for a in r.attempts)
    assert witness.calls == 0, "a pixel veto fired; the ~1 s witness must not have run"


def test_a_missing_witness_reaches_the_provenance(monkeypatch, pdf_scanned):
    """§3's corollary: degrading without breaking is right, in silence is not.

    With Tesseract off the PATH, vetoes 3 to 5 never fire and every escalated
    document pays the expensive step. That used to produce a provenance
    byte-for-byte identical to a run where the witness had approved — the one
    thing that made the difference invisible to whoever reads the record.
    """
    witness = _Witness(None, ok=False, reason="tesseract is not on the PATH")
    _with_witness(monkeypatch, witness)
    expensive = FakeEngine("expensive", PROSE)
    cascade = Cascade(
        Config(
            min_chars_per_page=5000,
            veto_engine="witness",
            expensive_step_vetoes=True,
            consensus_gate=False,
            agreement_gate=False,
        ),
        steps=[NativeStep(), OCRStep(FakeEngine("cheap", PROSE)), _expensive(expensive)],
    )
    r = cascade.extract(pdf_scanned)

    notes = [a for a in r.attempts if a.step == "veto:witness"]
    assert notes, "the absence of the witness has to be recorded"
    assert "tesseract is not on the PATH" in notes[0].reason
    # And it is a NOTE, not a veto: the expensive step still ran.
    assert expensive.calls > 0


def test_a_witness_that_raises_never_brings_the_cascade_down(monkeypatch, pdf_scanned):
    witness = _Witness(None, raises=True)
    _with_witness(monkeypatch, witness)
    expensive = FakeEngine("expensive", PROSE)
    cascade = Cascade(
        Config(
            min_chars_per_page=5000,
            veto_engine="witness",
            expensive_step_vetoes=True,
            consensus_gate=False,
            agreement_gate=False,
        ),
        steps=[NativeStep(), OCRStep(FakeEngine("cheap", PROSE)), _expensive(expensive)],
    )
    r = cascade.extract(pdf_scanned)

    assert r.attempts
    assert any(a.step == "veto:witness" and "failed to read" in a.reason for a in r.attempts)
    assert expensive.calls > 0


# ── per-page routing must not lose the native half ───────────────────────


def test_routing_puts_the_ocr_page_back_among_the_native_ones(pdf_mixed):
    """Routing is an economy, not a decision about what the document IS.

    With `per_page_routing` on, only the pages WITHOUT native text are
    rasterised — and the step's candidate used to be just those pages. On a
    mixed filing that means the result is either the native text without the
    scanned attachment, or the attachment without the pages around it, never the
    union: measured on the shape this library was built for, a 39-page filing
    with 29 native pages and a 10-page attachment lost 29 pages of text with
    nothing in the provenance to say so.

    `DoclingStep` had `_reassemble` for exactly this; `OCRStep` had no
    counterpart.
    """
    marker = "MARCADOR DA PAGINA DIGITALIZADA que so o motor de OCR pode ler"
    engine = FakeEngine("ocr", marker)
    cascade = Cascade(
        Config(per_page_routing=True, coverage_gate=False, consensus_gate=False),
        steps=[NativeStep(), OCRStep(engine)],
    )
    r = cascade.extract(pdf_mixed)

    # Only the one page without a text layer was rasterised.
    ocr_attempt = next(a for a in r.attempts if a.step == "ocr")
    assert ocr_attempt.details["ocr_pages"] == [2]
    assert engine.calls == 1

    # BOTH halves survive, and the OCR'd page sits between the native ones
    # rather than at the end.
    assert marker in r.text
    assert "Pagina 1." in r.text
    assert "Pagina 4." in r.text
    assert r.text.index("Pagina 1.") < r.text.index(marker) < r.text.index("Pagina 4.")


def test_the_merge_says_so_when_it_cannot_align(pdf_mixed):
    """No alignment, no merge — and never in silence.

    An engine that overrides `transcribe` without filling `page_texts` leaves
    nothing to align by. Guessing the order would reintroduce the scrambling;
    dropping the native pages quietly is the defect above. The only honest
    answer is to keep the engine's text and record why.
    """

    class NoAlignment(FakeEngine):
        def transcribe(self, pages, *, parallelism=4, force_parallelism=False):
            from autosxtract.types import Transcription

            return Transcription(
                text=self.text,
                engine=self.name,
                pages_sent=len(pages),
                pages_answered=len(pages),
                mean_confidence=95.0,
            )

    engine = NoAlignment("ocr", "texto sem alinhamento nenhum por pagina")
    cascade = Cascade(
        Config(per_page_routing=True, coverage_gate=False, consensus_gate=False),
        steps=[NativeStep(), OCRStep(engine)],
    )
    r = cascade.extract(pdf_mixed)

    ocr_attempt = next(a for a in r.attempts if a.step == "ocr")
    assert "native_merge" in ocr_attempt.details
    assert "skipped" in ocr_attempt.details["native_merge"]


# ── the acceptance gate sees the SCORE (CLAUDE.md §2) ────────────────────


def test_low_quality_text_escalates_even_when_it_is_long_enough(pdf_scanned):
    """`Config.min_score` reached the gate through nobody.

    `OCRStep` computed the score for the contest and passed neither `score=` nor
    `min_score=` to `evaluate`, so the gate's quality branch was unreachable in
    production: text that cleared the word floor and the density floor stopped
    the cascade whatever its quality, and the better engine underneath it never
    ran. Half of "the same question with the same code" was not being asked.
    """
    # Long and word-rich enough to clear the word floor and the density floor,
    # and junk by the scorer: `score_text` puts it at 0.40. `min_score` is
    # raised above it so the assertion is about the WIRING — whether the
    # configured floor reaches `evaluate` at all — rather than about where the
    # shipped default happens to sit.
    junk = " ".join(["xkq zwvb jhgf tprm ndsl" for _ in range(120)])
    from autosxtract.quality.scoring import score_text

    assert score_text(junk)["score"] < 0.5
    good = FakeEngine("good", PROSE)
    cascade = _cascade(
        FakeEngine("junk", junk),
        good,
        min_score=0.5,
        consensus_gate=False,
        agreement_gate=False,
    )
    r = cascade.extract(pdf_scanned)

    junk_attempt = next(a for a in r.attempts if a.step == "junk")
    assert not junk_attempt.accepted
    assert "below the minimum" in junk_attempt.reason
    assert good.calls > 0, "the engine underneath the junk has to get its turn"
