# AutosXtract — project rules

This file is for whoever touches the code (person or agent). It records the
decisions that are **not** obvious from the code and that have already cost
something once.

## 1. The default cascade does no networking, and networking is never accidental

`Cascade()` assembles local steps only, and nothing it assembles opens a socket.
Everything in the package that CAN reach the network is listed here. The list is
exhaustive on purpose: an audit of this invariant is a grep for `httpx`, and a
file that turns up in that grep and is not named below is either a defect or a
line somebody forgot to add.

- `engines/models.py` downloads the PP-OCRv6 weights **once**, and extraction
  works without it (falling back to rapidocr's embedded model).
- `steps/remote.py` brings `DoclingStep` and `VLMStep`, which **require `url` in
  the constructor**. They are not in the default cascade, there is no discovery
  through an environment variable, no built-in default and no fallback to a
  known endpoint.
- `engines/worker.py` brings `VisionWorkerEngine` — an **engine** that speaks
  HTTP, which is why it needs saying out loud. Same constructor rule (`url`
  mandatory), plus one more: it is deliberately absent from the registration
  imports in `engines/__init__.py`, so `engine_order()` can never select it and
  no cascade can acquire it by accident. It exists because on Linux there is no
  other way to reach Apple Vision, and reaching Vision over a tunnel is
  literally the incident below — which is why the guard is one layer stricter
  than for a remote *step*.
- `engines/paddle.py` and `engines/onnx.py` fetch model weights from Hugging Face
  on first load when their heavier backends are installed (`_load_paddleocr`
  sets `PADDLE_PDX_MODEL_SOURCE`; `onnxtr` fetches its pretrained weights). Same
  class of traffic as `models.py` — weights, once, not document content — but it
  happens outside `models.py`, so an audit that only watched that file would
  miss it.

`steps/docling_local.py` is the useful counterexample: the same engine as
`DoclingStep`, with no networking at all. It stays out of the default cascade
for a **different** reason — it weighs ~2 GB of models and ~4 s per document —
and that is why it lives outside `remote.py`. Confusing "expensive" with
"remote" would make this paragraph's invariant meaningless.

This is not a preference: the previous version of this pipeline reached the OCR
engine on a Mac over a reverse SSH tunnel, and that worker going down
**silently degraded the text** — 488 documents re-extracted down the worse path,
19.5 min instead of 4.9, 28,239 characters lost, and nobody noticed until
someone checked. A remote step nobody declared must not exist.

The corollary that holds the rest together: **`Config` has not a single host,
port, URL or credential field.** All networking lives in the constructor of a
step somebody wrote by hand. `tests/unit/test_config.py::test_no_field_points_at_a_network`,
`tests/unit/test_remote_steps.py` and `tests/integration/test_remote.py` are the
guard rails.

## 2. One acceptance criterion

`quality/gate.py::evaluate` decides, for every step, whether the text suffices.
Whoever decides the current step solved it and whoever decides the next one is
worth paying for ask the same question, with the same code.

Two competing notions of "adequate extraction" in one pipeline was the defect
this function exists to avoid repeating: the step approved itself by one
criterion and the cascade refused it by another.

## 3. A missing engine is never an exception

`available()` returns `(False, reason)`, the step goes inert and the cascade
moves on. **The absence of a tool is not evidence about the document** —
treating "I have no OCR" as "the page is empty" switches the pipeline off in
silence.

Corollary: degrading without breaking is right; degrading without warning is
not. Every reason goes to the provenance and to `autosxtract diagnose`.

## 4. Two different gates, and the difference is what happens to the refused

**Acceptance gate** (`quality/gate.py`): "is this text good enough to stop the
cascade?". Something refused here **stays in the contest** — it may be the best
reading there is.

**Replacement gate** (`quality/rejection.py`): runs only after an `expensive`
step and asks "is it better than what I already had, and did it lose nothing?".
Something refused here is **discarded**. Letting it compete would cancel the
gate, because volume is usually on the wrong side: the corrupted text is
precisely the longest one.

Confusing the two is the easy mistake. The first compares against a threshold;
the second compares against a concrete text and has already concluded the new
one is worse.

## 5. Refused text still competes

`StepResult` separates the **verdict** (does the cascade stop?) from the
**candidate** (does the text enter the contest?). A refused step may have
produced the best reading there is. Discarding it left 682 documents with zero
characters while the PDF had a text layer.

## 6. PyMuPDF is serialised, and that is not negotiable

It **crashes the process** with several threads: a segfault in
`page_get_textpage`, captured with `faulthandler` and reproduced with 489 PDFs
across 12 threads. `try/except` does not protect you — a segmentation fault is
not a Python exception.

Every access goes through `pdf/lock.py`. The measured cost is ~4% (37.2 s with 4
threads against 38.6 s with 24). The useful parallelism is **per document**.

The same goes for `get_image_rects` / `get_image_info`: `pdf/coverage.py` uses a
single `get_text("dict")` traversal precisely because the per-image version
segfaulted under concurrency.

## 7. Engine confidence does not arbitrate quality

Measured on 60 documents audited by four reviewers: engine confidence does not
separate a good reading from an unsafe one — there was an unsafe document at
confidence 100. It enters only as a floor against degenerate output, never as a
criterion.

## 8. Measured numbers go in the comment

Every threshold in `config.py` carries the measurement that fixed it. Changing a
number without measuring is the mistake this project tries to make difficult.

And the methodological lesson, which is worth more than any specific number: **an
isolated measurement has already lied here.** Turning off Vision's language
correction improved anchors across 60 documents (+4) and worsened them across
the whole cascade (−227), because the worse text failed the gate and fell to
worse engines. What decides is the cascade's behaviour, not one engine's output.
Use `scripts/compare_engines.py`, which measures both.

A time carries its machine, always. A latency, a throughput or a "6.2 min
against 4.44" without the hardware behind it is not falsifiable, and the reader
is right to ignore it. The reference environment is
`docs/architecture.md`'s "The machine every number was measured on": 2 × Xeon
E5-2699 v3 (72 logical cores, dual socket, Debian 13) for everything on Linux,
and a fanless MacBook Air M5 for Vision. No discrete GPU and no CUDA path
anywhere in the package — except Apple Vision, which runs on the Neural Engine
and is exactly why "everything was measured on CPU" is the convenient sentence
and the wrong one. A number measured elsewhere names its own machine on the spot.

## 9. No real document in the repository

The fixtures are generated on the fly by PyMuPDF, with invented text
(`tests/conftest.py`). `.gitignore` blocks `*.pdf` at the root. A failing test
must point at the code, not at one specific archive file.

That applies to **identifiers inside comments and docstrings** too. Documenting a
measurement with the case number it was made on looks harmless and is not:
`scripts/privacy_check.py` caught a real case number that had made its way into
the examples here, with a valid check digit. The examples use numbers with an
**invalid** check digit on purpose — that way the scanner stays quiet and nobody
has to decide case by case whether a number exists.

The scanner runs in `pre-commit` (the first hook, before the style ones) and on
every CI push. It validates tax IDs, company IDs and case numbers by their check
digit: precision matters more than raw recall, because a noisy scanner gets
switched off.

Watch out for one trap: `pre-commit` stashes unstaged changes before running. It
inspects **what will be committed**, not what is in your working tree — fixing a
file without `git add` leaves the hook looking at the old version.

## 10. Layers

```
pdf/         knows only the file    — does not know what an engine is
quality/     knows only text        — does no I/O
engines/     reads pixels           — does not know what a cascade is
steps/       composes the two       — does not know which engine is behind it
cascade.py   orchestrates
```

If an import crosses the arrow backwards, the design has broken. It was that
boundary that let the OCR step be **a single one**, generic, for Vision and
PP-OCRv6 alike.

## 11. The platform decides twice, and both are necessary

    install    a PEP 508 marker in `pyproject.toml`, evaluated by pip
    runtime    `platform.py` plus the registry in `engines/base.py`

The first makes `pip install autosxtract` bring Vision on macOS and PP-OCRv6
elsewhere, with no extra. The second is what stops the library from blowing up
when the marker did not match — an image built for another platform,
`--no-deps`, a lockfile for another `sys_platform`, an incomplete pyobjc.

A temptation to resist: deleting the second layer because "the first already
guarantees it". It does not guarantee it — it guarantees the common case.
`tests/packaging/test_packaging.py` pins the first;
`tests/integration/test_shipped_engines.py` pins the second.

## 12. English in the code, Portuguese in the patterns

Names, docstrings and messages are in English, so the library is usable outside
Brazil. The **regexes and word lists stay in Portuguese**, because they describe
the corpus: the conformity stamp, the enclitic pronouns, the abbreviations, the
identity-card markers, the legal vocabulary of the lexicon.

That is the adaptation seam, and it is a **TOML pattern pack**, not four Python
modules. The regexes used to live as `re.compile` calls in ten files, which made
"swap the patterns" a claim the code could not honour — it meant editing Python
in ten places and hoping the tests noticed. They are data now:

    autosxtract/patterns/data/base.toml    nothing that describes a language
    autosxtract/patterns/data/pt_br.toml   the corpus this library was measured on

Resolution, most specific first: `Config.patterns` -> `AUTOSXTRACT_PATTERNS` ->
the bundled pack chosen by `Config.language` -> `base`. A user pack overrides
**entry by entry** and the bundled packs stay underneath, so a pack that
redefines one stamp is a legitimate, complete pack — it never restates the other
sixty-five, and it keeps receiving their fixes. File-level merging would force a
copy, and a copy is a fork that stops receiving fixes.

Two rules follow, and a review checks both. Every entry carries the measurement
that fixed it in its `why` field: that text travelled here from the code with
the pattern, and an entry whose `why` no longer holds is an entry to **delete**,
not to adjust in silence. And `base.toml` describes no language — the moment a
Portuguese word appears there, the layering stops meaning anything and the seam
is closed again. Writing `re.compile` with a domain word inside `quality/` is
now a design regression, not a style question.

The lexicon is the other half of the same seam and behaves the same way:
`Config.lexicon` takes any `LexiconLike`, and the built-in word list is a floor,
not a truth.

**And where a CONTRACT is declared: `interfaces.py`.** Patterns externalise the
data; `interfaces.py` externalises the collaborations. A subsystem talks to
another through a name declared there, not through an import of the class that
happens to implement it today. Everything in it is a structural `Protocol` — an
implementation inherits nothing, it merely has the methods — and the module
imports nothing at runtime, which is what keeps it below all five layers of
section 10. If you are adding an extension point, or discover that a
collaboration is only written down in a docstring, that is where it goes.
`tests/contract/test_interfaces.py` is what stops it becoming a comment: it had
already drifted once, publishing `transcribe(pages, *, parallelism)` while
`OCRStep` had been passing `force_parallelism` for months, and nothing failed
because nothing looked.

## 13. What runs BEFORE the expensive step

`quality/vetoes.py` holds the five vetoes, and the order is by rising cost:
pixel statistics at 40 DPI (ms), then a real local OCR (~1 s), then comparing
text already read (free).

Two warnings that have already cost time:

- **The first two are only valid together with "extracted no text".** On their
  own they would discard an old photocopy on dark paper, which is continuous
  tone and carries thousands of legitimate characters (measured: 0.99 / 0.99 /
  0.83 mid-tone with 1,001, 2,612 and 632 characters).
- **The witness has to be of another architecture.** A second engine of the same
  family is not independent evidence, and the agreement veto stops meaning what
  it says. That is why `veto_engine` points at Tesseract and not at a second
  PP-OCR.

`local_reading=None` means "I don't know" and skips the last three vetoes. It
never becomes "there is no text".

## 14. Parallelism is decided by the machine, not by the code

The three fields accept `None` = "decide here", and that is the default. An
explicit number is obeyed; what it is not, is a promise.

    threads   72 cores     2 cores
       1       1.36 pg/s   1.44 pg/s
       2       1.74        1.68     <- plateau
       4       1.99        1.58
       8       2.18        1.54     <- worse than 2 threads
      16       2.27        1.71

Three things that have bitten and are pinned in code:

- **`os.cpu_count()` lies inside a container.** It reports the host, not the
  quota. `resources.cores()` crosses affinity, cgroup v1/v2 and `cpu_count` and
  keeps the smallest — none of the three alone covers `taskset` AND `--cpus`.
- **The product multiplies silently.** `documents × pages` reaches 32 pages in
  flight from values that look modest. The aggregate cap cuts the PAGES, never
  the documents: cutting documents raises total time predictably, cutting pages
  costs almost nothing.
- **The engine has the last word.** Whoever configures the cascade does not know
  whether a hardware queue sits behind it. `OCREngine.scales_with_threads =
  False` makes the engine use 1 thread, and `OCRStep` records the effective
  value in the provenance when it differs from the requested one — clamping
  silently would be the same antipattern as section 1.

Resolution is a **method**, not a field computed in the constructor: the machine
that resolves may not be the one that serialised the configuration.

## 15. The engine contract has two levels, and the detailed one is optional

`transcribe_page` returns `(text, confidence)`; `read_page` returns it line by
line, with polygon and score. The second is **optional** — `None` is the honest
answer from an engine without geometry, and the cascade falls back to the first.

Except that without it there are no containment layers, and they are the
pipeline's cheapest measured gain (entity recall 0.902 → 0.921, and latency
FALLS). When writing a new engine, implement the detailed contract if the
backend exposes geometry.

