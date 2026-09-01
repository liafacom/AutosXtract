# Releasing AutosXtract

Repository: <https://github.com/liafacom/AutosXtract> · Distribution:
<https://pypi.org/project/autosxtract/> · Documentation:
<https://liafacom.github.io/AutosXtract/>

This file covers three things that are normally tribal knowledge, and stops
being useful the moment they stop being written down:

1. **How a release happens** — the tag, what `.github/workflows/release.yml`
   checks, where the notes come from, and what to do when a step refuses.
2. **Where the package actually lives** — PyPI, GitHub Releases, and the honest
   answer about GitHub Packages.
3. **The two settings pages nobody can diff** — PyPI collaborators and Trusted
   Publishing, and the repository's About block.

Everything here is an *admin* procedure. The commands are exact and the click
paths are exact, because the failure mode of a vague runbook is not a wrong
click — it is a maintainer who does not attempt the release at all.

---

## 1. What a release is here

A release is a **decision**, and the workflow is built so it cannot be made by
accident. There is no publish on a push to `main`, no publish on a merged pull
request, and no manual dispatch. The only trigger is a tag matching `v*`:

```bash
git tag -a v0.4.1 -m "0.4.1"
git push origin v0.4.1
```

Everything downstream of that is automatic, and everything upstream of it is a
human's job.

### The version lives in exactly one file

`autosxtract/_version.py` holds `__version__`, and `[tool.hatch.version]` in
`pyproject.toml` points hatchling at it. There is no second copy: the wheel's
metadata, `autosxtract --version` and `import autosxtract; autosxtract.__version__`
all resolve to that one string.

The docstring above it is not decoration. It records **what kind of change the
bump is** — the 0.4.0 entry says "MINOR: the registry's `get` gained options"
and then lists why. Whoever bumps the version writes that first; the number
follows from it.

The tag adds a second place the version is stated, and two places drift. The
workflow's first step compares them and fails the build if they disagree,
because publishing `0.4.0` under the tag `v0.4.1` **cannot be undone** — PyPI
never allows a filename to be reused, so the wrong artefact is permanent and the
right one has to go out under a burnt version number.

### Tag format

`vX.Y.Z`, annotated. The `v` prefix is stripped before the comparison with
`_version.py`, so the file says `0.4.1` and the tag says `v0.4.1`.

Pre-releases use PEP 440 spellings — `v0.5.0rc1`, `v1.0.0a1`, `v1.0.0b2` — and
the workflow detects them and marks the GitHub Release as a pre-release. That
matters for a reason that is easy to miss: the "Latest" badge on the repository
home page is what people read as *the current version*, while `pip install
autosxtract` will not install a pre-release without `--pre`. If the badge says
`v1.0.0rc1` and pip installs `0.4.0`, the repository is lying to its readers.

---

## 2. Cutting a release, in order

**1. Decide the bump, and write the docstring.** Open
`autosxtract/_version.py`. Say what kind of change this is and why, above the
number. A bump with no sentence explaining it is a bump nobody can review.

**2. Bump `__version__`.** Semantic versioning, and the project's own reading
of it: a changed *threshold* is a minor bump even though no signature moved,
because it changes what the library accepts, and a caller's output changes
underneath them.

**3. Move `[Unreleased]` to `[X.Y.Z]` in `CHANGELOG.md`.** Add the date. Open a
fresh empty `[Unreleased]`. Update the two link definitions at the bottom.

This is not bookkeeping — the workflow reads that section and puts it at the top
of the GitHub Release. Two conventions from the top of `CHANGELOG.md` apply and
are the reason the entries are worth reading a year later:

- an entry that changes a number carries **the measurement that fixed it** —
  old value, new value, corpus, what improved and what regressed;
- an entry says **what it prevents**, because "fixed X" is only half an entry
  when the library's job is to not lose text silently.

**4. Open a pull request with those three changes.** Label it `area: packaging`.
It goes through CI like anything else — `quality`, `with-ocr`, `packaging`,
`pinned`, `bootstrap` — and through CODEOWNERS review, because
`autosxtract/_version.py` and `CHANGELOG.md` are both owned files.

**5. Merge it, then tag the merge commit.**

```bash
git checkout main && git pull
git tag -a v0.4.1 -m "0.4.1"
git push origin v0.4.1
```

Tag the commit that is on `main`, never a local one. `--verify-tag` in the
release job refuses if the tag is not on the remote.

