"""What KIND of page this is — step 0 of the ladder.

Classifies the page from what the cheap engine already read, running no model
at all (~1 ms). It exists so each page can go to the step that resolves it,
rather than sending them all to the same one:

    table               short lines in aligned columns, repeated amounts,
                        little prose
    stamped_digital     carries a digital signature seal AND a readable body
    degraded            low, scattered coverage with no structure — nothing
                        reads it well, so accept what there is and flag it
    normal              everything else

**About the table route, a measured verdict worth more than the route itself.**
Across 17 pages classified as tables, the cheap engine with containment layers
recovered **0.797** of the numeric values, against 0.699 for a dedicated table
structure model (SLANet) that also cost 6 to 29 s per page against 0.27 s. A
heavier structure pipeline (PPStructureV3) landed between them, at ~60 s/page.

The conclusion: on a poor scan the bottleneck **is not the structure model, it
is the cell OCR**. Reconstructing the grid does not help if the recogniser
cannot read the cell, and the reconstruction still loses the surrounding prose.
Across a 895-page sample, switching to the table model's output won on **1
page**.

That is why the library **classifies** the route and does not embed a table
step: the information is useful to anyone who needs the structure as markdown
and accepts losing ~10 points of value recall, and noise to everyone else.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from autosxtract import patterns
from autosxtract.quality.lexicon import Lexicon

# The four signals this module reads off the page — digits, amounts, the digital
# seal, drawn rules — are ``routing.*`` in the pattern catalogue. The VOTES and
# the thresholds stay here: they were measured on 17 pages classified as tables
# and on a 895-page sample, and they do not travel with the language.


@dataclass(frozen=True)
class Route:
    """The classification, with the signals that produced it — so it is auditable."""

    kind: str
    signals: dict[str, float]

    @property
    def evidence(self) -> str:
        parts = ", ".join(f"{k}={v:.2f}" for k, v in sorted(self.signals.items()))
        return f"{self.kind} ({parts})"


def _aligned_columns(lines, width: float) -> float:
    """Fraction of lines whose starting x coincides with others'.

    A table has several lines starting in the same column; prose does not. The
    tolerance is 2% of the width, which absorbs detector jitter without merging
    neighbouring columns.
    """
    xs = sorted(min(p[0] for p in ln.poly) / width for ln in lines if ln.poly and width > 1)
    if len(xs) < 6:
        return 0.0
    groups, current = [], [xs[0]]
    for x in xs[1:]:
        if x - current[-1] <= 0.02:
            current.append(x)
        else:
            groups.append(current)
            current = [x]
    groups.append(current)
    in_columns = sum(len(g) for g in groups if len(g) >= 3)
    return in_columns / len(xs)


def route(page, *, lexicon: Lexicon | None = None) -> Route:
    """Classify the page from what the cheap engine read."""
    lexicon = lexicon or Lexicon.builtin()
    lines = [ln for ln in page.lines if ln.text.strip()]
    if not lines:
        return Route("degraded", {"lines": 0})

    catalogue = patterns.default()
    texts = [ln.text.strip() for ln in lines]
    body = " ".join(texts)
    n = len(texts)

    coverage = lexicon.coverage(body)
    short = sum(1 for t in texts if len(t) <= 22) / n
    digit = catalogue.regex("routing.digit")
    numeric = sum(1 for t in texts if len(digit.findall(t)) >= 2 and len(t) <= 40) / n
    amounts = len(catalogue.regex("routing.amount").findall(body))
    rule = catalogue.regex("routing.rule")
    rules = sum(1 for t in texts if rule.search(t))
    columns = _aligned_columns(lines, page.width)
    has_seal = bool(catalogue.regex("routing.seal").search(body))
    # Prose: a long line ending in sentence punctuation.
    prose = sum(1 for t in texts if len(t) > 45 and t[-1:] in ".;:") / n
    median_score = statistics.median([ln.score for ln in lines])

    signals = {
        "coverage": round(coverage, 3),
        "short": round(short, 3),
        "numeric": round(numeric, 3),
        "amounts": float(amounts),
        "rules": float(rules),
        "columns": round(columns, 3),
        "prose": round(prose, 3),
        "median_score": round(median_score, 3),
    }

    # Table: six weak signals, none decisive on its own. Requiring 4 of 6 plus
    # numeric density is what separates a table from a form and from a header.
    table_votes = (
        (short > 0.55)
        + (numeric > 0.30)
        + (amounts >= 6)
        + (rules >= 3)
        + (columns > 0.35)
        + (prose < 0.12)
    )
    signals["table_votes"] = float(table_votes)
    if table_votes >= 4 and numeric > 0.20:
        return Route("table", signals)

    # The seal alone is not enough: it appears on every page of a digital case
    # file. What distinguishes is the seal WITH a readable body — there is text
    # to gain from a better step.
    if has_seal and coverage >= 0.45:
        return Route("stamped_digital", signals)

    if coverage < 0.40 and median_score < 0.90 and prose < 0.15:
        return Route("degraded", signals)

    return Route("normal", signals)
