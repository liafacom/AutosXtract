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

That is it. **One command and one class, identical on macOS, Linux and
Windows** — the OCR engine arrives already chosen by the machine, and there is
no extra to memorise and no configuration to write.

> Extraction **does no networking**. No external worker, no SSH tunnel, no
> remote endpoint, no third-party service call. The only connection in the whole
> package is the one-off download of the PP-OCRv6 weights — unnecessary once
> they are on disk.

📖 **[Full documentation](docs/index.md)** — getting started, architecture, the
interfaces, the gates, how to extend it, and the decision records.

---

## Why a cascade

Measured across two real archives, one good model for everything **worsens** the
time — 6.2 min against 4.44 for 935 documents. The reason is the distribution,
not the model: **31% of documents already have a text layer** and cost 13 ms,
while a single model would charge ~400 ms on pages with no OCR to do.

```
    STEP                        COST/DOC   RESOLVES   QUALITY (60 audited docs)
    -------------------------------------------------------------------------------
    0. unwrap                    ~0.1 ms      —       RTF / BRy / PKCS#7
    1. native (PyMuPDF)          13.4 ms     31%      native text, exact
    2. Apple Vision             ~400 ms      64%      words 92%  anchors 100%
       or PP-OCRv6 tiny         ~500 ms               (off Apple hardware)
    3. vetoes + screening         ~1 s       the rest
    4. remote steps            4 to 47 s     opt-in   only if you instantiate them
```

| platform | cascade |
|---|---|
| macOS | `native → vision → paddle` |
| Linux, Windows | `native → paddle` |

PP-OCRv6 is **not** an extra and **not** Vision's substitute on a Mac: it is the
step below it, and the second independent reading the agreement gate needs in
order to fire at all. One engine can never confirm another.

To see what **your** machine resolved:

```bash
autosxtract diagnose
```

```
autosxtract 0.5.0
machine    Linux (x86_64)
resources  72 usable core(s)
engines:
  [ ] vision       vision requires Darwin  (single queue: ignores threads)
  [x] paddle       PP-OCRv6 tiny
  [ ] tesseract    tesseract unavailable: No module named 'pytesseract'; install with pip install autosxtract[veto]
cascade:   native -> paddle
```

