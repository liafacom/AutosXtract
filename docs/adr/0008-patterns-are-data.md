# 0008 — The domain patterns are data, not Python

**Status:** accepted · **Supersedes:** the seam described in CLAUDE.md §12 before the catalogue existed · [How to write a pack](../extending/patterns.md)

## Context

The library reads Brazilian legal PDFs, and that fact was spread across **ten
modules** as `re.compile` calls: the conformity stamp, the enclitic pronouns, the
forensic abbreviations, the identity-card markers, the legal lexicon.

Each pattern was correct and each was measured. Between them they made a claim
the code could not honour — that adapting the library to another corpus was a
matter of swapping the patterns. It was not. It was a matter of editing Python in
ten files and hoping the test suite noticed.

The documentation said "swap `quality/stamp.py`, `lexicon.py`, `prose.py` and
`screening.py`". That is not a seam, it is a fork.

## Decision

The patterns are **data**: 66 entries in TOML under `autosxtract/patterns/data/`,
versioned with the package and layered.

```
base.toml     nothing that describes a language — control bytes, glyph-index
              runs, digit runs, markdown structure, homoglyphs
pt_br.toml    the corpus this library was measured on
```

Resolution, most specific first: `Config.patterns` → `AUTOSXTRACT_PATTERNS` →
the bundled pack for `Config.language` → `base`. A user pack overrides
**entry by entry**; the bundled packs stay underneath.

## Consequences

- **A pack that redefines one entry is a legitimate, complete pack.** File-level
  merging would force whoever wants a different stamp to copy the other
  sixty-five patterns, and *a copy is a fork that stops receiving fixes.*
- A pack overrides entries; it never removes them. Asking for a name nothing
  defines is an error that names the packs that were loaded.
- **TOML, not JSON.** `tomllib` is in the standard library from 3.11 — which this
  package already requires — so the catalogue costs **no new dependency**. Its
  literal strings carry a regex verbatim, with no escaping layer between what is
  written and what `re` compiles; a JSON catalogue would require doubling every
  backslash by hand, and a pattern that looks right and is wrong is the worst
  kind. And it takes comments.
- Every entry carries a `why` **parsed into the object**, not left as a comment,
  reachable through `patterns.why(name)`. That text travelled here from the code
  with the pattern. **An entry whose `why` no longer holds is an entry to delete,
  not to adjust in silence.**
- The whole catalogue compiles at resolution time — about sixty patterns, under a
  millisecond — so a malformed pack fails **at load**, naming the entry and the
  file, instead of in the middle of a batch.
- A language with no bundled pack falls back to the default one rather than
  raising. That is deliberate: before the catalogue existed the patterns were
  Portuguese whatever `Config.language` said, and raising would break a
  configuration that works today.
- New rule for reviewers: writing `re.compile` with a domain word inside
  `quality/` is now a **design regression**, not a style question.

## Evidence

The claim being repaired was structural rather than numeric: ten modules held
language-specific regexes, and the four the documentation named as the "seam"
were not all of them. The catalogue is 35 language-neutral entries plus 31
Portuguese ones, and the count is the argument — the seam is now checkable, and
`tests/unit/test_patterns.py` checks it.
