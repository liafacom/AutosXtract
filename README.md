# AutosXtract

Cascading text extraction from PDFs: **every document descends steps from the
cheapest to the most expensive and stops at the first one that produces
acceptable text.**

```bash
pip install autosxtract
```

```python
from autosxtract import Cascade

r = Cascade().extract_file("document.pdf")
print(r.text)
```

One command and one class, identical on macOS and Linux — the OCR engine arrives
already chosen by the machine, with no extra to memorise. Windows installs and
should behave like Linux (the same PP-OCRv6 step, no Vision), but no CI runner
exercises it and the PyPI classifiers do not claim it: treat it as unverified
rather than supported.

> Extraction **sends no document anywhere**. No worker, no tunnel, no
> third-party service. The only traffic is model weights on first load — the
> PP-OCRv6 download, and Hugging Face for the heavier PaddleOCR and onnxtr
> backends — unnecessary once they are on disk.

📖 **[Full documentation](docs/index.md)** · [Getting started](docs/getting-started.md) ·
[Architecture](docs/architecture.md) · [Decision records](docs/adr/index.md)

---

## Why a cascade

Measured across two real archives, one good model for everything **worsens** the
time — 6.2 min against 4.44 for 935 documents. The reason is the distribution,
not the model: **31% of documents already have a text layer** and cost 13 ms,
while a single model would charge ~400 ms on pages with no OCR to do.

```
    STEP                        COST/DOC   RESOLVES   QUALITY (60 audited docs)
    -------------------------------------------------------------------------------
    1. native (PyMuPDF)          13.4 ms     31%      native text, exact
    2. Apple Vision             ~400 ms      64%      words 92%  anchors 100%
       or PP-OCRv6 tiny         ~500 ms               (off Apple hardware)
    3. agreement + consensus       ~0 ms    the rest  inside Cascade.extract
       + the contest                                 always run, not steps
    -- opt-in: you pass them in steps= ---------------------------------------
       unwrap                   ~0.1 ms      —       RTF / BRy / PKCS#7
       screening                                     identity documents
       remote / docling       4 to 47 s              expensive = True, which is
                                                     what arms the five vetoes
                                                     and the replacement gate
```

