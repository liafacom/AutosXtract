# Contributing to AutosXtract

Two things to read before anything else, because they explain most of the
rules below.

`CLAUDE.md` records the decisions that are **not** obvious from the code and
that have already cost something once — a silent degradation, a segfault, 682
documents extracted as empty. Every rule in this file traces back to one of
them. The README documents the public surface and, in *What has been measured
and does not work*, the ideas that were tried and refuted with numbers; it will
save you from spending a weekend on something already settled.

The short version of the project's temperament: **a number changes only with a
measurement, and no real document ever enters this repository.**

---

## 1. Setting up

```bash
git clone https://github.com/liafacom/AutosXtract
cd autosxtract
make setup          # == ./scripts/bootstrap.sh
```

One command, idempotent, Linux and macOS. It creates `.venv`, installs the
package with the `dev` extra against the pins in `constraints/dev.txt`,
installs the pre-commit hooks, and finishes by running `autosxtract diagnose`.

That last line is not decoration. What the library does to a document depends
on which engines the machine actually has, and the cascade is a **chain**, not
a choice:

```
macOS            native -> vision -> paddle
Linux/Windows    native ->           paddle
```

Those are different pipelines. A bug that reproduces on one may not exist on
the other, and a cascade that is one step short does not announce itself — so
read the diagnosis once at the start, and paste it into any issue you open. It
also says why each *absent* engine is absent, which is the commonest cause of a
surprising result.

Variants, when the defaults do not fit:

```bash
./scripts/bootstrap.sh --extras veto        # plus the Tesseract witness
PYTHON=python3.11 ./scripts/bootstrap.sh    # reproduce one CI matrix leg
make venv                                   # environment only: no hooks, no diagnose
```

`make` with no target prints the list of targets, which is the fastest way to
find out what exists.

The `Makefile` runs `.venv/bin/python` by path and never activates anything —
an activated shell is state carried between commands, and state is what turns
"it works here" into a bug report nobody can reproduce. Every target refuses
with a sentence if that interpreter is missing. If you keep environments
elsewhere, `VENV=/somewhere/else ./scripts/bootstrap.sh` works, and the
underlying commands are all one line and listed below.

### The pins

`constraints/dev.txt` is a photograph of an environment that was working, and
`bootstrap.sh` installs against it so that two people, on two machines, get the
same versions. The runtime ranges in `pyproject.toml` stay **open** on purpose:
a library that pins its runtime dependencies is unusable downstream.

Regenerate the photograph only after deliberately upgrading something —

```bash
make lock           # rewrites constraints/dev.txt from the current venv
```

— and never to "fix" a failing install. A photograph of a broken environment is
worth nothing.

### Optional pieces

The default install gives you the whole cascade this machine can run, which is
enough for almost all work. The extras exist to ask for *the other* engine:

```bash
.venv/bin/pip install -e ".[dev,veto]"        # pytesseract — the veto witness
.venv/bin/pip install -e ".[dev,onnx]"        # onnxtr — a second cheap engine
.venv/bin/pip install -e ".[dev,paddleocr]"   # the full PP-OCR backend
.venv/bin/pip install -e ".[dev,remote]"      # httpx, for the remote steps
.venv/bin/pip install -e ".[dev,docling]"     # docling in-process (~2 GB of models)
```

`veto` also needs the Tesseract binary on the PATH
(`apt install tesseract-ocr`, `brew install tesseract`). On macOS, `apple`
brings `ocrmac` as a safety net for a broken pyobjc — Vision itself arrives
with the base install through a PEP 508 marker.

### Before every push

```bash
make all            # lint + typecheck + test + privacy
```

That is exactly what CI's `quality` job runs, in the order in which a failure
is cheapest to read. `make lint` runs **both** `ruff check` and `ruff format
--check`: they are different checks, and running only the first leaves CI red
with your tree green.

## 2. The architecture, in the order the code runs

```
cascade.py   orchestrates
steps/       composes engine + quality — does not know which engine is behind it
engines/     reads pixels             — does not know what a cascade is
quality/     knows only text          — does no I/O
pdf/         knows only the file      — does not know what an engine is
```

**If an import crosses an arrow backwards, the design has broken.** That is not
tidiness. It is the boundary that let the OCR step be a *single*, generic step
serving Vision and PP-OCRv6 alike, and it is what lets each layer be tested
without the others.

Two more shapes worth carrying in your head before you touch anything:

