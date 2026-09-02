"""The native step's decision — CLAUDE.md §2, the one acceptance criterion.

This step used to end the cascade on its own criterion, ``score_structure``
against ``native_accept_score``, and never consult ``quality.gate.evaluate`` at
all. The two disagreed on exactly the input the gate was written for: a page
whose text layer is only the conformity stamp is well-formed *as structure* and
scores around 0.90, while the gate escalates it for holding ten useful words.
Of 1,339 documents in the archive this was measured on, 403 had text that looked
fine and was only the signature stamp.

The step still has refusals of its own, and they are legitimate: a structural
score below the floor, and a large image in a region the text layer does not
cover. What it no longer has is a competing notion of *adequate*.

The file exists because the change had none. It is the riskiest edit in the
review pass — it moves documents from "the cascade stops here" to "pay for the
next step" — and a behaviour change with no test is a behaviour change nobody
can argue with later.
"""

from __future__ import annotations

import pymupdf
import pytest

from autosxtract.config import Config
from autosxtract.steps.base import Context
from autosxtract.steps.native import NativeStep

PROSE = (
    "O requerente vem respeitosamente a presenca de Vossa Excelencia nos autos "
    "do processo em epigrafe requerer a citacao do requerido, tendo em vista a "
    "decisao proferida pela vara civel e a certidao do oficial de justica que "
    "instrui o presente pedido para que sejam produzidos os efeitos legais de "
    "direito, na forma da fundamentacao que segue e dos documentos anexos."
)

# The conformity band, and nothing else. Repeated so the page is DENSE: that is
# what the real archive looks like and what makes the case interesting —
# `score_structure` sees well-formed, plentiful text and returns 0.90, far above
# `native_accept_score`, while the stamp stripper leaves zero useful words. A
# single copy scores 0.65 and never reaches the gate at all, so a test built on
# one would pass through the structural floor and prove nothing about §2.
STAMP = (
    "Este documento e copia do original assinado digitalmente por FULANO DE "
    "TAL. Para conferir o original acesse o site do tribunal e informe o "
    "codigo de verificacao 8A2F91C. fls. 42\n"
) * 5


def _pdf(pages: list[str], *, with_image: bool = False) -> bytes:
    """``with_image`` is not decoration — see the note on the gate below."""
    doc = pymupdf.open()
    image = None
    if with_image:
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 400, 300))
        pix.set_rect(pix.irect, (210,))
        for y in range(20, 280, 24):
            pix.set_rect(pymupdf.IRect(20, y, 380, y + 6), (40,))
        image = pix.tobytes("png")
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 380), text, fontsize=11)
        if image is not None:
            page.insert_image(pymupdf.Rect(60, 400, 540, 740), stream=image)
    data = doc.tobytes()
    doc.close()
    return data


# ── the one thing to know before reading the rest ────────────────────────
#
# ``evaluate`` short-circuits on ``profile.has_visual_content`` — image OR
# vector — and a born-digital, text-only filing has neither. So on that
# population the gate returns "do not escalate" without looking at the text at
# all, and unifying the criterion changes NOTHING there.
#
# That is the correct answer rather than a hole: with no image and no vector on
# the sheet, an OCR pass has nothing to find that the text layer did not already
# give, so escalating would be pure cost. The gate bites where there IS
# something the text layer might have missed — which is the stamp-only page with
# a scanned body, the case §2 is about. The tests below say which population
# they are in, because a test that gets this wrong passes for the wrong reason.


def _run(pdf_bytes: bytes, **config):
    ctx = Context(pdf_bytes=pdf_bytes, config=Config(**config))
    return NativeStep().run(ctx)


# ── what still ends here ─────────────────────────────────────────────────


def test_a_good_filing_still_ends_the_cascade():
    """31% of a real archive ends here at ~13 ms; that is the cascade's reason
    for existing, and this change must not have moved it."""
    result = _run(_pdf([PROSE, PROSE]))
    assert result.accepted
    assert result.attempt.reason == "adequate extraction"


def test_the_accepted_reason_never_describes_the_sheet():
    """A born-digital page has neither image nor vector, so ``evaluate`` returns
    ``page with no visual content`` — a true statement about the SHEET and a
    misleading one as the provenance of a good extraction."""
    result = _run(_pdf([PROSE, PROSE]))
    assert "visual content" not in result.attempt.reason


# ── what the gate now catches, and the step alone did not ────────────────


def test_a_stamp_only_page_no_longer_ends_the_cascade():
    """The dominant false success, and the reason `evaluate` exists.

    `score_structure` sees well-formed text and scores it above
    `native_accept_score`; the gate strips the stamp and finds almost nothing
    left. Before this test the step accepted it and the cascade stopped.
    """
    # WITH an image: there is something on the sheet the text layer did not
    # describe, so the gate actually judges the text. A text-only stamp page is
    # a different population — see the note above.
    pdf = _pdf([STAMP, STAMP], with_image=True)

    # The step's OWN criterion would have accepted this: it is the disagreement
    # that matters, not merely the refusal.
    from autosxtract.quality.scoring import score_structure
    from autosxtract.steps.native import read_native_text

    text, pages = read_native_text(pdf)
    assert score_structure(text, pages)["score"] >= Config().native_accept_score

    result = _run(pdf, coverage_gate=False)
    assert not result.accepted
    assert "useful words" in result.attempt.reason
    # And it is REFUSED, not discarded: it may still be the best reading there
    # is, so it stays in the contest (CLAUDE.md §5).
    assert result.candidate is not None
    assert result.candidate.text.strip()


def test_the_structural_floor_still_runs_first():
    """`native_accept_score` is not dead config — it is this step's own refusal,
    ahead of the gate and at a stricter floor."""
    result = _run(_pdf([PROSE, PROSE]), native_accept_score=0.99)
    assert not result.accepted
    assert "below 0.99" in result.attempt.reason


def test_no_text_layer_is_refused_before_anything_else():
    result = _run(_pdf([""]))
    assert not result.accepted
    assert result.attempt.reason == "no text layer"
    assert result.candidate is None


# ── the gate is ONE object, and it is replaceable from outside ───────────


def test_the_gate_is_injectable_and_is_the_thing_that_decides():
    """§2 says step and cascade must ask the same question with the same code.
    A caller measuring an alternative criterion replaces it in one place."""
    seen: list[str] = []

    def always_escalate(text, profile, **kwargs):
        from autosxtract.quality.gate import Verdict

        seen.append(text)
        return Verdict(True, "the injected gate said so")

    ctx = Context(pdf_bytes=_pdf([PROSE, PROSE]), config=Config())
    result = NativeStep(gate=always_escalate).run(ctx)

    assert seen, "the injected gate has to be the one consulted"
    assert not result.accepted
    assert result.attempt.reason == "the injected gate said so"


@pytest.mark.parametrize("floor", [12, 400])
def test_the_word_floor_reaches_the_step(floor):
    """The configured floor is the gate's, and it now applies here too."""
    result = _run(
        _pdf([PROSE, PROSE], with_image=True), min_useful_words=floor, coverage_gate=False
    )
    assert result.accepted is (floor == 12)


def test_a_text_only_page_is_accepted_without_the_text_being_judged():
    """The short-circuit, pinned so nobody reads the tests above as universal.

    No image and no vector means an OCR pass has nothing to add, so the gate
    declines to escalate whatever the text says — even a word count that would
    escalate the same text on a page carrying an attachment.
    """
    result = _run(_pdf([PROSE, PROSE]), min_useful_words=400)
    assert result.accepted
