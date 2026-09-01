# Guardrails

Every gate between a change and a user, why it exists, what it costs, and how to
get past it when you legitimately need to.

This is a **published library**. A bad merge here does not break a deployment
somebody can roll back — it becomes a wheel on PyPI, mirrored worldwide within
minutes, installed by `pip install --upgrade` on machines nobody controls, and
**PyPI does not allow a filename to be reused**. A wrong artefact cannot be
replaced, only superseded by burning the next version number. That asymmetry is
the reason the gate is as heavy as it is.

There is a second asymmetry, specific to this project. Most of the checks here
prevent a red build. Exactly one of them prevents a **leak**: the tree that CI
runs on sits a few directories away from real judicial documents, and a
distracted `git add -A` publishes a case file. A red build costs an afternoon; a
published document has no undo. That is why the privacy scan runs first, twice,
and now in a job of its own (`CLAUDE.md` section 9).

> This file explains the guardrails. `.github/rulesets/README.md` explains the
> individual rules inside the two ruleset files. `SECURITY.md` explains how to
> report something. `CONTRIBUTING.md` explains how to work.

---

## 1. The map

Three places enforce things, and they are not interchangeable.

| where | can be skipped by | catches |
|---|---|---|
| **pre-commit hook** | `git commit --no-verify`, or simply not installing the hooks | you, in seconds, before the mistake has a URL |
| **CI workflow** | nothing, but it only *reports* — a red check does not stop a merge on its own | anything that can be checked by running code |
| **ruleset** | only a declared bypass actor, and every use is recorded | the merge itself |

A hook is advice. A workflow is evidence. **Only a ruleset is a gate.** A
repository with excellent CI and no ruleset has a merge button that ignores all
of it, which is the state this repository was in before these files existed.

---

## 2. The guardrail table

