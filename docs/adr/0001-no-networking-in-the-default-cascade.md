# 0001 — The default cascade does no networking, and networking is never accidental

**Status:** accepted · **Relates to:** CLAUDE.md §1

## Context

An earlier version of this pipeline reached the OCR engine on a Mac over a
reverse SSH tunnel. The worker went down. Nothing raised, nothing logged, and
nothing in the output said so: the documents simply fell through to the next
step and were extracted by a worse engine.

The failure was invisible because a remote step that fails looks exactly like a
document that is hard to read.

## Decision

`Cascade()` assembles **local steps only**. No engine and no gate opens a socket.
There are exactly two exceptions and both are explicit:

- `engines/models.py` downloads the PP-OCRv6 weights **once**, and extraction
  works without it (falling back to rapidocr's embedded model).
- `steps/remote.py` brings `DoclingStep` and `VLMStep`, which **require `url` in
  the constructor**. There is no discovery through an environment variable, no
  built-in default and no fallback to a known endpoint.

The corollary that holds the rest together: **`Config` has not a single host,
port, URL or credential field.** All networking lives in the constructor of a
step somebody wrote by hand.

## Consequences

- Turning on a remote step is a code change, visible in review. It cannot be
  switched on by a configuration file, an environment variable or a deploy.
- `steps/docling_local.py` is the useful counterexample: the same engine as
  `DoclingStep`, with no networking at all. It stays out of the default cascade
  for a **different** reason — ~2 GB of models and ~4 s per document. Confusing
  "expensive" with "remote" would make this invariant meaningless, which is why
  it lives outside `remote.py`.
- A `token` never appears in a `repr`, a log or a result.
- `tests/unit/test_config.py::test_no_field_points_at_a_network` and the remote
  step tests are the guard rails. They fail on a *field name*, deliberately — the
  check has to be cheap enough to never be disabled.

## Evidence

The tunnel outage: **488 documents** re-extracted down the worse path, **19.5
minutes instead of 4.9**, **28,239 characters lost**, and nobody noticed until
someone checked by hand.
