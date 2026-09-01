# 0007 — Engine confidence does not arbitrate quality

**Status:** accepted · **Relates to:** CLAUDE.md §7

## Context

Every OCR engine reports a confidence, and it is the most tempting number in the
pipeline: it is free, it is per page, and it looks like exactly the signal a
cascade needs in order to decide whether to escalate.

It was audited against human judgement, and it does not carry that meaning.

## Decision

Confidence enters as a **floor against degenerate output** (`min_confidence`,
default 70) and never as a criterion for quality. The
[acceptance gate](../gates.md#the-acceptance-gate) decides, from the text.

The rule is written into the `Engine` protocol itself, because it is a constraint
on engine authors as much as on the cascade: do not build logic on your own
confidence, and do not suppress low-confidence lines before returning them. The
cascade wants the reading; the judging happens elsewhere and in one place.

## Consequences

- An engine reporting no meaningful confidence is still a perfectly good engine.
- The contest between candidates is settled by `score × log(1 + volume)` from
  `quality/scoring.py`, never by the engine's own opinion of itself.
- `Line.score` is on a 0–1 scale while `transcribe_page` returns 0–100, and
  mixing them is silent: an engine that puts 96.0 on a `Line` makes every line
  look perfect and Layer 1 stops containing anything.
- The `mean_confidence` on a `Transcription` remains in the provenance. It is
  reported because it is *informative*, and ignored because it is not
  *decisive* — and those are different things.

## Evidence

Measured on **60 documents audited by four reviewers**: engine confidence did not
separate a good reading from an unsafe one. **There was an unsafe document at
confidence 100.**
