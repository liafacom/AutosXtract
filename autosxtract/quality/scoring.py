"""From a set of metrics to the number between 0 and 1 that settles the contest.

The score is a sum of penalties against 1.0, and every penalty carries its
reason in words — because the number alone is not auditable. Whoever reads the
result must be able to answer "why was this step refused?" without reading code.

Three families, deliberately separate:

``_form``            odd characters, short lines, fragmented words
``_plausibility``    glyph index, broken encoding, no Portuguese at all
``_domain``          expected vocabulary — the only one that can ADD

They are separate because the native step's score has a fourth family (density
and empty pages) that OCR engines do not have: they return no page structure.
Sharing the first three keeps both paths comparable.
"""

from __future__ import annotations

from typing import Any

from autosxtract.quality.metrics import MIN_WORDS_TO_JUDGE, text_metrics


def _form(m: dict[str, Any]) -> tuple[float, list[str]]:
    delta = 0.0
    reasons: list[str] = []

    if m["odd_char"] > 0.15:
        delta -= 0.30
        reasons.append("High rate of odd characters.")
    elif m["odd_char"] > 0.05:
        delta -= 0.15
        reasons.append("Moderate rate of odd characters.")

    if m["short_line"] > 0.60:
        delta -= 0.20
        reasons.append("Many short lines; layout may have broken badly.")
    elif m["short_line"] > 0.40:
        delta -= 0.10
        reasons.append("A notable number of short lines.")

    if m["single_char_word"] > 0.20:
        delta -= 0.20
        reasons.append("Many one-character words; possible fragmentation.")
    elif m["single_char_word"] > 0.10:
        delta -= 0.10
        reasons.append("Some word fragmentation.")

    return delta, reasons


def _plausibility(m: dict[str, Any]) -> tuple[float, list[str]]:
    """ "Is this even readable text?"

    Without this family, a glyph index and a broken encoding scored high enough
    to win the cascade's contest and be persisted as if they were content.
    """
    delta = 0.0
    reasons: list[str] = []

    glyph = m.get("glyph_index", 0.0)
    if glyph > 0.30:
        delta -= 0.60
        reasons.append("Text is a glyph index, not content (font without ToUnicode).")
    elif glyph > 0.10:
        delta -= 0.30
        reasons.append("Stretches of glyph index in the text.")

    if m.get("control_char", 0.0) > 0.05:
        delta -= 0.40
        reasons.append("High rate of control bytes; broken encoding.")

    # Only judge plausibility when there is enough prose. Tables, forms and
    # record cards pass unpunished — the absence of function words is expected
    # there.
    stop = m.get("stopword")
    words = m.get("alphabetic_words", 0)
    if stop is not None and words >= MIN_WORDS_TO_JUDGE:
        if stop < 0.02:
            delta -= 0.45
            reasons.append("No function words at all; text is unreadable.")
        elif stop < 0.08:
            delta -= 0.25
            reasons.append("Very few function words; transcription is probably poor.")

    return delta, reasons


def _domain(m: dict[str, Any]) -> tuple[float, list[str]]:
    coverage = m.get("domain_coverage", 0.0)
    if coverage < 0.03:
        return -0.15, ["Few domain patterns detected."]
    if coverage > 0.10:
        return 0.05, ["Good presence of the expected domain patterns."]
    return 0.0, []


def _label(score: float) -> str:
    if score >= 0.75:
        return "good"
    if score >= 0.50:
        return "fair"
    return "poor"


def score_text(text: str, domain_patterns: list[str] | None = None) -> dict[str, Any]:
    """Score a loose string. This is the criterion applied to EVERY OCR step.

    Empty text scores ``0.0`` explicitly — without that, the three "degenerate
    text" reasons would add up to only -0.85 and an empty string would come out
    at 0.15, competing with real text.
    """
    m = text_metrics(text, domain_patterns)
    if not (text or "").strip():
        return {"score": 0.0, "label": "poor", "reasons": ["Empty text."], "metrics": m}

    d1, r1 = _form(m)
    d2, r2 = _plausibility(m)
    d3, r3 = _domain(m)
    score = max(0.0, min(1.0, 1.0 + d1 + d2 + d3))
    return {"score": round(score, 4), "label": _label(score), "reasons": r1 + r2 + r3, "metrics": m}


def score_structure(
    text: str, pages: list[dict[str, Any]], domain_patterns: list[str] | None = None
) -> dict[str, Any]:
    """Score the native text, which comes with page structure.

    The order of the reasons is density -> form -> plausibility -> empty pages
    -> domain -> fragmentation, and it is stable on purpose: whoever reads the
    log compares runs.
    """
    m = text_metrics(text, domain_patterns)
    n = len(pages) or 1
    m["pages"] = len(pages)
    m["chars_per_page"] = round(sum(p["chars"] for p in pages) / n, 2)
    m["empty_pages"] = round(sum(1 for p in pages if p["chars"] < 50) / n, 4)
    total_words = sum(p["words"] for p in pages)
    m["fragmentation"] = round(
        (sum(p["blocks"] for p in pages) / total_words) if total_words else 1.0, 4
    )

    score = 1.0
    reasons: list[str] = []

    if m["chars_per_page"] < 50:
        score -= 0.45
        reasons.append("Very little text per page; the PDF is probably scanned.")
    elif m["chars_per_page"] < 300:
        score -= 0.25
        reasons.append("Low text density per page.")

    d, r = _form(m)
    score += d
    reasons += r
    d, r = _plausibility(m)
    score += d
    reasons += r

    if m["empty_pages"] > 0.30:
        score -= 0.30
        reasons.append("Many nearly empty pages.")
    elif m["empty_pages"] > 0.10:
        score -= 0.15
        reasons.append("Some nearly empty pages.")

    d, r = _domain(m)
    score += d
    reasons += r

    if m["fragmentation"] > 0.08:
        score -= 0.10
        reasons.append("Text may be heavily fragmented into blocks.")

    score = max(0.0, min(1.0, score))
    return {"score": round(score, 4), "label": _label(score), "reasons": reasons, "metrics": m}