| # | guardrail | enforced by | fires when | what happens |
|---|---|---|---|---|
| 1 | Privacy scan, staged files | pre-commit hook (`privacy-check`, first in the list) | a staged file carries a real tax ID, company ID or case number (validated by check digit), a private key, a token, an institutional path or host, an e-mail address, or a forbidden extension | the commit is refused, locally, before anything has a URL |
| 2 | Privacy scan, whole tree | `ci.yml` job **`privacy`** — required check | the same, anywhere in the tree, on every push and pull request | the check goes red and the merge is blocked |
| 3 | Privacy scan, commit messages and transient lines | `guardrails.yml` job **`history-scan`** — required check | an identifier or credential appears in a commit *message*, or in a line this branch added and later removed | the check goes red and the merge is blocked |
| 4 | Privacy scan, the release tree | `release.yml` (`build` job) | the same, on the tree the tag points at | the release aborts before anything reaches PyPI |
| 5 | Lint, format, types, tests on 3.11 / 3.12 / 3.13 | `ci.yml` job **`quality`** — 3 required checks | any of them fails on any supported interpreter | merge blocked |
| 6 | The suite with a real OCR engine | `ci.yml` job **`with-ocr`** — required check | the engine is missing, inert, or the integration tests fail | merge blocked |
| 7 | The Apple cascade | `ci.yml` job **`apple`** — required check | Vision's path breaks on macOS | merge blocked |
| 8 | The pinned environment, and that the pins are regenerable | `ci.yml` job **`pinned`** — required check | `constraints/dev.txt` was hand-edited, or the pinned toolchain fails | merge blocked |
| 9 | A fresh clone still bootstraps, on Linux and macOS | `ci.yml` job **`bootstrap`** — 2 required checks | `scripts/bootstrap.sh` rotted | merge blocked |
| 10 | The wheel imports in a clean environment | `ci.yml` job **`packaging`** — required check | a subpackage is missing from the wheel — invisible inside the repository, fatal outside it | merge blocked |
| 11 | The documentation still builds, strictly | `docs.yml` job **`docs`** — required check | a dead link, or a page in no navigation entry | merge blocked |
| 12 | Static analysis of the Python | `codeql.yml` job **`CodeQL (python)`** — required check | a dataflow defect: traversal, injection, an unsafe deserialisation | merge blocked; the finding lands in the Security tab |
| 13 | New dependencies are neither vulnerable nor licence-incompatible | `guardrails.yml` job **`dependency-review`** — required check | a pull request adds a dependency with a moderate-or-worse advisory, or a licence outside the allow list | merge blocked |
| 14 | The title survives being squashed | `guardrails.yml` job **`pr-hygiene`** — required check | the title is not `type(scope): subject` | merge blocked; fix by retitling, no new commit needed |
| 15 | Diff size | `guardrails.yml` job `pr-hygiene` | over 1000 changed lines or 40 files | a **warning** only — never blocks |
| 16 | Notebooks still execute | `notebooks.yml` job `notebooks` | a notebook's API drifted | reported, deliberately **not** required — see §7 |
| 17 | A pull request is mandatory | ruleset `main - protected` | anyone pushes to `main` directly | the push is refused by the server |
| 18 | One approval, from a code owner | ruleset `main - protected` | the approval is missing, or comes from nobody in `.github/CODEOWNERS` | merge button disabled |
| 19 | Stale approvals are dismissed | ruleset `main - protected` | a commit is pushed after the approval | the approval disappears; re-review needed |
| 20 | The last pusher cannot be the approver | ruleset `main - protected` | you approve, then push, then try to merge | merge button disabled |
| 21 | Every review thread resolved | ruleset `main - protected` | a comment is left open | merge button disabled |
| 22 | The branch is up to date with `main` | ruleset `main - protected` | `main` moved since the last CI run | "Update branch", then CI re-runs |
| 23 | No force push, no deletion, linear history | ruleset `main - protected` | a force push or a merge commit reaches `main` | the push is refused by the server |
| 24 | A release tag cannot be moved or deleted | ruleset `release tags - immutable` | anyone re-points or deletes a `v*` tag | the push is refused by the server |
| 25 | A release tag must be a version number | ruleset `release tags - immutable` | `vfoo`, `v1`, `v1.2` | the tag push is refused, before the release workflow starts |
| 26 | Secrets are blocked at push time | GitHub push protection (native) | a push carries a recognised provider credential | the push is refused, with a bypass prompt |
| 27 | Known-vulnerable dependencies are reported | Dependabot alerts + security updates | an advisory lands for something in the graph | an alert, and a pull request that fixes it |
| 28 | Dependency updates are grouped and reviewable | `.github/dependabot.yml` | weekly, Monday | one grouped pull request, majors separately |
| 29 | Publishing needs a human | `release.yml`, the `pypi` GitHub environment | a `v*` tag is pushed | the upload waits for a named reviewer |
| 30 | Publishing uses no stored credential | PyPI Trusted Publishing (OIDC) | always | there is no long-lived token to steal |

Rows 2, 3 and 4 are the same scanner in four places, and the redundancy is
deliberate: the hook runs on the index, `privacy` runs on the tree,
`history-scan` runs on what the tree no longer shows, and the release run
happens on a different object (a tag) at a different time. None of them is
a superset of the others.

---

## 3. Required status check names, verbatim

These are the strings in `.github/rulesets/main.json`. Copy them exactly.

```
privacy
history-scan
quality (3.11)
quality (3.12)
quality (3.13)
with-ocr
apple
pinned
bootstrap (ubuntu-latest)
bootstrap (macos-latest)
packaging
docs
CodeQL (python)
dependency-review
pr-hygiene
```

**A wrong name does not fail loudly — it protects nothing, and blocks
everything.** GitHub matches a required check by name. A name nothing reports
leaves the pull request sitting on *"Expected — waiting for status to be
reported"*, forever, for a run that will never happen; a name that is simply
absent from the list leaves that check advisory while looking enforced. Both
failures are silent.

Three ways to get it wrong, all of which have happened to other projects:

- **Matrix legs.** The reported name is the job id followed by the matrix values
  in parentheses: `quality (3.11)`, not `quality`. Requiring `quality` matches
  nothing at all.
- **An explicit `name:`.** When a job declares one, it *replaces* the id.
  `docs.yml`'s job id is `build` and its name is `docs`; `codeql.yml`'s job id is
  `analyze` and its name is `CodeQL (python)`. The name is what a ruleset needs.
  Renaming a job silently empties the rule that named it.
