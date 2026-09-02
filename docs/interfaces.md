# The interfaces

Everything extensible in this library is a contract, and every contract lives in
one file: [`autosxtract/interfaces.py`](https://github.com/liafacom/AutosXtract/blob/main/autosxtract/interfaces.py).
Eleven `typing.Protocol` objects, all `@runtime_checkable`, all re-exported from
the package root:

```python
from autosxtract import (
    Renderer, PageSource, DocumentContext,      # the document, as a step sees it
    Engine, Step,                                # the two extension points
    Tokenizer, StampStripper, LexiconLike,       # what counts as a word
    Scorer, Gate, GateVerdict,                   # what judges the text
)
```

Three properties hold for all of them, and each was paid for:

**They are structural.** An implementation does **not** inherit from these. A
class satisfies a contract by having the methods — which is what let
`quality.stamp.Stamp`, written long before the file existed, become a
`StampStripper` without one line of it changing. Requiring inheritance would have
made the same refactor a rewrite.

**They import nothing at runtime.** Every type the module mentions arrives under
`if TYPE_CHECKING`, so importing a contract never drags in what implements it.
That is what puts `interfaces` below all five [layers](architecture.md#the-layer-rule)
while depending on none of them.

**They are checked.** `tests/test_interfaces.py` asserts, for every shipped
implementation, that it still satisfies the protocol it claims — by `isinstance`
*and by signature*. That test is what makes the file worth anything: an interface
nobody checks is a comment, and this one had already drifted. The `Engine`
protocol declared `transcribe(pages, *, parallelism)` while `OCRStep` had been
passing `force_parallelism` for months. Nothing failed, because nothing looked —
and an engine written to the published contract would have crashed on its first
document.

!!! tip "How to check your own implementation"

    ```python
    from autosxtract import Engine
    assert isinstance(MyEngine(), Engine)
    ```

    `isinstance` against a runtime-checkable Protocol verifies that the *names*
    exist, not that the signatures match. For the stricter check, copy
    `_assert_signature` from `tests/test_interfaces.py` — it compares parameter
    names, kinds and defaults, and it is what catches the drift above.

---

## The two extension points

### `Engine`

**What it is.** Everything the cascade requires of something that reads pixels.

**What implements it.** `engines.base.OCREngine` and, through it, the five
registered engines:

| name | priority | platform | extra | measured |
|---|---|---|---|---|
| `vision` | 10 | Darwin | `apple` | ~400 ms/page, 92% of words, 100% of anchors |
| `ocrmac` | 15 | Darwin | `apple` | the same engine through a library, +~61 ms round-trip |
| `paddle` | 20 | any | `paddle` | ~500 ms/page, the off-Apple candidate |
| `onnx` | 30 | any | `onnx` | a second cheap engine of a different architecture |
| `tesseract` | 90 | any | `veto` | ~1.4 s/page; **witness only**, it never transcribes |

Per-page costs measured on [these machines](architecture.md#the-machine-every-number-was-measured-on): Vision on the Neural
Engine, everything else on a 72-core Xeon CPU with no GPU.

Inheriting `OCREngine` is the easy road and gives you the page sweep, the locked
single load and the witness reading for free. It is a convenience, not the
requirement: `OCRStep` asks for the **protocol**, so an engine sharing nothing
with the base still descends the cascade —
`tests/test_interfaces.py::FakeEngine` is exactly that, in ten lines.

**The surface.**

```python
name: str
scales_with_threads: bool

def available(self) -> tuple[bool, str]: ...
def transcribe_page(self, image: bytes) -> tuple[str, float]: ...
def read_page(self, image: bytes) -> Page | None: ...
def recognize_crop(self, image: bytes) -> tuple[str, float] | None: ...
def transcribe(self, pages: list[bytes], *, parallelism: int = 4,
               force_parallelism: bool = False) -> Transcription | None: ...
def read_document(self, pdf_bytes: bytes, *, max_pages: int = 3,
                  min_reliable_words: int = 3) -> LocalReading | None: ...
```

**What you must guarantee.**

- `available()` **never raises.** It returns `(False, reason)` in words. The
  reason is not decoration — it reaches `autosxtract diagnose` and the
  provenance, and it is how somebody finds out that their scanned PDF came out
  empty because `pyobjc` is broken. See
  [ADR 0003](adr/index.md#0003-a-missing-engine-is-never-an-exception).
- `transcribe()` **preserves page order.** Reassembling in completion order
  scrambles the document and nothing downstream can tell that it did. If you
  parallelise, use `map`, not `as_completed`.
- **Confidence is 0–100 in `transcribe_page`, 0–1 on a `Line`.** The two scales
  are different and both are load-bearing: the layer thresholds assume 0–1, so
  an engine reporting 0–100 into a `Line` makes every line look perfect.
- `Transcription.pages` is filled **only when every page answered in detail.** A
  partial list makes the [containment layers](gates.md#the-containment-layers)
  operate on a different document from the one transcribed, and the page index
  stops lining up.
- `pages_answered < pages_sent` means the reading is **incomplete**, and
  `failures` says why the missing pages raised. That distinction is the whole
  point: a page read as blank and a page never reached look identical in the
  text, and only one of them means the engine is down.
- `scales_with_threads = False` if a single hardware queue sits behind you. You
  are the only party that knows. Apple's Neural Engine serves one request at a
  time — measured from 1 to 12 threads, constant throughput and latency from
  430 ms to 3,492 ms.

**What is optional.** `read_page` and `recognize_crop` may answer `None`, and
that is the honest reply from an engine without geometry or without a
detection-free path. It blocks nothing. What it costs is the containment layers,
the cheapest measured gain in the pipeline: entity recall 0.902 → 0.921 **and
latency falls** from 298 to 236 ms. Implement them when the backend exposes
geometry.

**What breaks if you get it wrong.**

| mistake | symptom |
|---|---|
| `available()` raises | the whole cascade dies on a machine missing one optional dependency |
| returning `(True, …)` while the model is absent | every page fails one at a time, and the failure surfaces as an empty document rather than a missing engine |
| completion-order reassembly | the text is right and its order is wrong — nothing detects this |
| 0–100 scores on a `Line` | every line is classified `trusted`; Layer 1 stops containing anything |
| partial `Transcription.pages` | the layers crop the wrong page of the wrong document |
| forgetting `scales_with_threads` | you configure 8 threads and measure the latency of 8 with the throughput of 1 |

→ [How to add an engine](extending/engine.md)

### `Step`

**What it is.** One attempt at extraction, with a reason for whatever happens.
The smaller extension point: a name and a `run`.

**What implements it.** `NativeStep`, `OCRStep`, `ScreeningStep`, `UnwrapStep`,
`LocalDoclingStep`, `DoclingStep`, `VLMStep`.

```python
name: str
def run(self, ctx: DocumentContext) -> StepResult: ...
```

**What you must guarantee.**

- **Return a `StepResult` even when you fail.** `StepResult` has two fields
  because the verdict and the candidate are different things: `attempt.accepted`
  decides whether the cascade *stops*; `candidate` decides whether the text
  *enters the contest*. A refused step may have produced the best reading there
  is. Returning `None` for a refusal left 682 documents with zero characters
  while the PDF had a text layer
  ([ADR 0004](adr/index.md#0004-refused-text-still-competes)).
- **Fill `Attempt.reason` with a sentence a human can act on.** `"refused"` is
  not a reason. `"only 4 useful words outside the stamp"` is.
- **Never raise for an expected condition.** A network failure, a missing
  binary, an unreadable file: all of those are refused attempts with a reason.
- **Do not reach for evidence you did not gather.** `DocumentContext`
  deliberately withholds `readings` and `texts`; see below.
- **Report what was done to the page, not only what you read from it.**
  `ctx.orientation` says whether the page was turned upright before your engine
  saw it, or why it could not be. Copying it into your details is what stops a
  correction that ran and one that silently did not from leaving identical
  evidence.

**What is optional.** A class attribute `expensive = True` makes the cascade run
the [five vetoes](gates.md#the-five-vetoes) before you and submit your output to
the [replacement gate](gates.md#the-replacement-gate) afterwards. It is read with
`getattr` and stays *off* the protocol on purpose: making it mandatory would
force every three-line step to declare that it is cheap.

**What breaks if you get it wrong.** A step that raises takes down a batch. A
step that returns a candidate with a score on a different scale corrupts the
final contest, because the native step and every OCR step put their candidates
into the same one.

→ [How to add a step](extending/step.md)

---

## The document, as a step sees it

### `Renderer`

**What it is.** Turning a PDF into page images.
**What implements it.** `pdf.render.render`.

```python
def __call__(self, pdf_bytes: bytes, *, dpi: int = 150, max_pages: int = 64,
             grayscale: bool = True, indices: list[int] | None = None) -> list[bytes]: ...
```

**What you must guarantee.** The signature is the easy half. The promise is the
other: **the same arguments give back the same pixels.** Two engines compared on
one document must receive identical images, otherwise the difference measured
between them is preprocessing noise rather than evidence about the engines — and
comparing engines is how every threshold in `config` was fixed. `Context` caches
renders *on that promise*, so a renderer that quietly varies its output does not
merely mislead, it poisons the cache.

`[]` is a legitimate answer, not a failure: an unreadable PDF, or nothing left to
rasterise. **A renderer that raises turns a document the cascade could have
degraded through into a traceback**, which is the one outcome this library never
produces.

**Why it is injectable.** So a step can be driven over invented pixels without
PyMuPDF opening anything — and PyMuPDF is precisely what cannot be run freely
([ADR 0006](adr/index.md#0006-pymupdf-is-serialised)).

```python
from autosxtract import Config
from autosxtract.steps.base import Context

def renderer(pdf_bytes, *, dpi=150, max_pages=64, grayscale=True, indices=None):
    return [b"page-one", b"page-two"]

ctx = Context(pdf_bytes=b"not a pdf", config=Config(dpi=300), renderer=renderer)
ctx.images()   # [b'page-one', b'page-two'] — and the second call is cached
```

### `PageSource`

**What it is.** A document's bytes and its rasterised pages, paid for once. The
narrow half of `DocumentContext`.

```python
@property
def pdf_bytes(self) -> bytes: ...
def images(self, *, indices: list[int] | None = None) -> list[bytes]: ...
```

**Why it exists separately.** So that whatever needs only pixels can say so in
its own signature. A collaborator asking for the whole context when it looks at
nothing but images is how a helper silently acquires the right to read the
configuration and record readings.

**What you must guarantee.** `images` **caches**. Rasterising is the second most
expensive thing the cascade does after OCR itself, and every step of a document
must be handed the same pixels rather than its own render.

### `DocumentContext`

**What it is.** Everything a step may rely on about the document — and nothing
more. Extends `PageSource`.
**What implements it.** `steps.base.Context`.

```python
@property
def config(self) -> Config: ...
@property
def profile(self) -> PageProfile: ...
@property
def pages_without_text(self) -> list[int] | None: ...
def best_text(self) -> str: ...
def record_reading(self, engine: str, text: str) -> None: ...
def replace_bytes(self, new_bytes: bytes) -> None: ...
```

**Annotate your step against this, not against `Context`.** Then a test can hand
it thirty lines of fake instead of a real PDF, and a step written outside the
library is told exactly what it is allowed to assume. The list is short on
purpose: it is an audit of what the shipped steps actually touch, not a copy of
`Context`'s attributes.

**What is deliberately absent is as much of the contract as what is here.**
`readings` and `texts` — the blackboard the consensus and agreement gates read —
are **not** on this protocol, and `tests/test_interfaces.py` asserts they stay
off it. Those gates belong to the cascade, not to a step. A step that reached
into them would be deciding on evidence it did not gather, and the two gates
would stop being answerable from one place.

**Two members mutate, and both earn it:**

`record_reading(engine, text)`
:   How a **refused** step still counts as a vote. The consensus gate only means
    "there is no text here" because every engine, *including the ones that were
    turned down*, left what it read. Call it whether you were accepted or not.
    It is free at the point of decision and unavailable afterwards.

`replace_bytes(new_bytes)`
:   The unwrap step swapping an envelope for its payload. It invalidates the
    profile, the page list and the render cache, because all three belonged to
    the envelope. Without it the following steps measure the wrapper — the whole
    point of stage 0 lost, and 128 documents of a real archive unreadable.

**`pages_without_text` has three answers, not two.** `None` means *"I could not
tell"* and must fall back to rasterising everything; `[]` means *"no page is
missing text"* and means there is nothing to OCR. Collapsing `None` into `[]`
switches the OCR off on exactly the documents whose structure is broken.

---

## Text, and what judges it

### `Tokenizer`

**What it is.** The single answer to *"what is a word here?"*.
**What implements it.** `quality.stamp.Stamp`.

```python
def words(self, text: str) -> list[str]: ...
def count(self, text: str) -> int: ...
def vocabulary(self, text: str) -> set[str]: ...
```

**Why one and not a regex per call site.** Whoever **counts** useful words and
whoever **compares** two readings have to agree, or the two gates that depend on
them diverge without ever disagreeing out loud: one engine's text passes the
word floor and the same text fails the vocabulary overlap.

**What breaks if you get it wrong.** `vocabulary` must be built from the same
tokens `words` returns. If they disagree, `min_useful_words` and
`min_agreement` stop describing the same text and the agreement gate fires on
documents it should not.

### `StampStripper`

**What it is.** A `Tokenizer` that first removes the boilerplate banner off the
page. Extends `Tokenizer` with one method.
**What implements it.** `quality.stamp.Stamp`.

```python
def strip(self, text: str) -> str: ...
```

**Why this exists at all.** Every digital case-file system prints a conformity
stamp in the margin, in a font whose encoding survives when the body of the page
produces nothing. That is 250 to 600 characters that sail past any size
threshold: in an audit of **1,339 documents, 227 extractions looked successful
and all there was, was the stamp.** **Measuring an extraction without stripping
is measuring the stamp.**

**This is the library's adaptation seam.** The shipped patterns are Brazilian
court boilerplate; another corpus supplies its own through `Config.stamps`, a
[pattern pack](extending/patterns.md), or its own implementation of this
protocol — and no measurement code changes, because everyone measures through
here.

```python
from autosxtract import Config
from autosxtract.steps.base import Context

class EverySecondWord:                        # a Tokenizer and a StampStripper
    def words(self, text): return text.split()[::2]
    def count(self, text): return len(self.words(text))
    def vocabulary(self, text): return set(self.words(text))
    def strip(self, text): return text

ctx = Context(pdf_bytes=b"", config=Config(), tokenizer=EverySecondWord())
ctx.record_reading("fake", "um dois tres quatro")
ctx.readings["fake"]    # 2
```

### `LexiconLike`

**What it is.** The vocabulary a line is judged readable against.
**What implements it.** `quality.lexicon.Lexicon`. `Config.lexicon` accepts it —
the field is typed loosely there for pydantic's sake, so **this protocol is where
the actual requirement is written down**.

```python
def __contains__(self, word: str) -> bool: ...
def coverage(self, text: str) -> float: ...
def tokens(self, text: str) -> list[str]: ...
```

**What you must guarantee.** `coverage` must answer `1.0` for a line with **no
alphabetic token**. A case number and a date are not words, and punishing them
for being absent classifies exactly what matters most to preserve as junk.

**The failure mode worth stating before anybody hits it, because it points the
wrong way round.** A lexicon that is *too small* makes correct text look like
junk — but that is the **safe** error: the line falls to `suspect`, the text
still passes, the page merely loses confidence and tends to escalate. A lexicon
full of OCR errors is the **unsafe** one, because it teaches the classifier that
the errors are the language. That is why `Lexicon.from_texts` drops anything
appearing fewer than three times: an OCR error rarely repeats three times.

Build yours from **validated** text only:

```python
from pathlib import Path
from autosxtract import Config
from autosxtract.quality.lexicon import Lexicon

Config(lexicon=Lexicon.from_texts(Path("validated").glob("*.txt")))
```

### `Scorer`

**What it is.** Text → a number between 0 and 1, with the reasons in words.
**What implements it.** `quality.scoring.score_text`.

```python
def __call__(self, text: str, domain_patterns: list[str] | None = None) -> dict[str, Any]: ...
```

Returns a dictionary carrying at least `score`, plus `label`, `reasons` and
`metrics`. The reasons are not decoration: the score alone is not auditable, and
*"why was this step refused?"* has to be answerable from the result rather than
from the source.

**Two properties are load-bearing.**

- **Empty text must score `0.0` explicitly.** Summing the degenerate-text
  penalties leaves an empty string at 0.15, competing with real text.
- **The scale must stay comparable across steps.** The native step and every OCR
  step put their candidates into the same contest, which is settled by
  `score × log(1 + volume)`. A scorer generous on one path and strict on another
  does not merely misjudge — it silently reorders the contest.

### `GateVerdict`

**What it is.** A decision plus the sentence that justifies it.
**What implements it.** `quality.gate.Verdict`.

```python
@property
def escalate(self) -> bool: ...
@property
def reason(self) -> str: ...
```

The reason travels into the provenance, which is this library's product as much
as the text is. **A gate returning a bare `bool` would satisfy the cascade and
destroy that.**

### `Gate`

**What it is.** *Is this text good enough to stop the cascade?*
**What implements it.** `quality.gate.evaluate`.

```python
def __call__(self, text: str, profile: PageProfile, *,
             min_useful_words: int = 12, min_chars_per_page: int = 200,
             score: float | None = None, min_score: float = 0.35,
             glyph_index: float = 0.0,
             stamps: tuple[str, ...] | None = None) -> GateVerdict: ...
```

**This protocol is a contract about a design rule as much as about a signature.**
There is **one** acceptance criterion in this pipeline: whoever decides the
current step solved it and whoever decides the next one is worth paying for must
ask the same question with the same code
([ADR 0002](adr/index.md#0002-one-acceptance-criterion)).

So a *replacement* gate is a legitimate thing to inject; a **second acceptance
gate alongside the first is not**. Note that `quality.rejection`'s replacement
gate is deliberately **not** this contract: it compares against a concrete
earlier text rather than a threshold, and what it refuses is *discarded* rather
than left in the contest.

**What you must guarantee.** No I/O, no network, no global configuration — which
is what lets it be called from both sides of the decision at no cost. And it must
**restate no threshold of its own**: the defaults on the protocol are checked
against `evaluate`'s by
`tests/test_interfaces.py::test_the_gate_contract_repeats_no_threshold_of_its_own`,
because a protocol that copied a measured number would be a second place to
change it.

Injecting one, and a scorer with it:

```python
from autosxtract import Config
from autosxtract.quality.gate import Verdict
from autosxtract.steps.ocr import OCRStep
from autosxtract.engines import get

def gate(text, profile, **kwargs):
    return Verdict(escalate=len(text) < 5_000, reason="my own floor")

step = OCRStep(get("paddle"), gate=gate)
```
