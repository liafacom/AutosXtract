"""The stamp has to go before measuring — it is the dominant false success."""

from __future__ import annotations

from autosxtract.quality.stamp import Stamp, strip_stamp, useful_words

STAMP = (
    "Este documento e copia do original assinado digitalmente por FULANO. "
    "Para conferir o original acesse o site e informe o codigo de verificacao "
    "8A2F91C. fls. 42"
)


def test_stamp_alone_does_not_count_as_content():
    # 150+ characters that would sail past any size threshold.
    assert len(STAMP) > 150
    assert useful_words(STAMP) < 12


def test_body_survives_the_stripping():
    text = STAMP + "\nO requerente pede a citacao do requerido nos autos."
    stripped = strip_stamp(text)
    assert "requerente" in stripped
    assert "codigo de verificacao" not in stripped


def test_patterns_are_replaceable():
    """The adaptation point for another domain: swap the list, nothing else."""
    other = Stamp(patterns=(r"CONFIDENTIAL - INTERNAL USE",))
    text = "CONFIDENTIAL - INTERNAL USE\nquarterly sales report"
    assert "CONFIDENTIAL" not in other.strip(text)
    # And the court stamp, absent from the new list, remains.
    assert "verificacao" in other.strip(STAMP).lower()


def test_tokenisation_is_the_same_for_counting_and_comparing():
    """Counting useful words and comparing vocabulary must agree.

    If they diverge, the consensus and acceptance gates start disagreeing
    silently about what a word is.
    """
    stamp = Stamp()
    text = "O requerente pede a citacao do requerido nos autos."
    assert stamp.count(text) == len(stamp.words(text))
    assert stamp.vocabulary(text) == set(stamp.words(text))
