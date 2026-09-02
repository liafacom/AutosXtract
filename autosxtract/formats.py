"""Files delivered in something other than PDF — stage 0 of the cascade.

Why this exists: in a real archive, **128 documents arrive with a `.pdf`
extension and contents that are not PDF** — plain RTF (16), a proprietary BRy
envelope (74) and PKCS#7/DER with the signed document inside (38). PyMuPDF
raises ``FileDataError('Failed to open stream')`` and no OCR helps: there is no
image to recognise, there is plain text nobody was reading. These are documents
from 49 cases, nearly all of them old.

Two decisions this module carries:

* **The extension is not the source of truth.** In those files it is
  demonstrably wrong, so classification goes by byte signature.
* **Inner content is reclassified, never assumed.** A BRy envelope holds a
  PKCS#7 that holds an RTF; a PKCS#7 could hold a PDF. Unwrapping is recursive
  and every level goes back through detection.

Pure module: it decides and unwraps in memory, with no storage and no network.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from enum import StrEnum

from autosxtract.exceptions import AutosXtractError

# Signatures measured in the archive.
_PDF_SIGNATURE = b"%PDF"
_RTF_SIGNATURE = b"{\\rtf"
_BRY_SIGNATURE = b"BRyPDDE"
_ZIP_START = b"PK\x03\x04"

# DER: SEQUENCE (0x30) followed by the length byte. Only the long forms
# (0x81/0x82/0x83) matter — a signed envelope never fits in 127 bytes, and
# accepting the short form would classify any 0x30-prefixed junk as PKCS#7.
_DER_SEQUENCE = 0x30
_DER_LONG_LENGTHS = frozenset({0x81, 0x82, 0x83})

# The prefix is enough to decide the format — the whole file is not read here.
_SIGNATURE_BYTES = 16

# Defensive caps: the envelope's ZIP comes from outside and nothing in it is
# trustworthy, starting with the declared sizes.
_MAX_ZIP_MEMBERS = 32
_MAX_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_NESTING = 4

# Timestamp members (RFC 3161). They are DER like the signed document, but they
# hold the timestamp's TSTInfo rather than the document — if they enter the
# unwrapping they return a hash instead of the file.
_TIMESTAMP_SUFFIX = ".tsr"

# RTFs from the older systems are cp1252/latin-1, not UTF-8.
_RTF_ENCODING = "cp1252"


class FileFormat(StrEnum):
    """What the file actually is, by byte signature."""

    PDF = "pdf"
    RTF = "rtf"
    BRY = "bry"
    PKCS7 = "pkcs7"
    UNKNOWN = "unknown"


class UnreadableFormat(AutosXtractError):
    """The envelope was recognised but could not be opened."""


@dataclass(frozen=True)
class Unwrapped:
    """What is left after peeling the envelope layers off.

    ``text`` filled in means the content is already text and the cascade need
    not run. ``bytes_for_cascade`` means the opposite: a binary document (PDF or
    otherwise) is left for the following steps to handle.
    """

    format: FileFormat
    text: str = ""
    bytes_for_cascade: bytes | None = None
    reason: str = ""

    @property
    def readable(self) -> bool:
        return bool(self.text.strip()) or self.bytes_for_cascade is not None

    @property
    def is_plain_pdf(self) -> bool:
        """Nothing was unwrapped — an ordinary PDF, the cascade runs as usual."""
        return self.format is FileFormat.PDF and not self.text


def detect_format(data: bytes) -> FileFormat:
    """Classify the file by its first bytes.

    An unrecognised format returns ``UNKNOWN`` explicitly — it is never treated
    as a PDF in silence, which is exactly the mistake that lost those 128 files
    entirely.
    """
    prefix = data[:_SIGNATURE_BYTES]
    if prefix.startswith(_PDF_SIGNATURE):
        return FileFormat.PDF
    if prefix.startswith(_RTF_SIGNATURE):
        return FileFormat.RTF
    if prefix.startswith(_BRY_SIGNATURE):
        return FileFormat.BRY
    if len(prefix) >= 2 and prefix[0] == _DER_SEQUENCE and prefix[1] in _DER_LONG_LENGTHS:
        return FileFormat.PKCS7
    return FileFormat.UNKNOWN


def _rebalance_braces(markup: str) -> str:
    """Drop surplus closing braces from RTF markup.

    Why this exists: one of the source systems emits an extra ``}`` in the
    middle of the header table. ``striprtf`` follows Word's behaviour and
    **stops reading** as soon as the root group closes — with the surplus brace
    that happens before the body, and a whole ruling comes out as two line
    breaks (measured: 0 useful characters in all 38 PKCS#7 files of the
    archive).

    Assumption: the file has a single root group — true across the whole
    archive. In well-formed RTF no brace is dropped and the function returns its
    input untouched.

    Finding the root group's close is the whole difficulty, and taking it to be
    the **last** ``}`` in the file was wrong. A file with trailing bytes after
    the root close — padding left over from carving the RTF out of a PKCS#7
    envelope, which is where these files come from — inverts the rule: the
    genuine close gets classified as the surplus one and dropped, the padding's
    brace becomes the root close, and everything in between is promoted to
    document body. Worse than merely wrong: the polluted text is LONGER, so it
    also wins ``best_text`` and the final contest, which is the failure CLAUDE.md
    §4 describes.

    The discriminator is what comes AFTER a candidate close, and it has to be
    RTF **control words**, not braces. What follows a surplus brace is the
    document body, which is RTF: ``\\f0 … \\par``. What follows the real root
    close is padding, which is bytes. Braces do not separate the two — the body
    of the measured case contains none at all, so a rule keyed on ``{`` throws
    the ruling away, which is the very defect this function exists to repair.

    So: the root close is the **first** unescaped ``}`` with no unescaped control
    word after it, and everything past it is discarded — Word's rule, which the
    previous version claimed to follow while appending the tail whole. If no
    candidate qualifies (a file that is control words all the way down), the last
    ``}`` stands, which is the old behaviour.
    """
    total = len(markup)

    def _control_word_after(pos: int) -> bool:
        """Is there an unescaped ``\\word`` after ``pos``? Then RTF continues."""
        j = pos + 1
        while j < total - 1:
            if markup[j] == "\\":
                if markup[j + 1].isalpha():
                    return True
                j += 2  # ``\\``, ``\{``, ``\}``, ``\'e7`` — an escape, not a word
                continue
            j += 1
        return False

    root_close = -1
    i = 0
    while i < total:
        char = markup[i]
        if char == "\\":
            # Escapes (``\\``, ``\{``, ``\}``, ``\'e7``) never close a group.
            i += 2
            continue
        if char == "}" and not _control_word_after(i):
            root_close = i
            break
        i += 1
    if root_close < 0:
        root_close = markup.rfind("}")
    if root_close < 0:
        # No close at all: nothing to repair, and truncating would lose the lot.
        return markup

    parts: list[str] = []
    start = 0
    depth = 0
    repaired = False
    i = 0
    while i <= root_close:
        char = markup[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            if depth <= 1:
                if i == root_close:
                    break  # the root group's legitimate close
                parts.append(markup[start:i])
                start = i + 1
                repaired = True
                i += 1
                continue
            depth -= 1
        i += 1
    if not repaired:
        return markup
    # Up to and including the root close, and not one byte further.
    parts.append(markup[start : root_close + 1])
    return "".join(parts)


def text_from_rtf(data: bytes) -> str:
    """Text of an RTF, without the markup.

    Uses ``striprtf`` deliberately: hand-rolled regex cleaning lets the font
    table and the metadata through, inflating the result with hundreds of font
    names.
    """
    try:
        from striprtf.striprtf import rtf_to_text
    except ImportError as exc:
        raise UnreadableFormat(f"striprtf unavailable: {exc}") from exc

    markup = _rebalance_braces(data.decode(_RTF_ENCODING, errors="replace"))
    try:
        return rtf_to_text(markup, encoding=_RTF_ENCODING, errors="ignore")
    except Exception as exc:
        raise UnreadableFormat(f"unreadable RTF: {exc}") from exc


def document_from_bry_envelope(data: bytes) -> bytes:
    """The inner document of a ``BRyPDDE##`` envelope.

    The envelope is a proprietary header followed by a ZIP whose members follow
    the pattern ``..._DOC_78253.~doc.p7s`` (the signed document) and
    ``...p7s.tsr`` (the timestamp). It picks the largest member that is not a
    timestamp: the timestamp is always small and never holds the document.

    The size cap is applied to the bytes **actually produced**, not to the ZIP
    directory's ``file_size``: that value is declared by the file itself, and an
    envelope lying about it would decompress freely before the CRC caught the
    fraud.
    """
    start = data.find(_ZIP_START, 0, _SIGNATURE_BYTES * 4)
    if start < 0:
        raise UnreadableFormat("BRy envelope with no ZIP after the header")
    try:
        with zipfile.ZipFile(io.BytesIO(data[start:])) as envelope:
            members = envelope.infolist()
            if len(members) > _MAX_ZIP_MEMBERS:
                # Silently truncating the list would make a large envelope look
                # like "no document", indistinguishable from an empty one.
                raise UnreadableFormat(
                    f"BRy envelope with {len(members)} members, above {_MAX_ZIP_MEMBERS}"
                )
            candidates = [
                info
                for info in members
                if not info.is_dir()
                and not info.filename.lower().endswith(_TIMESTAMP_SUFFIX)
                and info.file_size > 0
            ]
            if not candidates:
                raise UnreadableFormat("BRy envelope with no document member")
            largest = max(candidates, key=lambda info: info.file_size)
            with envelope.open(largest) as stream:
                # ``read(n)`` propagates the limit to the decompressor;
                # ``read(-1)`` does not — the difference between 140 MB and
                # 815 MB of measured peak memory.
                content = stream.read(_MAX_MEMBER_BYTES + 1)
    except UnreadableFormat:
        raise
    except Exception as exc:
        raise UnreadableFormat(f"corrupt BRy envelope: {exc}") from exc

    if len(content) > _MAX_MEMBER_BYTES:
        raise UnreadableFormat(f"BRy envelope member above {_MAX_MEMBER_BYTES} bytes")
    return content


def content_from_pkcs7(data: bytes) -> bytes:
    """The signed content of a PKCS#7/DER envelope.

    Deserialises the ASN.1 and reads ``encap_content_info`` from the
    ``SignedData``. Carving ``{\\rtf`` out of the byte stream does **not**
    work: it returns zero characters, because the content is not stored
    contiguous and literal.

    The signature is not validated — the goal is to read the document, not to
    attest authenticity; an expired certificate must not hide the file.
    """
    try:
        from asn1crypto import cms
    except ImportError as exc:
        raise UnreadableFormat(f"asn1crypto unavailable: {exc}") from exc

    try:
        envelope = cms.ContentInfo.load(data)
        if envelope["content_type"].native != "signed_data":
            raise UnreadableFormat(f"PKCS#7 is not signed_data: {envelope['content_type'].native}")
        content = envelope["content"]["encap_content_info"]["content"]
        inner = content.native if content else None
    except UnreadableFormat:
        raise
    except Exception as exc:
        raise UnreadableFormat(f"unreadable PKCS#7: {exc}") from exc

    if not inner:
        raise UnreadableFormat("PKCS#7 with no embedded signed content")
    return inner


def _unwrap_level(data: bytes, fmt: FileFormat, *, level: int) -> tuple[str, bytes | None]:
    """One envelope level; recurses, reclassifying the inner content."""
    if level > _MAX_NESTING:
        raise UnreadableFormat(f"nesting above {_MAX_NESTING} layers")
    if fmt is FileFormat.RTF:
        return text_from_rtf(data), None
    if fmt is FileFormat.BRY:
        inner = document_from_bry_envelope(data)
    elif fmt is FileFormat.PKCS7:
        inner = content_from_pkcs7(data)
    else:
        # PDF and unrecognised formats leave through the same channel: bytes
        # for the cascade. Discarding an already-unwrapped payload just because
        # its signature is not in the catalogue would lose the whole document
        # in the name of classification.
        return "", data
    return _unwrap_level(inner, detect_format(inner), level=level + 1)


def unwrap(data: bytes) -> Unwrapped:
    """Peel the envelope layers off until text or extractable bytes remain.

    Never raises: a failure becomes a filled-in ``reason`` and empty content,
    because ingesting a batch must not fall over because of one document. The
    broad ``except`` is deliberate — this contract is worth more than the
    elegance of enumerating a third-party library's failures.
    """
    fmt = FileFormat.UNKNOWN
    try:
        fmt = detect_format(data)
        text, bytes_for_cascade = _unwrap_level(data, fmt, level=0)
    except UnreadableFormat as exc:
        return Unwrapped(format=fmt, reason=str(exc))
    except Exception as exc:
        # Safety net for the contract above.
        return Unwrapped(format=fmt, reason=f"unexpected failure while unwrapping: {exc}")
    return Unwrapped(format=fmt, text=text, bytes_for_cascade=bytes_for_cascade)
