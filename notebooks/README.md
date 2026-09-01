# notebooks/ — the guided tour

Seven notebooks, in order, each standing on its own and each assuming the one
before it. Together they are the fastest honest path from `pip install` to
"I can add an engine to this".

They exist because prose documentation drifts and nobody notices. **A notebook
that no longer runs is documentation that lies**, so `make notebooks` executes
all of them headlessly and CI is where that gets checked. If you change the
library and a notebook stops running, the notebook is the bug report.

## The order, and what each one teaches

| # | notebook | what it teaches |
|---|---|---|
| 01 | `01_quickstart.ipynb` | Install check, `autosxtract diagnose` and how to read **which cascade this machine has**, a synthetic PDF, `extract`, and `Result.provenance` / `Result.to_dict()`. |
| 02 | `02_the_cascade_step_by_step.ipynb` | Every step run by hand on one shared `Context`: unwrap → native → OCR → screening. A step refused **whose text keeps competing** (CLAUDE.md §5), the attempts table, and the contest at the bottom. |
| 03 | `03_quality_and_the_gates.ipynb` | The acceptance gate against the replacement gate (§4) — a threshold against a concrete text, and what happens to the refused. The score and its reasons. The **same text measured with and without the stamp stripped**, which is the 227-false-successes lesson. Consensus, agreement, and the containment layers on an engine with geometry. |
| 04 | `04_configuration_and_measurement.ipynb` | The `Config` fields that matter, read out of the code with the measurement each carries. Parallelism resolved as a *method*. Then one knob measured **twice** — at the engine and at the cascade — because an isolated measurement has already lied in this project (§8). |
| 05 | `05_writing_your_own_engine.ipynb` | A toy `Engine` written against the Protocol alone — no base class, no import of a shipped engine. `isinstance` conformance, what breaks when a method is missing, the optional geometry contract and what it buys, registration, and watching it descend the real cascade. |
| 06 | `06_writing_your_own_step.ipynb` | The same for `Step`, including a step exercised against a twenty-line fake with no PDF at all. Then `expensive = True`: the five vetoes before it, the replacement gate after it, and an observed interaction between the gates worth knowing before you rely on either. |
| 07 | `07_another_language_or_domain.ipynb` | A small TOML pattern pack, loaded three ways (`Config(patterns=…)`, `AUTOSXTRACT_PATTERNS`, `Config.language`), merging **entry by entry** over the bundled packs, and a domain term recognised that the pt-BR pack misses — including the false success it manufactures. |

## Running them

Jupyter is **deliberately not a project dependency**. It is a large toolchain to
impose on everyone who only wants to run the tests, and nothing the library does
needs it. Install it into the project venv when you want it:

```
.venv/bin/python -m pip install nbconvert ipykernel
```

Then, from the repository root:

```
make notebooks          # executes every notebook headlessly, in order
```

`make notebooks` says so and exits 0 when `nbconvert` is missing, so a green
`make` never depends on whether you happen to have installed it.

One notebook at a time, which is what to run while editing:

```
.venv/bin/python -m nbconvert --to notebook --execute --stdout \
    notebooks/03_quality_and_the_gates.ipynb > /dev/null
```

Non-zero exit means a cell raised. That is the only check that matters here.

## The rules these notebooks follow

**They must execute end to end on a machine with no Apple hardware.** Apple
Vision is the first OCR step on macOS and does not exist anywhere else, so a
notebook that needs it is a notebook that fails on every CI runner this project
has. Where an engine may be absent, the cell says which one and continues —
which is the library's own rule (§3): a missing engine is never an exception,
`available()` returns `(False, reason)`, and *the absence of a tool is not
evidence about the document*. The notebooks model that rather than describing
it.

**No real document, ever** (§9). Every PDF is generated in-cell by PyMuPDF with
invented text, the same technique `tests/conftest.py` uses. The repository has a
privacy scanner that enforces this, and it validates Brazilian tax IDs, company
IDs and case numbers **by their check digit** — so any identifier invented for
an example here has a deliberately **invalid** check digit. That way the scanner
stays quiet and nobody has to decide, case by case, whether a number belongs to
somebody. Before committing:

```
.venv/bin/python scripts/privacy_check.py .
```

**No network.** Nothing here downloads anything. The one connection the package
can make is the one-off fetch of the PP-OCRv6 weights, and the notebooks never
trigger it: they ask `available()` first and explain themselves if the answer is
no.

**Committed with outputs cleared.** Outputs make notebook diffs unreadable and
are the easiest way to embed data in the repository by accident — a rendered
page, a transcript, a path from somebody's machine. Clear them before
committing:

```
.venv/bin/python -m nbconvert --clear-output --inplace notebooks/*.ipynb
```

or, equivalently, `--ClearOutputPreprocessor.enabled=True`. The consequence is
that reading a notebook on GitHub shows you the reasoning and the code but not
the numbers; **run it** to get those, which is the point.

## House style

The markdown cells explain **why**, and cite the measurement that settled it.
They do not restate what the next cell obviously does. If a paragraph could be
deleted without losing a reason, it should be — and if a number appears without
saying what it was measured on, it is not yet a reason.
