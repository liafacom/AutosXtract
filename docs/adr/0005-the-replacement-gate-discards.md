# 0005 — The replacement gate discards what it refuses

**Status:** accepted · **Relates to:** CLAUDE.md §4 · [Quality gates](../gates.md#the-replacement-gate)

## Context

[ADR 0004](0004-refused-text-still-competes.md) says refused text keeps
competing. Applied uniformly, that rule cancels the gate that runs after an
expensive step.

The reason is that the two gates ask different questions. The acceptance gate
compares against a **threshold**: "is this good enough to stop?". The replacement
gate compares against a **concrete earlier text**: "is it better than what I
already had, and did it lose nothing?" — and by the time it refuses, it has
already concluded the new text is worse or dangerous.

## Decision

Two gates, with opposite dispositions for what they refuse:

| | `quality/gate.py` | `quality/rejection.py` |
|---|---|---|
| question | good enough to **stop**? | better than what I **had**? |
| compares against | a threshold | a concrete text |
| runs | after every step | only after an `expensive` step |
| what happens to the refused | **stays in the contest** | **discarded** |

The replacement gate is deliberately **not** the `Gate` protocol, so the type
system does not invite anyone to swap one for the other.

## Consequences

- Letting a candidate refused here compete would cancel the gate, because
  **volume is usually on the wrong side: the corrupted text is precisely the
  longest one.**
- The gate is only valid while the previous text is a *trustworthy reference*.
  Four exemptions stand it down — a degenerate previous text, an explicitly
  untrustworthy one, an accepted truncation, and a new text that is
  incomparably richer per page. Without them the gate rejects exactly the
  document the expensive step exists to rescue.
- Everything it accepts *with reservations* records a **warning** in the
  provenance. Silence is what made the original loss undetectable.
- Length is the **last** check, not the first.

## Evidence

Length alone gets both of the costliest cases wrong:

- **Coverage.** A power of attorney transcribed up to page 10 of 15 is still
  longer than a bad extraction of all 15. It replaced it silently, and the
  document lost **three notarial acts**.
- **Fidelity.** `9XXYZ3ZE…` scores exactly like `9XXYZ32E…`. Length and text
  score are blind to a corrupted digit.

And an exemption measured in the other direction: **51,440 characters** were
being rejected for "losing" protocol numbers that were present only in the
previous step's **774 characters of header**.
