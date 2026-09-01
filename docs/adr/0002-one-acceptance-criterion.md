# 0002 — There is one acceptance criterion

**Status:** accepted · **Relates to:** CLAUDE.md §2 · [Quality gates](../gates.md#the-acceptance-gate)

## Context

A cascade has two moments that look like different questions and are not:

1. the step asking *"did I solve this document?"*
2. the cascade asking *"is the next step worth paying for?"*

Implemented separately, they drifted. The step approved itself by one criterion
and the cascade refused it by another — so a document could be simultaneously
finished and inadequate, and which answer you saw depended on where you looked.

## Decision

`quality/gate.py::evaluate` answers both, and there is no second implementation.
It takes the text, the page profile and the thresholds, does no I/O, opens
nothing, and returns a `Verdict(escalate, reason)`.

The `Gate` protocol in `interfaces.py` is a contract about this rule as much as
about a signature: injecting a *replacement* gate is legitimate; adding a
**second acceptance gate** alongside the first is not.

## Consequences

- Every step calls the same function with the same `Config` numbers. A step that
  invents its own floor is a bug, not a feature.
- Because the gate is pure, calling it twice costs nothing — which is what makes
  a single criterion affordable in the first place.
- The gate returns a **sentence**, not a boolean. That sentence is what
  `Result.provenance` is made of. A gate returning a bare `bool` would satisfy
  the cascade and destroy the audit trail.
- The thresholds live in `Config` and nowhere else. The `Gate` protocol restates
  none of them, and
  `tests/contract/test_interfaces.py::test_the_gate_contract_repeats_no_threshold_of_its_own`
  enforces that — a protocol carrying a copy of a measured number is a second
  place for it to change.

## Evidence

The defect this prevents is the one it was extracted from: two competing notions
of "adequate extraction" in one pipeline, where the same document was accepted by
the step that produced it and refused by the cascade that consumed it. The four
questions `evaluate` asks are each backed by a measurement — most sharply the
word floor, from an audit of **1,339 documents** in which **403** had text that
looked fine and **227** contained only the conformity stamp.