**6. Approve the publish.** The `publish` job targets the `pypi` GitHub
environment. If that environment has a required reviewer configured — it should,
see §7 — the run pauses and waits for a human. That pause is the last point at
which a release can be stopped, and it is worth having: everything before it is
reversible and everything after it is not.

**7. Check the two pages.** <https://pypi.org/project/autosxtract/> renders the
README and lists the new version; the GitHub Release has the changelog section,
the generated pull request list, and both distribution files attached.

### If the release fails

| It failed at | What it means | What to do |
|---|---|---|
| tag / version mismatch | The tag and `_version.py` disagree | Delete the tag (`git push --delete origin vX.Y.Z`), fix the file on `main`, tag again. Nothing was published. |
| CHANGELOG section missing | You tagged with the section still called `[Unreleased]`, or it is empty | Same: delete the tag, fix, re-tag. |
| clean-venv install and import | The wheel is missing a subpackage or the pattern data | Real defect. It is invisible inside the repository because the source tree is on `sys.path` and hides the hole. Fix `[tool.hatch.build]`, cut a new patch version. |
| `twine check` | PyPI would refuse to render the README, leaving the project page blank | Fix the README, cut a new patch version. |
| privacy scan | A real identifier or document is in the tree the tag points at | **Stop.** This is a leak, not a build failure. Do not re-tag until it is out of the tree, and read `SECURITY.md`. |
| PyPI upload — "not a trusted publisher" | The publisher registration and the workflow disagree | §7. Do not create an API token to work around it. |
| GitHub Release creation | PyPI already has the version | Re-run that job alone. It is the announcement; the distribution is already out and is not affected. |

A version number burnt by a failed release is not a problem. Burning `0.4.1`
and releasing `0.4.2` costs nothing; publishing the wrong `0.4.1` costs
forever.

---

## 3. Where the release notes come from

Two halves, of deliberately different kinds, and the release body carries both.

**The human half** is the `## [X.Y.Z]` section of `CHANGELOG.md`, lifted
verbatim and prepended. It says *why*, and it carries the measurements. It is
written by a person and can be wrong, incomplete, or eloquent.

