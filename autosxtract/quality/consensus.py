"""Proof by agreement between independent engines.

No pixel statistic tells "blank page" from "dense but faded page" — nine
families were tested (total ink, projection bands, compressed bytes per page,
image coverage, six preprocessing tracks, the CCpdf *born-digital* rule) and
all failed for the same reason: the two cases produce identical statistics.

What does separate them is **measuring instead of estimating**, and measuring
with engines of different architectures. Measured on a real archive, with the
pipeline's floor of 12 useful words:

    document         engine A   engine B   engine C
    9089248 - 1             0          2          3   <- 3/3 say empty
    9089310 - 144           0          1          1   <- 3/3
    9089333 - 1             0          4          4   <- 3/3
    108577445 - 1          59        110        109   <- 3/3 say it has content
    126767951 - 1          83        118        112
    94828602 - 1           49         95         95

The separation is absolute — 0 to 4 against 49 to 118, with no grey zone. It is
the *ensemble* principle: errors from independent engines do not correlate, so
agreement is worth more than any single vote.

Two different questions live here:

``assess_emptiness``   is the page EMPTY?      (proof of absence)
``assess_agreement``   is the reading COMPLETE? (proof of sufficiency)

The module takes readings that were already made and returns the verdict with
the evidence attached. "The system thought it was empty" is not an auditable
answer; "three independent engines read 0, 1 and 1 useful word" is.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autosxtract.quality.stamp import default as default_stamp


@dataclass(frozen=True)
class Consensus:
    """The emptiness verdict, with the evidence that supports it."""

    empty: bool
    readings: dict[str, int] = field(default_factory=dict)

    @property
    def evidence(self) -> str:
        parts = ", ".join(
            f"{engine} read {n} " + ("useful word" if n == 1 else "useful words")
            for engine, n in sorted(self.readings.items())
        )
        return f"{len(self.readings)} independent engines: {parts}"


def assess_emptiness(
    readings: dict[str, int],
    *,
    word_floor: int,
    min_engines: int = 2,
) -> Consensus:
    """Do the engines AGREE that the page has no content?

    Requires ``min_engines`` readings and that **all** of them fall below the
    floor. A single dissenting engine breaks the consensus — that asymmetry is
    what makes this safe: declaring a page with text empty discards
    information, so one contrary opinion is enough to escalate.
    """
    valid = {e: n for e, n in readings.items() if n >= 0}
    if len(valid) < min_engines:
        return Consensus(empty=False, readings=valid)
    return Consensus(empty=all(n < word_floor for n in valid.values()), readings=valid)


@dataclass(frozen=True)
class Agreement:
    """Do two independent readings say the same thing about the page?"""

    agree: bool
    similarity: float
    words: dict[str, int] = field(default_factory=dict)

    @property
    def evidence(self) -> str:
        parts = ", ".join(
            f"{engine} read {n} " + ("useful word" if n == 1 else "useful words")
            for engine, n in sorted(self.words.items())
        )
        return f"{parts}; they agree on {100 * self.similarity:.0f}% of the vocabulary"


def assess_agreement(
    readings: dict[str, str],
    *,
    word_floor: int,
    min_similarity: float,
    stamps: tuple[str, ...] | None = None,
) -> Agreement:
    """Do the engines AGREE about what the page says?

    The same principle as ``assess_emptiness``, aimed at the other question.
    There you prove the absence of content; here you prove the reading is
    **complete** — that the page is short because the document is short, and
    not because the extraction failed. No statistic separates those two cases;
    two engines of different architectures reading the same text do.

    The measure is Jaccard over the vocabulary outside the stamp — insensitive
    to order and repetition, which is what you want: the two readings may break
    lines differently without that counting as disagreement.

    It requires **both** readings to clear the floor. Below it the right
    question is the emptiness one, and two nearly empty readings would agree
    trivially.

    It costs nothing in the cascade: at the point of decision both readings are
    already in hand. Measured on 935 documents: 23 vetoes, the expensive step
    fell from 25 to 16 calls, and the real content went UP by 424 characters.
    """
    stamp = default_stamp(stamps)
    vocabularies = {engine: stamp.vocabulary(t) for engine, t in readings.items()}
    sizes = {engine: len(v) for engine, v in vocabularies.items()}
    if len(vocabularies) < 2 or any(n < word_floor for n in sizes.values()):
        return Agreement(agree=False, similarity=0.0, words=sizes)

    sets = list(vocabularies.values())
    union = set().union(*sets)
    intersection = set(sets[0]).intersection(*sets[1:])
    similarity = len(intersection) / len(union) if union else 0.0
    return Agreement(agree=similarity >= min_similarity, similarity=similarity, words=sizes)
