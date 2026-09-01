# 0003 — A missing engine is never an exception

**Status:** accepted · **Relates to:** CLAUDE.md §3

## Context

Engines are optional by construction: Apple Vision exists only on macOS,
Tesseract needs a binary on the `PATH`, OnnxTR needs an extra. Any of them can be
absent, and the absence can also be an *accident* — an image built for another
platform, an install with `--no-deps`, a lockfile for another `sys_platform`, an
incomplete `pyobjc`.

Two wrong answers were available. Raising turns a missing optional dependency
into a dead pipeline. Treating the missing engine's silence as a reading turns
"I have no OCR" into "the page is empty", which switches the pipeline off without
saying so.

## Decision

`available()` returns `(can_run, reason)` and **never raises**. A step whose
engine is unavailable goes **inert** and the cascade moves on. The reason is a
sentence in words, and it travels to two places: `Result.provenance` and
`autosxtract diagnose`.

The same rule applies to the witness: `read_document` answering `None` means
*"I don't know"* and skips the vetoes that depend on it. It never becomes "there
is no text".

## Consequences

- `Cascade.extract` never raises for a missing engine or an unreadable PDF. It
  returns an empty `Result` that explains itself. A caller that needs an
  exception must check `result.empty` and raise its own.
- **Degrading without breaking is right; degrading without warning is not.** The
  reason string is not decoration — it is the entire mechanism by which somebody
  discovers that their scanned PDF came out empty because `pyobjc` is broken.
- Anything that can fail belongs in `_load`, whose exception message becomes the
  reason. `available()` itself must have nothing to throw.
- This is why the platform decides **twice**: a marker at `pip install` time and
  the registry at runtime. The first guarantees the common case; the second is
  what makes the uncommon one degrade instead of crash.

## Evidence

`autosxtract diagnose` on a default Linux install reports each absent engine with
its reason and the extra that installs it — `onnx unavailable: No module named
'onnxtr'; install with pip install autosxtract[onnx]`. The failure mode this
replaces is unmeasurable by construction, which is the point: an engine treated
as evidence about the document produces a plausible empty result and no signal at
all.