**The mechanical half** is what GitHub generates from the pull requests merged
since the previous tag, grouped by label according to `.github/release.yml`. It
is exhaustive, it credits every author, and nobody can forget to update it.
[GitHub's configuration schema is documented here.](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)

Neither replaces the other. The changelog is the reason; the generated list is
the receipt.

### The categories, and why they are in that order

A pull request lands in the **first** category whose labels it matches and never
in a second one, so the order in `.github/release.yml` decides what a reader
sees when a pull request is labelled twice — and they usually are.

```
💥 Breaking changes          breaking-change
🩹 Extraction quality        quality
🐛 Fixed                     bug
✨ Added                     enhancement
🔐 Privacy and security      privacy
📖 Documentation             documentation
🏗 CI, packaging, release    ci, area: packaging
📦 Dependencies              dependencies
🧹 Everything else           *
```

`quality` deliberately outranks `enhancement`: a pull request carrying both is
a quality fix that also added a knob, and filing it under "Added" buries the
half the project exists for. The `*` catch-all must stay last — anything after
it would be permanently empty — and its presence is what makes the notes
exhaustive: an unlabelled pull request still shows up, under a vague heading,
which is exactly how a missing label becomes visible.

### One gap, on purpose

`breaking-change` **does not exist yet** in `.github/labels.yml`. The category
is held open rather than invented under pressure the day a major version is
cut; while the label does not exist the category is simply empty, which costs
nothing. Whoever owns `.github/labels.yml` should add it:

```yaml
- name: breaking-change
  color: b60205
  description: Removes or changes public behaviour a caller depends on. Requires a major bump.
```

There is deliberately **no `exclude:` block**. Only pull requests merged into
the range appear at all, so the triage labels (`needs-triage`, `needs-repro`,
`needs-measurement`, `already-refuted`) can never surface and excluding them
would be decoration. Excluding `dependabot` as an author would be worse than
decoration — it would empty the Dependencies category, and a release that
silently moved a pinned dependency is precisely what a reader of the notes is
entitled to see.

---

## 4. What is attached to a Release, and why

The `github-release` job attaches the **wheel and the sdist** — the same two
files that went to PyPI, downloaded from the build job's artifact rather than
rebuilt. That distinction matters: two builds of "the same" tree are two
artefacts, and then the checksum on the Release page does not describe what is
on PyPI, which defeats the reason for attaching them.

They are attached for two reasons. A GitHub Release is the only copy that
survives a PyPI project deletion, and an air-gapped or firewalled install has
nowhere else to fetch them from.

The Release is created **after** the PyPI upload, never before. An announcement
of something that did not happen is worse than a missing announcement: a Release
page linking to a version PyPI never received sends every reader to
`pip install` a version that 404s.

---

## 5. GitHub Packages — the honest answer

**GitHub Packages cannot host this library, and never will.**

GitHub Packages serves npm, RubyGems, Apache Maven, Gradle, NuGet, and Docker/OCI
container images. Python is not among them —
[the registry list is here](https://docs.github.com/en/packages/working-with-a-github-packages-registry)
and
[the supported-clients table here](https://docs.github.com/en/packages/learn-github-packages/introduction-to-github-packages).
This is not an oversight waiting to be fixed: the roadmap item
[github/roadmap#94, "Packages: Python (PyPi) support"](https://github.com/github/roadmap/issues/94),
opened in July 2020, is **closed as not planned**.

So the arrangement is:

| Channel | What it carries | Why |
|---|---|---|
| **PyPI** | the wheel and the sdist | The only thing `pip install autosxtract` reads. This is *the* distribution channel; everything else is a copy. |
| **GitHub Releases** | the same wheel and sdist, attached as assets | A durable second copy with notes and a date, readable without a package manager. Not an index — `pip` will not resolve from it. |
| **GitHub Packages** | nothing, today | No Python registry exists. |

### Does `.devcontainer/` change the answer?

No — and it is worth saying why, because it is the obvious place to think it
might.

The devcontainer is a **development** environment. It reproduces the Linux side
of the cascade (`native → paddle`) so a contributor can debug a Linux bug and
verify that the library degrades correctly without Apple Vision. It is built
locally from `.devcontainer/Dockerfile` by whoever opens the repository. It is
not a runtime artefact, nobody consumes it, and pushing it to a registry would
serve no user.

GitHub Packages would become relevant on exactly one condition: **if the project
ever ships a container image as a product** — a batch extraction service, or a
pinned image with the PP-OCRv6 weights already baked in so a deployment does not
depend on a model download. That image would go to the Container registry at
`ghcr.io/liafacom/autosxtract`, published by a separate workflow with
`packages: write`, and it would be a *distribution* decision with its own
versioning, its own security surface and its own maintenance cost. Today no such
image exists and there is no reason to invent one.

There are third-party tools that store Python distributions in `ghcr.io` as
generic OCI artifacts. They are not a PyPI-compatible index — `pip` cannot
install from them without extra client tooling — and adopting one would replace
a channel every Python user already trusts with one nobody does. Not for this
project.

---

## 6. PyPI collaboration runbook

Page: <https://pypi.org/manage/project/autosxtract/collaboration/>

### The role model, and what each role can actually do

PyPI has exactly two project roles.
[Per PyPI's own help page](https://pypi.org/help/):

- **Maintainer** — "Can upload releases for a package. **Cannot** add
  collaborators. **Cannot** delete files, releases, or the project."
- **Owner** — "Can upload releases. Can add other collaborators. Can delete
  files, releases, or the entire project."

The whole difference is *destruction and delegation*. Both roles can publish;
only an Owner can hand out roles or delete anything.

One consequence that is not obvious: **Trusted Publishing makes the upload
permission largely moot for day-to-day work.** Nobody uploads from a laptop
here — the workflow does it. So the roles are not really about who can publish;
they are about **who can still act when the automation cannot**, and about who
can destroy the project.

### Who should hold what

| Person | GitHub | Role on PyPI | Why |
|---|---|---|---|
| Arthur Silva Dantas | @ArthurSilvaDantas | **Owner** | Code owner on every path in `.github/CODEOWNERS`. |
| Edson Matsubara | @edsontm | **Owner** | Same. |

**Two Owners, not one Owner and one Maintainer.** The reason is bus factor and
nothing else: a Maintainer cannot promote anybody. If the sole Owner leaves the
institution, loses their 2FA device, or simply stops answering, the remaining
Maintainer can keep uploading and can change *nothing* — not the collaborator
list, not the Trusted Publisher registration, not a mistaken upload. Recovery
then means [a PEP 541 name-transfer request](https://peps.python.org/pep-0541/#how-to-request-a-name-transfer),
which is a public, slow, discretionary process run by PyPI admins and is not
something to discover under pressure. The second Owner costs nothing and removes
the entire scenario.

> **Confirm the PyPI usernames before inviting.** A PyPI username is not a
> GitHub username and there is no link between the two — `edsontm` on GitHub may
> be `edsontm`, `ematsubara` or something else entirely on PyPI, and the name
> may already be taken by a stranger. Ask each person for the exact handle shown
> on their own <https://pypi.org/manage/account/> page, or invite by the email
> address on that account. Inviting the wrong `edsontm` hands a stranger the
> ability to delete the project.

### Adding a collaborator

1. Sign in to PyPI as an Owner of the project.
2. Go to <https://pypi.org/manage/project/autosxtract/collaboration/>.
3. Under **Invite collaborator**, enter the confirmed username or email.
4. Choose the role — **Owner** for both maintainers, per the table above.
5. Send. The invitation must be **accepted** by the recipient; until then the
   collaborator list shows it as pending and that person can do nothing. Chase
   it, rather than assuming the role landed.

To change or remove a role, the same page has a per-collaborator control. An
Owner cannot remove the last Owner.

### 2FA is not optional

[PyPI states plainly](https://pypi.org/help/) that "Two-factor authentication
**is required** on your PyPI account." Every Owner and Maintainer must have it.

Two practical consequences that bite later:

- **Enrol a second factor, not just one.** A single TOTP app on a single phone
  is a single point of failure for the whole project, and losing it while being
  the sole Owner is the scenario §6's two-Owner rule exists to avoid.
- **Store the recovery codes somewhere that is not the phone.** PyPI issues them
  once.

### Do not create an API token. At all.

It is tempting, when the first release fails, to create a PyPI API token, drop
it into repository secrets, and move on. Don't — and the reason is not
tidiness:

- A long-lived token in repository secrets is readable by **any workflow that a
  contributor can cause to run**, and it does not expire. Trusted Publishing
  mints a credential valid for minutes, scoped to one repository, one workflow
  file and one environment.
- A token defeats the environment gate. The `pypi` environment's required
  reviewer is what makes the publish reviewable; a token in a secret can be used
  by a job that never touches that environment.
- Once a token exists, it is one leaked log line away from letting someone
  overwrite the project — and it will still be there, unrotated, in two years.

If a release fails to authenticate, the registration is wrong. Fix the
registration. §7.

### Organisation ownership — is it a better fit?

PyPI has organisation accounts, with their own roles: Owner, Manager, Member and
Billing Manager, described at
<https://docs.pypi.org/organization-accounts/roles-entities/>. A `liafacom`
organisation on PyPI would let the lab own the project and grant access through
teams, so a person joining or leaving is a membership change rather than a
per-project edit. [Community organisations are free](https://docs.pypi.org/organization-accounts/pricing-and-payments/):
"All current Organizations features of PyPI are provided to qualifying Community
Organizations at no cost."

**Recommendation: not yet, but plan for it.** With one project and two
maintainers, an organisation adds an approval process and a second layer of
roles to administer, and buys nothing that two Owners do not already give. It
becomes the right shape at the point where the lab has **three or more published
packages, or contributors who rotate** — a student cohort, for instance — because
that is where per-project collaborator lists start disagreeing with each other
and somebody keeps upload rights after leaving. Migrating a project into an
organisation later is supported and does not change the package name or break
anything installed.

Note that an organisation does not remove the bus-factor question, it moves it:
an organisation with one Owner has the same failure. Keep two either way.

### What happens if an owner leaves

- **Two Owners:** nothing. The remaining Owner adds a replacement.
- **One Owner, unreachable:** the project is frozen for anyone but them.
  Recovery is [PEP 541](https://peps.python.org/pep-0541/#how-to-request-a-name-transfer),
  filed as an issue against `pypi/support`, judged case by case by PyPI admins,
  and slow. Meanwhile releases can still go out *if* Trusted Publishing is
  configured and the workflow keeps running — which is one more reason it is
  configured at the project level and not tied to a person's token.
- **Either way**, the GitHub Releases keep every artefact ever shipped. That is
  the fallback that requires no one's cooperation.

---

## 7. Trusted Publishing — the exact registration

No secret is stored anywhere. The `publish` job mints a short-lived OIDC
identity; PyPI verifies it against a publisher it has been told to trust and
exchanges it for a credential valid for minutes.

Register it **once**, at:

<https://pypi.org/manage/project/autosxtract/settings/publishing/>

(Or: <https://pypi.org/manage/projects/> → **Manage** on `autosxtract` →
**Publishing** in the sidebar, which is the path
[PyPI documents](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).)

Fill in exactly these four values. They are matched **literally** against the
OIDC claims:

| Field | Value | Watch out for |
|---|---|---|
| Owner | `liafacom` | The organisation, not a person. |
| Repository | `AutosXtract` | Capital `X`. |
| Workflow name | `release.yml` | **Filename only.** Not `.github/workflows/release.yml` — a path here fails the upload. |
| Environment name | `pypi` | Must equal `environment.name` in the `publish` job. Change one, change both. |

The environment is [optional per PyPI's documentation](https://docs.pypi.org/trusted-publishers/adding-a-publisher/),
which nonetheless calls it "**strongly** recommended: with a GitHub environment,
you can apply additional restrictions to your trusted workflow, such as
requiring manual approval on each run by a trusted subset of repository
maintainers." Here it is **not** optional: it is registered, and it is what the
required reviewer hangs off.

A failed upload reporting *"not a trusted publisher"* is always one of those four
fields. Compare them character by character against
`.github/workflows/release.yml` before changing anything else, and never reach
for a token.

### The GitHub side of the same setting

**Settings → Environments → New environment**, named `pypi`:

- **Required reviewers**: @ArthurSilvaDantas and @edsontm. This is the pause in
  step 6 of §2, and the last reversible moment in a release.
- **Deployment branches and tags**: restrict to the tag pattern `v*`. Without
  it, any branch that can reach this environment can attempt a publish.
- **No secrets and no variables.** If a `PYPI_API_TOKEN` ever appears here,
  something went wrong; delete it and fix the registration instead.

### The very first release, when the project does not exist on PyPI yet

The page above only exists for a project PyPI already knows about. For a name
that has never been published, register a **pending** publisher instead, at
<https://pypi.org/manage/account/publishing/> — same four fields, plus the
project name `autosxtract`. The first successful upload creates the project and
converts the pending publisher into a normal one, with the uploading account as
Owner. Add the second Owner immediately afterwards (§6).

### Attestations come along for free

`pypa/gh-action-pypi-publish` generates and uploads
[PEP 740 digital attestations](https://github.com/marketplace/actions/pypi-publish)
by default for projects using Trusted Publishing — "Generating signed digital
attestations for all the distribution files and uploading them all together is
now on by default for all projects using Trusted Publishing." Nothing to
configure. It is the other half of what `id-token: write` buys: not only "PyPI
believes this upload came from here" but "anyone downloading can verify that
afterwards". Do not switch it off.

---

## 8. The repository's shop window

Everything in this section is applied by `scripts/github_project_setup.sh`,
which reads the current state, prints only what would change, and is safe to run
twice:

```bash
./scripts/github_project_setup.sh --dry-run   # print the plan, touch nothing
./scripts/github_project_setup.sh             # print the plan, then apply it
```

It refuses with a usable message if `gh` is missing, if it is not authenticated,
or if the account is not an admin. The click paths below are for whoever has no
CLI; the script and this section state the same values, and if they ever
disagree the script is the one that gets run.

### About block

**Click path:** repository home → the **⚙ gear** to the right of **About** →
Description, Website, Topics → **Save changes**.

**Description** (GitHub's cap is 350 characters; this is 248). It leads with the
mechanism, because "PDF text extraction" is a crowded shelf and "stops at the
first step that suffices" is the part that is different:

> Cascading PDF text extraction: every document descends steps from the cheapest
> to the most expensive and stops at the first one that produces acceptable
> text. Apple Vision on macOS, PP-OCRv6 everywhere else, one pip install and no
> engine to choose.

**Website:** `https://liafacom.github.io/AutosXtract/` — the MkDocs site
deployed by `.github/workflows/docs.yml`, not the repository URL. Somebody
arriving from a search result wants the getting-started page, not a directory
listing.

> This field 404s until an admin sets **Settings → Pages → Build and deployment
> → Source: GitHub Actions**. With the source left on "Deploy from a branch" the
> deploy job fails with a message that does not obviously say so.

### Topics

[GitHub's rules](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics):
"Add no more than **20** topics", "Use **lowercase letters, numbers, and
hyphens**", "Use **50 characters or less**."

There are exactly 20 below, which is the point — a topic list is a ranking, not
an inventory, and anything added has to displace something.

```
pdf                              document-ai            apple-vision
pdf-extraction                   document-processing    paddleocr
pdf-to-text                      information-extraction onnxruntime
text-extraction                  scanned-documents      pymupdf
ocr                                                     macos
optical-character-recognition                           linux
python                                                  legal-tech
cli                                                     portuguese
```

Three groups, and all three earn their place:

- **Discovery** (`pdf`, `pdf-extraction`, `pdf-to-text`, `text-extraction`,
  `ocr`, `optical-character-recognition`, `python`, `cli`) — the words somebody
  types when they do not know this project exists. These are the only ones that
  bring in a stranger.
- **Framing** (`document-ai`, `document-processing`, `information-extraction`,
  `scanned-documents`) — what kind of problem this is. `scanned-documents` is
  the honest one: the whole cascade exists because the cheap path fails on them.
- **Technology and domain** (`apple-vision`, `paddleocr`, `onnxruntime`,
  `pymupdf`, `macos`, `linux`, `legal-tech`, `portuguese`) — what a reader wants
  to confirm before installing 570 MB, and who the corpus actually belongs to.
  `portuguese` is not the code's language; it is the pattern catalogue's, which
  is the adaptation seam described in `CLAUDE.md` §12.

Applied by the script as `gh repo edit liafacom/AutosXtract --add-topic …`,
computed as a delta so a topic added by hand and not listed here is **removed**
— which is what keeps the file and the page from drifting apart.

### Features

**Click path:** **Settings → General → Features**.

| Feature | Setting | Why |
|---|---|---|
| **Issues** | **on** | The YAML issue forms are the intake, and the Extraction quality form is the one that matters: it collects the provenance string, the attempt list and the page profile **instead of the document**. Turning issues off sends people to email, where they attach the PDF. |
| **Discussions** | **on** | `.github/ISSUE_TEMPLATE/config.yml` already routes "is this supposed to work like that?" to `/discussions`. With Discussions off, that contact link is a 404 on the busiest page in the repository. |
| **Wiki** | **off** | The documentation is versioned in `docs/` and deployed with `mkdocs build --strict`, which fails on a dead link. A wiki is a second, unversioned, unreviewed copy that cannot fail a build — so it drifts, and then contradicts the one that is checked. |
| **Projects** (repo tab) | **off** | Planning here is issues and milestones. An empty tab is a link that teaches people the navigation is decorative. Organisation-level Projects are a separate thing and are unaffected. |
| **Sponsorships** | **off** | It needs a `.github/FUNDING.yml` to point anywhere, and a Sponsor button that leads nowhere reads as abandonment. This is an academic project; if funding ever needs a channel, add the file first and the toggle second. |

Two more, on the same page and worth the click:

- **Secret scanning** and **push protection** — **on**. Push protection is the
  only control here that *prevents* a leak rather than reporting one: it blocks
  the push carrying a credential instead of opening an alert after it is already
  in the history and already mirrored. The project has a privacy scanner for
  documents (`scripts/privacy_check.py`); this is its equivalent for secrets.
  Free on public repositories, and set by the script.
- **Social preview** (**Settings → General → Social preview**) — upload one.
  It is the card every link to this repository renders as, in Slack, on X and in
  a search result. Without it the card is a grey octocat and reads as a scratch
  repository. No API and no `gh` flag; a human has to upload the image.

### Merge behaviour

Squash only, delete the branch on merge. One merged pull request becomes one
commit on `main`, which is what makes `git log v0.4.0..v0.4.1` readable as a
release and what makes a bisect land on a reviewable change instead of on "wip".
Set by the script; branch protection itself lives in `.github/rulesets/` and is
applied separately.

---

## 9. One-time setup checklist

For whoever is standing the repository up, in the order that avoids waiting on
someone else:

- [ ] `./scripts/github_project_setup.sh --dry-run`, read it, then run it for
      real. (Needs `gh`, authenticated, admin.)
- [ ] Apply `.github/labels.yml` — the snippet at the top of that file.
- [ ] **Settings → Pages → Source: GitHub Actions**, or the Website field 404s.
- [ ] **Settings → Environments → `pypi`**: required reviewers
      @ArthurSilvaDantas and @edsontm, deployment tags restricted to `v*`, no
      secrets.
- [ ] Apply the branch ruleset from `.github/rulesets/`, including "Require
      review from Code Owners" — without it `CODEOWNERS` is a polite suggestion.
- [ ] Upload a social preview image.
- [ ] PyPI: confirm both maintainers' **PyPI** usernames, invite both as
      **Owner**, confirm 2FA on both accounts.
- [ ] PyPI: register the Trusted Publisher with the four values in §7. Create no
      token.
- [ ] Cut a throwaway pre-release (`v0.4.1rc1`) to prove the whole path before
      the first real one. It costs one burnt version number and tests every step
      that is expensive to get wrong.
