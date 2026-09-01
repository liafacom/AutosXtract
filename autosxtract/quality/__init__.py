"""How you measure whether an extraction worked.

A layer with no I/O and no network: it takes text (and, where it exists, the
page profile) and returns a number, a verdict and evidence. It is what the
cascade consults to decide whether to pay for the next step.
"""

from autosxtract.quality.anchors import anchors, lost
from autosxtract.quality.consensus import (
    Agreement,
    Consensus,
    assess_agreement,
    assess_emptiness,
)
from autosxtract.quality.gate import Verdict, evaluate
from autosxtract.quality.lexicon import Lexicon
from autosxtract.quality.lines import Containment, contain, reassemble, resegment
from autosxtract.quality.metrics import text_metrics
from autosxtract.quality.prose import normalize, rebuild_prose
from autosxtract.quality.routing import Route, route
from autosxtract.quality.scoring import score_structure, score_text
from autosxtract.quality.selection import losers, pick
from autosxtract.quality.stamp import BRAZILIAN_COURT_PATTERNS, Stamp, strip_stamp, useful_words

__all__ = [
    "BRAZILIAN_COURT_PATTERNS",
    "Agreement",
    "Consensus",
    "Containment",
    "Lexicon",
    "Route",
    "Stamp",
    "Verdict",
    "anchors",
    "assess_agreement",
    "assess_emptiness",
    "contain",
    "evaluate",
    "losers",
    "lost",
    "normalize",
    "pick",
    "reassemble",
    "rebuild_prose",
    "resegment",
    "route",
    "score_structure",
    "score_text",
    "strip_stamp",
    "text_metrics",
    "useful_words",
]
