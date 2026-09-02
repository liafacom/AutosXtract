# AutosXtract

**Every document descends steps from the cheapest to the most expensive and stops
at the first one that produces acceptable text.**

That is the whole idea, and it works for a reason that has nothing to do with
models: the distribution is uneven. Measured across two real archives, 31% of
documents already carry a text layer and cost 13.4 ms; only the rest pay the
~400 ms of an OCR engine. Collapsing the cascade into one good model was tried
and measured — 6.2 minutes against 4.44 for 935 documents. Both figures are
CPU-against-CPU on [a 72-core Xeon with no GPU](architecture.md#the-machine-every-number-was-measured-on);
an accelerator narrows the gap and does not touch the 31%.

```python
from autosxtract import Cascade

cascade = Cascade()
result = cascade.extract_file("document.pdf")

result.text          # the extracted text
result.provenance    # 'vision: native(quality 0.42 below 0.75) -> vision(ok)'
```

The engine arrives already chosen by the machine, and the cascade is a *chain*
rather than a single pick:

| platform | cascade |
|---|---|
| macOS | `native → vision → paddle` |
| Linux, Windows | `native → paddle` |

## What makes it different from a wrapper around an OCR engine

**The provenance is the product, as much as the text is.** Every result carries
every step that ran and the reason each refusal happened. "The system extracted
the text" is not an auditable answer; "the native step read 41 characters and
was refused on density, Vision read 3,812 and passed" is. That sentence is
`Result.provenance`, and it is not optional.

**There is exactly one notion of adequate extraction.** The step that thinks it
solved the document and the cascade that decides whether to pay for the next one
ask the same question with the same code — [`quality/gate.py::evaluate`](gates.md).
Two competing criteria in one pipeline is the defect that function exists to
stop repeating.

**No document leaves the machine.** No worker, no tunnel, no endpoint, and
`Config` has not a single host, port, URL or credential field. The only traffic
the package can generate is **model weights, once** — `engines/models.py`, and
the Hugging Face fetch that `engines/paddle.py` and `engines/onnx.py` do on
first load with their heavier backends installed. That is not a preference:
an earlier version of this pipeline reached the OCR engine over a reverse SSH
tunnel, and the worker going down *silently degraded the text* — 488 documents
re-extracted down the worse path, 28,239 characters lost, and nobody noticed
until someone checked. See [ADR 0001](adr/index.md#0001-no-networking-in-the-default-cascade).

**A missing tool degrades, it does not raise.** An engine that will not load
answers `(False, reason)`, the step goes inert, and the reason reaches the
provenance and `autosxtract diagnose`. The absence of a tool is not evidence
about the document.

**Every threshold carries the measurement that fixed it.** The
[configuration reference](configuration.md) is generated from the model, so the
number and its justification cannot drift apart.

## When NOT to use it

This library was built for one job and is honest about the rest.

- **You need layout, tables or reading order as structure.** AutosXtract returns
  *text* with a per-page trust report, not a document tree. A dedicated table
  structure model was measured against the cheap engine with containment layers
  on 17 table pages: 0.699 value recall against **0.797**, at 6–29 s per page
  against 0.27 s. Across 895 pages, switching to the table model's output won on
  one page. If you need cells and spans, use a layout model — and read
  [ADR 0008](adr/index.md#0008-the-domain-patterns-are-data) first, because the answer depended
  on the archive.
- **Your PDFs are clean, born-digital and all have a text layer.** Then
  `page.get_text()` is the whole job and this library is 300 MB of overhead for
  a 13 ms step you could call yourself.
- **You want one model everywhere, tuned once.** The cascade's value is that it
  *stops early* on most documents. If your archive is uniformly scanned and
  uniformly hard, the cheap steps never fire and you are paying for gates that
  never save anything.
- **You need a service.** There is no server here, and none is coming: the
  networking that does exist is opt-in per step and must be constructed by hand
  ([`steps/remote.py`](extending/step.md)). Wrapping this in your own service is
  fine; expecting the library to be one is not.
- **Your corpus is not Brazilian legal text and you are not willing to write a
  pattern pack.** The regexes and word lists that judge quality describe *this*
  corpus. They are externalised as data and swapping them is a documented,
  supported operation — [a new pattern pack](extending/patterns.md) — but the
  defaults will misjudge a corpus they were not measured on.
- **You need a guaranteed answer.** Extraction is a process with an uncertain
  outcome. `Cascade.extract` never raises for a missing engine or an unreadable
  PDF; it returns an empty `Result` that explains itself. If your caller needs
  an exception, it has to check `result.empty` and raise its own.

## Where to go next

<div class="grid cards" markdown>

- **[Getting started](getting-started.md)** — install, read `diagnose`, first
  extraction, and what `Result.provenance` is telling you.
- **[Command line](cli.md)** — the three subcommands, every flag, and the exit
  codes.
- **[Python API](api.md)** — `Cascade`, `Result` and the shape of `to_dict()`:
  what you receive.
- **[Architecture](architecture.md)** — the five layers, the import direction,
  and where a decision is made versus where it is measured.
- **[Quality gates](gates.md)** — acceptance versus replacement, the five
  vetoes, the containment layers, consensus and agreement.
- **[Files that are not PDFs](formats.md)** — the 128 documents that arrive as
  `.pdf` and are not, and the opt-in step that reads them.
- **[Extending](extending/engine.md)** — a new engine, a new step, a new
  pattern pack, and the eleven protocols behind them.
- **[Decision records](adr/index.md)** — the eleven decisions that have already
  been paid for once.

</div>

Contributors should read [`CONTRIBUTING.md`](https://github.com/liafacom/AutosXtract/blob/main/CONTRIBUTING.md)
in the repository — it covers the development environment, the pins, the review
checklist and the release process, none of which is repeated here.
[`.github/GUARDRAILS.md`](https://github.com/liafacom/AutosXtract/blob/main/.github/GUARDRAILS.md)
lists the checks that exist to protect an invariant rather than a behaviour, and
what to do when one of them goes red.
