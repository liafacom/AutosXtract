# 0011 — No real document in the repository

**Status:** accepted · **Relates to:** CLAUDE.md §9 · [Testing](../testing.md#no-real-document-ever)

## Context

This library was built against real case files. The obvious way to test a PDF
pipeline is to commit a few PDFs that reproduce the interesting failures, and
every one of those documents contains personal data.

There is a second, less obvious problem: a test that depends on one archived file
tells you *that file* broke. It does not tell you what in the code did.

## Decision

**No real document enters the repository.** The fixtures are generated on the fly
by PyMuPDF with invented text (`tests/conftest.py`), and `.gitignore` blocks
`*.pdf` at the root.

The rule extends to **identifiers inside comments and docstrings**. Examples use
numbers with a deliberately **invalid** check digit, so the scanner stays quiet
and nobody has to decide case by case whether a number exists.

`scripts/privacy_check.py` runs as the **first** pre-commit hook — before the
style ones — and on every CI push. It validates tax IDs, company IDs and case
numbers by their **check digit**, not by their shape.

## Consequences

- A failing test points at the code, not at one archive file. If a bug cannot be
  reproduced synthetically, usually the document's *shape* is what matters — a
  large image in a region with no text, a rotated page, a stamp band — and that
  is buildable.
- **Precision matters more than raw recall**, because a scanner that shouts at
  every fourteen-digit number gets switched off in the first week, and then it
  reports nothing at all.
- The hook order is deliberate: a commit blocked on formatting costs thirty
  seconds; a real document published has no undo.
- One trap that has cost time: `pre-commit` stashes unstaged changes before
  running. It inspects **what will be committed**, not the working tree — fixing
  a file without `git add` leaves the hook looking at the old version.

## Evidence

The scanner has already paid for itself: it caught **a real case number, with a
valid check digit, that had made its way into this library's own examples.**
