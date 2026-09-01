"""The contest: the best one wins, not the last one that ran."""

from __future__ import annotations

from autosxtract.quality.selection import losers, pick
from autosxtract.types import Candidate


def test_an_empty_candidate_never_wins():
    """This was the case that left 682 documents with zero characters."""
    good = Candidate("native", "genuine text extracted from the whole document", 0.8)
    empty = Candidate("ocr", "", 1.0)
    assert pick([good, empty]) is good


def test_volume_alone_does_not_win():
    """A long unreadable OCR must not beat a short correct reading."""
    clean = Candidate("native", "a" * 400, 0.9)
    junk = Candidate("ocr", "b" * 800, 0.1)
    assert pick([clean, junk]) is clean


def test_quality_alone_does_not_win():
    """A short clean placeholder must not beat the whole filing."""
    placeholder = Candidate("ocr", "NO CONTENT", 1.0)
    filing = Candidate("native", "x" * 20000, 0.6)
    assert pick([filing, placeholder]) is filing


def test_a_tie_goes_to_the_cheapest():
    """Entry order is cascade order: do not switch engines for no gain."""
    first = Candidate("native", "exactly the same text", 0.7)
    second = Candidate("ocr", "exactly the same text", 0.7)
    assert pick([first, second]) is first


def test_no_candidates_returns_none():
    assert pick([]) is None
    assert pick([Candidate("a", "", 1.0)]) is None


def test_losers_preserve_the_provenance():
    a = Candidate("native", "short", 0.2)
    b = Candidate("ocr", "considerably longer text of better quality", 0.9)
    assert losers([a, b], pick([a, b])) == [a]