- **A job that does not run on every pull request.** `docs.yml`'s `deploy` job
  runs only on a push to `main`. Requiring it would block every pull request
  permanently. Never require a job with a branch, path or event filter that a
  pull request can miss.

Verify against reality rather than against this list:

```bash
scripts/github_guardrails_setup.sh --check-names <head sha of a finished PR>
```

It asks GitHub which check runs that commit actually produced and diffs them
against the file. Or by hand:

```bash
gh api repos/liafacom/AutosXtract/commits/<sha>/check-runs --jq '.check_runs[].name' | sort -u
```

`integration_id` is deliberately absent from every context. Adding it (the
GitHub Actions app is `15368`) would stop a commit status of the same name
posted by anything else from satisfying the rule — stricter, and worth doing
once someone can verify it, but a *wrong* `integration_id` makes the rule match
nothing, which is the failure above. Read the real one off a check run first:

```bash
gh api repos/liafacom/AutosXtract/commits/<sha>/check-runs \
  --jq '.check_runs[] | {name: .name, app: .app.id}'
```

---

## 4. Turning it on

### 4.1 Everything the CLI can do

```bash
scripts/github_guardrails_setup.sh --dry-run   # print the plan, change nothing
scripts/github_guardrails_setup.sh             # print the plan, then apply it
```

It is idempotent — it matches each ruleset by name and updates it in place — it
refuses clearly when `gh` is missing or unauthenticated, and it needs **admin**
rights, not write. It applies the rulesets, Dependabot alerts, Dependabot
security updates and private vulnerability reporting.

Its sibling `scripts/github_project_setup.sh` owns the rest of the settings page
— description, topics, features, merge buttons, secret scanning and push
protection. Neither script touches what the other owns.

### 4.2 The rulesets, by hand

```
Settings -> Rules -> Rulesets -> New ruleset - Import a ruleset
  -> .github/rulesets/main.json          -> review -> Create
  -> .github/rulesets/tags-release.json  -> review -> Create
```

Or:

```bash
gh api -X POST repos/liafacom/AutosXtract/rulesets --input .github/rulesets/main.json
gh api -X POST repos/liafacom/AutosXtract/rulesets --input .github/rulesets/tags-release.json
```

Sending the file directly works, but the script strips the `source_type` key
first: it is what makes the file importable in the UI and it is not a parameter
the create endpoint accepts.

**The files are the source of truth, not a snapshot of it.** Editing a ruleset in
the web UI without changing the file is how the two drift, and the next import
silently reverts the UI edit. Change the file, open a pull request, then apply.

### 4.3 Secret scanning and push protection

```
Settings -> Advanced Security -> Secret Protection -> Enable
                              -> Push protection    -> Enable
```

or `gh repo edit liafacom/AutosXtract --enable-secret-scanning --enable-secret-scanning-push-protection`
(which is what `scripts/github_project_setup.sh` does).

Secret scanning **runs automatically and free on public repositories**, and the
secret types included in push protection by default apply to every repository
with secret scanning enabled, free public repositories included. Push protection
is the only control in this whole document that stops a leak at the moment of
the push rather than reporting it afterwards — the same job the privacy scanner
does for documents.

Anyone with write access can bypass a push-protection block by choosing a reason
("used in tests", "false positive", "will fix later"). That is a deliberate hole
in GitHub's design, not in ours; the bypass is recorded.

### 4.4 Code scanning

`.github/workflows/codeql.yml` is **advanced setup**. Do not also enable default
setup — the two conflict, and GitHub disables one of them without making it
obvious which. If default setup is already on:

```
Settings -> Advanced Security -> Code scanning -> CodeQL analysis -> ... -> Disable CodeQL
```

then let the workflow run.

### 4.5 Private vulnerability reporting

```
Settings -> Advanced Security -> Private vulnerability reporting -> Enable
```

or `gh api -X PUT repos/liafacom/AutosXtract/private-vulnerability-reporting`.

