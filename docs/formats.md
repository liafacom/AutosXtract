# Files that are not PDFs

**In a real archive, 128 documents arrive with a `.pdf` extension and contents
that are not PDF.** PyMuPDF raises `FileDataError('Failed to open stream')` on
every one of them, and no OCR engine recovers them — there is no image to
recognise, there is plain text nobody was reading.

| what they actually were | how many |
|---|---|
| a proprietary BRy envelope | 74 |
| PKCS#7/DER with the signed document inside | 38 |
| plain RTF | 16 |

They came from 49 cases, nearly all of them old — which is the part worth
generalising. An archive that spans two decades of filing systems contains the
output of systems nobody runs any more, and the extension is the first thing
those systems got wrong.

## The step

`UnwrapStep` runs before anything else and almost always does nothing: on a real
PDF it costs reading 16 bytes. **It is not in the default cascade** — you pass it
in:

```python
from autosxtract import Cascade, NativeStep, OCRStep, UnwrapStep
from autosxtract.cascade import engine_order
from autosxtract.engines import base as engines

cascade = Cascade(steps=[UnwrapStep(), NativeStep()]
                        + [OCRStep(engines.get(n)) for n in engine_order()])
```

It is opt-in for one reason: it makes the cascade accept files that are not PDFs,
which is a widening of the contract, not a quality improvement. If your ingestion
already validates formats upstream, you do not want it.

Two outcomes, and the difference decides whether the cascade continues:

- **Text.** An RTF, or an envelope holding one. The cascade **stops here** —
  sending an RTF to OCR would be absurd. The text enters the contest like any
  other candidate.
- **Bytes.** A PDF that was inside a signed envelope. The step swaps the
  context's content and the cascade carries on over the payload, which is why
  `native` and the OCR steps see a normal document.

A plain PDF produces a refused attempt with the reason `"it is a PDF; the cascade
continues"` — visible in the provenance, which is the point: a stage that did
nothing should say so.

## Two decisions inside `formats.py`

**The extension is not the source of truth.** In these files it is demonstrably
wrong, so classification goes by byte signature: `%PDF`, `{\rtf`, `BRyPDDE`, and
for PKCS#7 a DER `SEQUENCE` (`0x30`) followed by a **long-form** length byte
(`0x81`/`0x82`/`0x83`). The short form is rejected on purpose — a signed envelope
never fits in 127 bytes, and accepting it would classify any `0x30`-prefixed junk
as PKCS#7. An unrecognised prefix returns `UNKNOWN` explicitly; it is never
treated as a PDF in silence, which is exactly the mistake that lost those 128
files.

**Inner content is reclassified, never assumed.** A BRy envelope holds a PKCS#7
that holds an RTF; a PKCS#7 could hold a PDF. Unwrapping is recursive and every
level goes back through detection.

The envelope's ZIP comes from outside and nothing in it is trustworthy, starting
with the declared sizes, so the caps are defensive: at most 32 members, 64 MB per
member, 4 levels of nesting. RFC 3161 timestamp members (`.tsr`) are skipped —
they are DER like the signed document but hold the timestamp's `TSTInfo`, so
letting them in returns a hash instead of the file.

## The API

```python
from autosxtract.formats import detect_format, unwrap, FileFormat

detect_format(data)   # -> FileFormat.PDF | RTF | BRY | PKCS7 | UNKNOWN
result = unwrap(data)

result.format             # FileFormat
result.text               # str   — filled means it is already text
result.bytes_for_cascade  # bytes | None — a binary document for the next steps
result.reason             # str   — why nothing came out
result.readable           # property
result.is_plain_pdf       # property: nothing was unwrapped
```

`unwrap` **never raises**. A failure becomes a filled-in `reason` and empty
content, because ingesting a batch must not fall over because of one document.
The broad `except` inside it is deliberate: that contract is worth more than the
elegance of enumerating a third-party library's failure modes. The narrower
`UnreadableFormat` — an envelope recognised but not openable — is available if
you call the level functions (`text_from_rtf`, `document_from_bry_envelope`,
`content_from_pkcs7`) yourself.

The module does no I/O and opens no socket: it decides and unwraps in memory.
