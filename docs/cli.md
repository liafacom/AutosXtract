# Command line

Three subcommands. `extract` is the one you script; `diagnose` is the one that
saves you the most time, because when the text comes out worse than expected the
cause is almost always a missing engine.

```bash
autosxtract extract document.pdf            # text on stdout, provenance on stderr
autosxtract extract folder/*.pdf --json out.json
autosxtract diagnose
autosxtract download-models
autosxtract --version
```

## `extract`

```
autosxtract extract [FILES...] [options]
```

**The stdout/stderr split is deliberate.** Without `--json`, stdout carries the
text and nothing else, so `autosxtract extract x.pdf > x.txt` does what you
expect; the provenance line goes to stderr, where it does not pollute the
redirection.

**One bad file does not cost the batch.** A file deleted between the shell's glob
and the read becomes a `FAILED` line on stderr and an `{"file": …, "error": …}`
entry in the JSON, and the run continues. This matters most with `--json`, where
the write happens after the loop: document 3 of 500 failing used to throw away
the two already extracted and write nothing at all.

| flag | default | what it does |
|---|---|---|
| `--dpi N` | `150` | Render resolution for OCR. 150 is the floor that preserves numeric anchors — at 100 DPI preservation falls to 85.5%, losing dates and tax numbers in 35 of 60 documents. |
| `--engines a,b` | decided by the machine | Explicit engine order. Names come from the registry: `vision`, `ocrmac`, `paddle`, `onnx`, `tesseract`. Naming an unavailable engine is not an error — it becomes a refused attempt with the reason. |
| `--det TIER` | `tiny` | PP-OCR detector tier: `tiny`, `small` or `medium` (1.5M / 7.7M / 34.5M parameters). |
| `--rec TIER` | the detector's | PP-OCR recogniser tier. Most of the quality lives in the recogniser, so `--det tiny --rec medium` is usually the better trade. |
| `--rec-dir PATH` | — | Directory of your own fine-tuned recogniser. |
| `--no-layers` | layers on | Turns line containment off. Measured on 895 pages, leaving it on is worth entity recall 0.902 → 0.921 **and** p50 latency 298 → 236 ms, so turn it off only to measure it. |
| `--routes` | off | Classify each page (`table` / `stamped_digital` / `degraded` / `normal`) into the provenance. It does not change the extraction — it is a signal for whoever consumes the output. |
| `--no-fix-orientation` | correction on | Stops the pre-OCR orientation fix. It turns a sideways page upright before any engine sees it, using Tesseract's OSD (the `[veto]` extra). Without that extra the correction is skipped and **the reason goes to the provenance** — it does not fail quietly. |
| `--parallelism N` | decided by the machine | Threads per document. An explicit number is obeyed; see [ADR 0010](adr/index.md#0010-parallelism-is-decided-by-the-machine) before raising it. |
| `--json FILE` | — | Write the full result of every document — `Result.to_dict()` plus the file name — to this file instead of printing text. |

The numbers in that table were measured on [a 72-core Xeon with no GPU](architecture.md#the-machine-every-number-was-measured-on),
with PP-OCRv6 on the CPU. The ratios hold; the absolute values are your
machine's business.

!!! warning "`--det`, `--rec` and `--rec-dir` replace the cascade"

    Any of the three builds `Cascade(config, steps=[NativeStep(), OCRStep(PaddleEngine(...))])`
    — a two-step cascade with **that** engine, on every platform, Vision
    included. That is the point (measuring a model swap without writing code),
    but it means `autosxtract extract x.pdf --det small` on a Mac is not
    measuring the Mac's default cascade.

**Exit codes.** `0` all files extracted, `1` at least one file failed (the count
goes to stderr), `2` no files were given. An empty result is **not** a failure:
extraction is a process with an uncertain outcome, and a document that legitimately
has no readable text exits `0` with an empty text and a provenance that explains
itself.

## `diagnose`

```bash
autosxtract diagnose
```

Reports the version, the machine, the usable cores, the automatic parallelism,
every registered engine with a `[x]`/`[ ]` and the reason, the assembled cascade,
and where the models are. An `orientation:` line says whether sideways pages are being turned upright,
and — the case that used to be invisible — whether the correction was asked for
and the OSD is not installed. Two engine annotations are worth knowing about:
`single queue:
ignores threads` (the engine sets `scales_with_threads = False`) and `no line
geometry: the layers do not run` (the engine implements only the coarse contract,
so [containment](gates.md#the-containment-layers) is unavailable). With no OCR
engine at all it prints a warning, because a scanned PDF will then come out
empty — correctly, and visibly.

[The full annotated output →](getting-started.md#autosxtract-diagnose-and-how-to-read-it)

## `download-models`

```bash
autosxtract download-models
```

Fetches the PP-OCRv6 tiny weights (~10 MB) into `~/.cache/autosxtract` and prints
each file with its size. Exits `1` with the failure on stderr — the message is
this command's product.

For a closed environment, run it where there is network and point
`AUTOSXTRACT_MODELS` at the copied directory. Extraction works without the
weights: the engine falls back to rapidocr's embedded model and says so in
`diagnose`.