**This one is not cosmetic.** `SECURITY.md` and two entries in
`.github/ISSUE_TEMPLATE/config.yml` send people to
`https://github.com/liafacom/AutosXtract/security/advisories/new`, including the
entry headed *"A real document leaked into this repository"*. While the feature
is off, that link 404s and the reporter's next move is a **public issue pointing
at the leaked file** — the exact outcome the template exists to prevent. Verify
it while signed out.

### 4.6 Discussions

```
Settings -> General -> Features -> [x] Discussions
```

Same reasoning, lower stakes: the first contact link in the issue chooser points
at `/discussions`, and it is a 404 until the tab exists.
(`scripts/github_project_setup.sh` sets this.)

---

## 5. Getting past a guardrail legitimately

Three exits, in the order you should reach for them.

### 5.1 Fix the thing

Almost always the answer, and worth saying because the other two are more
interesting. A red `pr-hygiene` is a retitle. A red `privacy` is a real finding
— read it before assuming it is not.

### 5.2 The admin bypass

`main - protected` carries one bypass actor: the built-in **Admin** repository
role, in `pull_request` mode. That means an admin still has to open a pull
request — the change still has a diff, a CI run and a URL — but can merge it
without the second pair of eyes and without every check green.

**Acceptable:**

1. **A one-person emergency.** The other maintainer is unreachable and something
   published is actively wrong: a leak in the tree, a wheel that does not import.
2. **A required check is broken rather than failing.** A runner outage, a
   third-party action pulled, a job stuck. The check is not telling you anything
   about the diff.
3. **Unblocking the gate itself** — a fix to a workflow that the gate needs in
   order to pass.

**Not acceptable:** it is late; the check is "probably" flaky; the change is
"just documentation"; the reviewer is slow. Each of those is the first step of
the path where the gate stops meaning anything.

Every use is recorded in **Settings → Rules → Insights**, with a name and a
timestamp, and that page is worth reading after a release. If a bypass turns out
to be routine, the honest response is to change the rule in a pull request, not
to keep bypassing it.

To remove the hole entirely, set `"bypass_actors": []` in `main.json`. The only
remaining exit is then §5.3.

### 5.3 Standing the ruleset down

```
Settings -> Rules -> Rulesets -> main - protected -> Enforcement status: Disabled
```

or `gh api -X PUT repos/liafacom/AutosXtract/rulesets/<id> -f enforcement=evaluate`.

`evaluate` is the better of the two: rules are checked and logged but do not
block, so you keep the record of what *would* have failed. Both are visible in
the ruleset's history, and both have to be undone deliberately — which is the
point. This is the exit for a repository-wide operation (a licence change, a
mass rename), not for one pull request.

### 5.4 What has no bypass

- **Push protection** can be bypassed with a reason by anyone with write access.
- **The pre-commit hooks** can be skipped with `--no-verify`, which is why the
  same scanner runs in CI, where it cannot be.
- **PyPI.** Nothing above can retract a published wheel. This is the one place
  where the guardrails genuinely end.

---

## 6. What needs a public repository, or Advanced Security

`liafacom/AutosXtract` is **public**, so everything below is free today. It is
listed because the answer changes the day somebody makes the repository private,
and that change would silently remove three guardrails.

| guardrail | free on a public repo | on a private repo | fallback if unavailable |
|---|---|---|---|
| Secret scanning | yes, automatic | needs **GitHub Secret Protection** | `scripts/privacy_check.py` already matches private keys, `sk-`, `ghp_`, `AKIA`, `xox*` and generic credential assignments, in CI and in the hook |
| Push protection | yes, for the default provider patterns | needs **GitHub Secret Protection** | the `privacy-check` pre-commit hook, which is a local block rather than a server-side one — skippable with `--no-verify` |
| Code scanning / CodeQL | yes | needs **GitHub Code Security** | `codeql.yml` will fail with a licensing error. Remove it from the required checks and lean on `ruff` and `mypy`, which are a weaker but real substitute |
| Dependency review | yes, once the dependency graph is on | needs **GitHub Code Security** | `guardrails.yml`'s `dependency-review` job fails. `pip-audit` in a job of its own is the closest free equivalent for the vulnerability half; the licence half has no free equivalent |
| Dependabot alerts and updates | yes | yes — included in all plans | none needed |
| Rulesets | yes | yes | none needed; rulesets are not an Advanced Security feature |
| Private vulnerability reporting | yes | public repositories only | publish a contact route in `SECURITY.md` — note that this project's own privacy scanner rejects an e-mail address written into the tree, so that route needs thought |