If it says **`cascade: native` alone**, no OCR engine was installed — the
diagnosis says why, and it is the only case where a scanned PDF comes out empty.
[How to read the whole report →](docs/getting-started.md#autosxtract-diagnose-and-how-to-read-it)

## In thirty seconds

```python
from autosxtract import Cascade

cascade = Cascade()          # instantiate ONCE and reuse
r = cascade.extract_file("document.pdf")

r.text          # the extracted text
r.step          # who produced it: 'native', 'vision', 'paddle', ...
r.score         # 0.0 to 1.0
r.provenance    # "vision: native(no text layer) -> vision(ok)"
r.empty         # nothing survived
r.to_dict()     # all of that, ready for JSON

results = cascade.extract_batch(["a.pdf", "b.pdf"])   # {name: Result}
cascade.names                                          # the assembled steps
```

Instantiating `Cascade()` once and reusing it matters: loading the models is the
dominant cost of the first call.

```bash
autosxtract extract document.pdf          # text on stdout, provenance on stderr
autosxtract extract *.pdf --json out.json
autosxtract extract document.pdf --dpi 200 --engines paddle --no-layers
autosxtract extract document.pdf --det tiny --rec medium --rec-dir /my/finetune
autosxtract download-models
```

## Provenance is the product

Every result carries the whole path, with the reason for each refusal.

```python
print(r.provenance)
# vision: native(quality 0.42 below 0.75) -> vision(ok)

for a in r.attempts:
    print(a.step, a.accepted, a.reason, a.chars, f"{a.ms:.0f}ms")
```

"The system extracted the text" is not an auditable answer. "The native step read
41 characters and was refused on density; Vision read 3,812 and passed" is.

The winner is **not** necessarily the last step: the cascade ends with a contest
on `quality × log(1 + volume)`, and a refused step still competes.
[The gates, in full →](docs/gates.md)

## Configuration

Every threshold in one place, each annotated with the measurement that fixed it,
and the reference page is generated from the model so it cannot go stale.

```python
from autosxtract import Cascade, Config

cascade = Cascade(Config(
    dpi=150,                # at 100 DPI anchor preservation falls to 85.5%
    min_useful_words=12,    # floor outside the stamp
    min_agreement=0.60,     # calibrated on 24 real escalations
    engines=["paddle"],     # explicit order; None = the machine decides
    page_parallelism=None,  # None = decide from this machine
))
```

**No field points at a network.** There is no host, port, URL or credential on
the model, and a test enforces it.
[Every field →](docs/configuration.md)

## The extension points

Four seams, and none of them requires editing this library.

**A new engine** — a class with one method plus a decorator:

```python
from autosxtract.engines.base import OCREngine, register

@register(name="my_ocr", priority=25, extra="my-ocr")
class MyOCR(OCREngine):
    def _load(self):
        import my_ocr
        return my_ocr.Reader()

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        r = self.model.read(image)
        return r.text, r.confidence * 100
```

[→ full guide](docs/extending/engine.md)

**A new step** — any object with `name` and `run(ctx) -> StepResult`, joined
through `Cascade(steps=[...])`. [→ full guide](docs/extending/step.md)

**A pattern pack** — every domain regex is data now, 66 TOML entries under
`autosxtract/patterns/data/`, overridden **entry by entry**:

```bash
export AUTOSXTRACT_PATTERNS=/path/to/my_pack.toml   # a file, or a directory
```

```python
Config(patterns="/path/to/my_pack.toml")           # or a PatternSet
```

Resolution order: `Config.patterns` → `AUTOSXTRACT_PATTERNS` → the bundled pack
for `Config.language` → `base`. A pack that redefines one entry inherits the
other sixty-five and keeps receiving their fixes.
[→ full guide](docs/extending/patterns.md)

**A lexicon** — the built-in word list is a floor, not a truth:

```python
from autosxtract import Config
from autosxtract.quality.lexicon import Lexicon

Config(lexicon=Lexicon.from_texts(Path("validated").glob("*.txt")))
```

Everything extensible is a **contract**, and the contracts live in one file,
`autosxtract.interfaces`: `Engine` and `Step` are the two extension points, and
`Renderer`, `PageSource`, `DocumentContext`, `Tokenizer`, `StampStripper`,
`LexiconLike`, `Scorer`, `Gate` and `GateVerdict` are the collaborations
underneath them. They are structural `Protocol` objects — an implementation
inherits nothing, it merely has the methods — and they are re-exported from the
package root:

```python
from autosxtract import Engine, Step, DocumentContext
assert isinstance(MyEngine(), Engine)
```

[→ the interfaces reference](docs/interfaces.md)

## Extras

None is needed for ordinary use. They exist to ask for **the other** engine —
your platform's already arrived.

| extra | what for |
|---|---|
| `paddleocr` | the three official PP-OCRv6 tiers, INT8 and a fine-tuned recogniser |
| `apple` | `ocrmac`, a safety net for Vision's direct path |
| `veto` | Tesseract as the witness of the vetoes (needs the binary on PATH) |
| `onnx` | OnnxTR, a second cheap engine of a different architecture |
| `remote` | steps that talk to an external service (Docling API, vision model) |
| `docling` | Docling running inside the process, no network |
| `paddle` | nothing new — PP-OCRv6 is mandatory everywhere; kept so old commands work |
| `all` | everything above that runs on this platform |

```bash
pip install 'autosxtract[paddleocr]'
```

Python 3.11+. First run off Apple hardware downloads ~10 MB of PP-OCRv6 weights
into `~/.cache/autosxtract`; for a closed environment run
`autosxtract download-models` where there is network and point
`AUTOSXTRACT_MODELS` at the copied directory.
[Install, in full →](docs/getting-started.md#install)

## What has been measured and does **not** work

So nobody spends time again on what has already been refuted.

| tried | result |
|---|---|
| turning off Vision's language correction | doubles throughput (2.5 → 5.4 pages/s) and **loses text**: 102 documents fall to worse engines, −227 anchors, −4,981 characters across 935 documents |
| collapsing the cascade into one model | 6.2 min against 4.44 min |
| nine families of pixel statistics for "empty page" | an empty page and a dense-but-faded page produce identical statistics — what separates them is consensus between engines |
| a dedicated table structure model | 0.699 value recall against 0.797 for the cheap engine with layers, at 6–29 s/page against 0.27 s |
| a signature detector trained on a public dataset | 19% of pages with a detection, most false positives on seals, stamps, logos and QR codes |
| more threads against Vision | constant throughput, linear latency: it is a single hardware queue |
| grey JPEG at 100 DPI | 85.5% anchor preservation; it loses dates and tax numbers |
| deduplicating pages | only 2.0% repeat (33 of 1,675) |

And the methodological lesson, worth more than any specific number: **an isolated
measurement has already lied here.** What decides is the cascade's behaviour, not
one engine's output. `scripts/compare_engines.py` measures both.

## Known limits

- **Apple Vision does not scale with threads.** A single Neural Engine queue:
  ~2.5 pages/s per machine. The useful parallelism is per document.
- **With no OCR engine installed**, a scanned PDF comes out empty — correctly,
  and `autosxtract diagnose` says so.
- **PyMuPDF is serialised** by a process lock: it crashes the process under
  concurrency. The measured cost is ~4%.
- It returns **text**, not a document tree. If you need cells and spans, use a
  layout model. [When not to use this →](docs/index.md#when-not-to-use-it)

## Development

```bash
make setup       # venv, [dev] against the pins, hooks, diagnose
make test        # pytest
make all         # lint + typecheck + test + privacy — everything CI checks
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the architecture tour, the review
checklist and the release process, and
[`tests/README.md`](tests/README.md) for how the suite is organised.

## Licence

MIT.
