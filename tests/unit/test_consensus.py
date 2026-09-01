"""Consensus and agreement — the two questions only several engines answer."""

from __future__ import annotations

from autosxtract.quality.consensus import assess_agreement, assess_emptiness

PROSE_A = (
    "certidao de intimacao do executado no processo em epigrafe expedida pela "
    "secretaria da vara civel na data indicada com ciencia do oficial"
)
# The same content, with a second engine's typical errors: one word swapped and
# another missing. The vocabulary stays mostly identical.
PROSE_B = (
    "certidao de intimacao do executado no processo em epigrafe expedida pela "
    "secretaria da vara civel na data indicada com ciencia do oficlal"
)


def test_one_engine_is_not_a_consensus():
    """An isolated refusal is "I could not", not "there is none"."""
    assert not assess_emptiness({"a": 0}, word_floor=12).empty


def test_all_below_the_floor_means_empty():
    v = assess_emptiness({"a": 0, "b": 2, "c": 1}, word_floor=12)
    assert v.empty
    assert "3 independent engines" in v.evidence


def test_one_dissenter_breaks_the_consensus():
    """The asymmetry is deliberate: one contrary opinion is enough to escalate."""
    assert not assess_emptiness({"a": 0, "b": 59}, word_floor=12).empty


def test_the_evidence_is_auditable():
    v = assess_emptiness({"tesseract": 0, "paddle": 1}, word_floor=12)
    assert "tesseract read 0 useful words" in v.evidence
    assert "paddle read 1 useful word" in v.evidence


def test_agreement_confirms_a_complete_reading():
    a = assess_agreement({"a": PROSE_A, "b": PROSE_B}, word_floor=12, min_similarity=0.60)
    assert a.agree
    assert a.similarity >= 0.60


def test_different_readings_do_not_agree():
    a = assess_agreement(
        {"a": PROSE_A, "b": "ministerio da fazenda fim de relatorio pagina"},
        word_floor=3,
        min_similarity=0.60,
    )
    assert not a.agree


def test_two_nearly_empty_readings_do_not_agree_trivially():
    """Below the floor the right question is emptiness, not agreement."""
    a = assess_agreement({"a": "fls. 1", "b": "fls. 1"}, word_floor=12, min_similarity=0.60)
    assert not a.agree
