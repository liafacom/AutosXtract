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

Nothing yet.

## [0.6.0] — 2026-09-02

A review pass over the whole tree. Every entry below is a case where the code
and a written invariant disagreed, and the invariant was the one that had been
measured — so the code moved.

### Fixed

- **Per-page routing no longer drops the native half of a mixed PDF.**
  `OCRStep` rasterised only the pages without a text layer and then offered
  *those pages alone* as its candidate, so the result was either the native text
  without the scanned attachment or the attachment without the pages around it,
  never the union — and when the step was accepted the contest never saw the
  other half either. On the shape this library was built for (29 native pages
  plus a 10-page attachment) that is 29 pages of text gone with nothing in the
  provenance. `DoclingStep` had `_reassemble` for exactly this; `OCRStep` now
  has its counterpart, aligned by page index and never by splitting the joined
  text.
- **`Config.min_score` reaches the acceptance gate.** `evaluate` has a quality
  branch; `OCRStep` computed the score for the contest and passed neither
  `score=` nor `min_score=`, leaving that branch unreachable in production.
  Junk that cleared the word and density floors stopped the cascade, and the
  better engine underneath it never ran.
- **`NativeStep` decides with `quality.gate.evaluate`**, like every other step,
  instead of with its own `score_structure >= native_accept_score`. The two
  disagreed on exactly the input the gate was written for: a page whose text
  layer is only the conformity stamp scores 0.90 as *structure* and escalates on
  the gate. That is the defect §2 exists to prevent, and it was living in the
  step.
- **`Transcription.pages` no longer comes back misaligned.** The guard compared
  the detailed pages against the pages that *answered* rather than against the
  pages *sent*, and a page that raised is counted in neither — so the equality
  survived the hole and the list arrived compacted. `layers.apply` pairs it
  positionally against the images, so line geometry was cropped out of the wrong
  sheet. New `Transcription.page_texts` keeps one slot per page sent.
- **The cheap vetoes run before the expensive witness again.** `assess_vetoes`
  took the local reading as a value, so Python evaluated a full local OCR — with
  its 300 DPI recovery track — before the first 40 DPI pixel statistic. It now
  accepts a callable and invokes it only if the cheap vetoes did not fire.
- **A missing veto witness reaches the provenance.** With Tesseract off the
  PATH, vetoes 3 to 5 silently never fired and every escalated document paid the
  expensive step, with a record byte-for-byte identical to a run where the
  witness had approved.
- **`VisionWorkerEngine` divides line confidence by 100**, as its own docstring
  said it did. Without it every line scored 40–95 on a 0–1 scale: nothing was
  ever illegible or suspect, the structural signature rule was dead, and Layer 2
  could never beat the original.
- **`register()` accepts an engine with no docstring.** The description fell
  back to `splitlines()[0]` on a possibly empty list, so the library's advertised
  extension point raised `IndexError` at import — and the module's own worked
  example is a class with no docstring. It also broke the package under `-OO`.
- **`LocalDoclingStep.available()` builds its converter pool under a lock.**
  `extract_batch` hands the same step to every worker thread, so N documents
  built N pools of ~2 GB each, N-1 of them orphaned and resident.
- **`pdf.pages.subdocument` closes the target document on every path**, not only
  on success.
- **`OCRStep` writes `pages_sent` / `pages_answered` into its details**, the
  names the replacement gate reads. Only the remote steps wrote them, so the
  gate's truncation branch was unreachable from any OCR step marked expensive.

### Changed

- `steps.layers.apply` returns `(text, report, page_texts)`. The joined text
  cannot be split back into pages, and the caller that has to put a page back in
  its place needs the aligned list.
- `pdf.ink._sample` takes `pdf_lock` itself rather than relying on both callers
  holding it, so §6 stops depending on every caller of a private helper
  remembering the rule.
- CI: `mypy` is a hard gate. It carried `continue-on-error: true` while four
  documents listed types among the required checks.
- CI: `release.yml` runs the suite on the tree the **tag** points at. The tag
  ruleset constrains the tag's name, not what it points at.
- `CODEOWNERS` and `CONTRIBUTING.md` stop listing required checks by hand and
  point at `.github/rulesets/main.json`. The hand-written list named 3 of 14 and
  omitted both leak gates.
- `make docs` reports the missing `mkdocs` with the install line instead of
  dying on `No module named mkdocs`; `docs` and `notebooks` gained
  `require-venv`.
- `SECURITY.md` records that `dependency-review` is reported rather than
  required; `CLAUDE.md` §1 now lists every networking site in the package rather
  than claiming there are two.

### Added

- Tests for what had none: the PyMuPDF lock (§6), the privacy scanner's own
  check-digit validation (§9), the vetoes reached *through* the cascade (§13),
  the partial-fill guard on `Transcription.pages` (§15), and the construction
  branch of the crop recogniser (§16) — the previous test assigned `_crop_rec`
  itself, so the branch that makes the instance separate never ran.
- `test_page_order_is_preserved` asserts the order of the text. It asserted
  `engine.n >= 1` on a one-page fixture.
