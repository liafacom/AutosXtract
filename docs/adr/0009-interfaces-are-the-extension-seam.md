# 0009 — Interfaces are the extension seam

**Status:** accepted · [The interfaces](../interfaces.md)

## Context

The library advertised two extension points — an engine and a step — and the
advertisement was true only by convention. The contracts existed as docstrings on
base classes, spread across the modules that happened to consume them, and
nothing checked that they still described what the code required.

They had already drifted. The `Engine` contract declared
`transcribe(pages, *, parallelism)` while `OCRStep` had been passing
`force_parallelism` for months. **Nothing failed, because nothing looked** — and
an engine written to the published contract would have crashed on its first
document.

## Decision

Every collaboration in the library is declared once, in
`autosxtract/interfaces.py`: eleven `typing.Protocol` objects, all
`@runtime_checkable`, all re-exported from the package root.

A subsystem talks to another through a name declared there, not through an import
of the class that happens to implement it today.

## Consequences

- **They are structural.** An implementation does not inherit from them — a class
  satisfies a contract by having the methods. That is what let
  `quality.stamp.Stamp`, written long before the file existed, become a
  `StampStripper` without one line of it changing. Requiring inheritance would
  have made the same refactor a rewrite.
- **The module imports nothing at runtime.** Every name arrives under
  `TYPE_CHECKING`, so importing a contract never drags in what implements it.
  That is what puts `interfaces` below all five layers of CLAUDE.md §10 while
  depending on none of them, and it makes the layering a fact rather than a
  convention.
- **They are checked, or they are comments.** `tests/contract/test_interfaces.py`
  asserts every shipped implementation still satisfies its protocol, by
  `isinstance` *and by signature*, and drives a hand-written fake that implements
  only the protocol — no base class, no import of the concrete thing — through
  the real cascade. A claim about extensibility is only true if somebody has
  extended it from the outside.
- **What is absent from a protocol is part of it.** `DocumentContext` withholds
  `readings` and `texts` because those are the evidence the consensus and
  agreement gates decide on; a step reaching into them would decide on evidence
  it did not gather. A test asserts they stay off.
- A protocol restates no measured threshold. `Gate`'s defaults are checked
  against `evaluate`'s, because a copy is a second place for a number to change.
- Extra work: an engine that grows a parameter now has to grow it in two places.
  That cost is the entire point — the second place is where anybody outside the
  library reads what is required.

## Evidence

The drift itself: `transcribe(pages, *, parallelism)` published, `force_parallelism`
required. It survived months and a full test suite, because the contract and the
call site were different files and neither referred to the other.

The payoff, in the suite: a **ten-line** engine and a **twenty-line** context,
inheriting nothing, run the real cascade end to end. Before them, exercising a
step meant a real PDF, PyMuPDF and a profile read off disk — which is to say
never on a CI runner.
