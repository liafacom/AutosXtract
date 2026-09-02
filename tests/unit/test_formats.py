"""Stage 0: is the file really a PDF?

Without this step, 128 documents from a real archive are unreadable in their
entirety — and it is not a case OCR solves: there is no image to recognise.
"""

from __future__ import annotations

from autosxtract.formats import (
    FileFormat,
    _rebalance_braces,
    detect_format,
    text_from_rtf,
    unwrap,
)

RTF = rb"{\rtf1\ansi\deff0{\fonttbl{\f0 Times;}}\f0\fs24 Mandado de citacao expedido.\par}"


def test_detects_a_pdf():
    assert detect_format(b"%PDF-1.7\n...") is FileFormat.PDF


def test_detects_rtf_behind_a_lying_extension():
    """The extension is not the source of truth: in those files it is wrong."""
    assert detect_format(RTF) is FileFormat.RTF


def test_detects_a_bry_envelope():
    assert detect_format(b"BRyPDDE01PK\x03\x04rest") is FileFormat.BRY


def test_detects_der_pkcs7():
    assert detect_format(b"\x30\x82\x0a\x00rest") is FileFormat.PKCS7


def test_the_short_der_form_is_not_pkcs7():
    """Accepting it would classify any 0x30-prefixed junk as PKCS#7."""
    assert detect_format(b"\x30\x10anything") is FileFormat.UNKNOWN


def test_unknown_never_becomes_a_pdf_silently():
    """That silence is what lost the 128 files."""
    assert detect_format(b"anything at all") is FileFormat.UNKNOWN


def test_text_from_rtf():
    assert "Mandado de citacao" in text_from_rtf(RTF)


def test_a_surplus_brace_does_not_truncate_the_body():
    """One source system emits an extra ``}`` in the header table.

    striprtf follows Word and STOPS READING when the root group closes — with
    the surplus brace that happens before the body, and a whole ruling came out
    as two line breaks (0 useful characters in 38 archive files).
    """
    broken = rb"{\rtf1\ansi{\fonttbl{\f0 Times;}}}\f0 Corpo do despacho aqui.\par}"
    assert "Corpo do despacho" in text_from_rtf(broken)


def test_trailing_padding_is_not_promoted_to_document_body():
    """Bytes after the root close are not content, and must not become it.

    The repair used to take "the last ``}`` in the file" as the root group's
    close. A file with padding after the close — which is what carving an RTF
    out of a PKCS#7 envelope leaves behind — inverts that: the genuine close is
    classified as the surplus one and dropped, the padding's brace becomes the
    root close, and everything between them is promoted to body.

    Worse than merely wrong. The polluted text is LONGER, so it also wins
    ``best_text`` and the final contest — volume on the wrong side, which is the
    failure CLAUDE.md §4 exists to name.
    """
    body = rb"{\rtf1\ansi\deff0 {\fonttbl{\f0 Arial;}}\f0 SENTENCA procedente.}"
    padding = b"\r\n" + b"PADDING-NAO-E-CONTEUDO " * 5 + b"}"

    assert text_from_rtf(body) == text_from_rtf(body + padding)
    assert "PADDING" not in text_from_rtf(body + padding)


def test_a_surplus_brace_survives_trailing_padding_too():
    """Both defects in one file — the shape the archive actually produces."""
    broken = rb"{\rtf1\ansi{\fonttbl{\f0 Times;}}}\f0 Corpo do despacho.\par}"
    text = text_from_rtf(broken + b"\r\nPADDING PADDING }")
    assert "Corpo do despacho" in text
    assert "PADDING" not in text


def test_well_formed_rtf_passes_untouched():
    markup = r"{\rtf1\ansi texto\par}"
    assert _rebalance_braces(markup) == markup


def test_a_plain_pdf_lets_the_cascade_continue():
    r = unwrap(b"%PDF-1.7\ncontent")
    assert r.is_plain_pdf
    assert r.bytes_for_cascade is not None
    assert not r.text


def test_rtf_returns_text_and_ends():
    r = unwrap(RTF)
    assert r.format is FileFormat.RTF
    assert "Mandado" in r.text
    assert r.bytes_for_cascade is None


def test_a_failure_becomes_a_reason_never_an_exception():
    """Ingesting a batch must not fall over because of one document."""
    r = unwrap(b"BRyPDDE01 with no zip in here at all")
    assert not r.readable
    assert r.reason
