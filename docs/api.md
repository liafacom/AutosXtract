# Python API

Everything on this page is imported from the package root: `from autosxtract
import Cascade, Config, Result`. This is what you **receive**; the protocols you
would *implement* are in [the interfaces](interfaces.md).

## Running a cascade

```python
from autosxtract import Cascade, Config

cascade = Cascade()                                  # this machine's default
cascade = Cascade(Config(dpi=200))                   # configured
cascade = Cascade(config, steps=[NativeStep(), ...]) # assembled by hand
```

| | |
|---|---|
| `Cascade(config=None, steps=None)` | `steps=None` assembles this machine's cascade from the registry; passing a list overrides it entirely, including the platform rules. |
| `.names -> list[str]` | The assembled steps, in order. `['native', 'paddle']` on Linux. |
| `.extract(pdf_bytes, identifier="") -> Result` | An in-memory PDF. The identifier is for the provenance only. |
| `.extract_file(path) -> Result` | The file name becomes the identifier. |
| `.extract_batch(paths, *, parallelism=None) -> dict[str, Result]` | Keyed by file name. Parallel **per document** — it re-derives the per-document page budget from the aggregate cap, so `documents × pages` cannot grow unnoticed. |

**`extract` never raises** for a missing engine or an unreadable PDF: it returns
an empty `Result` whose provenance says what happened at each step. If your
caller needs an exception, check `result.empty` and raise your own.
`extract_file` does read the path first, so a file that is not there raises
`OSError` — the CLI catches it per file for exactly that reason.

There is also a module-level shortcut, which builds a fresh cascade on every
call — convenient in a script, expensive in a loop:

```python
from autosxtract import extract
result = extract("document.pdf")
```

## `Result`

```python
result.text          # str  — the winning text
result.step          # str  — which step produced it
result.score         # float | None
result.ms            # float
result.attempts      # list[Attempt]     — every step that ran, in order
result.discarded     # list[Candidate]   — texts that lost the contest
result.details       # dict              — merged into to_dict()
result.empty         # property: text is blank or whitespace
result.provenance    # property: the auditable sentence
```

**`result.step` and the last entry of `result.attempts` are frequently
different**, and that is the design, not a bug: a step may refuse itself and
still have produced the best reading there is
([ADR 0004](adr/index.md#0004-refused-text-still-competes)). The cascade ends
with a contest, and `provenance` prints both the winner and the path:

```
vision: native(quality 0.42 below 0.75) -> vision(ok)
```

`to_dict()` is the serialisable form — what goes to JSON, a log or a database,
and what `--json` writes:

```json
{
  "text": "Termo de encerramento lavrado nesta data.\n...",
  "step": "paddle",
  "score": 0.85,
  "ms": 423.6,
  "chars": 82,
  "provenance": "paddle: native(quality 0.50 below 0.75) -> paddle(ok)",
  "attempts": [
    {"step": "native", "accepted": false, "reason": "quality 0.50 below 0.75",
     "chars": 82, "ms": 20.5,
     "details": {"reasons": ["Low text density per page.",
                             "Few domain patterns detected."]}},
    {"step": "paddle", "accepted": true, "reason": "page with no visual content",
     "chars": 82, "ms": 399.2,
     "details": {"confidence": 98.4, "pages_sent": 1, "pages_answered": 1,
                 "layers": {"lines_total": 2, "lines_illegible": 0,
                            "trusted_fraction": 1.0, "suggested_action": "ok"}}}
  ],
  "confidence": 98.4,
  "pages": 1,
  "layers": {"lines_total": 2, "trusted_fraction": 1.0, "suggested_action": "ok"}
}
```

An `orientation` key joins `details` when the page was turned before the engine
saw it (`{"rotated": {3: 90}}`, by the document's page number) or when the
correction was asked for and could not run (`{"unavailable": "..."}`). Its
absence means an upright document, which is the common case.

Three things that surprise people reading this for the first time.
`result.details` is merged at the **top level**, not nested — `confidence`,
`pages` and `layers` above are the winning step's, promoted. `Attempt.details`
carries the *reasons* behind a refusal, which is where you look when a step you
expected to win did not. And `text` is **not** truncated while `discarded` is
**not** included at all: the losing candidates are debugging state, the winning
text is the product, and a batch of 500 documents produces a large file on
purpose.

## `Attempt` and `Candidate`

The two halves that [`StepResult`](interfaces.md#step) keeps separate — the
verdict and the text.

```python
Attempt(step, accepted, reason, chars=0, ms=0.0, details={})
Candidate(step, text, score, ms=0.0, details={})
```

`Attempt.reason` is a sentence in words, and it is the reason the provenance is
readable at all — `"quality 0.42 below 0.75"`, not `False`.
`Candidate.usefulness` is `score × log(1 + volume)`, the value the contest ranks
by; `Candidate.volume` is the character count after normalisation.

## What an engine returns

You only touch these when writing or calling an engine directly —
[a new engine](extending/engine.md) covers them in full.

```python
Transcription(text, engine, pages_sent=0, pages_answered=0,
              mean_confidence=0.0, ms=0.0, pages=[], page_texts=[], failures=[])
Page(lines=[], width=0.0, height=0.0)        # .text, .mean_confidence
Line(text, score=1.0, poly=None)             # .bbox
```

Two traps that have cost time. `Transcription.pages` is filled **only when every
page answered in detail** — a partial list would make the containment layers
operate on a different document from the one transcribed. And `Line.score` is
**0–1** while `transcribe_page` returns **0–100**; mixing the scales classifies
every line as trusted and silently stops the layers containing anything.

## Configuration

`Config` is a pydantic model with no host, port, URL or credential field —
[by decision](adr/index.md#0001-no-networking-in-the-default-cascade), not by
omission. Every threshold carries the measurement that fixed it, and the
[configuration reference](configuration.md) is generated from the model so the
number and its justification cannot drift apart.

The parallelism fields resolve through **methods**, not attributes:
`config.batch_concurrency()` and `config.pages_in_flight()` ask the machine at
call time, because the machine that resolves may not be the one that serialised
the configuration.

## Exceptions

Every one of them descends from `AutosXtractError`, so one `except` catches the
library.

| | raised when |
|---|---|
| `UnreadablePDF` | The bytes do not open as a PDF, not even after every attempt. |
| `EngineUnavailable` | An **explicitly named** engine is not installed or fails to load. An engine merely absent from the registry never raises — the step goes inert ([ADR 0003](adr/index.md#0003-a-missing-engine-is-never-an-exception)). |
| `UnknownEngine` | An engine name that is not in the registry. |
| `InvalidConfiguration` | A combination of parameters that does not describe a runnable cascade. |
| `UnreadableFormat` | An envelope was recognised but could not be opened ([stage 0](formats.md)). |