**There is one acceptance criterion.** `quality/gate.py::evaluate` answers, for
every step, whether the text suffices. The step that thinks it solved the
document and the cascade that decides whether to pay for the next one ask the
same question with the same code. Two competing notions of "adequate
extraction" in one pipeline is the defect that function exists to prevent
repeating.

**Two gates, and the difference is what happens to the refused text.** The
acceptance gate (`quality/gate.py`) asks "is this good enough to stop?" —
something refused there **stays in the contest**, because it may still be the
best reading the document has. The replacement gate (`quality/rejection.py`)
runs only after an expensive step and asks "is it better than what I already
had, and did it lose nothing?" — something refused there is **discarded**.
Confusing the two cancels the second gate, because volume usually sits on the
wrong side: the corrupted text is precisely the longest one.

---

## 3. Adding an engine

The README's *How to add an engine* has the code. Do not re-read it here; read
it there, and then read these three obligations, which are what a review will
actually check.

1. **A missing engine is never an exception.** `available()` returns
   `(False, reason)` in words, the step goes inert, the cascade moves on. The
   absence of a tool is not evidence about the document — treating "I have no
   OCR" as "the page is empty" switches the pipeline off in silence. The reason
   must reach the provenance and `autosxtract diagnose`.

2. **Confidence does not arbitrate quality.** Measured across 60 documents
   audited by four reviewers: engine confidence does not separate a good
   reading from an unsafe one — there was an unsafe document at confidence 100.
   It enters only as a floor against degenerate output.

3. **Implement `read_page` if the backend exposes geometry.** The detailed
   contract is optional and `None` is the honest answer without it, but without
   geometry the containment layers do not run, and they are the pipeline's
   cheapest measured gain: entity recall 0.902 → 0.921, with latency *falling*.
   `Transcription.pages` is filled only when **every** page answered in detail,
   because a partial list would make the layers operate on a different document
   from the one transcribed.

And one trap that cost real text: **never reuse the main OCR instance to
recognise a crop.** Calling `rapidocr` with `use_det=False` turns detection off
permanently on that object; the next whole-page read returned 1 line where it
had returned 56, and a document came out with 1 character instead of 3,900.
`PaddleEngine._recognizer()` keeps a separate instance, and
`tests/unit/test_paddle.py` pins it. Generally: a third-party object with
per-instance state is a shared resource, and a path that reconfigures it needs
its own copy.

`priority` is preference order, lowest first, and the existing values come from
comparative measurement on the same sample: 10 Vision, 20 PP-OCRv6, 90
Tesseract. A new engine's number needs the same justification.

---

## 4. Adding a step

Again, the code is in the README's *How to add a step* — a step is any object
with `name` and `run(ctx) -> StepResult`. The parts to get right:

`StepResult` separates the **verdict** (does the cascade stop?) from the
**candidate** (does this text enter the contest?). Returning a refusal without
a candidate throws away text that might be the best reading there is —
discarding refused text left 682 documents with zero characters while the PDF
had a text layer.

`expensive = True` changes the machinery around your step: the five vetoes in
`quality/vetoes.py` run before it, and the replacement gate runs after. Declare
it if the step costs seconds or money.

**If your step opens a socket, it does not go in the default cascade.** The
`url` is a constructor argument with no default, there is no discovery through
an environment variable, and there is no fallback to a known endpoint —
`steps/remote.py` is the model. `Config` has not a single host, port, URL or
credential field, and `tests/unit/test_config.py::test_no_field_points_at_a_network`
enforces that. The reason is in `CLAUDE.md` §1 and it is not hypothetical: a
remote OCR worker went down and the pipeline degraded *silently* — 488
documents re-extracted down the worse path, 28,239 characters lost, nobody
noticed until somebody checked.

Note that "expensive" and "remote" are different properties.
`steps/docling_local.py` is entirely local and stays out of the default cascade
for the other reason: ~2 GB of models and ~4 s per document.

---

## 5. Adding a pattern pack

Names, docstrings and messages are **English**, so the library is usable
outside Brazil. The regexes and word lists are **Portuguese**, because they
describe the corpus: the conformity stamp, the enclitic pronouns, the forensic
abbreviations, the identity-card markers, the legal vocabulary.

That is the adaptation seam, and it is now a real one rather than a promise.
The patterns are **data**, in TOML, under `autosxtract/patterns/`:

```
autosxtract/patterns/__init__.py     the loader, the overlay, the resolution order
autosxtract/patterns/data/base.toml  nothing that describes a language
autosxtract/patterns/data/pt_br.toml the corpus this library was measured on
```

