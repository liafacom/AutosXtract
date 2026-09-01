# 0004 — Refused text still competes

**Status:** accepted · **Relates to:** CLAUDE.md §5 · [Quality gates](../gates.md)

## Context

The naive cascade is: a step succeeds and returns text, or it fails and returns
nothing. That collapses two independent facts into one.

A step can produce text **and** be refused. "Refused" means *not good enough to
stop the cascade here* — it does not mean the text is worthless. If every later
step does worse, the refused text is the best reading the document has.

## Decision

`StepResult` has two fields:

```python
StepResult(attempt: Attempt, candidate: Candidate | None = None)
```

`attempt.accepted` is the **verdict**: does the cascade stop?
`candidate` is the **text**: does it enter the final contest?

A step fills `candidate` whenever it produced text, regardless of the verdict.
The cascade ends with a **contest** rather than with the last reading: the winner
is the candidate with the highest `score × log(1 + volume)`.

## Consequences

- The winner in `Result.provenance` is frequently not the last step that ran, and
  readers have to be told that.
- Every refused step also calls `DocumentContext.record_reading`, which is what
  makes the [consensus gate](../gates.md#consensus) mean "there is no text here"
  rather than "the engines that were accepted found nothing".
- The contest needs both dimensions. Volume alone lets a long unreadable OCR beat
  a short correct reading; quality alone lets a 14-character placeholder — clean
  precisely *because* it is short — beat the whole document. The logarithm damps
  volume so a candidate must be *much* larger to make up for worse quality.
- This rule does **not** apply after the replacement gate, and that exception is
  deliberate — see [ADR 0005](0005-the-replacement-gate-discards.md).

## Evidence

Discarding refused text left **682 documents with zero characters while the PDF
had a text layer** — **12.7%** of the documents that fell through the cascade.
