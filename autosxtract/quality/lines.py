"""Line containment layers — stamps, signatures and junk.

**The premise, which comes from an audit rather than intuition:** a small OCR
engine reads the *body* of a document almost perfectly — case number, parties,
address, dates, amounts. The error concentrates in four places:

1. **vertical stamp** (protocol, digital seal) — read sideways, it becomes junk;
2. **signature over printed text** — it corrupts the whole line;
3. **two-column header** with a handwritten ruling — it scrambles;
4. **run-together words** in caps (``ESTADODEMATOGROSSODOSUL``).

No OCR reads *through* a stamp. The strategy, then, is not "read better": it is
to **contain the damage, flag where it is, and recover what is recoverable**.

    Layer 1   classifies each line; junk becomes a marker, fragments are
              dropped, the body passes untouched. No model, ~2 ms.
    Layer 1b  re-segments run-together words against the lexicon.
    Layer 2   hands back the targets to re-read — the step re-runs the engine.
    Layer 3   a per-page report: how much of the text is trustworthy, and what
              to do about it.

Measured on 895 pages against the same engine without the layers:

    median CER      0.132 -> 0.129
    mean CER        0.238 -> 0.229
    entity recall   0.902 -> 0.921
    p50 latency       298 -> 236 ms

79 pages improve (mean gain +0.10) and **only 4 get worse** (-0.03, all of them
already bad). Clean pages are untouched (0.054 -> 0.053). On the subset of 188
pages with a vertical stamp, entity recall rises from 0.745 to 0.837.

And it is **faster** than the bare engine, because the ceiling on re-reads costs
less than the junk lines that stop reaching the recogniser.

The principle behind the thresholds: ``illegible`` only for **unambiguous**
junk. Anything doubtful — a name misread under a signature, a blurred header —
becomes ``suspect``: the text passes, but the page loses confidence and tends
to escalate. That way the weak signal is not lost.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field

from autosxtract import patterns
from autosxtract.quality.lexicon import Lexicon, short_words

ILLEGIBLE_MARKER = "[illegible]"
SIGNATURE_MARKER = "[signature]"

# Everything this module matches on lives in the catalogue, under ``lines.*``:
# what a reference line is, what a job title is, what a proper name looks like.
# The THRESHOLDS stay here, because they were measured on the classifier and not
# on the vocabulary.


@dataclass
class ClassifiedLine:
    """One line and the verdict on it."""

    i: int
    text: str
    #: ``clean`` passes untouched; ``suspect`` passes but lowers confidence;
    #: ``illegible`` and ``vertical`` become markers and are re-read targets;
    #: ``fragment`` is dropped; ``signature`` gets its own marker.
    kind: str
    score: float
    coverage: float
    junk: float
    bbox: tuple[float, float, float, float] | None = None


@dataclass
class Containment:
    """Layer 1's result, with what Layer 2 needs to re-read."""

    text: str
    lines: list[ClassifiedLine] = field(default_factory=list)
    n_total: int = 0
    n_illegible: int = 0
    n_vertical: int = 0
    n_fragment: int = 0
    n_suspect: int = 0
    n_signature: int = 0
    trusted_fraction: float = 1.0
    targets: list[int] = field(default_factory=list)

    @property
    def needs_escalation(self) -> bool:
        """The damage is NOT localised — the page is a candidate for a costly step."""
        return (
            self.trusted_fraction < 0.72
            or self.n_illegible >= 3
            or (self.n_illegible + self.n_suspect) >= 6
        )

    @property
    def suggested_action(self) -> str:
        if self.needs_escalation:
            return "escalate"
        return "ok" if self.n_illegible == 0 else "accept_with_holes"

    def report(self) -> dict:
        """Layer 3: the per-page summary that drives routing.

        The policy belongs to the caller, not here — this module measures, it
        does not decide.
        """
        return {
            "lines_total": self.n_total,
            "lines_illegible": self.n_illegible,
            "lines_suspect": self.n_suspect,
            "lines_signature": self.n_signature,
            "lines_vertical": self.n_vertical,
            "trusted_fraction": self.trusted_fraction,
            "needs_escalation": self.needs_escalation,
            "suggested_action": self.suggested_action,
        }


# ── Layer 1b: run-together words ─────────────────────────────────────────

#: Longest word the segmentation tries to match in one go.
_MAX_WORD = 18