Read the module docstring in `autosxtract/patterns/__init__.py` before writing
a pack — it is the specification, and it explains the resolution order, why the
format is TOML rather than JSON, and what the `why` field on each entry is for.
Do not learn it from this file; this file only tells you what a review will
check.

A user pack **overrides entry by entry** and the bundled packs stay underneath,
so a pack that replaces one entry is a legitimate, complete pack — it never has
to restate the rest. Point at it with the environment variable, or install one
programmatically:

```bash
AUTOSXTRACT_PATTERNS=/path/to/my_pack.toml   # a file, or a directory of *.toml
```

```python
from autosxtract import patterns

mine = patterns.load("/path/to/my_pack.toml")
patterns.use(mine)                  # process-wide; patterns.reset() undoes it
patterns.available_packs()          # what ships in the box
```

Four things a review will look for:

1. **Every entry carries its `why`.** That text travelled here from the code
   along with the pattern, and it is the measurement that fixed it. An entry
   whose `why` no longer holds is an entry to **delete**, not to quietly
   adjust.
2. **`base.toml` describes no language.** Control bytes, glyph-index runs,
   digit runs, markdown structure. The moment a Portuguese word appears there,
   the layering stops meaning anything and the seam is closed again.
3. **A language-specific rule outside this package is a design regression.** If
   you find yourself writing `re.compile` with a Portuguese word in
   `quality/`, that is the bug — the whole point of the catalogue is that the
   ten modules that used to hold those calls no longer do.
4. **A pattern that fires on one archive and not another is a pack, not a new
   built-in.** Widening the bundled `pt_br` patterns needs a count: how many
   documents gained, how many lost, out of how many.

The lexicon is the other half of the seam and works the same way — a floor you
are expected to replace:

```python
from autosxtract import Config
from autosxtract.quality.lexicon import Lexicon

mine = Lexicon.from_texts(Path("validated").glob("*.txt"))   # minimum=3
Config(lexicon=mine)
```

`from_texts` drops what appears fewer than three times on purpose: an OCR error
rarely repeats three times, and without that cut the lexicon learns the very
errors it exists to detect. Build it from **validated** text only. With a small
lexicon more correct text falls into `suspect` — the safe side of the error,
but it escalates pages for nothing.

---

## 6. Tests

The suite is split by what a failure MEANS, not by what it touches. A red
`tests/unit/` is a defect in a function; a red `tests/contract/` is a promise
this package makes to other code, broken; a red `tests/packaging/` is a defect
users hit and maintainers do not, because the source tree hides it.

```
tests/unit/          test_gate.py test_rejection.py test_vetoes.py     the gates
                     test_routing.py test_selection.py test_scoring.py orchestration and contest
                     test_engine_base.py test_paddle.py test_registry.py engines and the registry
                     test_stamp.py test_lexicon.py test_prose.py       the Portuguese patterns
                     test_config.py test_platform.py                   the invariants
tests/contract/      test_interfaces.py test_geometry.py               the extension points
tests/integration/   test_cascade.py test_assembly.py test_worker.py   the whole thing, assembled
                     test_real_engine.py test_shipped_engines.py       a real engine, when present
tests/packaging/     test_packaging.py test_documentation.py           the wheel, and the README's promises
tests/conftest.py                                                      synthetic fixtures
```

```bash
make test                                        # the whole suite
make test-unit                                   # tests/unit
make test-integration                            # tests/integration
.venv/bin/python -m pytest tests/unit/test_gate.py  # one file
.venv/bin/python -m pytest -k gate -q            # by name
.venv/bin/python -m pytest -m "not slow" -q      # skip the long ones
.venv/bin/python -m pytest --cov=autosxtract --cov-report=term-missing
```

`make test-unit` and `make test-integration` run the two halves separately.
Reach for the first while you are working — it is the fast one, and it is where
a defect in a function shows up — and for the whole suite before you push.

`addopts` already carries `--strict-markers`: an unregistered marker is an
error, not a typo that silently deselects nothing. The three registered markers
are declared in `pyproject.toml`:

| marker | meaning | how CI treats it |
|---|---|---|
| `slow` | long-running | runs everywhere; deselect locally with `-m "not slow"` |
| `apple` | needs macOS with Vision — never runs on the Linux CI | every Linux job deselects it (`-m "not apple"`: `quality`, `with-ocr` and `pinned`); the `apple` job on macOS runs it |
| `paddle` | needs the PP-OCRv6 stack really working, not merely importable | runs everywhere — no job deselects it |

Two things to know about, because both have already been written down wrong
here:

