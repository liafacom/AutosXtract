"""The public vocabulary — the types that travel through the cascade.

Five objects and one rule:

``Line`` / ``Page``
    What **one engine** read from a page, line by line, with geometry. Optional:
    an engine that only returns a plain string is still a valid engine.

``Transcription``
    What one engine read from a whole document. A single contract, so the
    cascade never needs to know which engine is behind it.

``Candidate``
    A transcription **competing** for the document's text slot. It carries the
    quality score, which is what settles the competition.

``Result``
    What the cascade returns: the winning text, the step that produced it and
    the full provenance — every step attempted, with the reason it was refused.

The rule: provenance is mandatory, not optional. "The system extracted the
text" is not an auditable answer; "the native step read 41 characters and was
refused on density, Vision read 3,812 and passed" is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Line:
    """One line read by an engine, with where it is and how much it trusts it.

    The polygon is what separates "upright stamp in the margin" from "body
    text", and the score is what separates "read it badly" from "did not read
    it". Without both, all you can do with an OCR's output is accept or reject
    the whole page — and the whole page is rarely the problem.
    """

    text: str
    #: Engine confidence, **always between 0 and 1**. The layer thresholds
    #: depend on that scale; an engine reporting 0-100 must divide before
    #: building the ``Line``, otherwise every line looks perfect.
    score: float = 1.0
    #: ``((x, y), ...)`` in image pixels, origin at the TOP left. ``None`` when
    #: the engine exposes no geometry — the position-dependent layers are then
    #: skipped.
    poly: tuple[tuple[float, float], ...] | None = None

    @property
    def bbox(self) -> tuple[float, float, float, float] | None:
        """``(x1, y1, x2, y2)``, or ``None`` without a polygon."""
        if not self.poly:
            return None
        xs = [p[0] for p in self.poly]
        ys = [p[1] for p in self.poly]
        return min(xs), min(ys), max(xs), max(ys)


@dataclass(frozen=True)
class Page:
    """What an engine read from ONE page, line by line.

    This is the detailed contract, and it is optional: an engine with no
    geometry returns ``None`` from ``read_page`` and the cascade falls back to
    the simple contract. What is lost there are the line layers, not the
    extraction.
    """

    lines: list[Line] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text.strip())

    @property
    def mean_confidence(self) -> float:
        scores = [line.score for line in self.lines if line.text.strip()]
        return round(100.0 * sum(scores) / len(scores), 1) if scores else 0.0


@dataclass(frozen=True)
class Transcription:
    """What one engine read from a whole document.

    ``pages_answered < pages_sent`` is an **incomplete** reading: a page failed
    and the document has a hole. The cascade refuses on that — partial text
    passes any volume test and disappears without a trace.
    """

    text: str
    engine: str
    pages_sent: int = 0
    pages_answered: int = 0
    mean_confidence: float = 0.0
    ms: float = 0.0
    #: Filled in only when the engine exposes line geometry. It feeds the
    #: containment layers; empty means "this engine does not tell", never "the
    #: page has no lines".
    pages: list[Page] = field(default_factory=list)
    #: One entry per page **sent**, in the order they were sent, with an empty
    #: string where the page raised or read nothing.
    #:
    #: ``text`` joins only the pages that produced something, so it cannot be
    #: split back into pages: a page that came back blank leaves no trace in it,
    #: and a page's own text may contain the blank line the join uses. Whoever
    #: has to put a page back in its place in the document — the per-page
    #: routing of ``OCRStep`` — needs the alignment, not the concatenation.
    #: Dropping a page from the middle here is how a mixed PDF silently returns
    #: the scanned attachment without the pages that surround it.
    page_texts: list[str] = field(default_factory=list)
    #: Why pages did not come back, when they RAISED rather than read nothing.
    #:
    #: The distinction is the whole point: a page the engine read as blank and a
    #: page the engine never reached look identical in the text, and only one of
    #: them means the engine is down. Reporting the second as "no text" is how a
    #: dead worker degrades an archive in silence — 488 documents re-extracted
    #: down the worse path before anybody noticed.
    failures: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.pages_sent > 0 and self.pages_answered == self.pages_sent

    @property
    def empty(self) -> bool:
        return not (self.text or "").strip()


@dataclass(frozen=True)
class Candidate:
    """A transcription competing for the document's text slot."""

    step: str
    text: str
    score: float
    ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def volume(self) -> int:
        return len((self.text or "").strip())

    @property
    def usefulness(self) -> float:
        """``quality x log(1 + volume)`` — both dimensions, always.

        Volume alone lets a long unreadable OCR beat a short correct reading;
        quality alone lets a 14-character placeholder — clean precisely because
        it is short — beat the whole document.

        The logarithm damps volume on purpose: doubling the text does not
        double the usefulness, so a candidate has to be *much* larger to make
        up for worse quality.
        """
        if self.volume == 0:
            return 0.0
        return max(self.score, 0.0) * math.log1p(self.volume)


@dataclass(frozen=True)
class Attempt:
    """A step that ran, and what happened to it.

    ``accepted`` false with ``reason`` filled in is the interesting case: it is
    the record of why the cascade paid for the next step.
    """

    step: str
    accepted: bool
    reason: str
    chars: int = 0
    ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Result:
    """The extracted text and the whole path that led to it."""

    text: str
    step: str
    score: float | None
    ms: float
    attempts: list[Attempt] = field(default_factory=list)
    discarded: list[Candidate] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.text or "").strip()

    @property
    def provenance(self) -> str:
        """An auditable sentence with the whole cascade, in the order it ran."""
        path = " -> ".join(f"{a.step}({'ok' if a.accepted else a.reason})" for a in self.attempts)
        return f"{self.step}: {path}"

    def to_dict(self) -> dict[str, Any]:
        """The serialisable form — what goes to JSON, a log or a database."""
        return {
            "text": self.text,
            "step": self.step,
            "score": self.score,
            "ms": round(self.ms, 1),
            "chars": len(self.text or ""),
            "provenance": self.provenance,
            "attempts": [
                {
                    "step": a.step,
                    "accepted": a.accepted,
                    "reason": a.reason,
                    "chars": a.chars,
                    "ms": round(a.ms, 1),
                    **({"details": a.details} if a.details else {}),
                }
                for a in self.attempts
            ],
            **self.details,
        }
