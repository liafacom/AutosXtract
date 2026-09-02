"""The orientation fix, and the two ways it used to vanish — CLAUDE.md §3.

A page that arrives sideways is read badly by every engine, and everything
downstream — the acceptance gate, the score, the vetoes — then judges a bad
reading caused by an input defect none of them can see.

The correction existed and was invisible in both directions, which is why this
file exists rather than a note in the review:

* ``fix_orientation=True`` on a machine without Tesseract corrected nothing and
  said so **nowhere**. ``detect`` returned 0 on ``ImportError``, so a run with
  the OSD working and a run without it left byte-for-byte identical evidence —
  the failure mode §3 forbids, and the same shape as the witness that silently
  never fired.
* When it *did* rotate, the degrees were discarded at the call site
  (``images = [fix(i)[0] for i in images]``), so a corrected page and an
  untouched one were also indistinguishable.

A correction nobody can see in the record is not auditable, and an unauditable
correction is one nobody can argue with when the text comes out wrong.
"""

from __future__ import annotations

import pytest

from autosxtract.config import Config
from autosxtract.pdf import orientation
from autosxtract.steps.base import Context

PAGE = b"fake-image-bytes"


def _ctx(images: list[bytes], **config) -> Context:
    """A context whose renderer is a stub: this file is about what happens
    AFTER rasterising, and a real PDF would only make the test slower."""
    return Context(
        pdf_bytes=b"%PDF-1.7",
        config=Config(**config),
        renderer=lambda *a, **k: list(images),
    )


# ── the absence is announced ─────────────────────────────────────────────


def test_available_explains_itself_instead_of_raising():
    ok, reason = orientation.available()
    assert isinstance(ok, bool)
    assert reason, "an unavailable OSD with no reason is the defect this replaces"


def test_a_missing_osd_reaches_the_record_instead_of_doing_nothing(monkeypatch):
    monkeypatch.setattr(orientation, "available", lambda: (False, "no tesseract here"))
    ctx = _ctx([PAGE], fix_orientation=True)

    assert ctx.images() == [PAGE]
    assert ctx.orientation == {"unavailable": "no tesseract here"}


def test_the_availability_check_runs_once_per_document_not_once_per_page(monkeypatch):
    """It starts a process to read Tesseract's version. Paying that per page of
    a 64-page scan would cost more than the OSD it guards."""
    calls = []
    monkeypatch.setattr(orientation, "available", lambda: (calls.append(1), (False, "absent"))[1])
    ctx = _ctx([PAGE, PAGE, PAGE], fix_orientation=True)

    ctx.images()
    ctx.images(indices=[0])

    assert len(calls) == 1


def test_nothing_is_recorded_when_the_correction_was_never_asked_for(monkeypatch):
    monkeypatch.setattr(orientation, "available", lambda: (False, "absent"))
    ctx = _ctx([PAGE], fix_orientation=False)

    assert ctx.images() == [PAGE]
    assert ctx.orientation == {}


# ── the correction is announced too ──────────────────────────────────────


def test_the_degrees_applied_are_recorded_per_page(monkeypatch):
    monkeypatch.setattr(orientation, "available", lambda: (True, "stub"))
    monkeypatch.setattr(
        orientation, "fix", lambda image: (b"upright", 90 if image == b"sideways" else 0)
    )
    ctx = _ctx([b"upright-already", b"sideways"], fix_orientation=True)

    ctx.images()

    assert ctx.orientation == {"rotated": {1: 90}}


def test_the_recorded_page_is_the_document_s_page_not_the_batch_s(monkeypatch):
    """Under per-page routing the engine is handed pages 3 and 7, not 0 and 1.
    Recording the position in the batch would point the reader at the wrong
    sheet — the same class of defect as the routed ``pages_sent`` count."""
    monkeypatch.setattr(orientation, "available", lambda: (True, "stub"))
    monkeypatch.setattr(orientation, "fix", lambda image: (image, 180))
    ctx = _ctx([PAGE, PAGE], fix_orientation=True)

    ctx.images(indices=[3, 7])

    assert ctx.orientation == {"rotated": {3: 180, 7: 180}}


def test_an_upright_document_records_nothing(monkeypatch):
    monkeypatch.setattr(orientation, "available", lambda: (True, "stub"))
    monkeypatch.setattr(orientation, "fix", lambda image: (image, 0))
    ctx = _ctx([PAGE], fix_orientation=True)

    assert ctx.images() == [PAGE]
    assert ctx.orientation == {}


def test_unwrapping_forgets_the_envelope_s_page_numbers(monkeypatch):
    """``rotated`` indexed the envelope's pages. The payload that comes out of a
    BRy envelope is a different document, and keeping the numbers would point
    at sheets that no longer exist."""
    monkeypatch.setattr(orientation, "available", lambda: (True, "stub"))
    monkeypatch.setattr(orientation, "fix", lambda image: (image, 270))
    ctx = _ctx([PAGE], fix_orientation=True)
    ctx.images()
    assert ctx.orientation["rotated"]

    ctx.replace_bytes(b"%PDF-1.7 payload")

    assert "rotated" not in ctx.orientation


# ── never break the extraction over an optional dependency ───────────────


def test_fix_returns_the_page_untouched_when_it_cannot_rotate(monkeypatch):
    monkeypatch.setattr(orientation, "detect", lambda image: 0)

    assert orientation.fix(PAGE) == (PAGE, 0)


def test_detect_answers_zero_rather_than_guessing(monkeypatch):
    """OSD fails on a page with no text, and 'I do not know' has to be 0 — a
    random angle applied with confidence is worse than no correction."""

    class _Broken:
        Output = type("O", (), {"DICT": "dict"})

        @staticmethod
        def image_to_osd(*a, **k):
            raise RuntimeError("too few characters")

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", _Broken)
    assert orientation.detect(PAGE) == 0


@pytest.mark.parametrize("confidence,expected", [(0.0, 0), (5.0, 90)])
def test_a_low_confidence_reading_is_not_applied(monkeypatch, confidence, expected):
    class _Stub:
        Output = type("O", (), {"DICT": "dict"})

        @staticmethod
        def image_to_osd(*a, **k):
            return {"rotate": 90, "orientation_conf": confidence}

    class _Image:
        @staticmethod
        def open(*a, **k):
            import contextlib

            return contextlib.nullcontext(object())

    sys = __import__("sys")
    monkeypatch.setitem(sys.modules, "pytesseract", _Stub)
    monkeypatch.setitem(sys.modules, "PIL", type("M", (), {"Image": _Image}))
    monkeypatch.setitem(sys.modules, "PIL.Image", _Image)

    assert orientation.detect(PAGE) == expected
