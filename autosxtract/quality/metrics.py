"""Metrics for "is this actually text?", and the score they feed.

All of them work on a loose string, on purpose: that way the output of **any**
engine is scored by the same criterion as the native text, and the competition
between steps is fair. The ones that need page structure enter only into the
native step's score.

The three detectors in the "text that is not text" section each exist because
they caught a case every other check let through:

- **glyph index** — a font with no ``ToUnicode`` table makes the extractor
  return the glyph index instead of the character (``g40g86g87g72``). It is
  alphanumeric, has no odd symbols, and the word counter's ``\\w+`` treats the
  whole run as a single word. Measured: 1,171 characters of junk scoring
  **0.85**.
- **control bytes** — broken encoding, not content.
- **function words** — the cheapest and strongest discriminator for "is this
  Portuguese?". Running prose sits between 0.20 and 0.30; an unreadable
  transcription sits below 0.03.

The last two of those describe a LANGUAGE, and the domain vocabulary describes a
CORPUS, so none of them is written here: they are the ``metrics.*`` entries of
the pattern catalogue. The thresholds stay, because they were measured on the
metric and not on the words.
"""

from __future__ import annotations

import re
from typing import Any

from autosxtract import patterns

# Below this there is not enough evidence to judge plausibility. It protects
# tables, forms and record cards — which legitimately have no prose and must
# not be punished as if they were bad OCR.
MIN_WORDS_TO_JUDGE = 15


def normalize(text: str) -> str:
    """Drop non-breaking spaces, soft hyphens and excess whitespace."""
    catalogue = patterns.default()
    text = text.translate(catalogue.translation("metrics.character_fixes"))
    text = catalogue.regex("metrics.horizontal_space").sub(" ", text)
    text = catalogue.regex("metrics.blank_lines").sub("\n\n", text)
    return text.strip()


def odd_char_ratio(text: str) -> float:
    if not text:
        return 1.0
    return len(patterns.default().regex("metrics.allowed_chars").findall(text)) / max(len(text), 1)


def short_line_ratio(text: str, max_len: int = 20) -> float:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return 1.0
    return sum(1 for ln in lines if len(ln) < max_len) / len(lines)


def single_char_word_ratio(text: str) -> float:
    words = patterns.default().regex("metrics.word").findall(text)
    if not words:
        return 1.0
    return sum(1 for w in words if len(w) == 1) / len(words)


def glyph_index_ratio(text: str) -> float:
    """Fraction of the text taken up by glyph-index runs (``g40g86g87``)."""
    if not text:
        return 0.0
    matches = patterns.default().regex("metrics.glyph_index").findall(text)
    return sum(len(m) for m in matches) / max(len(text), 1)


def control_char_ratio(text: str) -> float:
    if not text:
        return 0.0
    return len(patterns.default().regex("metrics.control_chars").findall(text)) / max(len(text), 1)


def stopword_ratio(text: str) -> tuple[float, int]:
    """The function-word ratio and the total alphabetic word count.

    Only alphabetic tokens of 2+ characters count: numbers, codes and form
    abbreviations stay out of both the numerator and the denominator.
    """
    catalogue = patterns.default()
    words = [w.lower() for w in catalogue.regex("metrics.alphabetic_word").findall(text)]
    if not words:
        return 0.0, 0
    stopwords = catalogue.words("metrics.stopwords")
    return sum(1 for w in words if w in stopwords) / len(words), len(words)


def domain_coverage(text: str, domain_patterns: list[str] | None = None) -> dict[str, Any]:
    expected = (
        list(patterns.default().patterns("metrics.domain"))
        if domain_patterns is None
        else domain_patterns
    )
    if not expected:
        return {"found": [], "count": 0, "coverage": 0.0}
    lowered = text.lower()
    found = [p for p in expected if re.search(p, lowered, flags=re.IGNORECASE)]
    return {"found": found, "count": len(found), "coverage": len(found) / len(expected)}


def text_metrics(text: str, domain_patterns: list[str] | None = None) -> dict[str, Any]:
    """Everything measurable from a loose string, without opening a PDF."""
    domain = domain_coverage(text, domain_patterns)
    stop, words = stopword_ratio(text)
    return {
        "odd_char": round(odd_char_ratio(text), 4),
        "short_line": round(short_line_ratio(text), 4),
        "single_char_word": round(single_char_word_ratio(text), 4),
        "glyph_index": round(glyph_index_ratio(text), 4),
        "control_char": round(control_char_ratio(text), 4),
        "stopword": round(stop, 4),
        "alphabetic_words": words,
        "domain_coverage": round(domain["coverage"], 4),
        "domain_patterns": domain["count"],
        "chars": len(text),
    }