`Transcription.pages` is only filled when **every** page answered in detail. A
partial list would make the layers operate on a different document from the one
transcribed, and the page index would stop lining up.

## 16. Never reuse the main OCR instance to recognise a crop

Calling the main `rapidocr` with `use_det=False` turns detection off
**permanently on that object**. Measured: the next whole-page read returned 1
line where it had returned 56, and the document came out with 1 character
instead of 3,900.

The defect is of the worst kind — silent, order-dependent, and only visible from
the second page of the batch, because the first still uses a clean object. It
passed a whole test suite without showing; it only appeared on measuring
document by document.

`PaddleEngine._recognizer()` keeps a **separate** instance for Layer 2.
`tests/unit/test_paddle.py` pins that.

The general corollary: a third-party library with per-instance state is a shared
resource. If one path changes configuration, that path needs its own object.

## 17. A visual detector does not decide on its own

The signature detector (YOLO) was measured on a real archive: 19% of pages with
a detection, most of them **false positives** on seals, stamps, logos, QR codes
and coats of arms. A model that is good on a public benchmark can be useless in
your domain, and the way to find out is to run it on your archive, not to read
the mAP.

The answer was neither to throw the detector away nor to trust it: it was to
**cross it with the text**. A box only counts if some overlapping line is
illegible, and it is discarded if any overlapping line is stamp text. That is the
pattern to repeat whenever a visual signal enters the pipeline — alone it errs,
crossed with what is already known it helps.
