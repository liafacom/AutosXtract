# Security Policy

## Supported versions

The project is pre-1.0, so the supported surface is deliberately narrow: fixes
go onto the **latest released minor**, and a release is cut from `main`. There
are no maintenance branches, and older minors do not receive backports.

| version | supported |
|---|---|
| 0.4.x | yes — current |
| < 0.4 | no. Upgrade; the public API has not broken between 0.x minors so far, and `CHANGELOG.md` records what did change |

`pip install --upgrade autosxtract` is the fix for every version below the
current one, and `autosxtract diagnose` prints the version you actually have —
worth checking before reporting, because a virtualenv shadowing a system
install is a common source of "already fixed" reports.

## Reporting a vulnerability

**Never in a public issue.** Use GitHub's private vulnerability reporting:

> https://github.com/liafacom/AutosXtract/security/advisories/new

That form opens a private advisory visible only to the maintainers. It is the
only reporting route this project offers, and that is on purpose rather than
for lack of an e-mail address: a private advisory carries the discussion, the
fix and the disclosure in one place, and — see below — this repository's own
privacy scanner rejects any e-mail address written into the tree, so an address
published here could not survive `make privacy`. If the advisory form is
unavailable to you, open a public issue saying only that you have a security
report and naming no detail, and a maintainer will open the private channel.

What to include: the version, the platform, whether an OCR engine was
installed, and the smallest input that triggers it. **The smallest input must
not be a real document** — see the section below; a synthetic PDF built with
PyMuPDF, as `tests/conftest.py` does, is both safer and more useful.

What to expect: acknowledgement within a few working days, an assessment of
severity and scope, a fix on the latest minor, and a published advisory
crediting you unless you ask otherwise. Please give us a reasonable window
before disclosing publicly.

### What counts as a vulnerability here

Beyond the usual, three classes specific to what this library does:

- **A path that opens a socket during extraction when nobody asked it to.**
  See below — this is treated as a security defect, not a feature request.
- **A path that writes document text somewhere unexpected** — a log, a
  temporary file left behind, an exception message carrying page content, a
  `repr` that includes a token or a transcription.
- **Anything that lets a crafted PDF escape being merely unreadable**: command
  execution, a path traversal on write, unbounded memory or a hang on a small
  input. A malformed file is expected to raise `UnreadablePDF` or degrade with
  a reason, never to do something else.

Not vulnerabilities: a document extracted badly (that is the *Extraction
quality* issue form), a missing engine making a scanned PDF come out empty
(`diagnose` reports it, and the absence of a tool is never treated as evidence
about the document), or a slow document.

## Data privacy — the part that is specific to this project

This library reads private legal documents. The privacy stance below is
architectural, and it is enforced by tests rather than promised in prose.

### Extraction does no networking

`Cascade()` assembles local steps only. **No engine and no gate opens a
socket** while a document is being extracted. There are exactly two exceptions,
and both are explicit and visible:

1. `engines/models.py` downloads the PP-OCRv6 weights **once**, before or
   outside extraction — and extraction works without it, falling back to
   rapidocr's embedded model. You can do it deliberately and offline
   afterwards: `autosxtract download-models`.
2. `steps/remote.py` provides `DoclingStep` and `VLMStep`, which **require a
   `url` in the constructor**. They are not in the default cascade, there is no
   discovery through an environment variable, no built-in default, and no
   fallback to a known endpoint. If you did not write the URL, the step does
   not exist.

The invariant that holds the rest together: **`Config` has not a single host,
port, URL or credential field.**
`tests/unit/test_config.py::test_no_field_points_at_a_network`,
`tests/unit/test_remote_steps.py` and `tests/integration/test_remote.py` are
the guard rails, and they run on every push.

This is not caution for its own sake. The previous version of this pipeline
reached its OCR engine on another machine over a reverse SSH tunnel. That
worker went down and the pipeline **silently degraded the text** — 488
documents re-extracted down the worse path, 19.5 minutes instead of 4.9, 28,239
characters lost, and nobody noticed until somebody checked. A remote step
nobody declared must not exist.

