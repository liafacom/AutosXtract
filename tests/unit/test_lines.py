"""Containment layers: contain the damage, flag it, recover what is recoverable.

The premise comes from an audit: the cheap engine reads the BODY almost
perfectly, and the error concentrates in vertical stamps, signatures over text
and run-together words. You do not read *through* a stamp — you contain it.
"""

from __future__ import annotations

from autosxtract.quality.lexicon import Lexicon
from autosxtract.quality.lines import (
    ILLEGIBLE_MARKER,
    SIGNATURE_MARKER,
    contain,
    reassemble,
    resegment,
)
from autosxtract.types import Line, Page

WIDTH, HEIGHT = 1200.0, 1700.0


def _poly(x1, y1, x2, y2):
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def _page(*lines: Line) -> Page:
    return Page(list(lines), WIDTH, HEIGHT)


PROSE = "O requerente vem requerer a citacao do requerido nos autos do processo"


# ── Layer 1: classification ──────────────────────────────────────────────


def test_a_clean_body_passes_untouched():
    r = contain(_page(Line(PROSE, 0.98, _poly(60, 100, 900, 130))))
    assert r.text == PROSE
    assert r.trusted_fraction == 1.0
    assert r.suggested_action == "ok"


def test_a_fragment_is_dropped_silently():
    r = contain(
        _page(
            Line(PROSE, 0.98, _poly(60, 100, 900, 130)),
            Line("·", 0.4, _poly(60, 140, 66, 146)),
        )
    )
    assert "·" not in r.text
    assert r.n_fragment == 1


def test_a_vertical_margin_stamp_becomes_a_marker():
    """A tall narrow box in the margin: a protocol read sideways."""
    r = contain(
        _page(
            Line(PROSE, 0.98, _poly(60, 100, 900, 130)),
            Line("OU0510200513130020", 0.6, _poly(20, 200, 60, 900)),
        )
    )
    assert ILLEGIBLE_MARKER in r.text
    assert r.n_vertical == 1
    assert r.targets  # Layer 2 has something to re-read


def test_a_vertical_box_mid_page_is_not_a_stamp():
    """The margin is part of the criterion: a narrow column in the body is text."""
    r = contain(_page(Line("texto em coluna", 0.9, _poly(560, 200, 610, 900))))
    assert r.n_vertical == 0


def test_obvious_junk_becomes_a_marker():
    r = contain(_page(Line("xkqw zpmm bqrt zzxp lmnq wrtz", 0.40, _poly(60, 100, 900, 130))))
    assert ILLEGIBLE_MARKER in r.text
    assert r.n_illegible == 1


def test_a_case_number_is_never_junk():
    """A reference line is what LEAST can disappear, however odd it looks."""
    r = contain(_page(Line("0001234-56.2020.8.12.0001", 0.5, _poly(60, 100, 400, 130))))
    assert "0001234-56.2020.8.12.0001" in r.text
    assert r.n_illegible == 0


def test_an_address_with_a_structural_anchor_survives():
    """A misread prefix does not condemn a line that has an anchor."""
    r = contain(_page(Line("Rua Xyzw qrt, 123 - CEP 79.002-000", 0.6, _poly(60, 100, 700, 130))))
    assert "CEP" in r.text


def test_the_doubtful_becomes_suspect_and_keeps_its_text():
    """The safe side of the error: the text passes, the page loses confidence."""
    r = contain(_page(Line("Chrismane Alencr qrtz nomes", 0.70, _poly(60, 100, 700, 130))))
    assert "Chrismane" in r.text
    assert r.n_suspect == 1
    assert r.trusted_fraction < 1.0


def test_the_marker_does_not_repeat():
    """Two junk lines in a row become one marker, not two."""
    junk = "xkqw zpmm bqrt zzxp lmnq wrtz"
    r = contain(
        _page(
            Line(junk, 0.4, _poly(60, 100, 900, 130)),
            Line(junk, 0.4, _poly(60, 140, 900, 170)),
        )
    )
    assert r.text.count(ILLEGIBLE_MARKER) == 1


