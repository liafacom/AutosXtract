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


# ── the two pixel vetoes ─────────────────────────────────────────────────
#
# Until ``InkSignals`` existed these had no test at all: ``assess_vetoes``
# called ``pdf.ink`` directly, so exercising them meant building a PDF and
# opening it with PyMuPDF, and every test above opted out with
# ``pixel_signals=False``. Lines 97-100 were the only uncovered ones in the
# module — and they are the branch that can THROW A READABLE DOCUMENT AWAY.


class _Ink:
    """A stand-in for ``pdf.ink``, answering whatever the test needs."""

    def __init__(self, *, photograph: bool = False, nearly_blank: bool = False) -> None:
        self._photograph = photograph
        self._nearly_blank = nearly_blank
        self.asked: list[str] = []

    def is_photograph(self, pdf_bytes: bytes) -> bool:
        self.asked.append("is_photograph")
        return self._photograph

    def is_nearly_blank(self, pdf_bytes: bytes) -> bool:
        self.asked.append("is_nearly_blank")
        return self._nearly_blank


def test_a_page_with_no_text_and_continuous_tone_vetoes():
    veto = assess_vetoes(b"", "", ink=_Ink(photograph=True))
    assert veto is not None
    assert veto.name == "photograph"


def test_a_page_with_no_text_and_almost_no_ink_vetoes():
    veto = assess_vetoes(b"", "", ink=_Ink(nearly_blank=True))
    assert veto is not None
    assert veto.name == "no_ink"


def test_the_photograph_veto_is_asked_first():
    """Order is by rising cost, and it is also what the reasons say."""
    ink = _Ink(photograph=True, nearly_blank=True)
    assert assess_vetoes(b"", "", ink=ink).name == "photograph"
    assert ink.asked == ["is_photograph"]


def test_pixels_alone_never_veto_a_page_that_HAS_text():
    """The correctness condition, and the reason for ``and no_text``.

    An old photocopy on dark paper is continuous tone AND nearly blank by these
    statistics, and carries thousands of legitimate characters — measured at
    0.99 / 0.99 / 0.83 mid-tone with 1,001, 2,612 and 632 characters. Firing on
    the pixels alone discards it. Nothing must even be ASKED of the pixels when
    the text is already there.
    """
    ink = _Ink(photograph=True, nearly_blank=True)
    assert assess_vetoes(b"", PROSE, local_reading=None, ink=ink) is None
    assert ink.asked == []


def test_pixel_signals_off_skips_the_two_even_when_they_would_fire():
    ink = _Ink(photograph=True, nearly_blank=True)
    assert assess_vetoes(b"", "", pixel_signals=False, ink=ink) is None
    assert ink.asked == []


def test_the_default_signals_are_the_shipped_module():
    """Injecting must not become the only path: the default still has to work."""
    from autosxtract.interfaces import InkSignals
    from autosxtract.pdf import ink
    from autosxtract.quality.vetoes import _default_ink

    assert _default_ink() is ink
    assert isinstance(ink, InkSignals)
