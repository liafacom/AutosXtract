# Extending: a new engine

An engine is the thing that turns pixels into text. It is the library's **first
extension point**, and the claim the design makes is that adding one costs a
class with one method plus a decorator — nothing in `cascade.py`, `steps/` or
`config.py` changes.

That claim is only true because `OCRStep` asks for the
[`Engine` protocol](../interfaces.md#engine) rather than for a concrete class, and
`tests/test_interfaces.py` proves it from the outside with a ten-line engine that
inherits nothing.

## The minimum

```python
from autosxtract.engines.base import OCREngine, register

@register(name="my_ocr", priority=25, extra="my-ocr")
class MyOCR(OCREngine):
    def _load(self):
        import my_ocr                 # raising here means "unavailable"
        return my_ocr.Reader()

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        reading = self.model.read(image)
        return reading.text, reading.confidence * 100     # confidence is 0–100
```

`_load` runs **once per process, under a lock** — without the lock, four threads
load four copies of the model. `self.model` is `None` when it did not load, and
`available()` then returns the reason.

`priority` is preference order, **lowest first**. The shipped numbers come from
comparative measurement on the same 60-document sample:

| priority | engine | measured |
|---|---|---|
| 10 | Apple Vision | ~400 ms/page, 92% of words, 100% of anchors |
| 20 | PP-OCRv6 tiny | ~500 ms/page, the off-Apple candidate |
| 90 | Tesseract | ~1.4 s/page, veto only — it does not persist text |

`extra` is the name of the pip extra that installs your backend. It is quoted
back to the user in `available()`'s reason and in `autosxtract diagnose`, which
is the difference between *"engine unavailable"* and *"install with
`pip install autosxtract[my-ocr]`"*.

`platforms=("Darwin",)` filters the engine out **before it is instantiated**, so
declaring it avoids importing what is not there.

## A complete, runnable example

This one runs anywhere, because the engine invents its reading instead of loading
a backend — replace `_load` and `read_page` with yours and nothing else changes.
It implements the **detailed** contract, so the containment layers run.

```python
import pymupdf
from autosxtract import Cascade, Config, Engine, Line, Page
from autosxtract.cascade import engine_order
from autosxtract.engines.base import OCREngine, register
from autosxtract.steps.ocr import OCRStep


@register(
    name="demo",
    priority=25,
    extra="demo-ocr",
    description="A demonstration engine — it invents its reading",
)
class DemoEngine(OCREngine):
    scales_with_threads = True

    def _load(self):
        # Anything truthy. Raising here means "engine unavailable", and the
        # message becomes the reason in available() and in diagnose.
        return object()

    def read_page(self, image: bytes) -> Page | None:
        lines = [
            "EXCELENTISSIMO SENHOR DOUTOR JUIZ DE DIREITO DA VARA CIVEL",
            "O requerente, nos autos do processo 0001234-56.2020.8.12.0001,",
            "vem respeitosamente a presenca de Vossa Excelencia expor e",
            "requerer a intimacao da parte executada para que se manifeste",
            "no prazo legal, sob pena de preclusao, conforme a decisao",
            "proferida e a certidao do oficial de justica nestes autos.",
        ]
        return Page(
            lines=[
                Line(
                    text=text,
                    score=0.96,                       # 0–1 on a Line. Not 0–100.
                    poly=(
                        (60, 60 + 28 * i), (760, 60 + 28 * i),
                        (760, 84 + 28 * i), (60, 84 + 28 * i),
                    ),
                )
                for i, text in enumerate(lines)
            ],
            width=827.0,
            height=1169.0,
        )


engine = DemoEngine()
assert isinstance(engine, Engine)
print(engine.available())                 # (True, 'ok')
print(engine_order(Config()))             # ['paddle', 'demo'] — priority order

# A one-page PDF with an image and no text layer, so the OCR step is reached.
doc = pymupdf.open()
sheet = doc.new_page()
sheet.insert_image(sheet.rect, pixmap=pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 200, 280)))
pdf_bytes = doc.tobytes()
doc.close()

cascade = Cascade(Config(use_native=False), steps=[OCRStep(engine)])
result = cascade.extract(pdf_bytes)

print(result.step)                        # demo
print(result.provenance)                  # demo: demo(ok)
print(result.details["confidence"])       # 96.0
print(result.details["layers"]["trusted_fraction"])   # 1.0
```

Once registered, the engine is reachable by name everywhere:

```python
from autosxtract import get, Cascade, Config

get("demo")                               # the shared instance
Cascade(Config(engines=["demo"]))         # an explicit chain
```

```bash
autosxtract extract document.pdf --engines demo
```

## `transcribe_page` or `read_page`?

Implement **one**. The base class derives the other:

- Implement only `transcribe_page` → `read_page` returns `None`, the cascade
  falls back to running text, and the containment layers are skipped with the
  reason recorded. Nothing breaks.
- Implement only `read_page` → `transcribe_page` is derived from it
  (`page.text`, `page.mean_confidence`), as in the example above.

**Implement `read_page` if your backend exposes geometry.** The containment
layers are the cheapest measured gain in the pipeline: entity recall
0.902 → 0.921 across 895 pages, and p50 latency **falls** from 298 ms to 236 ms.
They only exist because somebody knows where each line sits on the sheet.

Add `recognize_crop` if your backend can recognise **without** detecting. Layer 2
calls it once per target; without it the layer re-runs full detection on every
crop and goes from tens of milliseconds to ~3 s per document — from improvement
to regression.

## The rules that are not obvious

### Confidence does not arbitrate quality

Across 60 audited documents, engine confidence did not separate a good reading
from an unsafe one — **there was an unsafe document at confidence 100.** It enters
only as a floor against degenerate output; the [gate](../gates.md) decides. Do
not build logic on your own confidence, and do not suppress low-confidence lines
before returning them. See [ADR 0007](../adr/0007-confidence-does-not-arbitrate-quality.md).

### A missing engine is never an exception

`available()` must never raise. Anything that can fail belongs in `_load`, whose
exception message becomes the reason. The absence of a tool is not evidence about
the document — treating "I have no OCR" as "the page is empty" switches the
pipeline off in silence. See [ADR 0003](../adr/0003-a-missing-engine-is-never-an-exception.md).

### Two confidence scales, and mixing them is silent

`transcribe_page` returns **0–100**. `Line.score` is **0–1**. The layer
thresholds assume the second, so an engine that puts 96.0 on a `Line` makes every
line look perfect and Layer 1 stops containing anything. Nothing raises.

### Say whether threads help you

```python
scales_with_threads = False
```

Set it when a **single hardware queue** sits behind you. Apple's Neural Engine
serves one request at a time: measured from 1 to 12 threads, constant throughput
at ~2.5 pages/s and latency from 430 ms to 3,492 ms. You are the only party that
knows this — whoever configures the cascade cannot see behind the engine.

It is a good default and a bad law, which is why the operator can overrule it
with `Config(engine_parallelism={"my_ocr": 4})`. `OCRStep` records the
**effective** value in the provenance when it differs from the requested one;
clamping in silence would be the same antipattern as a hidden network call.

### Never reuse one backend instance for two purposes

If your library carries **per-instance state**, a second code path that changes
configuration needs its own object. Calling `rapidocr` with `use_det=False` turns
detection off *permanently on that object*: measured, the next whole-page read
returned 1 line where it had returned 56, and the document came out with 1
character instead of 3,900. The defect is of the worst kind — silent,
order-dependent, and invisible until the second page of a batch, because the
first still uses a clean object. `PaddleEngine._recognizer()` keeps a separate
instance for Layer 2, and `tests/test_paddle.py` pins that.

### Preserve page order

If you override `transcribe`, parallelise with `map`, not `as_completed`.
Reassembling in completion order scrambles the document and **nothing downstream
can tell that it did**.

## The witness contract

`read_document` is a different question from `transcribe`: not *"what is the
text?"* but *"is there legible text here?"*. It feeds the
[vetoes](../gates.md#the-five-vetoes) that run before an expensive step.

The inherited implementation rasterises and transcribes, and approximates
`reliable_words` all-or-nothing from the engine's aggregate confidence, because
the common contract does not expose **per-word** confidence. Whoever does expose
it should override this method and measure properly — that is exactly why
Tesseract is the preferred witness.

`None` means *"I don't know"* and skips the three vetoes that depend on it. It
never becomes "there is no text".

## Before you ship it

```python
from autosxtract import Engine
assert isinstance(MyOCR(), Engine)
```

Then copy `_assert_signature` from `tests/test_interfaces.py` and run it against
each of the six methods. `isinstance` checks that the names exist; the signature
comparison is what catches the drift that motivated the interfaces module in the
first place.

Measure with `scripts/compare_engines.py`, which runs both the engine **and** the
whole cascade. That distinction is not pedantry: turning off Vision's language
correction improved anchors across 60 documents (+4) and worsened them across the
cascade (−227), because the worse text failed the gate and fell to worse engines.
**An isolated measurement has already lied here.**
