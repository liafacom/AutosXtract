"""The acceptance gate — the single criterion of the whole cascade."""

from __future__ import annotations

from autosxtract.pdf.profile import PageProfile
from autosxtract.quality.gate import evaluate

WITH_INK = PageProfile(pages=1, has_image=True)
BLANK = PageProfile(pages=1)

PROSE = (
    "O requerente vem respeitosamente a presenca de Vossa Excelencia expor e "
    "requerer a citacao do requerido nos autos do processo em epigrafe, tendo "
    "em vista a decisao proferida e a certidao do oficial de justica que "
    "instrui o pedido, para que sejam produzidos os efeitos legais."
)


def test_a_page_with_no_visual_content_never_escalates():
    """A blank back page has nothing to read — sending it on is pure cost."""
    assert evaluate("", BLANK).sufficient


def test_too_few_useful_words_escalate():
    v = evaluate("fls. 42", WITH_INK)
    assert v.escalate
    assert "useful words" in v.reason


def test_good_text_ends_the_cascade():
    assert evaluate(PROSE, WITH_INK).sufficient


def test_a_glyph_index_escalates_despite_volume():
    """1,171 characters of glyph index scored 0.85 before this veto."""
    v = evaluate(PROSE, WITH_INK, glyph_index=0.4)
    assert v.escalate
    assert "glyph" in v.reason


def test_low_density_escalates():
    """Legitimate text, but thin for the size of the sheet."""
    v = evaluate(PROSE, PageProfile(pages=12, has_image=True))
    assert v.escalate
    assert "chars/page" in v.reason


def test_a_score_below_the_minimum_escalates():
    v = evaluate(PROSE, WITH_INK, score=0.1, min_score=0.35)
    assert v.escalate
    assert "quality" in v.reason


def test_the_reason_is_always_filled_in():
    """Provenance depends on it: no decision without a readable reason."""
    for text, profile in [("", BLANK), ("fls. 1", WITH_INK), (PROSE, WITH_INK)]:
        assert evaluate(text, profile).reason
