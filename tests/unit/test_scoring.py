"""The score: text that is not text must score low."""

from __future__ import annotations

from autosxtract.quality.scoring import score_text

PROSE = (
    "O requerente vem a presenca de Vossa Excelencia nos autos do processo "
    "para requerer a citacao do requerido, tendo em vista a decisao proferida "
    "pela vara civel e a certidao que instrui o pedido."
)


def test_empty_text_scores_zero():
    """Without the explicit case the penalties add to -0.85 and 0.15 would remain."""
    assert score_text("")["score"] == 0.0
    assert score_text("   \n ")["score"] == 0.0


def test_a_glyph_index_scores_low():
    """1,171 characters like this scored 0.85 before this penalty."""
    junk = "g40g86g87g72g3g71g82 " * 60
    assert score_text(junk)["score"] < 0.35


def test_legal_prose_scores_high():
    assert score_text(PROSE)["score"] >= 0.75


def test_broken_encoding_scores_low():
    assert score_text("\x01\x02\x03" * 200 + PROSE)["score"] < 0.75


def test_a_table_without_prose_is_not_punished():
    """A form or record card legitimately has no function words.

    Below 15 alphabetic words plausibility is not judged — punishing here would
    fail a correct extraction of a table.
    """
    table = "NOME CPF VALOR\nFULANO 12345678901 1.234,56"
    assert "function word" not in " ".join(score_text(table)["reasons"])


def test_the_reasons_track_the_score():
    r = score_text("g40g86g87g72 " * 50)
    assert r["reasons"]
    assert r["label"] == "poor"