`-m "not apple"` is the **only** filter any job applies. `paddle` and `slow`
deselect nothing anywhere, so a test carrying either runs on every runner. That
is deliberate for `paddle` — `tests/packaging/test_packaging.py` documents its
paddle test as meant to *fail* rather than skip when the engine is missing,
because a silently skipped packaging test proves nothing — but it means marking
a test `paddle` does not make it optional.

And there is no "bare core" job. `pip install -e ".[dev]"` already brings
rapidocr and onnxruntime: they are mandatory runtime dependencies on every
platform, not an extra. What separates the `quality` matrix from `with-ocr` is
that `with-ocr` installs `libgl1`, without which `import cv2` raises and the
engine goes unavailable. If you need a test to depend on the engine actually
working, assert on `available()` rather than on what is installed.

**Fixtures are synthetic and generated on the fly**, by PyMuPDF, with invented
text — see the top of `tests/conftest.py`. This is not a preference either: a
failing test must point at the code, not at one specific archive file, and no
real document may enter the repository. `.gitignore` blocks `*.pdf` at the
root, and pre-commit blocks any added file above 1 MB.

A bug fix arrives with a regression test that fails without the fix. If you
cannot reproduce it synthetically, say so in the pull request — usually the
document's *shape* (a large image in a region with no text, a rotated page, a
stamp band) is what matters, and that is buildable.

### Documentation and notebooks

```bash
make docs           # builds docs/ if it exists and carries a builder
make notebooks      # executes every notebook headlessly
```

Both directories exist now, so neither target is a no-op any more. Neither
builder is a dev dependency, though — `mkdocs` lives in `docs/requirements.txt`
and `nbconvert` is not declared anywhere — so on a venv built by `make setup`
each target tells you the one command that installs what it needs and stops.
That is deliberate: imposing a documentation toolchain and a Jupyter stack on
everybody who only wants to run the tests costs more than the sentence does.

```bash
.venv/bin/python -m pip install -r docs/requirements.txt   # for make docs
.venv/bin/python -m pip install nbconvert ipykernel        # for make notebooks
```

Notebooks are committed with their **outputs cleared**. Two reasons, and the
second is the serious one: regenerated outputs produce a diff on every run, and
a stored output is exactly where a fragment of a real extracted document ends
up committed by accident. CI executes them and throws the results away; that is
the check that they still run.

---

## 7. Changing a number

This is the rule the project cares most about.

Every threshold in `config.py` carries, in its comment, the measurement that
fixed it. Changing a number without measuring is the mistake this project tries
to make difficult, and a pull request that moves a default without a
measurement in its body will be sent back — not out of ceremony, but because
nobody, including its author six months later, can tell a calibrated number
from a guessed one.

And the methodological lesson, which is worth more than any particular
threshold: **an isolated measurement has already lied here.** Turning off
Vision's language correction improved anchor preservation across 60 documents
(+4) and *worsened* it across the whole cascade (−227 anchors, −4,981
characters over 935 documents), because the worse text failed the gate and fell
to worse engines. What decides is the cascade's behaviour, not one engine's
output.

Measure both, on your own archive:

```bash
.venv/bin/python scripts/compare_engines.py ~/archive --n 30 --seed 11
```

It reports per engine **and** per cascade, side by side, which is precisely the
pair that reverses conclusions. Its output contains text from your documents —
do not commit it, do not paste it into an issue.

Then: the new number, the old one, the corpus size, what improved and what
regressed, all four in the comment beside the constant *and* in the pull
request. The template has a table for it.

