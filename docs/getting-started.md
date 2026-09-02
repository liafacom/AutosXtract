# Getting started

## Install

```bash
pip install autosxtract
```

That is the whole installation on macOS, Linux and Windows. `pip` evaluates
platform markers **on the installing machine**, so the same command brings a
different engine on each system and you do not choose one:

| | macOS | Linux and Windows |
|---|---|---|
| OCR engine | Apple Vision, in-process | PP-OCRv6 tiny on ONNX |
| what `pip` brings | `pyobjc-framework-Vision` | — |
| always | `pymupdf`, `pydantic`, `numpy`, `pillow`, `opencv-python-headless`, `striprtf`, `asn1crypto`, `rapidocr`, `onnxruntime` | same |
| resulting cascade | `native → vision → paddle` | `native → paddle` |
| installed size | ~330 MB | ~570 MB |

PP-OCRv6 has **no marker**: it installs everywhere. On a Mac it is not Vision's
substitute, it is the step *below* it — the one that runs when Vision refuses a
page, and the second independent reading the [agreement gate](gates.md#agreement)
needs in order to fire at all. One engine can never confirm another.

Python 3.11 or newer. The first run off Apple hardware downloads ~10 MB of
PP-OCRv6 weights into `~/.cache/autosxtract`; after that the machine can stay
offline. For a closed environment, run `autosxtract download-models` where there
is network and point `AUTOSXTRACT_MODELS` at the copied directory.

### The extras, and what each buys

None is needed for ordinary use — your platform's engine already arrived. The
extras exist to ask for *the other* one, or for a capability the default cascade
deliberately leaves out.

| extra | what it installs | what it buys |
|---|---|---|
| `paddleocr` | `paddleocr` | the three official PP-OCRv6 tiers, INT8 weights and a fine-tuned recogniser. Without it the engine uses `rapidocr`, which serves the tiny tier and nothing else |
| `apple` | `ocrmac` (macOS only) | a safety net for Vision's direct path. An incomplete `pyobjc` breaks the in-process route; paying `ocrmac`'s ~61 ms round-trip beats dropping in quality |
| `veto` | `pytesseract` | Tesseract as the **witness** for vetoes 3 to 5. It must also be on the `PATH` (`apt install tesseract-ocr`, `brew install tesseract`). Without it those three vetoes are skipped and the expensive step is paid where it need not have been |
| `onnx` | `onnxtr` | a second cheap engine of a *different* architecture — which is what makes the [consensus gate](gates.md#consensus) worth anything |
| `remote` | `httpx` | the two steps that talk to a service. Installing turns nothing on: they exist only if you construct them with a `url` |
| `docling` | `docling` | Docling running **inside** the process, ~2 GB of models, no network |
| `paddle` | nothing new | kept so existing commands keep working; PP-OCRv6 is a mandatory dependency now |
| `all` | everything above that runs on this platform | |
| `dev` | pytest, ruff, mypy, pre-commit | the development toolchain |

```bash
pip install 'autosxtract[paddleocr]'    # to pick a model tier
pip install 'autosxtract[veto]'         # + the tesseract binary on PATH
```

## `autosxtract diagnose`, and how to read it

Run this **first**, and run it again whenever a result surprises you. When text
comes out worse than expected, the cause is almost always a missing engine, and
this is the only place that says which one and how to install it.

```bash
autosxtract diagnose
```

On a Linux box with the default install, verbatim (`rapidocr` writes its own
`INFO` lines to *stderr*; the report below is stdout):

```
autosxtract 0.5.0
machine    Linux (x86_64)
resources  72 usable core(s)
automatic parallelism: 4 page(s) per document, 4 document(s) in flight (aggregate cap 144)

engines:
  [ ] vision       vision requires Darwin  (single queue: ignores threads)
  [ ] ocrmac       ocrmac requires Darwin  (single queue: ignores threads)
  [x] paddle       PP-OCRv6 tiny
  [ ] onnx         onnx unavailable: No module named 'onnxtr'; install with pip install autosxtract[onnx]
  [ ] tesseract    tesseract unavailable: No module named 'pytesseract'; install with pip install autosxtract[veto]

cascade:   native -> paddle

models:    /home/you/.cache/autosxtract  (complete)
```

Line by line:

`resources`
:   How many cores the process can actually use, and the parallelism that
    resolves from it. Detection is the **most restrictive** of three sources,
    because none of them covers everything: `sched_getaffinity` (catches
    `taskset` and cpusets), the cgroup quota (catches `docker run --cpus=2`) and
    `os.cpu_count()`. **`os.cpu_count()` lies inside a container** — it reports
    the host, so a pod with 2 CPUs on a 72-core machine would open 72 threads to
    fight over 2. If this line says more cores than your quota, that is the bug
    to report.

`engines`
:   Every registered engine, with `[x]` for the ones that load here and a
    **reason in words** for the ones that do not. A reason is not a warning —
    it is the mechanism. An engine that will not load is not an exception, it is
    an inert step ([ADR 0003](adr/index.md#0003-a-missing-engine-is-never-an-exception)),
    and the reason travels into every `Result.provenance` as well.
    `(single queue: ignores threads)` marks an engine that declared
    `scales_with_threads = False`.

`cascade`
:   The steps this machine will actually run, in order. **If it says `native`
    alone, no OCR engine was installed** — a scanned PDF will come out empty,
    correctly and silently, and this is the only case where that happens. It
    means the platform marker did not match: an image built on a Mac and run on
    Linux, an install with `--no-deps`, or a lockfile generated for another
    `sys_platform`.

`models`
:   Where the PP-OCRv6 weights live and whether the set is complete.

## Your first extraction

Runnable as it stands — it builds its own PDF, so there is nothing to download
and no real document involved:

```python
import pymupdf
from autosxtract import Cascade

body = (
    "EXCELENTISSIMO SENHOR DOUTOR JUIZ DE DIREITO DA VARA CIVEL\n\n"
    "O requerente, nos autos do processo 0001234-56.2020.8.12.0001, vem "
    "respeitosamente a presenca de Vossa Excelencia expor e requerer o que "
    "segue. A decisao proferida nestes autos determinou a intimacao da parte "
    "executada para que se manifestasse no prazo legal, sob pena de preclusao."
)

doc = pymupdf.open()
page = doc.new_page()
page.insert_textbox(pymupdf.Rect(50, 50, 550, 380), body, fontsize=11)
pdf_bytes = doc.tobytes()
doc.close()

result = Cascade().extract(pdf_bytes, identifier="synthetic.pdf")

print(result.step)         # native
print(result.provenance)   # native: native(ok)
print(round(result.score, 2))
```

```
native
native: native(ok)
0.95
```

Instantiate `Cascade()` **once and reuse it**. Loading the models is the
dominant cost of the first call, and one cascade per document pays it on every
file.

```python
cascade = Cascade()
result = cascade.extract_file("document.pdf")             # one file on disk
results = cascade.extract_batch(["a.pdf", "b.pdf"])       # {name: Result}
```

`extract_batch` parallelises **per document**, not per page, and the aggregate
cap has already cut the per-document pages before the pool starts. See
[parallelism](configuration.md#engines-and-parallelism) for why.

From the terminal:

```bash
autosxtract extract document.pdf          # text on stdout, provenance on stderr
autosxtract extract *.pdf --json out.json
```

The split is deliberate: `autosxtract extract x.pdf > x.txt` gives you the text
and nothing else, while the provenance still reaches your terminal.

## Reading `Result.provenance`

This is the part worth learning properly, because it is what you will read every
time something is surprising.

```python
result = cascade.extract(pdf_bytes)
print(result.provenance)
```

```
paddle: native(no text layer) -> paddle(ok)
```

The shape is `winner: step(outcome) -> step(outcome) -> …`. Before the colon is
the step whose text **won the contest**; after it, every step that ran, in order,
each with `ok` or with the sentence explaining why it was refused.

That example is the scanned path: the native step found no text layer, PP-OCRv6
read the page and its text passed the acceptance gate.

!!! warning "The winner is not necessarily the last step"

    The cascade ends with a **contest**, not with the most recent reading. The
    candidate with the highest `quality × log(1 + volume)` wins. A refused step
    still enters that contest — refusing means "not good enough to *stop* here",
    not "throw this away". Discarding refused text left 682 documents with zero
    characters while the PDF had a text layer
    ([ADR 0004](adr/index.md#0004-refused-text-still-competes)).

For anything more than the one-line summary, walk the attempts:

```python
for attempt in result.attempts:
    print(attempt.step, attempt.accepted, attempt.reason, attempt.chars, attempt.ms)
```

Each `Attempt` carries `step`, `accepted`, `reason`, `chars`, `ms` and a
free-form `details` dictionary. Step names you will see that are not steps:

| name in the provenance | what happened |
|---|---|
| `veto:<name>` | a [veto](gates.md#the-five-vetoes) fired *before* an expensive step, which therefore never ran |
| `agreement_gate` | two engines read the same thing, so the reading was declared complete |
| `consensus_gate` | every engine read almost nothing; the result's `step` is `empty_by_consensus` |

`result.step` is `none` when nothing produced a candidate at all, and
`empty_by_consensus` when the engines agreed the page has no content. Those two
are different answers and the distinction is load-bearing: the first means the
cascade failed, the second means the document is blank.

The whole thing serialises:

```python
result.to_dict()   # text, step, score, ms, chars, provenance, attempts[...]
```

`details` carries whatever the winning step recorded — the OCR confidence, the
page count, and the [containment layers'](gates.md#the-containment-layers) report:

```python
result.details["layers"]
# {'lines_total': 6, 'lines_illegible': 0, 'lines_suspect': 0,
#  'lines_signature': 0, 'lines_vertical': 0, 'lines_recovered': 0,
#  'trusted_fraction': 1.0, 'needs_escalation': False,
#  'suggested_action': 'ok'}
```

## Next

- [Architecture](architecture.md) — what the five layers are and why the import
  direction matters.
- [Configuration](configuration.md) — every field, with the measurement that
  fixed its default.
