# Rulesets — branch protection as a file

JSON cannot carry comments, so the reasoning for what sits in `main.json` and
`tags-release.json` lives here. The full guide — every guardrail, its cost, and
how to get past it legitimately — is `.github/GUARDRAILS.md`.

## Why rulesets and not classic branch protection

Classic branch protection lives only in a settings page. It cannot be exported,
diffed or reviewed, so the answer to "who loosened the gate, and when" is a
shrug. Rulesets are the modern replacement: they are exportable and importable
as JSON, they layer (several rulesets can apply to the same ref, and the most
restrictive wins), and every pass, failure and bypass is recorded in
**Settings → Rules → Insights**.

That is the whole point of these two files. The protection of `main` is a
reviewed artefact in the repository, owned by `.github/CODEOWNERS` like any
other, instead of a checkbox somebody remembers ticking.

## Importing one

    Settings → Rules → Rulesets → New ruleset ▾ → Import a ruleset
      → open .github/rulesets/main.json → review → Create

Or, non-interactively, `scripts/github_guardrails_setup.sh` — which does the
same thing through `gh api`, is idempotent, and has a `--dry-run`.

**These files are the source of truth, not a snapshot.** Editing a ruleset in
the web UI without updating the file here is how the two drift; the day someone
re-imports, the UI edit is silently reverted. Change the file, open a pull
request, then apply.

## `main.json` — what each rule buys, and what it costs

| rule | why | cost |
|---|---|---|
| `deletion` | `main` cannot be deleted, by anyone, ever. | none |
| `non_fast_forward` | No force push. History on `main` is append-only, so a commit that was green stays reachable and `git bisect` has something to stand on. | none |
| `required_linear_history` | No merge commits. The history reads as a list of reviewed changes, and reverting a release is one revert instead of an archaeology exercise. | merge-commit merges are refused; `allowed_merge_methods` below already removes the button. |
| `pull_request` | Nothing reaches `main` without a pull request, one approval, and a Code Owner among the approvers. | on a two-maintainer project this means **neither maintainer can merge alone** — see the bypass below. |
| `required_status_checks` | The fifteen checks named in the file must be green, and the branch must be up to date with `main` first. | every merge to `main` invalidates every open pull request, which must then be updated and re-run. |

### The `pull_request` parameters, individually

- `required_approving_review_count: 1` — one human, deliberately not two. Two
  approvals on a project with two maintainers means every change waits for both
  of them, and the predictable outcome is approvals given without reading.
- `require_code_owner_review: true` — this is the checkbox that makes
  `.github/CODEOWNERS` a gate rather than a suggestion. Without it, that file
  only *requests* a review and a pull request touching `quality/gate.py` can be
  merged with nobody having looked at it.
- `dismiss_stale_reviews_on_push: true` — an approval describes a diff, not a
  branch. A push after the approval produces a different diff, and the approval
  no longer says anything about it.
- `require_last_push_approval: true` — the person who pushed last cannot be the
  person who approved. This closes the "approve, then push one more commit, then
  merge" path, which is the cheapest way to land unreviewed code through a
  process that looks correct.
- `required_review_thread_resolution: true` — an unresolved comment is a
  question nobody answered. Merging over it converts a review finding into a
  silent decision.
- `allowed_merge_methods: ["squash", "rebase"]` — merge commits are removed from
  the UI, which is the same thing `required_linear_history` enforces at push
  time. Having both means the button disappears instead of the merge failing
  with a message nobody expects.

### The bypass, and why it exists

    "actor_type": "RepositoryRole", "actor_id": 5, "bypass_mode": "pull_request"

`actor_id: 5` is the built-in **Admin** repository role. `bypass_mode:
"pull_request"` is the narrow form: the holder still has to open a pull request
— the change is still visible, still has a diff, still gets a CI run — but can
merge it without the second pair of eyes and without every check green.

This is the single hole in the wall, and it is deliberate. A guardrail with no
legitimate way through gets removed the first Friday it blocks a fix, and then
nothing is protected. `.github/GUARDRAILS.md` lists the three situations in
which using it is acceptable; every use appears in Settings → Rules → Insights
with a name against it.

To close the hole entirely, set `"bypass_actors": []`. Then the only way past is
to set the ruleset's `enforcement` to `evaluate` or `disabled`, which is also
logged, and also has to be undone.

The well-known repository-role ids are `2` (Maintain), `4` (Write) and `5`
(Admin). They are stable and universally used, but GitHub does not document them
on the rulesets page — `scripts/github_guardrails_setup.sh --plan` prints what
it is about to send so a wrong id is visible before it is applied, and an
unknown actor makes the UI import fail loudly rather than silently.

### The required check names

They are the names GitHub actually reports, which for a matrix job is the job id
followed by the matrix values in parentheses — `quality (3.11)`, not `quality`.
**A name that never reports does not protect anything**: the rule matches no
check, the merge button waits for a status that will never arrive, and the
"protection" is indistinguishable from a permanently stuck pull request.

Before trusting this list, verify it against a real pull request:

    scripts/github_guardrails_setup.sh --check-names <sha>

which asks GitHub what check runs that commit produced and diffs them against
the contexts in `main.json`.

`integration_id` is deliberately absent from every entry. Pinning a check to the
GitHub Actions app (id `15368`) is stricter — it stops a commit status of the
same name posted by anything else from satisfying the rule — but a wrong
`integration_id` makes the rule match nothing at all, which is the failure this
file most wants to avoid. `.github/GUARDRAILS.md` has the command that reads the
real id off a check run, for whoever wants to add it.

`do_not_enforce_on_create: true` exempts branch *creation* from the status
checks. Without it, the first push of a new branch is refused for having no
checks yet — which is not a thing anyone can fix.

## `tags-release.json` — why a tag needs protecting at all

`.github/workflows/release.yml` fires on `v*` and publishes to PyPI. That makes a
tag in this repository an executable object, not a bookmark: whoever can move
`v0.4.1` can cause a different tree to be built and uploaded under a version
number users have already pinned.

- `deletion` and `non_fast_forward` and `update` — a `v*` tag, once pushed,
  cannot be deleted, force-moved or updated. Three rules for one property
  because a tag can be re-pointed in more than one way, and PyPI refuses to
  reuse a filename: a wrong upload cannot be replaced, only superseded by
  burning the next version number.
- `tag_name_pattern` — the release workflow triggers on the glob `v*`, which
  includes `vfoo` and `v1`. The regex confines it to
  `v<major>.<minor>.<patch>` with an optional `a`/`b`/`rc`/`.post` suffix, so a
  mistyped tag is refused at push time instead of starting a release that fails
  three minutes later in the version-check step.

Admins keep an `always` bypass here, unlike on `main`. Deleting a botched tag
*before* the publish job reaches PyPI is a genuine emergency with a clock on it,
and the alternative — disabling the ruleset, deleting, re-enabling — is three
steps at the worst possible moment.

## Signed commits

Not in either file, on purpose. `required_signatures` is a real hardening and it
is also the rule most likely to lock out an occasional contributor, because it
fails at `git push` with a message that does not explain how to fix it. The
trade-off, and the one-line command to enable it, are in
`.github/GUARDRAILS.md` under "Signed commits".