**And if the number is a time, it carries its machine.** A latency, a
throughput, a "X min against Y" — none of them means anything without the
hardware that produced it, and a reader who cannot falsify a number is entitled
to ignore it. The reference environment is one section,
[The machine every number was measured on](docs/architecture.md#the-machine-every-number-was-measured-on);
a timing measured there links to it, and a timing measured anywhere else states
that machine where it appears. Say explicitly whether an accelerator was
involved: this project's Linux numbers are CPU with no GPU and no CUDA path,
and Apple Vision's are the Neural Engine — writing "on CPU" over the whole set
would be the convenient sentence and the false one.

---

## 8. Privacy

This library reads private legal documents, and this repository sits a few
directories away from the real ones. That proximity is the whole threat model:
one distracted `git add -A`.

```bash
make privacy                                              # scan the tree
.venv/bin/python scripts/privacy_check.py . --staged      # only the git index
.venv/bin/python scripts/privacy_check.py . --json        # machine-readable
```

`pre-commit` runs the scan **first**, before the style hooks, and the order is
deliberate: a commit blocked on formatting costs thirty seconds, a real
document published has no undo. The scanner validates Brazilian tax IDs,
company IDs and case numbers by their **check digit** rather than their shape,
because a scanner that shouts at every 14-digit number is switched off in the
first week.

Three things that follow, and that have each cost time already:

- **Identifiers in comments and docstrings count.** Documenting a measurement
  with the case number it was taken on looks harmless and is not. The scanner
  caught a real case number, with a valid check digit, that had made its way
  into this library's own examples. Examples use numbers with a **deliberately
  invalid** check digit — that way the scanner stays quiet and nobody has to
  decide, case by case, whether a number is real.
- **`pre-commit` stashes your unstaged changes.** It inspects what will be
  committed, not your working tree. Fixing a file without `git add` leaves the
  hook looking at the old version — and passing.
- **Never attach a document to an issue.** GitHub attachments are public and
  survive the issue's deletion. The *Extraction quality* issue form exists to
  collect the provenance string, the attempt list and the page profile instead,
  which identify the defect without publishing anybody's case file.

---

## 9. Commits, branches, pull requests

Branch off `main`. `main` is protected: everything lands through a pull
request.

Commit messages: a short imperative subject, ideally with the area in front,
and a body that says **why** when the why is not obvious.

```
gate: raise min_useful_words from 8 to 12

Measured over 412 documents from a filings archive: at 8, 37 stamp-only
pages were accepted as extracted and never reached OCR. At 12 that drops
to 3, with no document losing text (anchors unchanged, chars -0.2%).
```

Squash-merge is the default, so the pull request title becomes the commit on
`main` — write it as the commit message it will be.

The pull request template is a checklist of this project's actual rules, not a
formality: the measurement behind any changed number, tests that fail without
the fix, `make all` green, no private data added, no networking introduced into
the default cascade, docs and notebooks updated, public API impact, and which
interface or extension point the diff touches. Filling it honestly is what
makes review fast; a "N/A" on the measurement row when a number moved is what
makes it slow.

### Review

`.github/CODEOWNERS` requests **@ArthurSilvaDantas** and **@edsontm** on every
pull request, with extra lines naming the files where a mistake is silent
rather than loud: the engine contract, the cascade, the two gates, the vetoes,
`config.py`, the pattern catalogue, the privacy scanner, the workflows and the
packaging.

Owner review is only *mandatory* if branch protection says so — the settings an
admin has to enable are written at the top of `CODEOWNERS`.

The status checks that must be green are the ones listed in
`.github/rulesets/main.json`, and that file is the only place they are listed.
This paragraph used to name three of them — `quality`, `with-ocr` and
`packaging` — while the ruleset required fourteen, which left `privacy` and
`history-scan`, the two checks that prevent something irreversible, out of the
list an admin transcribes by hand. A required-check list copied into prose goes
stale the first time a job is added, and nothing goes red when it does.

---

## 10. Releasing

Version numbers are semantic, and `autosxtract/_version.py` is the single
source — `pyproject.toml` reads it through `[tool.hatch.version]`. Note that
the file's docstring is used to explain *what kind* of change the bump is, and
why; keep that habit, it is the most useful release note the project has.

1. Bump `__version__` in `autosxtract/_version.py`, and write the reason above
   it as the existing entries do.
2. Move `## [Unreleased]` in `CHANGELOG.md` into a dated section for the new
   version.
3. Open a pull request with both, get the owner review, merge.
4. Optionally build locally first — `make build` puts the wheel and the sdist
   in `dist/`, and tells you how to install the `build` package if it is
   missing (it is release tooling, deliberately not a dev dependency).
5. Tag the merge commit and push the tag:

   ```bash
   git tag -a v0.4.1 -m "0.4.1"
   git push origin v0.4.1
   ```

`.github/workflows/release.yml` takes it from there: it refuses to continue if
the tag and `_version.py` disagree (PyPI never lets a filename be reused, so a
mismatched upload is permanent), builds the wheel and the sdist, installs the
wheel into a **clean virtualenv** and imports it — the check that catches a
subpackage missing from the wheel, which is invisible from inside the
repository — runs `twine check` and the privacy scan, and only then publishes.

Publishing uses **PyPI Trusted Publishing**: an OIDC identity minted for that
job, verified against a publisher PyPI has been told to trust, exchanged for a
credential that lives for minutes. There is no API token stored in this
repository and there must never be one. The upload waits on the `pypi`
environment, so a reviewer can be required at that point too.