def resegment(text: str, lexicon: Lexicon) -> str | None:
    """Split runs of 14+ joined letters into words from the lexicon.

    ``ESTADODEMATOGROSSODOSUL`` -> ``ESTADO DE MATO GROSSO DO SUL``.

    The search **backtracks**, and that is not a detail. The greedy version —
    match the longest word and move on — fails on exactly this example: in
    ``...DOSUL`` it matches ``dos``, gets stuck on ``ul`` and discards the whole
    run. With backtracking it gives up ``dos``, takes ``do`` and closes on
    ``sul``.

    Memoising by position keeps the cost at ``O(n x 18)`` despite the
    backtracking, and that matters: the error here is not slow, it is
    **silent** — the joined word stays joined and the line falls into
    ``suspect`` on low coverage, with nobody seeing why.

    Returns ``None`` when nothing segmented cleanly. The decision stays
    all-or-nothing per run: a partial split produces junk worse than the joined
    word.
    """

    short = short_words()

    def segment(run: str) -> str | None:
        lower = run.lower()
        n = len(lower)

        @functools.cache
        def solve(i: int) -> tuple[str, ...] | None:
            if i == n:
                return ()
            # Longest to shortest: preferring the longer word avoids splitting
            # "grosso" into "gros" + "so" when both exist.
            for j in range(min(n, i + _MAX_WORD), i + 1, -1):
                word = lower[i:j]
                if word in lexicon or word in short:
                    rest = solve(j)
                    if rest is not None:
                        return (run[i:j], *rest)
            return None

        parts = solve(0)
        return " ".join(parts) if parts and len(parts) > 1 else None

    new = (
        patterns.default()
        .regex("lines.run_together")
        .sub(lambda m: segment(m.group(0)) or m.group(0), text)
    )
    return new if new != text else None


# ── Layer 1: classification ──────────────────────────────────────────────


def _classify(
    text: str, score: float, bbox, width: float, height: float, lexicon: Lexicon
) -> ClassifiedLine:
    catalogue = patterns.default()
    t = (text or "").strip()

    # Foreign script: drop the character and keep the line.
    foreign_fraction = 0.0
    foreign = catalogue.regex("lines.foreign_scripts")
    if foreign.search(t):
        cleaned = foreign.sub("", t).strip()
        foreign_fraction = 1 - len(cleaned) / max(1, len(t))
        t = cleaned

    tokens = lexicon.tokens(t)
    coverage = lexicon.coverage(t)
    junk = len(catalogue.regex("lines.junk").findall(t)) / max(1, len(t))
    alphanumerics = sum(c.isalnum() for c in t)

    kind = "clean"
    if alphanumerics == 0 and len(t) <= 3:
        kind = "fragment"  # "·", "—", "::" — a lone symbol
    elif bbox is not None and width > 1 and height > 1:
        x1, y1, x2, y2 = bbox
        w, h = x2 - x1, y2 - y1
        cx = (x1 + x2) / 2
        upright = h > 1.5 * max(w, 1) and h > 0.06 * height
        in_margin = cx < 0.13 * width or cx > 0.87 * width
        if upright and in_margin:
            kind = "vertical"

    if kind == "clean":
        reference = bool(catalogue.regex("lines.reference_only").match(t)) or bool(
            catalogue.regex("lines.date").search(t)
        )
        title = len(t) <= 24 and bool(catalogue.regex("lines.caps_title").match(t))
        anchor = bool(catalogue.regex("lines.anchor").search(t))
        prose = len(tokens) >= 2

        # Layer 1b before judging: a joined word has artificially low coverage,
        # and condemning it for that would discard correct text.
        if not reference and prose and coverage < 0.55:
            resegmented = resegment(t, lexicon)
            if resegmented:
                new_coverage = lexicon.coverage(resegmented)
                if new_coverage >= 0.55:
                    t, tokens, coverage = resegmented, lexicon.tokens(resegmented), new_coverage

        if reference or title or anchor:
            pass  # structural text: never touched
        elif (
            foreign_fraction > 0.5
            or junk > 0.55
            or (score < 0.55 and coverage < 0.12 and len(t) >= 14)
        ):
            kind = "illegible"
        elif (prose and coverage < 0.35 and score < 0.85) or foreign_fraction > 0.2:
            kind = "suspect"

    return ClassifiedLine(
        i=-1,
        text=t,
        kind=kind,
        score=round(score, 3),
        coverage=round(coverage, 3),
        junk=round(junk, 3),
        bbox=bbox,
    )


def _looks_like_scribble(line: ClassifiedLine) -> bool:
    """What a recogniser spits out trying to read a handwritten signature."""
    t = line.text.strip()
    if not (2 <= len(t) <= 28):
        return False
    return (
        len(patterns.default().regex("lines.token").findall(t)) <= 3
        and line.coverage < 0.25
        and line.score < 0.97
        and not any(c.isdigit() for c in t)
    )


def _mark_signature_structurally(lines: list[ClassifiedLine]) -> None:
    """A scribble right ABOVE a name in caps, with a job title nearby.

    Purely structural, no model. It runs **always**, including when a visual
    detector is present: the two fail on different cases, and running the rule
    costs nothing.
    """
    catalogue = patterns.default()
    alive = [x for x in lines if x.kind != "fragment"]
    for idx, line in enumerate(alive):
        if line.kind != "clean" or not _looks_like_scribble(line):
            continue
        has_name = any(
            catalogue.regex("lines.caps_name").match(v.text.strip())
            for v in alive[idx + 1 : idx + 3]
        )
        has_title = any(
            catalogue.regex("lines.job_title").search(v.text) for v in alive[idx + 1 : idx + 4]
        )
        if has_name and has_title:
            line.kind = "signature"