# ── Layer 1b: run-together words ─────────────────────────────────────────


def test_resegmentation_backtracks():
    """The greedy version matches ``dos``, sticks on ``ul`` and discards everything."""
    lexicon = Lexicon.from_words(["estado", "mato", "grosso", "sul"])
    assert resegment("ESTADODEMATOGROSSODOSUL", lexicon) == "ESTADO DE MATO GROSSO DO SUL"


def test_resegmentation_is_all_or_nothing():
    """A partial split produces junk worse than the joined word."""
    assert resegment("XKQWZPMMBQRTZZXPLM", Lexicon.builtin()) is None


def test_a_short_run_is_left_alone():
    assert resegment("ESTADODEMATO", Lexicon.from_words(["estado", "mato"])) is None


# ── Layer 1.5: signatures ────────────────────────────────────────────────


def test_the_structural_rule_marks_a_signature():
    """A scribble right above a name in caps, with a job title nearby."""
    r = contain(
        _page(
            Line("Renen", 0.80, _poly(200, 400, 320, 440)),
            Line("CHRISTIANE DE ALENCAR", 0.98, _poly(200, 450, 600, 480)),
            Line("Escrivã Judicial", 0.97, _poly(200, 490, 500, 520)),
        )
    )
    assert SIGNATURE_MARKER in r.text
    assert "CHRISTIANE DE ALENCAR" in r.text  # the name stays


def test_a_box_over_a_seal_is_not_a_signature():
    """The detector fires on authenticity seals — the text is what decides."""
    box = (100, 100, 500, 200)
    r = contain(
        _page(Line("Selo de Autenticidade ICP-Brasil", 0.85, _poly(110, 110, 480, 150))),
        signature_boxes=[box],
    )
    assert SIGNATURE_MARKER not in r.text


def test_a_box_with_no_illegible_line_is_not_a_signature():
    """With no scribble read, the box is a crest, a QR code or a logo."""
    box = (60, 90, 900, 140)
    r = contain(_page(Line(PROSE, 0.99, _poly(60, 100, 900, 130))), signature_boxes=[box])
    assert SIGNATURE_MARKER not in r.text
    assert PROSE in r.text


# ── Layer 3: the report ──────────────────────────────────────────────────


def test_the_report_asks_to_escalate_when_damage_is_scattered():
    junk = "xkqw zpmm bqrt zzxp lmnq wrtz"
    lines = [Line(f"{junk} {i}", 0.4, _poly(60, 100 + 40 * i, 900, 130 + 40 * i)) for i in range(4)]
    r = contain(_page(*lines))
    assert r.needs_escalation
    assert r.report()["suggested_action"] == "escalate"


def test_localised_damage_is_accepted_with_holes():
    lines = [Line(PROSE, 0.98, _poly(60, 100 + 40 * i, 900, 130 + 40 * i)) for i in range(8)]
    lines.append(Line("xkqw zpmm bqrt zzxp lmnq", 0.4, _poly(60, 500, 900, 530)))
    r = contain(_page(*lines))
    assert not r.needs_escalation
    assert r.suggested_action == "accept_with_holes"


def test_reassembly_puts_the_recovered_line_in_place():
    r = contain(
        _page(
            Line(PROSE, 0.98, _poly(60, 100, 900, 130)),
            Line("OU0510200513130020", 0.6, _poly(20, 200, 60, 900)),
        )
    )
    target = r.targets[0]
    new = reassemble(r, {target: "PROTOCOLO 123456"})
    assert "PROTOCOLO 123456" in new.text
    assert ILLEGIBLE_MARKER not in new.text
    assert PROSE in new.text


def test_a_page_with_no_lines_does_not_break():
    r = contain(Page([], 0, 0))
    assert r.text == ""
    assert r.report()["lines_total"] == 0