When you *do* instantiate a remote step, the `token` never appears in a `repr`,
in a log or in the result, and a network failure becomes a refused attempt with
the reason in the provenance — never an exception, and never a silent
substitution.

### Your documents stay yours

The library reads the file you give it and returns text. It writes nothing you
did not ask for, sends nothing anywhere, and keeps no cache of document
content. The only thing it caches is model weights, under
`~/.cache/autosxtract` (`autosxtract diagnose` prints the path).

### No real document enters this repository

Test fixtures are generated on the fly by PyMuPDF with invented text
(`tests/conftest.py`), `.gitignore` blocks `*.pdf` at the root, and pre-commit
blocks any added file over 1 MB — the net that catches an archive file with the
right extension in the wrong directory.

The active defence is `scripts/privacy_check.py`. It runs:

- as the **first** pre-commit hook, before the style ones, because a commit
  blocked on formatting costs thirty seconds and a published document has no
  undo;
- in CI on **every push**, in a `privacy` job of its own — required before a
  merge, with no `pip install` in front of it, so an unrelated dependency
  failure cannot starve the one check whose failure is irreversible — and again
  inside the `quality` job on every Python version in the matrix;
- on every pull request in the `history-scan` job, over the **commit messages**
  the branch adds and over lines it added and later removed. Neither is visible
  to a scan of the tree, and both are published by a merge;
- again in the release workflow, on the tree the tag points at, before anything
  is uploaded to PyPI.

It looks for forbidden file types (`.pdf`, `.csv`, `.jsonl`, spreadsheets,
pickles, model weights), private keys and API tokens, institutional paths and
hard-coded hosts, e-mail addresses, and Brazilian tax IDs, company IDs and case
numbers — the last three **validated by their check digit**, not merely matched
by shape. Precision over recall, deliberately: a scanner that shouts at every
14-digit number is switched off in the first week, and a scanner that is off
protects nothing.

It has already paid for itself. It caught a real case number, with a valid
check digit, that had reached this library's own examples through a comment
documenting a measurement. That is why identifiers used as examples here carry
a **deliberately invalid** check digit: the scanner stays quiet and nobody has
to decide, case by case, whether a number belongs to a real person.

Run it yourself before pushing:

```bash
make privacy
.venv/bin/python scripts/privacy_check.py . --staged
```

### If you find leaked data in this repository

A real PDF, a real extracted text, a case number, a name, an address, an
institutional host — report it **privately**, through the same advisory form. A
public issue pointing at the file multiplies the exposure and makes the history
harder to rewrite. It is treated with the same urgency as a vulnerability,
because it is one.

### Supply chain

Dependencies are updated by Dependabot, grouped weekly so that a human can
actually read the pull request rather than rubber-stamping a dozen. Releases go
out through **PyPI Trusted Publishing** (OIDC): there is no long-lived API
token in this repository's secrets, and there must never be one — a stored
token is readable by any workflow a contributor can cause to run, and it does
not expire. CI workflows declare `permissions: contents: read`; only the Pages
deployment, the CodeQL upload and the PyPI upload ask for more, and only in the
job that needs it.

A pull request that introduces a dependency with a known advisory, or one whose
licence is outside the allow list, is refused by the `dependency-review` job
before it can be merged. `CodeQL (python)` analyses the package on every pull
request and weekly, because a query written next month can find a defect in code
that merged today.

### Where the rest of it is written down

`.github/GUARDRAILS.md` is the full map: every guardrail, where it is enforced
(pre-commit hook, CI workflow or ruleset), what it costs, what happens when it
fires, and how to get past it legitimately. `.github/rulesets/` holds the
protection of `main` and of the release tags as reviewable JSON rather than as a
settings page nobody can diff.