def _overlaps(bbox, box, minimum: float = 0.15) -> bool:
    if bbox is None:
        return False
    ax1, ay1, ax2, ay2 = bbox
    bx1, by1, bx2, by2 = box
    ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    iy = max(0.0, min(ay2, by2) - max(ay1, by1))
    area = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    return (ix * iy) / area >= minimum


def _box_is_signature(box, lines: list[ClassifiedLine]) -> ClassifiedLine | None:
    """Combines the visual detector with the text read — and the text decides.

    A box only counts as a signature if some line overlaps it **and** that line
    is illegible — the recogniser tried to read the scribble. If any overlapping
    line is stamp text, the box is discarded.

    This filter exists because of a measurement: a detector trained on contract
    signatures fired on 19% of the pages of a legal archive and most were
    **false positives** — an authenticity seal (confidence 0.92), a "DELIVERED"
    stamp, a logo, a QR code, a coat of arms, and even the printed word
    "SIGNATURES".
    """
    inside = [line for line in lines if line.bbox is not None and _overlaps(line.bbox, box)]
    catalogue = patterns.default()
    if any(catalogue.regex("lines.stamp_keywords").search(line.text) for line in inside):
        return None
    illegible = [
        line
        for line in inside
        if line.kind in ("clean", "suspect")
        and not catalogue.regex("lines.reference_only").match(line.text)
        and line.coverage < 0.30
        and line.score < 0.92
        and len(line.text) <= 40
    ]
    if not illegible:
        return None
    return min(illegible, key=lambda line: line.coverage)


def contain(
    page,
    *,
    lexicon: Lexicon | None = None,
    signature_boxes: list | None = None,
    mark_vertical: bool = True,
) -> Containment:
    """Layer 1: classify and clean. **It runs no model at all.**

    ``page`` is a ``Page`` — lines with polygon and score. ``signature_boxes``
    are bounding boxes from a visual detector (Layer 1.5); ``None`` leaves only
    the structural rule, which runs regardless.
    """
    lexicon = lexicon or Lexicon.builtin()
    classified: list[ClassifiedLine] = []
    for k, line in enumerate(page.lines):
        info = _classify(line.text, line.score, line.bbox, page.width, page.height, lexicon)
        info.i = k
        classified.append(info)

    if signature_boxes:
        for box in signature_boxes:
            line = _box_is_signature(tuple(box[:4]), classified)
            if line is not None:
                line.kind = "signature"
    _mark_signature_structurally(classified)

    return _assemble(classified, mark_vertical=mark_vertical)


def _assemble(
    lines: list[ClassifiedLine],
    *,
    mark_vertical: bool = True,
    recovered: dict[int, str] | None = None,
) -> Containment:
    """Build the final text from the classes, with no repeated marker.

    Shared by Layer 1 and Layer 2's reassembly — if each built the string on its
    own, a fix in one would go unnoticed in the other.
    """
    recovered = recovered or {}
    out: list[str] = []
    marked = False
    ok = total = 0
    targets: list[int] = []

    for line in lines:
        total += max(len(line.text), 1)
        if line.kind == "fragment":
            continue
        if line.i in recovered:
            out.append(recovered[line.i])
            ok += len(recovered[line.i])
            marked = False
            continue
        if line.kind == "clean":
            out.append(line.text)
            ok += len(line.text)
            marked = False
        elif line.kind == "suspect":
            # KEEPS the text; it just does not count as trusted. That is the
            # safe side of the error: you lose confidence, never content.
            out.append(line.text)
            marked = False
        elif line.kind == "signature":
            if not marked:
                out.append(SIGNATURE_MARKER)
            marked = True
        elif line.kind == "vertical":
            targets.append(line.i)
            if mark_vertical and not marked:
                out.append(ILLEGIBLE_MARKER)
            marked = mark_vertical
        else:  # illegible
            targets.append(line.i)
            if not marked:
                out.append(ILLEGIBLE_MARKER)
            marked = True

    return Containment(
        text="\n".join(out),
        lines=lines,
        n_total=len(lines),
        n_illegible=sum(1 for x in lines if x.kind == "illegible"),
        n_vertical=sum(1 for x in lines if x.kind == "vertical"),
        n_fragment=sum(1 for x in lines if x.kind == "fragment"),
        n_suspect=sum(1 for x in lines if x.kind == "suspect"),
        n_signature=sum(1 for x in lines if x.kind == "signature"),
        trusted_fraction=round(ok / max(1, total), 3),
        targets=targets,
    )


def reassemble(containment: Containment, recovered: dict[int, str]) -> Containment:
    """Layer 2, second half: rebuild the text with the re-read lines."""
    return _assemble(containment.lines, recovered=recovered)