**On what hardware.** Every number above is CPU, on 2 × Intel Xeon E5-2699 v3
@ 2.30 GHz — 36 physical cores, 72 logical, 125 GiB, Debian 13, x86_64, bare
metal — with **no discrete GPU and no CUDA path in the library at all**. The one
exception is Apple Vision, measured on a MacBook Air M5, which runs on the
Neural Engine rather than the CPU; that single hardware queue is why its
~2.5 pages/s ceiling does not move with threads. A GPU behind the single model would narrow
`6.2 min against 4.44` and would not touch the reason the cascade exists: 31% of
documents need no model at all, and nothing makes an existing text layer cheaper
than 13.4 ms. [The full measurement environment →](docs/architecture.md#the-machine-every-number-was-measured-on)

A Mac runs `native → vision → paddle`; everywhere else it is `native → paddle`.
PP-OCRv6 is not Vision's substitute on a Mac — it is the step below it, and the
second independent reading the agreement gate needs to fire at all. One engine
can never confirm another.

## What your machine resolved

```bash
autosxtract diagnose
```

```
autosxtract 0.6.0
machine    Linux (x86_64)
engines:
  [ ] vision       vision requires Darwin  (single queue: ignores threads)
  [x] paddle       PP-OCRv6 tiny
  [ ] tesseract    tesseract unavailable: No module named 'pytesseract'
orientation: REQUESTED BUT UNAVAILABLE: pytesseract is not installed
cascade:   native -> paddle
```

If it says **`cascade: native` alone**, no OCR engine was installed — the
diagnosis says why, and it is the only case where a scanned PDF comes out empty.
[How to read the whole report →](docs/getting-started.md#autosxtract-diagnose-and-how-to-read-it)

## The API

```python
cascade = Cascade()          # instantiate ONCE and reuse: loading the models
r = cascade.extract_file("document.pdf")   # dominates the first call

r.text          # the extracted text
r.step          # who produced it: 'native', 'vision', 'paddle', ...
r.score         # 0.0 to 1.0
r.provenance    # "vision: native(no text layer) -> vision(ok)"
r.empty         # nothing survived
r.to_dict()     # all of that, ready for JSON

cascade.extract_batch(["a.pdf", "b.pdf"])   # {name: Result}
cascade.names                               # the assembled steps
```

```bash
autosxtract extract document.pdf          # text on stdout, provenance on stderr
autosxtract extract *.pdf --json out.json
autosxtract extract document.pdf --dpi 200 --engines paddle --no-layers
autosxtract extract document.pdf --det tiny --rec medium --rec-dir /my/finetune
autosxtract download-models
```

## Provenance is the product

Every result carries the whole path, with the reason for each refusal.

```
vision: native(quality 0.42 below 0.75) -> vision(ok)
```

"The system extracted the text" is not an auditable answer. "The native step
read 41 characters and was refused on density; Vision read 3,812 and passed"
is. The winner is **not** necessarily the last step: the cascade ends with a
contest on `quality × log(1 + volume)`, and a refused step still competes.
[The gates, in full →](docs/gates.md)

## Configuration

Every threshold in one place, each annotated with the measurement that fixed it.

```python
from autosxtract import Cascade, Config

cascade = Cascade(Config(
    dpi=150,                # at 100 DPI anchor preservation falls to 85.5%
    min_agreement=0.60,     # calibrated on 24 real escalations
    engines=["paddle"],     # explicit order; None = the machine decides
    page_parallelism=None,  # None = decide from this machine
))
```

**No field points at a network.** There is no host, port, URL or credential on
the model, and a test enforces it. [Every field →](https://liafacom.github.io/AutosXtract/configuration/)

## Extending it

Four seams, none of which requires editing this library.

| seam | what it is | guide |
|---|---|---|
| **engine** | a class with one method plus a `@register` decorator | [→](docs/extending/engine.md) |
| **step** | any object with `name` and `run(ctx) -> StepResult` | [→](docs/extending/step.md) |
| **pattern pack** | 66 TOML entries, overridden **entry by entry** | [→](docs/extending/patterns.md) |
| **lexicon** | the built-in word list is a floor, not a truth | [→](docs/interfaces.md) |

```bash
export AUTOSXTRACT_PATTERNS=/path/to/my_pack.toml   # a file, or a directory
```

Everything extensible is a **contract**, and the contracts live in one file,
`autosxtract.interfaces` — structural `Protocol` objects, so an implementation
inherits nothing, it merely has the methods:

```python
from autosxtract import Engine, Step, DocumentContext
assert isinstance(MyEngine(), Engine)
```

[→ the interfaces reference](docs/interfaces.md)

## Extras

None is needed for ordinary use — your platform's engine already arrived. They
exist to ask for **the other** one.

| extra | what for |
|---|---|
| `paddleocr` | the three official PP-OCRv6 tiers, INT8 and a fine-tuned recogniser |
| `apple` | `ocrmac`, a safety net for Vision's direct path |
| `veto` | Tesseract as the witness of the vetoes (needs the binary on PATH) |
| `onnx` | OnnxTR, a second cheap engine of a different architecture |
| `remote` | steps that talk to an external service (Docling API, vision model) |
| `docling` | Docling running inside the process, no network |
| `all` | everything above that runs on this platform |

```bash
pip install 'autosxtract[paddleocr]'
```

Python 3.11+. First run off Apple hardware downloads ~10 MB of PP-OCRv6 weights
into `~/.cache/autosxtract`; for a closed environment run `autosxtract
download-models` where there is network and point `AUTOSXTRACT_MODELS` at the
copied directory. [Install, in full →](docs/getting-started.md#install)

## What has been measured and does **not** work

So nobody spends time again on what has already been refuted.

| tried | result |
|---|---|
| turning off Vision's language correction | 2× throughput and **loses text**: −227 anchors, −4,981 characters, 102 documents falling to worse engines |
| collapsing the cascade into one model | 6.2 min against 4.44 |
| pixel statistics for "empty page" | an empty page and a dense-but-faded page look identical; only consensus separates them |
| a dedicated table structure model | 0.699 value recall against 0.797, at 6–29 s/page against 0.27 |
| a public-dataset signature detector | 19% of pages flagged, most false positives on seals and logos |
| more threads against Vision | flat throughput, linear latency: one hardware queue |
| grey JPEG at 100 DPI | 85.5% anchor preservation; it loses dates and tax numbers |
| deduplicating pages | only 2.0% repeat (33 of 1,675) |

Same hardware as above — CPU, no GPU — so read these as ratios rather than as
absolutes to reproduce. The methodological lesson is worth more than any number
here: **an isolated measurement has already lied in this project.** What decides is the cascade's
behaviour, not one engine's output — `scripts/compare_engines.py` measures both.

## Known limits

- **Apple Vision does not scale with threads.** One Neural Engine queue,
  ~2.5 pages/s per machine. The useful parallelism is per document.
- **With no OCR engine installed**, a scanned PDF comes out empty — correctly,
  and `autosxtract diagnose` says so.
- **PyMuPDF is serialised** by a process lock: it crashes under concurrency.
  Measured cost ~4%.
- It returns **text**, not a document tree. If you need cells and spans, use a
  layout model. [When not to use this →](docs/index.md#when-not-to-use-it)

## Development

```bash
make setup       # venv, [dev] against the pins, hooks, diagnose
make test        # pytest
make all         # lint + typecheck + test + privacy — everything CI checks
```

[`CONTRIBUTING.md`](CONTRIBUTING.md) has the architecture tour, the review
checklist and the release process; [`tests/README.md`](tests/README.md) explains
how the suite is organised.

## Licence

MIT.
