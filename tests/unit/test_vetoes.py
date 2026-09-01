"""The five vetoes before the expensive step. Not escalating is NOT discarding."""

from __future__ import annotations

from autosxtract.quality.vetoes import LocalReading, assess_vetoes

PROSE = (
    "certidao de intimacao do executado expedida pela secretaria da vara civel "
    "para ciencia da decisao proferida nos autos do processo em epigrafe"
)


def _reading(text: str, reliable: int = 50) -> LocalReading:
    return LocalReading(
        text=text,
        words=reliable,
        reliable_words=reliable,
        mean_confidence=88.0,
        track="150/raw",
        pages_read=1,
    )


def test_without_a_witness_the_last_three_vetoes_do_not_run():
    """``None`` is "I don't know", never "there is no text"."""
    assert assess_vetoes(b"", "", local_reading=None, pixel_signals=False) is None


def test_a_local_ocr_with_no_legible_word_vetoes():
    """The only veto that MEASURES instead of estimating."""
    veto = assess_vetoes(b"", "", local_reading=_reading("", reliable=0), pixel_signals=False)
    assert veto is not None
    assert veto.name == "no_legible_word"
    assert "reliable words" in veto.evidence


def test_a_sparse_page_vetoes():
    """It asks "is there anything to read?" where the previous asks "can I read it?"."""
    veto = assess_vetoes(
        b"", "", local_reading=_reading("TERMO DE VISTA", reliable=3), pixel_signals=False
    )
    assert veto is not None
    assert veto.name == "sparse_page"


def test_a_confirmed_reading_vetoes():
    """Two engines read the same thing: the reading is already complete."""
    veto = assess_vetoes(b"", PROSE, local_reading=_reading(PROSE), pixel_signals=False)
    assert veto is not None
    assert veto.name == "reading_confirmed"
    assert "vocabulary" in veto.evidence


def test_diverging_readings_allow_escalation():
    other = (
        "ministerio da fazenda relatorio de consulta sem movimentacao apurada "
        "para o contribuinte indicado na pesquisa realizada pelo sistema"
    )
    assert assess_vetoes(b"", PROSE, local_reading=_reading(other), pixel_signals=False) is None


def test_agreement_turned_off_allows_escalation():
    assert (
        assess_vetoes(
            b"",
            PROSE,
            local_reading=_reading(PROSE),
            min_agreement=0.0,
            pixel_signals=False,
        )
        is None
    )
