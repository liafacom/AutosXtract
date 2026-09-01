# Testing

The suite is the specification of everything this documentation claims. If a page
here says a gate discards refused text, `tests/unit/test_rejection.py` is what
makes that true tomorrow.

**The reference is [`tests/README.md`](https://github.com/liafacom/AutosXtract/blob/main/tests/README.md)**,
in the repository. It is written by the people who own the suite and it says what
may and may not go in each slice. This page does not repeat it — it says what the
layout *is*, how to run it, and which tests are load-bearing for the promises made
on the other pages.

## The layout

The suite is split by **what a test is allowed to touch**, not by what it is
about:

```
tests/
  conftest.py        the synthetic PDFs — the only conftest, deliberately
  unit/              one module under test, no rendering, no engine
  integration/       several layers at once: the cascade, engines, workers
  contract/          protocol conformance and substitutability
  packaging/         the repository's own guarantees
```

The obvious alternative — one directory per package — is the arrangement this
replaced. Splitting by *reach* means the first thing a failure tells you is how
far the damage travelled: a red `unit` is one function; a red `integration` with
a green `unit` is a seam between layers, which is a different bug with a
different fix.

```bash
.venv/bin/python -m pytest tests/unit          # the edit loop, under a second
.venv/bin/python -m pytest tests/integration   # the seams
.venv/bin/python -m pytest tests/contract      # the published contracts
.venv/bin/python -m pytest tests/packaging     # what ships
.venv/bin/python -m pytest                     # everything — and what CI means

make test              # the whole suite
make test-unit
make test-integration
make all               # lint + typecheck + test + privacy, the pre-push gate
```

A bare `pytest` still runs everything: the split is addressed by path, never by
an `addopts` default that would let a slice quietly stop running.

## Markers

`addopts` carries `--strict-markers`, so an unregistered marker is an error
rather than a typo that silently deselects nothing. Three are declared in
`pyproject.toml`: `slow`, `apple`, `paddle`. `tests/README.md` has the table and
what CI does with each.

## The tests this documentation leans on

Every claim on the other pages is pinned somewhere. When you change behaviour,
these are the files that will tell you the documentation has gone stale:

| what it guards | test |
|---|---|
| the README's API names, CLI subcommands, flags and extras all exist | `tests/packaging/test_documentation.py` |
| `Config` has no host, port, URL or credential field | `tests/unit/test_config.py::test_no_field_points_at_a_network` |
| every shipped implementation still satisfies its [protocol](interfaces.md), by `isinstance` **and by signature** | `tests/contract/test_interfaces.py` |
| `interfaces` imports nothing at runtime, so the [layering](architecture.md#the-layer-rule) is a fact | `tests/contract/test_interfaces.py::test_the_module_pulls_in_nothing_at_import_time` |
| `DocumentContext` withholds `readings` and `texts` from steps | `tests/contract/test_interfaces.py::test_the_step_view_withholds_the_cascade_s_own_evidence` |
| the `Gate` protocol restates no measured threshold of its own | `tests/contract/test_interfaces.py::test_the_gate_contract_repeats_no_threshold_of_its_own` |
| an engine and a step written from the protocol alone descend the real cascade | `tests/contract/test_interfaces.py` (`FakeEngine`, `FakeStep`, `FakeContext`) |
| the platform marker (install-time) | `tests/packaging/test_packaging.py` |
| the runtime registry (availability) | `tests/integration/test_shipped_engines.py`, `tests/unit/test_registry.py` |
| the [pattern catalogue](extending/patterns.md): resolution order, overlay, validation at load | `tests/unit/test_patterns.py` |
| Layer 2 never reuses the main OCR instance | `tests/unit/test_paddle.py` |
| remote steps require an explicit `url` | `tests/unit/test_remote_steps.py`, `tests/integration/test_remote.py` |

## Two rules that will bite you

### No real document, ever

The fixtures are generated on the fly by PyMuPDF with invented text
(`tests/conftest.py`). `.gitignore` blocks `*.pdf` at the root and pre-commit
blocks any added file above 1 MB. **A failing test must point at the code, not at
one specific archive file.**

That applies to **identifiers inside comments and docstrings** too. Documenting a
measurement with the case number it was made on looks harmless and is not:
`scripts/privacy_check.py` caught a real case number that had made its way into
this library's own examples, with a valid check digit. The examples use numbers
with an **invalid** check digit on purpose — that way the scanner stays quiet and
nobody has to decide case by case whether a number exists. See
[ADR 0011](adr/0011-no-real-document-in-the-repository.md).

The scanner runs as the **first** pre-commit hook, before the style ones, and on
every CI push. The order is deliberate: a commit blocked on formatting costs
thirty seconds; a real document published has no undo.

!!! warning "pre-commit inspects what will be committed"

    It stashes unstaged changes before running. Fixing a file without `git add`
    leaves the hook looking at the old version.

### The suite must pass on a bare `pip install -e ".[dev]"`

That is how most people will have the library, and it is what the CI quality
matrix checks on 3.11, 3.12 and 3.13. A test that quietly needs an engine turns
somebody else's CI red for a reason they cannot act on: mark it, or make it skip
itself with a reason.

## The guard rails

A handful of tests exist to protect an invariant rather than a behaviour: no
network field on `Config`, no real document in the repository, no protocol that
has drifted from what the code requires, no engine that raises instead of
reporting. What each one guards, and what to do when one of them goes red, is
written down once in
[`.github/GUARDRAILS.md`](https://github.com/liafacom/AutosXtract/blob/main/.github/GUARDRAILS.md).
Read it before deleting or `xfail`-ing anything in the table above — a guard rail
that is inconvenient is doing its job.

## Writing a test for an extension

The payoff of the [interfaces](interfaces.md) is that you do not need a PDF, an
engine or PyMuPDF to exercise a step or an engine you wrote:

```python
from autosxtract import Engine, Step, DocumentContext

assert isinstance(MyEngine(), Engine)
assert isinstance(MyStep(), Step)
```

Copy `FakeContext` and `_assert_signature` from `tests/contract/test_interfaces.py`.
`isinstance` against a runtime-checkable Protocol only verifies that the names
exist; the signature comparison is what catches the drift that motivated the
interfaces module in the first place.

## Documentation and notebooks

```bash
make docs        # builds this site if mkdocs.yml is present
make notebooks   # executes every notebook headlessly
```

The site is built with `--strict` in CI, which turns two silent kinds of rot into
failures: a link to a page that was renamed, and a page that exists but is in no
navigation entry, so it is reachable only by guessing the URL.

```bash
.venv/bin/pip install mkdocs mkdocs-material     # NOT project dependencies
.venv/bin/python -m mkdocs serve                 # live reload while writing
.venv/bin/python -m mkdocs build --strict        # what CI runs
```

The pins live in `docs/requirements.txt`, which the docs workflow prefers over
its own fallback list. Neither ever enters `pyproject.toml`: `pip install
autosxtract` must not drag a documentation toolchain onto a user's machine.

A notebook that no longer runs is documentation that lies, which is why `make
notebooks` executes them rather than linting them.