The two rules a ruleset offers that *would* need Advanced Security —
**"Require code scanning results"** and **"Require code quality results"** — are
deliberately not in `main.json`. `CodeQL (python)` is required as a *status
check* instead, which is free, and which fails the merge if the analysis fails.
The difference is that the ruleset version can also block on the *severity* of
findings; if the repository ever gains Code Security, that is the upgrade.

---

## 7. What was deliberately left out

A guardrail that gets switched off is worse than one that was never added: it
teaches everyone that the red marks are negotiable. Each of these was
considered and rejected.

**Long-lived `develop` and `homolog` branches.** Asked for by name, and left
out because the three rules already in place would each charge for them without
paying anything back.

`main.json` matches `~DEFAULT_BRANCH`, so a protected `develop` needs a ruleset
of its own carrying **the same fifteen required check names**. Two lists that
have to be kept in step are two lists that drift, and the failure is silent in
the worst direction: a branch that looks protected and is not.

`required_linear_history` with squash-and-rebase merging means promoting
`develop` into `main` yields **one** flattened commit. The individual history is
exactly what a `develop` branch exists to preserve, so the arrangement pays
GitFlow's cost and discards its product.

And `homolog` mirrors a staging *environment*, which a library does not have.
Its equivalent is already in `tags-release.json`: the tag pattern admits
`a|b|rc`, so `v0.5.0rc1` publishes as a PEP 440 pre-release that `pip install
autosxtract` ignores and only `pip install --pre` fetches. Homologation for a
library is a version, not a branch — and the release workflow already refuses to
let a pre-release take the "Latest" badge.

What stands instead is what `CONTRIBUTING.md` §9 already described: branch off
`main`, land through a pull request, delete the branch on merge (the repository
does it), release by tag. Maintenance branches (`0.4.x`) are worth creating the
day a backport is actually needed and not before — a branch nobody has a commit
for is a branch nobody updates the protection of.

**Required signed commits.** The rule exists (`required_signatures`) and it is
genuine hardening — it is the only thing that makes commit authorship
unforgeable. It is left off because it fails at `git push`, with a message that
does not explain how to fix it, for anyone who has not set up GPG or SSH signing
— and the fix is to rebase every commit and force-push, which is a bad first
experience for a drive-by contributor and a bad Tuesday for a maintainer.
Web-UI merges, and Dependabot's commits, are signed by GitHub already, so the
rule would only ever fire on locally authored commits.

To turn it on anyway, add `{"type": "required_signatures"}` to `main.json`'s
`rules` and re-run the setup script, or:

```
Settings -> Rules -> Rulesets -> main - protected -> [x] Require signed commits
```

Do it when the contributor set is small and known, and put the signing setup in
`CONTRIBUTING.md` in the same pull request. Doing it without the second half is
how a gate acquires a reputation.

**A stale-issue or stale-PR bot.** Wrong for this project specifically. The
issues it would close are the `needs-repro` ones — and in a library that reads
private judicial documents, a reproduction is *hard by design*: the reporter
cannot send the document, so building a synthetic case takes real time. Closing
exactly those as "stale" punishes the reporters who are being most careful. With
two maintainers and a young issue tracker, the backlog is not the problem a bot
solves.

**A mandatory-label check.** The release-notes categories in
`.github/release.yml` are keyed on labels, so there is a real argument for it.
But `.github/release.yml` already ends with a `*` catch-all: an unlabelled pull
request still appears in the notes, under a vague heading, which makes the
missing label *visible* without failing anything. A check that reddens a correct
pull request because nobody clicked a label is the definition of the ceremony
that gets disabled.

**A hard diff-size limit.** It teaches people to split a coherent change into
incoherent halves. `pr-hygiene` warns and never blocks.

