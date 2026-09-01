"""Page routing: what KIND of page this is, at ~1 ms and with no model."""

from __future__ import annotations

from autosxtract.quality.routing import route
from autosxtract.types import Line, Page


def _poly(x1, y1, x2, y2):
    return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))


def test_an_empty_page_is_degraded():
    assert route(Page([], 1200, 1700)).kind == "degraded"


def test_legal_prose_is_normal():
    lines = [
        Line(
            "O requerente vem respeitosamente requerer a citacao do requerido "
            f"nos autos do processo em epigrafe, conforme decisao anterior. {i}",
            0.97,
            _poly(60, 100 + 40 * i, 1000, 130 + 40 * i),
        )
        for i in range(8)
    ]
    assert route(Page(lines, 1200, 1700)).kind == "normal"


def test_columns_of_amounts_are_a_table():
    lines = []
    for i in range(14):
        lines.append(Line(f"{i + 1:02d}/2020", 0.97, _poly(100, 100 + 40 * i, 220, 130 + 40 * i)))
        lines.append(Line(f"R$ 1.2{i}3,45", 0.97, _poly(400, 100 + 40 * i, 560, 130 + 40 * i)))
        lines.append(Line("----------", 0.9, _poly(700, 100 + 40 * i, 900, 130 + 40 * i)))
    assert route(Page(lines, 1200, 1700)).kind == "table"


def test_a_seal_with_a_readable_body_is_stamped_digital():
    lines = [
        Line(
            "O requerente vem requerer a citacao do requerido nos autos do "
            f"processo, conforme a decisao proferida pela vara civel. {i}",
            0.98,
            _poly(60, 100 + 40 * i, 1000, 130 + 40 * i),
        )
        for i in range(6)
    ]
    lines.append(
        Line(
            "Documento assinado digitalmente, codigo de verificacao 8A2F91C",
            0.97,
            _poly(60, 400, 1000, 430),
        )
    )
    assert route(Page(lines, 1200, 1700)).kind == "stamped_digital"


def test_a_seal_alone_is_not_enough():
    """The seal is on EVERY page of a digital case file — what distinguishes is
    the seal with a readable body, where a better step has text to gain."""
    lines = [
        Line("assinado digitalmente", 0.6, _poly(60, 100, 400, 130)),
        Line("xkqw zpmm bqrt zzxp lmnq wrtz kkjj", 0.5, _poly(60, 140, 900, 170)),
        Line("qwrt zzxp lmnq wrtz kkjj mmbb", 0.5, _poly(60, 180, 900, 210)),
    ]
    assert route(Page(lines, 1200, 1700)).kind != "stamped_digital"


def test_the_evidence_lists_the_signals():
    r = route(Page([Line("some text here", 0.9, _poly(60, 100, 400, 130))], 1200, 1700))
    assert "coverage=" in r.evidence
    assert r.kind in r.evidence