- Fixtures `pdf_scanned_multipage` (four *distinguishable* pages) and
  `pdf_mixed`.
- `tests/unit/test_native.py` — the native step had no test file at all, which
  is why the §2 change above went in unmeasured the first time.

### Fixed — second pass

An audit of the fixes above found two of them wrong, and both are recorded here
rather than quietly amended: a fix that introduces a defect is worse than the
bug, because it arrives with a test asserting it.

- **`OCRStep` no longer reports the routed page count as `pages_sent`.** The
  replacement gate reads that name as *how much of the document this text
  covers* — `remote.py` writes it from a render of the whole document. Under
  per-page routing they are different numbers, so `document_pages > pages_sent`
  was true on every mixed PDF: the gate called a complete document a partial
  transcription and **discarded** the candidate, throwing away the attachment
  the merge had just recovered.
- **`record_reading` gets the engine's own text, not the merged one.** Splicing
  the native layer into an engine's reading made that engine agree with the
  native step by construction, and the agreement gate ended the cascade on
  self-confirmation before the second engine ran. The candidate carries the
  merged text; the blackboard carries what the engine actually saw.
- `_merge_native` honours `Config.use_native` and reports `native_merge` on
  every path, including the ones that decline to merge.
- `NativeStep` no longer passes `score_structure`'s value under a `min_score`
  documented and measured for `score_text`; the score dimension is already
  covered, more strictly, by `native_accept_score`. It also no longer prints
  "page with no visual content" as the provenance of a good extraction.
- `veto:witness` is not emitted when `veto_engine=None` — a documented off
  switch is not a degradation, and a note on every document is a note nobody
  reads.
- **The RTF brace repair no longer promotes trailing padding to document body.**
  It took "the last `}` in the file" as the root close, so padding left over
  from carving the RTF out of a PKCS#7 envelope inverted the rule: the genuine
  close was dropped as surplus and the padding became content. The
  discriminator is now RTF control words rather than braces — the body of the
  measured case contains no `{` at all.
- **`Context.images(indices=[])` no longer poisons the render cache.** An empty
  list is falsy, so it shared a key with "render every page" while rendering
  nothing; every later `images()` on that document returned `[]` and the
  provenance blamed the engines.
- `engines/models.py` coerces dictionary entries to `str` inside the `try`. A
  character dictionary is mostly digits and unquoted digits parse as ints, so
  the join raised `TypeError`: `download` lost its deliberate error message and
  the cleanup that removes the weights never ran, silently re-paying the
  download every run.
- `anchors.punctuated` bounds each digit group. Unbounded `\d+` is quadratic on
  a contiguous digit run — 3.5 s at 16,000 digits — and `anchors` runs over the
  whole document with no cap, twice per replacement-gate comparison. Now 0.009 s.
- `docling_json` guards `page_no`, the primary sort key, as it already guarded
  the bounding box. One string page number made the whole conversion fail, in
  the module that exists *because* the markdown came back empty.
- `cli.py extract` no longer aborts the batch on one bad path, and writes the
  `--json` output even when some files failed; it exits 1 if any did.
- `scripts/lock.py` memoises `walk` on `(name, extras)` — no cycle guard meant
  `RecursionError` on a cyclic dependency and exponential re-walking of a
  diamond.

### Added — second pass

- Tests that catch what the first pass's tests did not: the isolation of
  `interfaces` against a *relative* import and against one placed after the
  `TYPE_CHECKING` block (the previous check compared `sys.modules` after the
  test file had already imported the package, so it could see nothing); a
  `pdf_lock` serialisation test with a yield point in the critical section (the
  previous one passed 200/200 with the lock replaced by a no-op); the lock sweep
  extended to `steps/native.py` and `engines/tesseract.py`, which open documents
  outside `pdf/`; the privacy sweep extended from `*.py` to every file the
  scanner reads; `page_texts` for a page that answered *blank*, not only one
  that raised; the crop recogniser pinned on both backends; and a network
  blocklist that strips plurals, so `docling_hosts` and `worker_ports` cannot
  walk past a list written in the singular.

### Fixed — orientation

- **A page that arrives sideways is turned upright before OCR, by default.**
  `Config.fix_orientation` was `False`, so the correction that already existed
  and already sat in the right place — the render cache, before any engine sees
  a pixel — never ran. What that costs is a reading judged by every gate
  downstream as if the text were the document's fault: the acceptance gate, the
  score and the vetoes all measure an input defect none of them can see. The
  cost is one OSD pass per **rasterised** page, so a document resolved by the
  native text layer pays nothing. **This number is not measured on this
  project's archive** — the field description says so, and says how to measure
  it. Turn it off with `--no-fix-orientation` if your scans are known upright.
- **`fix_orientation=True` without Tesseract no longer does nothing in
  silence.** `detect` returned `0` on `ImportError`, so a run with the OSD
  working and a run without it left byte-for-byte identical evidence — the same
  shape as the veto witness that never fired, and what §3 forbids: degrading
  without breaking is right, degrading without warning is not. New
  `orientation.available()` answers `(can_run, reason)` like an engine, the
  reason reaches `Result.provenance` and `autosxtract diagnose` grew a line for
  it.
