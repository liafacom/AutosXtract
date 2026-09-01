# Every target runs the venv's interpreter BY PATH and never activates it. An
# activated shell is state carried between commands, and state is exactly what
# turns "it works here" into a bug report nobody can reproduce.
PY := .venv/bin/python
VENV := .venv
CONSTRAINTS := constraints/dev.txt

# `make` with no argument prints the map instead of doing something. A newcomer
# who guesses a target wrong should learn what exists, not run the build.
.DEFAULT_GOAL := help

.PHONY: help setup bootstrap venv lock test test-unit test-integration lint fmt \
        typecheck diagnose privacy hooks build docs notebooks clean all require-venv

help:  ## Print this list
	@echo "autosxtract — make targets"
	@echo
	@grep -hE '^[a-zA-Z0-9_-]+:.*##' $(MAKEFILE_LIST) \
	  | sed -e 's/:.*##/\t/' \
	  | awk -F'\t' '{ printf "  \033[1m%-17s\033[0m %s\n", $$1, $$2 }'
	@echo
	@echo "  First time here:  ./scripts/bootstrap.sh   (same as: make setup)"

# ── getting there from a fresh clone ─────────────────────────────────────
# One command, idempotent, Linux and macOS. It ends with `diagnose` on purpose:
# what the library does to a document depends on which engines the machine has,
# and a cascade that is one step short does not announce itself.
setup:  ## Create the venv, install [dev] against the pins, install hooks, diagnose
	./scripts/bootstrap.sh

bootstrap: setup  ## Alias for `setup`

# Just the environment: no git hooks, no diagnose. Useful in a container layer
# or when re-syncing after someone bumped the pins.
venv:  ## Create/refresh the venv only (no hooks, no diagnose)
	./scripts/bootstrap.sh --no-hooks --no-diagnose

# Rewrites constraints/dev.txt from THIS venv. Run it after deliberately
# upgrading something, never to "fix" a failing install: the pins are a
# photograph of an environment that was working, and a photograph of a broken
# one is worth nothing. The runtime ranges in pyproject.toml stay open — a
# library that pins its runtime dependencies is unusable downstream.
lock: require-venv  ## Regenerate constraints/dev.txt from the current venv
	$(PY) scripts/lock.py

require-venv:
	@[ -x $(PY) ] || { \
	  printf '\nno %s yet.\n\n  make setup     # creates it and shows the cascade\n\n' "$(PY)"; \
	  exit 1; }

# ── the checks CI runs ───────────────────────────────────────────────────
test: require-venv  ## Run the whole suite
	$(PY) -m pytest

# BOTH commands, as in CI: `ruff check` does not verify formatting, and running
# only it leaves CI red with the local tree green.
lint: require-venv  ## ruff check + ruff format --check (both, as in CI)
	$(PY) -m ruff check . && $(PY) -m ruff format --check .

fmt: require-venv  ## Reformat with ruff
	$(PY) -m ruff format .

typecheck: require-venv  ## mypy over the package
	$(PY) -m mypy autosxtract

# Prints what THIS machine can run. Worth more than any log when an extraction
# result surprises you.
diagnose: require-venv  ## Show the cascade this machine actually has
	$(PY) -m autosxtract.cli diagnose

# The only check that prevents a leak rather than merely a red CI.
privacy: require-venv  ## Scan for sensitive artefacts (tax IDs, case numbers)
	$(PY) scripts/privacy_check.py .

hooks: require-venv  ## Install the pre-commit hooks
	$(PY) -m pre_commit install

# ── the split suite ──────────────────────────────────────────────────────
# The suite is split four ways — unit / integration / contract / packaging —
# and these two targets name the slices you actually reach for while working:
# `unit` is the sub-second loop, `integration` is what costs real time. The
# directory guard stays because a slice you can run is worth more than a target
# that explodes when someone works from an older tree.
test-unit: require-venv  ## Run tests/unit — the fast loop (~0.7 s)
	@if [ -d tests/unit ]; then \
	  $(PY) -m pytest tests/unit; \
	else \
	  echo "tests/unit does not exist yet — the suite is still flat. Running: make test"; \
	  $(PY) -m pytest; \
	fi

# `-m "not slow"` is deliberately NOT applied here: integration is where the
# slow marks live, and a target that silently skipped them would be a target
# that proves nothing.
test-integration: require-venv  ## Run tests/integration — cascade, engines, workers
	@if [ -d tests/integration ]; then \
	  $(PY) -m pytest tests/integration; \
	else \
	  echo "tests/integration does not exist yet — nothing to run."; \
	fi

# ── artefacts ────────────────────────────────────────────────────────────
# `build` is not in the dev extra on purpose: it is release tooling, and the
# people who need it know it. The message says how to get it instead of dying
# on an import error.
build: require-venv  ## Build the wheel and the sdist into dist/
	@$(PY) -c 'import build' 2>/dev/null || { \
	  echo "the 'build' package is missing (it is release tooling, not a dev dependency):"; \
	  echo "  $(PY) -m pip install build -c $(CONSTRAINTS)"; exit 1; }
	$(PY) -m build

# dist/ is rebuilt from source and never committed (.gitignore blocks it): a
# stale wheel in the tree is the one artefact that can make a packaging test
# pass against code that no longer exists.
clean:  ## Remove caches, build artefacts and dist/ (never the venv)
	rm -rf dist build *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	find . -path ./$(VENV) -prune -o -name '__pycache__' -type d -print0 | xargs -0 rm -rf
	@echo "the venv is left alone on purpose: rebuilding it re-downloads ~200 MB"
	@echo "of ONNX Runtime. Remove it by hand if that is really what you want."

# ── documentation and notebooks ──────────────────────────────────────────
# Both directories are being created right now by other hands. Until they land,
# these targets say so and exit 0 — a green `make` must not depend on which
# branch of someone else's work happens to be merged.
docs:  ## Build docs/ (no-op until docs/ exists)
	@if [ ! -d docs ]; then echo "docs/ does not exist yet — nothing to build."; \
	elif [ -f mkdocs.yml ]; then $(PY) -m mkdocs build; \
	elif [ -f docs/conf.py ]; then $(PY) -m sphinx docs docs/_build/html; \
	elif [ -f docs/Makefile ]; then $(MAKE) -C docs html; \
	else echo "docs/ exists but carries no builder (mkdocs.yml, conf.py or Makefile) — nothing to build."; fi

# Executing them is the only check that matters: a notebook that no longer runs
# is documentation that lies. Jupyter stays out of the dev extra — it is a large
# toolchain to impose on everyone who only wants to run the tests.
notebooks:  ## Execute notebooks/ headlessly (no-op until notebooks/ exists)
	@if [ ! -d notebooks ]; then echo "notebooks/ does not exist yet — nothing to run."; \
	elif ! $(PY) -c 'import nbconvert' 2>/dev/null; then \
	  echo "notebooks/ exists but nbconvert is missing (not a dev dependency):"; \
	  echo "  $(PY) -m pip install nbconvert ipykernel"; \
	else \
	  set -e; for nb in notebooks/*.ipynb; do \
	    [ -e "$$nb" ] || continue; \
	    echo "executing $$nb"; \
	    $(PY) -m nbconvert --to notebook --execute --stdout "$$nb" > /dev/null; \
	  done; fi

# The pre-push gate: everything CI will run on the quality job, in the order in
# which a failure is cheapest to read.
all: lint typecheck test privacy  ## Everything CI checks — run before pushing
