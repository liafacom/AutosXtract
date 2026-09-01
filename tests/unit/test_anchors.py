"""Numeric anchors: a later step may reorder, but it must not corrupt."""

from __future__ import annotations

from autosxtract.quality.anchors import anchors, lost


def test_vin_is_an_anchor():
    """Without the alphanumeric pattern the digit regex only saw the suffix."""
    assert "9XXYZ32E41A099887" in anchors("veiculo chassi 9XXYZ32E41A099887 placa")


def test_digit_corruption_in_the_vin_is_detected():
    assert lost("chassi 9XXYZ32E41A099887", "chassi 9XXYZ3ZE41A099887")


def test_different_punctuation_is_not_a_loss():
    """``001.06.012345-6`` and ``001-06-012345/6`` are the same anchor."""
    assert not lost("autos 001.06.012345-6", "autos 001-06-012345/6")


def test_space_separator_breaks_the_long_anchor():
    """A known limitation, pinned in a test so it is not "fixed" without measuring.

    Accepting a space as a separator would turn two neighbouring numbers in a
    table into an identifier that does not exist — a false positive worse than
    the false negative it avoids.
    """
    assert lost("autos 001.06.012345-6", "autos 001 06 012345 6")


def test_a_more_complete_anchor_is_not_a_loss():
    """A gain of information must not count as a loss."""
    assert not lost("processo 0001234", "processo 0001234-56.2020.8.12.0001")


def test_concatenation_does_not_absolve_a_lost_digit():
    """Containment is tested anchor by anchor, never against the concatenation.

    With ``12345`` and ``67890`` present, the concatenation contains ``234567``
    and the version comparing against the concatenation let the corruption
    through — precisely on a page full of numbers, which is the use case.
    """
    assert lost("guia 234567", "valores 12345 e 67890")


def test_an_ordinary_word_does_not_become_an_anchor():
    """``PROCESSO`` and ``PROTOCOLO`` became anchors with the negated class."""
    assert anchors("PROCESSO PROTOCOLO DESPACHO") == set()