- **A rotation that DID happen is now recorded.** The call site was
  `images = [fix(i)[0] for i in images]` — the degrees were computed and thrown
  away, so a corrected page and an untouched one were indistinguishable in the
  record. `DocumentContext.orientation` carries `{"rotated": {page: degrees}}`,
  keyed by the **document's** page number rather than the batch's, because under
  per-page routing the engine is handed pages 3 and 7, not 0 and 1.

### Changed — orientation

- **`DocumentContext` gained `orientation`.** A step reads it to report what
  happened to the page before the engine saw it. This widens the contract: a
  context implemented outside the library needs the attribute to satisfy
  `isinstance`. The twenty-line fake in `tests/contract/test_interfaces.py`
  grew one line, which is the whole cost.

## [0.5.0] — 2026-09-01

MINOR. Two subsystems that were shipped as code in 0.4.0's tree but never got a
version number of their own: the published contract and the pattern packs. Both
are public API — `interfaces.py` is what an engine written outside the library
depends on, and `patterns/` is the seam that makes "swap the patterns" a claim
the code can honour.

### Added

- `interfaces.py` — where a CONTRACT is declared. Eleven structural
  `Protocol`s, each with a conformance test in `tests/contract/`. It imports
  nothing at runtime, which is what keeps it below all five layers of
  CLAUDE.md §10. It exists because a collaboration written down only in a
  docstring drifts: `Engine` published `transcribe(pages, *, parallelism)`
  while `OCRStep` had been passing `force_parallelism` for months, and nothing
  failed because nothing looked.
- `patterns/` — the Portuguese regexes and word lists as a TOML pack instead of
  `re.compile` calls in ten Python files. Resolution, most specific first:
  `Config.patterns` -> `AUTOSXTRACT_PATTERNS` -> the bundled pack for
  `Config.language` -> `base`. A user pack overrides **entry by entry**, so a
  pack that redefines one stamp is complete and keeps receiving fixes to the
  other sixty-five. File-level merging would force a copy, and a copy is a fork.
  `base.toml` describes no language; every entry carries in its `why` field the
  measurement that fixed it.
- `InkSignals` — the contract for the two pixel statistics the vetoes run
  before the expensive step, satisfied by the `pdf.ink` module itself. See
  **Fixed**.

### Added — tooling

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

### Fixed

- **`quality/vetoes.py` no longer opens a PDF.** It imported `is_photograph`
  and `is_nearly_blank` from `pdf/ink.py` and called them on `pdf_bytes`, which
  put I/O inside `quality/` against CLAUDE.md §10 and left the two pixel vetoes
  with no seam to test through: every unit test opted out with
  `pixel_signals=False`, and lines 97-100 were the only uncovered ones in the
  module — 87% coverage with the gap in one place.

  What that gap could cost is the reason it is a fix and not a tidy-up. §13
  warns these two are valid **only together with "extracted no text"**: on their
  own they discard an old photocopy on dark paper, continuous tone carrying
  thousands of legitimate characters (0.99 / 0.99 / 0.83 mid-tone with 1,001,
  2,612 and 632 characters). The branch that can throw a readable document away
  was the branch no test exercised.

  `assess_vetoes` now takes `ink: InkSignals | None`, defaulting to `pdf.ink`
  resolved inside the one branch that needs it — the same shape `Renderer`
  already has. Behaviour is unchanged; coverage of the module goes 87% -> 98%,
  and the "pixels alone never veto a page that HAS text" condition is now
  pinned by a test rather than by a comment.
- `.github/labels.yml` could not be applied: GitHub caps a label description at
  100 characters and answers 422 past it, so `quality` (109) and
  `already-refuted` (138) were never created. Both shortened, the cap recorded
  in the file.
- `scripts/github_project_setup.sh` aborted with `cannot iterate over: null` on
  a repository with no topics — that is, on the first run, the only run a fresh
  repository has.
- `check-yaml` could not parse `mkdocs.yml`: Material registers the Mermaid
  fence with `!!python/name:`, which the safe loader has no constructor for. A
  syntax-only pass is now scoped to that one file, leaving the strict parse in
  place for the workflows.
- `tests/contract/test_interfaces.py` read `__protocol_attrs__`, which exists
  only on CPython 3.12+; the suite runs on 3.11 too, where it failed.
- `tests/integration/test_worker.py` asserted the order pages reach the client
  in. With `page_parallelism == 2` that order is the scheduler's, not the
  document's — it went red on a runner that delivered `[a, c, b, d]`. The
  order `transcribe` actually promises is pinned in
  `test_cascade.py::test_page_order_is_preserved`.
- `scripts/compare_engines.py` had a shebang and no executable bit.

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

[Unreleased]: https://github.com/liafacom/AutosXtract/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/liafacom/AutosXtract/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/liafacom/AutosXtract/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/liafacom/AutosXtract/releases/tag/v0.4.0
