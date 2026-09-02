# Extending: a new step

A step is **one attempt at extraction, with a reason for whatever happens**. It
is the library's second extension point and the smaller one: a `name` and a
`run`. It joins the cascade through `Cascade(steps=[...])` and nothing else
changes.

```python
class MyStep:
    name = "my_step"

    def run(self, ctx: DocumentContext) -> StepResult:
        ...
```

Annotate against [`DocumentContext`](../interfaces.md#documentcontext), not
against the concrete `Context`. That is what makes the sentence above true rather
than aspirational: a step written to the protocol can be exercised over a
thirty-line fake, with no PDF, no PyMuPDF and no engine installed.

## The two fields of `StepResult`, and why they are two

```python
StepResult(attempt: Attempt, candidate: Candidate | None = None)
```

`attempt.accepted` is the **verdict**: does the cascade stop here?
`candidate` is the **text**: does it enter the final contest?

They are separate because a step may have produced text **and** been refused, and
that text cannot be thrown away — if no later step does better, it is still the
best reading the document has. Returning `None` for a refusal left **682
documents with zero characters while the PDF had a text layer**.
See [ADR 0004](../adr/index.md#0004-refused-text-still-competes).

So: fill `candidate` whenever you produced text, regardless of the verdict.

## A complete, runnable example

A step that reads the text of any plain-text file **embedded** in the PDF — a
real case the cascade does not handle, and one that needs no OCR at all. It shows
every part of the contract: the protocol check, `record_reading`, the shared
acceptance gate, and both fields of `StepResult`.

```python
import pymupdf
from autosxtract import Cascade, Config, DocumentContext, Step, StepResult
from autosxtract.quality.gate import evaluate
from autosxtract.quality.scoring import score_text
from autosxtract.types import Attempt, Candidate


class AttachmentStep:
    """Read the text of any plain-text file embedded in the PDF."""

    name = "attachment"

    def run(self, ctx: DocumentContext) -> StepResult:
        try:
            doc = pymupdf.open(stream=ctx.pdf_bytes, filetype="pdf")
        except Exception as exc:
            # Never raise for an expected condition: an unreadable file is a
            # refused attempt with a reason, not a traceback.
            return StepResult(Attempt(self.name, False, f"unreadable: {exc}"))
        try:
            parts = []
            for i in range(doc.embfile_count()):
                info = doc.embfile_info(i)
                if str(info.get("filename", "")).endswith(".txt"):
                    parts.append(doc.embfile_get(i).decode("utf-8", "replace"))
        finally:
            doc.close()

        text = "\n\n".join(parts)
        if not text.strip():
            return StepResult(Attempt(self.name, False, "no text attachment"))

        # The consensus gate's vote. Record it even when you are refused.
        ctx.record_reading(self.name, text)

        score = score_text(text)["score"]
        verdict = evaluate(                       # THE acceptance gate, not yours
            text,
            ctx.profile,
            min_useful_words=ctx.config.min_useful_words,
            min_chars_per_page=ctx.config.min_chars_per_page,
            score=score,
            min_score=ctx.config.min_score,
            stamps=ctx.config.stamp_patterns(),
        )
        return StepResult(
            Attempt(self.name, verdict.sufficient, verdict.reason, len(text)),
            Candidate(step=self.name, text=text, score=score),
        )


assert isinstance(AttachmentStep(), Step)

body = (
    "O requerente, nos autos do processo 0001234-56.2020.8.12.0001, vem "
    "respeitosamente a presenca de Vossa Excelencia expor e requerer o que "
    "segue. A decisao proferida determinou a intimacao da parte executada "
    "para que se manifestasse no prazo legal, sob pena de preclusao, e o "
    "exequente informa que a diligencia restou devidamente cumprida."
)
doc = pymupdf.open()
doc.new_page()
doc.embfile_add("peticao.txt", body.encode("utf-8"))
pdf_bytes = doc.tobytes()
doc.close()

cascade = Cascade(Config(use_native=False, engines=[]), steps=[AttachmentStep()])
result = cascade.extract(pdf_bytes)

print(result.step)          # attachment
print(result.provenance)    # attachment: attachment(ok)
print(round(result.score, 2))
```

```
attachment
attachment: attachment(ok)
0.95
```

Put it into the real cascade in front of the others — the point of a cheap step
is that it runs first:

```python
from autosxtract import Cascade, NativeStep, OCRStep, get

cascade = Cascade(steps=[AttachmentStep(), NativeStep(), OCRStep(get("paddle"))])
```

## Call the shared gate, do not write your own

`evaluate` is the **single acceptance criterion** in this pipeline
([ADR 0002](../adr/index.md#0002-one-acceptance-criterion)). A step that invents its
own floor approves itself by one criterion while the cascade refuses it by
another, and both are then right.

If you genuinely need a different criterion, inject it — `OCRStep` takes
`gate=` and `scorer=` — rather than adding a second one alongside the first.

## Declaring a step expensive

```python
class MyExpensiveStep:
    name = "my_expensive"
    expensive = True
```

That one class attribute makes the cascade:

1. run the [five vetoes](../gates.md#the-five-vetoes) **before** you, so you are
   never called on a photograph, a blank sheet, or a document two engines have
   already read the same way;
2. submit your output to the [replacement gate](../gates.md#the-replacement-gate)
   **after**, which compares it against the text already in hand and **discards**
   it if it corrupted a digit, came back partial, or is a marker loop.

It is read with `getattr` and is deliberately **not** on the `Step` protocol:
making it mandatory would force every three-line step to declare that it is
cheap.

Whatever your step puts in `attempt.details` under `pages_sent`,
`pages_answered` and `failed_batches` is what the replacement gate uses to detect
a partial transcription. Filling them is how a truncated reading is caught
instead of silently replacing a complete one.

## What a step must not do

**Do not read `readings` or `texts`.** They are on the concrete `Context` and
deliberately **off** the `DocumentContext` protocol —
`tests/test_interfaces.py::test_the_step_view_withholds_the_cascade_s_own_evidence`
asserts it. They are the blackboard the consensus and agreement gates decide on,
and those gates belong to the cascade. A step reading them would decide on
evidence it did not gather.

**Do not rasterise on your own.** Call `ctx.images()`. It caches, and every step
of a document must be handed the *same* pixels — two engines compared on
different renders are a measurement of preprocessing, not of engines.

**Do not raise for an expected condition.** A missing binary, a network failure,
a file that is not a PDF: all of those are refused attempts with a reason in
words. `Cascade.extract` promises never to raise for a missing engine or an
unreadable PDF, and a step is the only thing that can break that promise.

**Do not write a vague reason.** `"refused"` tells the reader nothing.
`"only 4 useful words outside the stamp"` tells them what to change. The reason
is what `Result.provenance` is made of.

## Steps that talk to a network

They exist, and they are **explicit by construction**. `DoclingStep` and
`VLMStep` in `steps/remote.py` require `url` in the constructor: there is no
discovery through an environment variable, no built-in default and no fallback to
a known endpoint. `Config` has not a single host, port, URL or credential field,
and `tests/unit/test_config.py::test_no_field_points_at_a_network` keeps it that way.

```python
import os
from autosxtract import Cascade, NativeStep, OCRStep, ScreeningStep, get
from autosxtract.steps.remote import DoclingStep, VLMStep

cascade = Cascade(steps=[
    NativeStep(),
    OCRStep(get("paddle")),
    DoclingStep(url="http://docling:5001", token=os.environ["DOCLING_TOKEN"]),
    ScreeningStep(),
    VLMStep(url="https://my-endpoint/v1", model="PaddleOCR-VL-0.9B",
            token=os.environ["VLM_TOKEN"]),
])
```

`pip install 'autosxtract[remote]'` brings `httpx`. **Installing turns nothing
on.** Both are `expensive = True`. A network failure becomes a refused attempt
with the reason in the provenance, never an exception, and the `token` never
appears in a `repr`, a log or a result.

This is not a style preference. An earlier version of this pipeline reached the
OCR engine on a Mac over a reverse SSH tunnel, and that worker going down
**silently degraded the text** — 488 documents re-extracted down the worse path,
19.5 minutes instead of 4.9, 28,239 characters lost, and nobody noticed until
someone checked. **A remote step nobody declared must not exist.**
See [ADR 0001](../adr/index.md#0001-no-networking-in-the-default-cascade).

`steps/docling_local.py` is the useful counterexample: the same engine, running
inside the process, with no networking at all. It stays out of the default
cascade for a **different** reason — ~2 GB of models and ~4 s per document [on a 72-core Xeon CPU](../architecture.md#the-machine-every-number-was-measured-on) — and
that is why it lives outside `remote.py`. Confusing "expensive" with "remote"
would make the invariant meaningless.

```python
from autosxtract.steps.docling_local import LocalDoclingStep

docling = LocalDoclingStep(workers=2, ocr_engine="rapidocr")     # build ONCE
cascade = Cascade(steps=[NativeStep(), OCRStep(get("paddle")), docling])
```

Loading is lazy, so assembling the cascade and finding the PDF is native costs
nothing. But **reuse the instance**: one step per document pays the whole model
load on every file.

## Before you ship it

```python
from autosxtract import Step
assert isinstance(MyStep(), Step)
```

Then drive it over a fake context with no PDF at all — copy `FakeContext` from
`tests/test_interfaces.py`. If your step cannot run against twenty lines of fake,
it is asking for more than the protocol gives it, and that is the finding.