**A third-party secret scanner** (gitleaks, trufflehog). This repository has a
standing policy of one third-party action — the one PyPI itself documents for
Trusted Publishing — and a scanner would be a second, running on every pull
request, with a supply-chain surface of its own. Native push protection plus
`privacy_check.py` plus `history-scan` cover the same ground, and
`privacy_check.py` covers ground they cannot: Brazilian identifiers validated by
**check digit**, which no generic scanner attempts.

**`.github/settings.yml` (the Probot "Settings" app).** Rejected for three
reasons. The app is **not installed** on this repository, so the file would do
nothing at all — a configuration file that looks authoritative and is inert is
worse than no file. It cannot manage rulesets, only the classic branch
protection that rulesets replace, so it would create a *second*, overlapping
protection system where GitHub applies whichever is stricter and neither
document explains the result. And `scripts/github_project_setup.sh` already owns
the settings the app would manage, from a file, reviewably. If the app is ever
installed, the correct scope for `settings.yml` is the `repository:` block only,
with labels left to `.github/labels.yml` and protection left to
`.github/rulesets/`.

---

## 8. The licence question this cannot answer

`guardrails.yml` checks the licence of every dependency a pull request
introduces against an allow list, and the list does not contain GPL or AGPL —
this package's metadata says MIT, and a strong-copyleft runtime dependency would
make that claim wrong.

It carries exactly one named exemption, `pkg:pypi/pymupdf`, and that exemption is
an open question rather than an answer. **PyMuPDF is AGPL-3.0-or-later or a paid
commercial licence, and it is a mandatory dependency here, not an extra.**
Without the exemption every Dependabot bump of it would be refused, the weekly
dependency pull request would sit permanently red, and the first thing anyone
did would be to delete the licence check — so the exemption is what keeps the
rest of the rule alive.

What it does not do is settle whether a wheel whose metadata says `MIT` may
require an AGPL package. That is a decision for the maintainers, not for a
workflow, and it needs to be made deliberately rather than inherited from a
config file. Until it is, the exemption is a marker saying *somebody has to look
at this*.

---

## 9. What is still not robust

Written down rather than glossed over.

1. **Nothing here has been applied.** `gh` is not installed in the environment
   these files were written in and there are no credentials, so every ruleset,
   every setting and every enablement in this document is a plan an admin has to
   execute. `scripts/github_guardrails_setup.sh` has been syntax-checked,
   shellcheck-clean, and proved end to end against a stubbed `gh` — created,
   updated idempotently, refused without `gh`, refused unauthenticated — but it
   has never spoken to GitHub.
2. **The required check names are unverified against a real run.** They are
   derived from the job ids and `name:` keys in the workflow files and follow
   GitHub's documented matrix pattern, but no pull request has yet reported a
   check on this repository. Run `--check-names` on the first one, before
   trusting the gate.
3. **`bypass_actors` uses well-known role ids.** `5` is the built-in Admin
   repository role. The value is stable and universally used, and GitHub does not
   document it on the rulesets pages. If an import fails with *"contains an
   invalid actor"*, that is the field.
4. **`dependency-review` sees only what the dependency graph parses.**
   `pyproject.toml` is parsed; `constraints/dev.txt` is a plain text file in a
   directory GitHub does not treat as a requirements file, so a change to the
   pins is **not** licence- or vulnerability-checked by this job. The `pinned`
   job proves the pins still work; it does not prove they are safe.
5. **`history-scan` strips commit trailers before scanning.**
   `Co-authored-by:` and friends carry an address by design, and scanning them
   would fail every pull request ever opened. A real identifier hidden inside a
   line that looks like a trailer would be missed.
6. **`apple` and `bootstrap (macos-latest)` are required checks on macOS
   runners.** They are the slowest and the scarcest, and with
   "require branches up to date" on, every merge to `main` re-runs them for every
   open pull request. On a busy day that is the cost of this gate, and the
   honest mitigation is fewer simultaneous pull requests, not fewer checks.
7. **Actions are pinned to major tags, not commit SHAs.** A moved tag on a
   third-party action is a live supply-chain risk, and `codeql.yml` and
   `guardrails.yml` hold `security-events: write` and run on every pull request.
   Pinning to full SHAs is the next hardening step; Dependabot's
   `github-actions` ecosystem keeps SHA pins updated the same way it keeps tags.
