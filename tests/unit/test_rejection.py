"""The replacement gate: length gets both of the costliest cases wrong."""

from __future__ import annotations

from autosxtract.quality.rejection import assess_replacement

PREVIOUS = (
    "Procuracao lavrada no cartorio, protocolo 882167, referente ao processo "
    "0001234-56.2020.8.12.0001, com poderes para o foro em geral e ciencia "
    "das partes interessadas nos autos da execucao em tramite."
)
GOOD_NEW = PREVIOUS + " Segue a transcricao integral dos demais atos notariais praticados."


def test_better_text_is_accepted():
    assert assess_replacement(GOOD_NEW, PREVIOUS, document_pages=1).accepted


def test_digit_corruption_is_rejected():
    """``9XXYZ3ZE`` scores exactly like ``9XXYZ32E`` — only the anchor detects it."""
    corrupted = GOOD_NEW.replace("882167", "882187")
    r = assess_replacement(corrupted, PREVIOUS, document_pages=1)
    assert not r.accepted
    assert "anchors" in r.reason


def test_a_marker_loop_is_rejected():
    """6,281 characters of which 41 were content, in 319 s."""
    loop = "[ILLEGIBLE] " * 300 + "four real words here"
    r = assess_replacement(loop, PREVIOUS, document_pages=1)
    assert not r.accepted
    assert "marker" in r.reason


def test_a_partial_transcription_is_rejected():
    """Longer than a bad extraction, and still incomplete."""
    r = assess_replacement(GOOD_NEW, PREVIOUS, document_pages=15, pages_sent=10, pages_answered=10)
    assert not r.accepted
    assert "partial" in r.reason


def test_a_much_denser_partial_is_accepted_with_a_warning():
    """52 chars/page against 3,422: in that regime the partial one is better."""
    rich = ("Transcricao integral do ato notarial. " * 300) + " protocolo 882167"
    r = assess_replacement(rich, PREVIOUS, document_pages=15, pages_sent=10, pages_answered=10)
    assert r.accepted
    assert any("truncation accepted" in w for w in r.warnings)


def test_a_degenerate_previous_waives_the_gates():
    """With no trustworthy reference there is nothing to check against."""
    assert assess_replacement("any new text", "fls. 3", document_pages=1).accepted


def test_it_does_not_beat_the_previous_text():
    assert not assess_replacement(PREVIOUS, GOOD_NEW, document_pages=1).accepted


def test_an_untrustworthy_reference_waives_the_anchor_gate():
    """That path's premise is that the previous text is known to be bad."""
    corrupted = GOOD_NEW.replace("882167", "882187")
    r = assess_replacement(corrupted, PREVIOUS, document_pages=1, trustworthy_reference=False)
    assert r.accepted


def test_a_failed_batch_is_rejected():
    r = assess_replacement(
        GOOD_NEW,
        PREVIOUS,
        document_pages=4,
        pages_sent=4,
        pages_answered=2,
        failed_batches=1,
    )
    assert not r.accepted
    assert "batch" in r.reason
