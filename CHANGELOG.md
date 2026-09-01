# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two conventions specific to this project, which are what make the entries worth
reading a year later:

- **An entry that changes a number carries the measurement that fixed it.** Not
  "raised the threshold" but the old value, the new one, the corpus, and what
  improved and what regressed. Every default in `config.py` is annotated that
  way in the code; the changelog says the same thing to whoever is reading from
  outside.
- **An entry says what it prevents.** The library's job is to not lose text
  silently, so "fixed X" is only half an entry — the other half is which
  failure it stops.

The canonical version lives in `autosxtract/_version.py`, and the docstring
above it explains what kind of change the bump is. Releases are tagged `vX.Y.Z`
and published by `.github/workflows/release.yml`, which refuses to run if the
tag and that file disagree.

**This file is load-bearing, not a courtesy.** The release workflow reads the
`## [X.Y.Z]` section out of it and puts it at the top of the GitHub Release, so
a tag pushed with no section for its version — or with an empty one — fails the
build before anything is uploaded. Under that human section GitHub appends the
mechanical one it generates from pull request labels, configured in
`.github/release.yml`. The two are not redundant: this file is the *reason*, the
generated list is the *receipt*. The whole procedure is in `RELEASING.md`.

## [Unreleased]

### Added

- Project governance: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  this changelog, `.github/CODEOWNERS`, YAML issue forms (including
  **Extraction quality**, which collects the provenance string, the attempt
  list and the page profile instead of the document), a pull request template
  that blocks a changed threshold with no measurement behind it, and
  `.github/dependabot.yml` with weekly grouped updates.
- Workflows: `release.yml` (PyPI Trusted Publishing on a tag, with a clean-venv
  install-and-import smoke test before the upload), `docs.yml` (MkDocs to
  GitHub Pages) and `notebooks.yml` (headless execution, so a notebook cannot
  rot into documentation that lies). The last two guard on `hashFiles` and pass
  quietly until the directories they build exist.
- `RELEASING.md` — the release flow end to end, plus the runbooks for the two
  settings pages nobody can diff: the PyPI collaborators and Trusted Publisher
  registration, and the repository's About block. Both were tribal knowledge,
  which is the state in which a project loses the ability to ship the day its
  one publisher is unavailable.
- `.github/release.yml` — the categories GitHub groups the generated release
  notes into, keyed on the labels in `.github/labels.yml`. Ordered so that
  `quality` outranks `enhancement`: a pull request carrying both is a quality
  fix that also added a knob, and filing it under "Added" buries the half that
  matters.
- `scripts/github_project_setup.sh` — topics, description, website, feature
  toggles and secret-scanning push protection, applied by `gh` from values kept
  in the repository. It reads the current state first and prints only the
  differences, refuses without `gh`, without authentication or without admin,
  and has a `--dry-run`. Running it twice changes nothing the second time.

### Changed

- `release.yml` now creates the GitHub Release after — never before — the PyPI
  upload succeeds, attaching the *same* wheel and sdist that were published
  rather than rebuilding them, so the files on the Release page describe what is
  on PyPI. It also refuses to build a tag with no matching `CHANGELOG.md`
  section, and marks a PEP 440 pre-release as a pre-release instead of letting
  it take the "Latest" badge that `pip install` users read as the current
  version.
- `ci.yml` gained a least-privilege `permissions: contents: read` block and
  concurrency cancellation on pull requests only — runs on `main` are kept,
  because the per-commit record of which commit was green is what a bisect
  stands on.

## [0.4.0] — 2026-08-31

The engines themselves became configurable. **Minor:** the registry's `get`
gained options and `Config` gained a field; nothing existing breaks.

### Added

- `get(name, **options)` passes constructor arguments through to the engine.
  Engines were built by `factory()` with **no arguments**, which made PP-OCR's
  tier, the INT8 flag, the ONNX thread count, the preprocessing and the
  execution providers unreachable from an assembled cascade. A knob that exists
  in the constructor and cannot be turned from outside is not a knob.
- `Config.engine_options` — the same reach, for whoever configures a cascade
  rather than constructing the engine by hand.

### Fixed

- **`quantized` stopped lying.** It was read only by the `paddleocr` backend;
  with rapidocr — the backend most installs actually get — it was accepted,
  reported as INT8, and FP32 ran. It now uses the `int8/` weights when they are
  on disk and **says so** when they are not. Silently reporting a
  quantisation that did not happen is the same class of defect as a silent
  fallback to a worse engine: the result looks right and the provenance lies.

### Changed

- Engine instances are cached by `(name, options)` rather than by name alone.
  Asking for INT8 must not hand back the FP32 model somebody else built first —
  the cache was a correctness bug, not only a performance detail.

---

Versions before 0.4.0 predate this file. Their history lives in the docstring
of `autosxtract/_version.py` and in the git log.

[Unreleased]: https://github.com/liafacom/AutosXtract/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/liafacom/AutosXtract/releases/tag/v0.4.0
