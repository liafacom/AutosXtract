"""Screening out documents with no textual value — a deliberate, evidenced drop.

It covers one family: **identity documents** (photocopied national ID, tax card,
driving licence) and **vehicle documents**. Dropping them has double value: it
spares the expensive step *and* keeps tax numbers, parentage and place of birth
out of the output corpus.

The other family from the sample folder — a **notary draft**, a sheet with a
stamp, a signature and a date — is NOT detectable a priori: measured across
nine families of pixel signals, it produces exactly the same statistics as a
dense, faded page. What resolves it is the gate that MEASURES the content
(``quality.vetoes``), not this module. It is documented here on purpose, so
nobody tries an image heuristic again.

Where the markers come from
---------------------------
They are not hand-picked. They come from the **BID Dataset** (Brazilian
Identity Document Dataset, Soares/Neves Junior/Bezerra, SIBGRAPI 2020) — 28,800
images of ID cards, tax cards and driving licences across 8 classes. The
annotations carry the printed background text of each document; 9,238 such
regions were extracted, giving the real vocabulary of the cards rather than a
guess from three examples.

Of the 62 candidates with 10+ occurrences in BID, only those appearing in
**zero** of the 486 legitimate documents of the validation archive were kept.
That filter is what matters: BID says what is printed on the card, not what
DISCRIMINATES. It is what dropped ``REGISTRO GERAL`` and ``CARTEIRA DE
IDENTIDADE`` (4 false positives each) and what keeps out ``MINISTÉRIO DA
FAZENDA`` and ``SECRETARIA DA RECEITA FEDERAL``, legitimate on a tax card but
present on tax clearance certificates.

Measured separation: the archive's 3 cards score 2, 4 and 7 with a density of
3.5 to 6.5 marks per thousand characters; the most-marked legitimate document
sits at 1.56 — a margin of 2.2x.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from autosxtract import patterns

# Two marks are the floor, but the criterion that actually separates is
# DENSITY. A card is almost entirely markers; a legal document merely MENTIONS
# an identity document when identifying the parties. The distinction matters: a
# deed of sale from the archive, with a court order in its body, scores 2 — the
# same 2 as the tax card — and only an arbitrary size ceiling separated them,
# by 55 characters. By density the margin is 2.2x.
#
# Measured: cards at 3.49 / 5.65 / 6.51 marks per thousand characters; the
# most-marked legitimate document at 1.56.
MIN_MARKS = 2
MIN_DENSITY_PER_THOUSAND = 2.5

#: Above this a document labelled as a personal attachment is not a card. Cards
#: of 181 to 545 characters against 1,544 for the shortest legitimate document.
MAX_CARD_CHARS = 1000


def _normalize(text: str) -> str:
    """Uppercase, unaccented, letters and digits only, spaces collapsed.

    A photocopied card comes out of OCR with unstable accents and punctuation
    (``VÁLIDA EMTODO OTERRITÓRIO``, ``LEIN°7 116 DE 29/0E``), so comparing an
    accented or punctuated form is useless. It is the same normalisation
    applied to the BID transcriptions when deriving the markers.
    """
    catalogue = patterns.default()
    decomposed = unicodedata.normalize("NFKD", text or "")
    unaccented = "".join(c for c in decomposed if not unicodedata.combining(c))
    alphanumeric_only = catalogue.regex("screening.non_alphanumeric").sub(" ", unaccented)
    return catalogue.regex("screening.whitespace").sub(" ", alphanumeric_only).strip().upper()


def identity_marks(text: str) -> int:
    """How many identity-document marks the text shows."""
    catalogue = patterns.default()
    normalized = _normalize(text)
    marks = catalogue.strings("screening.identity_marks")
    total = sum(1 for mark in marks if mark in normalized)
    return total + (1 if catalogue.regex("screening.traffic_dept").search(normalized) else 0)


def is_vehicle_document(text: str) -> bool:
    """Is the text a vehicle registration certificate?

    It was VETOED from screening for a while, on the argument that it is proof
    of a seizable asset. The decision went the other way, and the reasoning
    holds: the certificate proves OWNERSHIP of the vehicle, while the fact that
    matters — the seizure — comes from a dedicated system or its own record,
    not from this attachment.
    """
    normalized = _normalize(text or "")
    return any(v in normalized for v in patterns.default().strings("screening.vehicle_marks"))


@dataclass(frozen=True)
class Screening:
    """The verdict with its evidence — a drop is irreversible."""

    drop: bool
    reason: str = ""
    marks: int = 0
    density: float = 0.0

    @property
    def evidence(self) -> str:
        return (
            f"{self.marks} identity-document marks, "
            f"density {self.density:.2f} per thousand characters"
        )


def assess(text: str, label: str | None = None) -> Screening:
    """Is the text the transcription of a photocopied identity/vehicle document?

    Three paths, because none covers the archive alone:

    1. **Vehicle document** — literal and unambiguous.
    2. **Physical card marks** (derived from BID) with density — catches the
       card when the OCR preserves the printed labels.
    3. **A personal-attachment label plus short text** — catches it when the
       OCR returns only names and codes, with no label at all. The label ALONE
       would discard deeds and marriage certificates (6 of the 9 documents so
       labelled in the archive); the size ceiling is what separates them —
       cards of 181 to 545 characters against 1,544 for the shortest legitimate
       document.

    Path 3 came from a real regression: the marks were calibrated on the output
    of an extractor that carried the printed labels, and putting a faster OCR in
    front made the same document read as loose names and codes ("ASSIN SILVIO
    ... C2 80 CT T8LC66000"), with no marks at all — and the card stopped being
    detected.
    """
    raw = (text or "").strip()
    if not raw:
        return Screening(False, "empty text")
    if is_vehicle_document(raw):
        return Screening(True, "vehicle document")
    attachment_label = patterns.default().text("screening.personal_attachment_label")
    if (label or "").strip().lower() == attachment_label and len(raw) <= MAX_CARD_CHARS:
        return Screening(True, "personal attachment with short text")
    marks = identity_marks(raw)
    density = 1000.0 * marks / len(raw)
    if marks < MIN_MARKS:
        return Screening(False, f"only {marks} marks", marks, density)
    if density < MIN_DENSITY_PER_THOUSAND:
        return Screening(False, f"density {density:.2f} below the minimum", marks, density)
    return Screening(True, "card marks with density", marks, density)


def is_identity_document(text: str, label: str | None = None) -> bool:
    """Boolean shortcut — equivalent to ``assess(...).drop``."""
    return assess(text, label).drop
