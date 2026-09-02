# Decision records

Eleven decisions that are **not** obvious from the code and that have already
cost something once. Each carries the measurement that settled it — because a
decision without its evidence is an opinion, and an opinion is something the
next person reasonably overrules.

They exist for one reason: **the argument is more expensive than the code.** Any
of these can be undone in an afternoon. Reconstructing why it was made takes an
archive, a reviewer and a week, and in several cases here it took a silent
production failure first.

| # | decision | what it cost to learn |
|---|---|---|
| [0001](#0001-no-networking-in-the-default-cascade) | The default cascade does no networking, and networking is never accidental | 488 documents silently degraded |
| [0002](#0002-one-acceptance-criterion) | There is one acceptance criterion | 227 documents that were only a stamp |
| [0003](#0003-a-missing-engine-is-never-an-exception) | A missing engine is never an exception | a plausible empty result, no signal |
| [0004](#0004-refused-text-still-competes) | Refused text still competes | 682 documents at zero characters |
| [0005](#0005-the-replacement-gate-discards) | The replacement gate discards what it refuses | three notarial acts lost |
| [0006](#0006-pymupdf-is-serialised) | PyMuPDF is serialised by a process lock | a segfault across 12 threads |
| [0007](#0007-confidence-does-not-arbitrate-quality) | Engine confidence does not arbitrate quality | an unsafe document at confidence 100 |
| [0008](#0008-the-domain-patterns-are-data) | The domain patterns are data, not Python | a seam the code could not honour |
| [0009](#0009-interfaces-are-the-extension-seam) | Interfaces are the extension seam | a contract that drifted for months |
| [0010](#0010-parallelism-is-decided-by-the-machine) | Parallelism is decided by the machine, not by the code | 8 threads slower than 2 |
| [0011](#0011-no-real-document-in-the-repository) | No real document in the repository | a real case number in the examples |

Every timing quoted below comes from [the two machines listed in Architecture](../architecture.md#the-machine-every-number-was-measured-on) — a 72-core Xeon
with no GPU, and an Apple-silicon Mac whose Vision path runs on the Neural
Engine rather than the CPU.

The long form of each — the reasoning as it is written for whoever edits the
code — lives in [`CLAUDE.md`](https://github.com/liafacom/AutosXtract/blob/main/CLAUDE.md)
in the repository, section by section. What follows is the decision, what you
have to live with, and the evidence.

---

## 0001 — No networking in the default cascade

**Decision.** `Cascade()` assembles local steps only, and nothing it assembles
opens a socket for document content. The exceptions are exhaustive and all of
them are about **model weights, once**, or about a step you constructed by hand:

- `engines/models.py` downloads the PP-OCRv6 weights once; extraction works
  without it, falling back to rapidocr's embedded model.
- `engines/paddle.py` and `engines/onnx.py` fetch weights from Hugging Face on
  first load when their heavier backends are installed.
- `steps/remote.py` (`DoclingStep`, `VLMStep`) and `engines/worker.py`
  (`VisionWorkerEngine`) **require `url` in the constructor**. No discovery
  through an environment variable, no built-in default, no fallback endpoint.
  `VisionWorkerEngine` is additionally left out of the registration imports, so
  `engine_order()` can never select it.

The corollary that holds the rest together: **`Config` has not a single host,
port, URL or credential field.**

**Consequence.** Turning on a remote step is a code change, visible in review;
it cannot be switched on by a config file or a deploy. `steps/docling_local.py`
is the counterexample that keeps the invariant meaningful — the same engine, no
networking, still out of the default cascade for a *different* reason (~2 GB of
models, ~4 s per document). Confusing "expensive" with "remote" would empty this
record of content.

**Evidence.** An earlier version reached the OCR engine on a Mac over a reverse
SSH tunnel. The worker went down, nothing raised and nothing logged: **488
documents** re-extracted down the worse path, **19.5 minutes instead of 4.9**,
**28,239 characters lost**, unnoticed until someone checked by hand.

## 0002 — One acceptance criterion

**Decision.** `quality/gate.py::evaluate` answers both "did this step solve the
document?" and "is the next step worth paying for?", and there is no second
implementation. It takes the text, the page profile and the thresholds, does no
I/O and returns a `Verdict(escalate, reason)`.

**Consequence.** Injecting a *replacement* gate is legitimate; adding a second
**acceptance** gate alongside the first is not. A step that decides on its own
whether to escalate looks like a simplification and reintroduces the defect.

**Evidence.** Two competing notions of "adequate extraction" in one pipeline —
the same document accepted by the step that produced it and refused by the
cascade that consumed it. The four questions `evaluate` asks are each backed by a
measurement, most sharply the word floor: of **1,339 audited documents**, **403**
had text that looked fine and **227** contained only the conformity stamp.

## 0003 — A missing engine is never an exception

**Decision.** `available()` returns `(can_run, reason)` and never raises. A step
whose engine is unavailable goes **inert** and the cascade moves on. The reason
is a sentence in words and travels to two places: `Result.provenance` and
`autosxtract diagnose`. The same rule covers the witness — `read_document`
answering `None` means *"I don't know"* and skips the vetoes that depend on it;
it never becomes "there is no text".

**Consequence.** Degrading without breaking is right; degrading without warning
is not. Every reason has to reach the provenance, which is why a bare `bool`
verdict anywhere in `quality/` would break this.

**Evidence.** The failure mode being replaced is unmeasurable by construction,
and that is the point: an engine treated as evidence about the document produces
a plausible empty result and no signal at all. What replaces it is legible —
`onnx unavailable: No module named 'onnxtr'; install with pip install
autosxtract[onnx]`.

## 0004 — Refused text still competes

**Decision.** `StepResult(attempt, candidate=None)` separates the **verdict**
(`attempt.accepted` — does the cascade stop?) from the **text** (`candidate` —
does it enter the final contest?). A step fills `candidate` whenever it produced
text, regardless of the verdict, and the cascade ends with a contest rather than
with the last reading: the winner is the highest `score × log(1 + volume)`.

**Consequence.** The cascade can return text from a step that refused itself, so
`Result.step` and the last entry in `Result.attempts` are frequently different —
which is a feature, and the reason the provenance prints both.

**Evidence.** Discarding refused text left **682 documents with zero characters
while the PDF had a text layer** — **12.7%** of the documents that fell through.

## 0005 — The replacement gate discards

**Decision.** Two gates, with opposite dispositions for what they refuse:

| | `quality/gate.py` | `quality/rejection.py` |
|---|---|---|
| question | good enough to **stop**? | better than what I **had**? |
| compares against | a threshold | a concrete text |
| runs | after every step | only after an `expensive` step |
| the refused | **stays in the contest** | **discarded** |

The replacement gate is deliberately **not** the `Gate` protocol, so the type
system does not invite anyone to swap one for the other.

**Consequence.** Discarding is not optional here: letting the refused text
compete would cancel the gate, because volume is usually on the wrong side —
the corrupted text is precisely the longest one.

**Evidence.** Length alone gets both costly cases wrong. **Coverage:** a power of
attorney transcribed to page 10 of 15 is still longer than a bad extraction of
all 15 — it replaced it silently and the document lost **three notarial acts**.
**Fidelity:** `9XXYZ3ZE…` scores exactly like `9XXYZ32E…`. And an exemption
measured in the other direction: **51,440 characters** were being rejected for
"losing" protocol numbers present only in the previous step's **774 characters of
header**.

## 0006 — PyMuPDF is serialised

**Decision.** Every access to PyMuPDF goes through `pdf/lock.py`. The useful
parallelism is **per document**, never per page inside the PDF layer. The same
applies to `get_image_rects` / `get_image_info`: `pdf/coverage.py` uses a single
`get_text("dict")` traversal because the per-image version segfaulted under
concurrency.

**Consequence.** `try/except` does not protect you — a segmentation fault is not
a Python exception, so this cannot be handled after the fact, only prevented.

**Evidence.** The crash: **489 PDFs across 12 threads**, captured with
`faulthandler`, a segfault in `page_get_textpage`. The cost of serialising:
**37.2 s with 4 threads against 38.6 s with 24**, about **4%** — the whole price,
and it buys a process that does not die.

## 0007 — Confidence does not arbitrate quality

**Decision.** Engine confidence enters as a **floor against degenerate output**
(`min_confidence`, default 70) and never as a criterion for quality. The
[acceptance gate](../gates.md#the-acceptance-gate) decides, from the text.

**Consequence.** The rule constrains engine authors as much as the cascade: do
not build logic on your own confidence, and do not suppress low-confidence lines
before returning them. The cascade wants the reading; the judging happens
elsewhere, in one place.

**Evidence.** Measured on **60 documents audited by four reviewers**: confidence
did not separate a good reading from an unsafe one. **There was an unsafe
document at confidence 100.**

## 0008 — The domain patterns are data

**Decision.** The patterns are **data**: 66 entries in TOML under
`autosxtract/patterns/data/`, versioned with the package and layered.
`base.toml` describes no language; `pt_br.toml` is the corpus this library was
measured on. Resolution, most specific first: `Config.patterns` →
`AUTOSXTRACT_PATTERNS` → the bundled pack for `Config.language` → `base`.

**Consequence.** A user pack overrides **entry by entry** and the bundled packs
stay underneath, so a pack that redefines one stamp is legitimate and complete —
it never restates the other sixty-five and keeps receiving their fixes.
File-level merging would force a copy, and a copy is a fork that stops receiving
fixes. Writing `re.compile` with a domain word inside `quality/` is now a design
regression, not a style question. [How to write a pack →](../extending/patterns.md)

**Evidence.** The claim being repaired was structural rather than numeric: ten
modules held language-specific regexes, and the four the documentation named as
the "seam" were not all of them. The catalogue is 35 language-neutral entries
plus 31 Portuguese ones, and the count is the argument — the seam is checkable
now, and `tests/unit/test_patterns.py` checks it.

## 0009 — Interfaces are the extension seam

**Decision.** Every collaboration is declared once, in
`autosxtract/interfaces.py`: eleven `typing.Protocol` objects, all
`@runtime_checkable`, all re-exported from the package root. A subsystem talks to
another through a name declared there, not through an import of the class that
happens to implement it today. [The interfaces →](../interfaces.md)

**Consequence.** `interfaces.py` imports nothing at runtime, which is what keeps
it below all five layers of the architecture. An extension point that exists only
in a docstring belongs there instead.

**Evidence.** The drift: `transcribe(pages, *, parallelism)` published while
`force_parallelism` was required. It survived months and a full test suite,
because the contract and the call site were different files and neither referred
to the other. The payoff: a **ten-line** engine and a **twenty-line** context,
inheriting nothing, run the real cascade end to end — where before, exercising a
step meant a real PDF, PyMuPDF and a profile read off disk.

## 0010 — Parallelism is decided by the machine

**Decision.** `page_parallelism`, `document_parallelism` and `concurrency_cap`
accept `None`, meaning **decide from this machine**, and that is the default. An
explicit number is obeyed; what it is not, is a promise. Resolution is a
**method** (`config.pages_in_flight()`), not a field computed in the constructor:
the machine that resolves may not be the one that serialised the configuration.

**Consequence.** Three things follow. `os.cpu_count()` lies inside a container,
so `resources.cores()` crosses affinity, cgroup v1/v2 and `cpu_count` and keeps
the smallest. The product `documents × pages` multiplies silently, so the
aggregate cap cuts the **pages**, never the documents. And the engine has the
last word: `scales_with_threads = False` makes it use one thread, with the
effective value recorded in the provenance when it differs from the requested
one.

**Evidence.** PP-OCRv6 tiny, 12 real pages, the same machine restricted with
`taskset`:

| threads | 72 cores | 2 cores |
|---|---|---|
| 1 | 1.36 pg/s | 1.44 pg/s |
| 2 | 1.74 | **1.68** ← plateau |
| 4 | **1.99** | 1.58 |
| 8 | 2.18 | 1.54 ← worse than 2 threads |
| 16 | 2.27 | 1.71 |

Apple's Neural Engine, 1 to 12 threads: **constant throughput at ~2.5 pages/s,
latency from 430 ms to 3,492 ms.** A single hardware queue turns parallelism into
stacked waiting.

## 0011 — No real document in the repository

**Decision.** No real document enters the repository. The fixtures are generated
on the fly by PyMuPDF with invented text (`tests/conftest.py`), and `.gitignore`
blocks `*.pdf` at the root. The rule extends to **identifiers inside comments and
docstrings**: examples use numbers with a deliberately **invalid** check digit, so
the scanner stays quiet and nobody has to decide case by case whether a number
exists.

**Consequence.** `scripts/privacy_check.py` runs as the **first** pre-commit hook
— before the style ones — and on every CI push, validating tax IDs, company IDs
and case numbers by their **check digit** rather than their shape. Precision
matters more than recall: a noisy scanner gets switched off. One trap:
`pre-commit` stashes unstaged changes, so it inspects what will be committed, not
your working tree. [Testing →](../testing.md#no-real-document-ever)

**Evidence.** The scanner has already paid for itself: it caught **a real case
number, with a valid check digit, that had made its way into this library's own
examples.**

---

## Writing a new one

Add a section to this page, numbered sequentially, and a row to the table. Keep
the three parts: **Decision** (what was decided), **Consequence** (what you now
live with, including the inconvenient parts) and **Evidence** (the measurement).

If you cannot fill in **Evidence**, do not write the record. Write the
measurement first — otherwise it is a preference, and it does not belong here.

If you are **overturning** one, do not delete it. Add a record that supersedes it
and say so in both, with the measurement that changed. The value of this page is
that it holds the arguments that were already had, including the ones that turned
out to be wrong.
