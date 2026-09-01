# How this suite is organised

The suite is split by **what a test is allowed to touch**, not by what it is
about. That distinction is the whole point, and it is worth being blunt about
why, because the obvious alternative — one directory per package, `tests/quality`
next to `tests/engines` — is the arrangement this replaced.

A test that opens a PDF, loads a model and asserts on the final text tells you
something failed. It does not tell you *what*. When the same file also holds
twenty pure functions over strings, a red suite is a research project. Splitting
by reach means the first thing a failure tells you is how far the damage
travelled: a red `unit` is one function; a red `integration` with a green `unit`
is a seam between layers, which is a different bug with a different fix.

The slices also run at different prices. `tests/unit` is under a second and is
what you run on every save. `tests/integration` renders pages and, on a cold
machine, downloads OCR weights. Keeping those apart is what makes the fast loop
actually fast.

```
tests/
  conftest.py        the synthetic PDFs — the only conftest, deliberately
  unit/              one module under test, no rendering, no engine
  integration/       several layers at once: the cascade, engines, workers
  contract/          protocol conformance and substitutability
  packaging/         the repository's own guarantees
```

## Running one slice

```bash
.venv/bin/python -m pytest tests/unit          # 229 tests, < 1 s — the edit loop
.venv/bin/python -m pytest tests/integration   #  69 tests — the seams
.venv/bin/python -m pytest tests/contract      #  38 tests — the published contracts
.venv/bin/python -m pytest tests/packaging     #  15 tests — what ships
.venv/bin/python -m pytest                     # 351 — everything, and what CI means
```

`make test-unit` and `make test-integration` wrap the first two. A bare `pytest`
still runs the whole suite: the split is addressed by path, never by an
`addopts` default that would let a slice quietly stop running.

## `tests/unit` — one module, and nothing behind it

**For:** a single module answered by its own code. Text in, verdict out. The
gates, the score, the lexicon, the prose rebuilder, the pattern catalogue, the
`Config` validation, the parallelism arithmetic, the engine base class driven by
a ten-line fake.

**Not for:** anything that renders a page, loads a model, assembles a `Cascade`
or reaches the network. A synthetic PDF may be *parsed* here — `test_pdf_pages`
cuts one into a subdocument — but the moment pixels are produced the test has
left the slice.

The rule is deliberately about mechanism rather than speed. "Fast" is a
consequence, not the criterion; a test that assembles a cascade and happens to
be quick because the engine was already cached still belongs next to the ones
that are slow for the same reason.

## `tests/integration` — where the layers meet

**For:** two or more layers exercised together. The cascade descending a
synthetic PDF with fake engines; the engine registry against what this machine
actually has installed; the remote steps inside a cascade with their client
replaced; the Vision worker's protocol; the header reader checked against a real
render.

**Not for:** a fact one module can answer alone. `VLMStep(url="")` raising is a
constructor contract and lives in `unit/test_remote_steps.py`; what the *default
cascade* does with a remote step lives here. When a file straddles that line it
gets split, and both halves keep their reason for existing in the docstring.

Fake engines are the norm here, and they are not a convenience: an engine of ten
lines descending the real cascade is the proof that the contract works. The real
engine installed on the machine is exercised in `test_real_engine.py`, which
skips itself when there is none — the default CI case.

Nothing in this slice opens a socket. `test_remote.py` replaces the client
before one can be built, which is also what keeps it running in a bare `[dev]`
environment where `httpx` is not installed.

## `tests/contract` — the protocols, and things written only to them

**For:** `autosxtract/interfaces.py` made load-bearing. Two jobs, and they are
different: **conformance** — every implementation the library ships still
satisfies the protocol it claims, by `isinstance` and by signature — and
**substitutability** — a hand-written fake that implements *only* the protocol,
inheriting nothing and importing nothing concrete, has to work.

The second is the one that earns the directory. "A new engine is a class with
one method" is a claim about extensibility, and a claim about extensibility is
only true if somebody has extended it from the outside. The fakes here inherit
nothing on purpose; deriving them from `OCREngine` would test the base class,
which is a different thing and is already covered in `unit/test_engine_base.py`.

**Not for:** behaviour. That an engine reads a page correctly is integration;
that it *declares* `read_page` at all, and hands over a score on the scale the
containment layers judge in, is a contract — see `test_geometry.py`.

## `tests/packaging` — what leaves the repository

**For:** guarantees about the artifact rather than the code. `test_packaging.py`
reads the **installed** package's metadata, because a wrong PEP 508 marker hides
exactly there and not in the source file; `test_documentation.py` reads the
README and checks every public name it promises still exists.

**Not for:** anything about extraction. These two files are the only place a
test is allowed to know that a repository, a wheel or a README exists.

The reason they are separated rather than deleted: documentation that ages
silently is worse than no documentation, because readers trust it. A rename that
breaks the README should break CI, not a user.

## Markers

Declared in `pyproject.toml` under `[tool.pytest.ini_options]`, and enforced by
`--strict-markers` so a typo is an error rather than a marker nobody selects.

| Marker | Means | Deselect with |
| --- | --- | --- |
| `slow` | Loads or downloads a real OCR model. Seconds, and a network on a cold machine. | `-m "not slow"` |
| `apple` | Can only conclude anything on macOS with Vision. | `-m "not apple"` |
| `paddle` | Needs the PP-OCRv6 stack really installed, not merely importable. | `-m "not paddle"` |

`apple` is the one that has to be right. A declared marker deselects nothing on
its own: the Linux CI runs `pytest -m "not apple"`, and a test whose assertions
only execute on Apple hardware is, off Apple, a test that passes by being inert.
Marking it is how it stops counting as green somewhere it never ran. The macOS
job runs the suite unfiltered, which is the only place those tests mean
anything.

A marker is not a way of avoiding a failure. `test_the_default_install_yields_a_cascade_with_ocr`
is *meant* to fail where the default install was honoured and the engine is
missing anyway; `paddle` on it says "I took the engine out on purpose", not "do
not look".

## Fixtures

There is **one** `conftest.py`, at the root of `tests/`. The four slices differ
in what they may touch, not in what they are handed, so a per-directory conftest
would either duplicate a fixture that already exists or hide one slice's setup
from the others. A new fixture earns its own directory conftest only when one
slice needs it and the others must not have it — and that has not happened yet.

Fixtures that belong to a single file stay in that file: the pattern
catalogue's `_clean_catalogue`, which resets the process-wide packs, is one, and
moving it to a conftest would silently apply it to tests that never asked.

## No real document, ever

Every PDF in this suite is generated on the fly by PyMuPDF, from invented text
(CLAUDE.md section 9). Nothing is read from disk and nothing is committed.

This is not squeamishness. A suite that depends on one archive file cannot run
in CI, cannot be shared, and — the part that actually costs time — stops telling
you whether a failure is in the code or in that one file. Synthetic fixtures make
a red test a statement about the code.

The rule extends to **identifiers in comments and docstrings**. The examples here
use case numbers, tax IDs and company IDs with a deliberately **invalid** check
digit, so `scripts/privacy_check.py` stays quiet and nobody has to decide, case
by case, whether a number belongs to somebody. It has caught a real one already.

If you need a new document shape, add a fixture to `tests/conftest.py` that
builds it — text in the top half, image in the bottom, as the existing ones do —
and say in its docstring which failure it reproduces. A fixture whose reason for
existing is not written down is one nobody dares delete.
