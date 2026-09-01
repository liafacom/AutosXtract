# 0006 — PyMuPDF is serialised by a process lock

**Status:** accepted · **Relates to:** CLAUDE.md §6

## Context

The obvious way to speed up a page-level pipeline is to render pages in parallel.
PyMuPDF does not survive it: it **crashes the process** with several threads —
a segfault in `page_get_textpage`.

`try/except` does not protect you. A segmentation fault is not a Python
exception, so the failure is not a bad result, it is the worker disappearing.

## Decision

Every access to PyMuPDF goes through `pdf/lock.py`. The useful parallelism is
**per document**, not per page inside the PDF layer.

The same applies to `get_image_rects` / `get_image_info`: `pdf/coverage.py` uses a
single `get_text("dict")` traversal precisely because the per-image version
segfaulted under concurrency.

## Consequences

- `Cascade.extract_batch` parallelises across documents. `page_parallelism`
  governs the **OCR engine**, not PyMuPDF, and the configuration says so.
- Any new code touching PyMuPDF must go through the lock. It is not a
  performance decision that can be revisited locally: one unlocked call is enough
  to bring the process down under load.
- `Renderer` is an injectable protocol partly because of this — a step can be
  driven over invented pixels without PyMuPDF opening anything, which is what
  makes most of the suite runnable at all.

## Evidence

The crash: reproduced with **489 PDFs across 12 threads**, captured with
`faulthandler`, a segfault in `page_get_textpage`.

The cost of serialising, measured: **37.2 s with 4 threads against 38.6 s with
24** — about **4%**. That is the whole price, and it buys a process that does not
die.
