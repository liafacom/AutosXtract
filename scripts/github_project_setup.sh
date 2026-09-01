#!/usr/bin/env bash
#
# The repository's shop window, in the repository.
#
# Topics, description, website and feature toggles live in a settings page that
# nobody can diff, nobody reviews, and nobody can restore after somebody
# "tidied up" the About box. This script is the reviewable version of that
# page: run it and the settings match the file, run it twice and the second run
# changes nothing.
#
#   ./scripts/github_project_setup.sh --dry-run    # print the plan, touch nothing
#   ./scripts/github_project_setup.sh              # print the plan, then apply it
#
# It reads the CURRENT state first and prints only the differences, so the plan
# is an honest list of what is about to change rather than a list of everything
# it would set. That is the difference between a script you can be persuaded to
# run on a live repository and one you cannot.
#
# What it deliberately does NOT touch:
#   * branch protection and rulesets   — .github/rulesets/, applied separately
#   * labels                           — .github/labels.yml, applied separately
#   * PyPI                             — RELEASING.md, applied by a human with 2FA
#   * Sponsorships                     — no API and no gh flag; see RELEASING.md
#
# Requires: gh (GitHub CLI), authenticated, with admin rights on the repository.

set -euo pipefail

# ── What the repository should look like ────────────────────────────────────

REPO_DEFAULT="liafacom/AutosXtract"

# 350 characters is GitHub's cap on the About description. This one leads with
# the mechanism rather than the category, because "PDF text extraction" is a
# crowded shelf and "stops at the first step that suffices" is the part that is
# actually different.
DESCRIPTION="Cascading PDF text extraction: every document descends steps from the cheapest to the most expensive and stops at the first one that produces acceptable text. Apple Vision on macOS, PP-OCRv6 everywhere else, one pip install and no engine to choose."

# The website field, not the repository URL. It points at the MkDocs site that
# .github/workflows/docs.yml deploys, because someone arriving from a search
# result wants the getting-started page, not a directory listing.
HOMEPAGE="https://liafacom.github.io/AutosXtract/"

# GitHub allows at most 20 topics, lowercase, digits and hyphens, 50 characters
# each. There are exactly 20 below, so anything added here has to displace
# something — which is the point: a topic list is a ranking, not an inventory.
#
# Three groups, and all three earn their place:
#
#   discovery   the words somebody types when they do not know this project
#               exists (pdf, ocr, text-extraction, pdf-to-text). These are the
#               only ones that bring in a stranger.
#   technology  the engines and libraries a reader wants to confirm before
#               installing 570 MB (apple-vision, paddleocr, onnxruntime,
#               pymupdf). These answer "is this the stack I already trust".
#   domain      what the corpus actually is (legal-tech, portuguese,
#               scanned-documents). These are what make the project findable by
#               the people it was built for rather than by everybody.
TOPICS=(
  # discovery
  pdf
  pdf-extraction
  pdf-to-text
  text-extraction
  ocr
  optical-character-recognition
  python
  cli
  # framing
  document-ai
  document-processing
  information-extraction
  scanned-documents
  # technology
  apple-vision
  paddleocr
  onnxruntime
  pymupdf
  macos
  linux
  # domain
  legal-tech
  portuguese
)

# Feature toggles, each with the reason it is set that way. "true" and "false"
# only; anything else is a bug in this file.
#
# issues       ON  — the YAML issue forms are the intake. The Extraction
#                    quality form is the one that matters: it collects the
#                    provenance string, the attempt list and the page profile
#                    INSTEAD of the document. Turning issues off would send
#                    people to email, where they attach the PDF.
# discussions  ON  — .github/ISSUE_TEMPLATE/config.yml already routes "is this
#                    supposed to work like that?" to /discussions. With
#                    Discussions off that contact link is a 404 on the busiest
#                    page in the repository.
# wiki         OFF — the documentation is versioned in docs/ and deployed by
#                    docs.yml with `mkdocs build --strict`, which fails on a
#                    dead link. A wiki is a second, unversioned, unreviewed
#                    copy that cannot fail a build, so it drifts and then
#                    contradicts the one that is checked.
# projects     OFF — the repository-level Projects tab. Planning here is issues
#                    and milestones; an empty tab is a link that teaches people
#                    the navigation is decorative. Organisation-level Projects
#                    are a separate thing and are unaffected by this.
FEATURE_ISSUES="true"
FEATURE_DISCUSSIONS="true"
FEATURE_WIKI="false"
FEATURE_PROJECTS="false"

# Merge behaviour. Squash only: one merged pull request becomes one commit on
# main, which is what makes `git log v0.4.0..v0.4.1` readable as a release and
# what makes a bisect land on a reviewable change instead of on "wip".
# Deleting the branch on merge keeps the branch list to work in progress.
MERGE_COMMIT="false"
MERGE_SQUASH="true"
MERGE_REBASE="false"
DELETE_BRANCH_ON_MERGE="true"

# Push protection is the only control here that prevents a leak rather than
# reporting one: it blocks the push that carries a credential instead of
# opening an alert after it is already in the history and already mirrored.
# The project has a privacy scanner for documents; this is its equivalent for
# secrets. Free on public repositories.
SECRET_SCANNING="true"

# ── Machinery ───────────────────────────────────────────────────────────────

REPO="$REPO_DEFAULT"
DRY_RUN="false"

usage() {
  cat <<'USAGE'
Usage: scripts/github_project_setup.sh [--dry-run] [--repo OWNER/NAME]

  --dry-run          Print the plan and exit without changing anything.
  --repo OWNER/NAME  Act on another repository (a fork, for a rehearsal).
                     Defaults to liafacom/AutosXtract.
  -h, --help         This text.

Exit codes: 0 nothing to do or applied, 1 refused (no gh, not authenticated,
not an admin), 2 bad usage.
USAGE
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN="true"; shift ;;
    --repo)    [ $# -ge 2 ] || { usage >&2; exit 2; }; REPO="$2"; shift 2 ;;
    --repo=*)  REPO="${1#--repo=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *)         printf 'error: unknown argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

# Refuse early and say what to do about it. A script that gets halfway through
# and then fails on authentication has already made the repository's state
# something nobody can describe.
command -v gh >/dev/null 2>&1 || die "the GitHub CLI (gh) is not on PATH.
  Install it from https://cli.github.com/ , or apply the same settings by hand:
  repository home -> About (the gear icon on the right) -> Description, Website,
  Topics; and Settings -> General -> Features for the toggles.
  RELEASING.md lists every value this script would have set."

gh auth status >/dev/null 2>&1 || die "gh is installed but not authenticated.
  Run:  gh auth login
  The account has to have admin rights on $REPO — repository metadata is an
  admin-only write, and a non-admin token fails per setting, halfway through."

# ── Read the current state ──────────────────────────────────────────────────
#
# One helper, one field per call. Slower than a single query, and worth it: a
# failing call names the field it could not read.
gh_field() {
  gh repo view "$REPO" --json "$1" --jq "$2"
}

cur_description=$(gh_field description '.description // ""')
cur_homepage=$(gh_field homepageUrl '.homepageUrl // ""')
cur_topics=$(gh_field repositoryTopics '.repositoryTopics[].name // empty')
cur_issues=$(gh_field hasIssuesEnabled '.hasIssuesEnabled')
cur_discussions=$(gh_field hasDiscussionsEnabled '.hasDiscussionsEnabled')
cur_wiki=$(gh_field hasWikiEnabled '.hasWikiEnabled')
cur_projects=$(gh_field hasProjectsEnabled '.hasProjectsEnabled')
cur_merge=$(gh_field mergeCommitAllowed '.mergeCommitAllowed')
cur_squash=$(gh_field squashMergeAllowed '.squashMergeAllowed')
cur_rebase=$(gh_field rebaseMergeAllowed '.rebaseMergeAllowed')
cur_delete_branch=$(gh_field deleteBranchOnMerge '.deleteBranchOnMerge')
cur_admin=$(gh_field viewerCanAdminister '.viewerCanAdminister')

[ "$cur_admin" = "true" ] || die "the authenticated account is not an admin of $REPO.
  Repository metadata (topics, description, features) is an admin-only write.
  Ask @ArthurSilvaDantas or @edsontm to run this, or to grant admin."

# Secret scanning is not exposed by `gh repo view --json`; it lives under
# security_and_analysis in the REST representation. An empty answer means the
# field is absent, which is how a repository that has never had it enabled
# looks.
cur_secret_scanning=$(gh api "repos/$REPO" \
  --jq '.security_and_analysis.secret_scanning.status // "disabled"' 2>/dev/null || echo "unknown")
cur_push_protection=$(gh api "repos/$REPO" \
  --jq '.security_and_analysis.secret_scanning_push_protection.status // "disabled"' 2>/dev/null || echo "unknown")

# ── Build the plan ──────────────────────────────────────────────────────────

PLAN=()
EDIT_ARGS=()

want_flag() {  # want_flag <flag> <desired true|false> <current> <human name>
  local flag="$1" want="$2" have="$3" name="$4"
  [ "$want" = "$have" ] && return 0
  PLAN+=("$name: $have -> $want")
  EDIT_ARGS+=("--${flag}=${want}")
}

if [ "$cur_description" != "$DESCRIPTION" ]; then
  PLAN+=("description: set (was ${#cur_description} chars, becomes ${#DESCRIPTION})")
  EDIT_ARGS+=(--description "$DESCRIPTION")
fi

if [ "$cur_homepage" != "$HOMEPAGE" ]; then
  PLAN+=("website: '${cur_homepage}' -> '${HOMEPAGE}'")
  EDIT_ARGS+=(--homepage "$HOMEPAGE")
fi

# Topics are a set, and gh edits it by delta rather than by replacement, so the
# script has to compute both directions. Adding a topic that is already there
# is harmless; the diff exists so the printed plan is truthful, not because gh
# would object.
for t in "${TOPICS[@]}"; do
  case $'\n'"$cur_topics"$'\n' in
    *$'\n'"$t"$'\n'*) : ;;
    *) PLAN+=("topic + $t"); EDIT_ARGS+=(--add-topic "$t") ;;
  esac
done

if [ -n "$cur_topics" ]; then
  while IFS= read -r t; do
    [ -n "$t" ] || continue
    keep="false"
    for w in "${TOPICS[@]}"; do [ "$t" = "$w" ] && keep="true" && break; done
    [ "$keep" = "true" ] || { PLAN+=("topic - $t  (not in the list above)"); EDIT_ARGS+=(--remove-topic "$t"); }
  done <<< "$cur_topics"
fi

want_flag enable-issues            "$FEATURE_ISSUES"          "$cur_issues"        "Issues"
want_flag enable-discussions       "$FEATURE_DISCUSSIONS"     "$cur_discussions"   "Discussions"
want_flag enable-wiki              "$FEATURE_WIKI"            "$cur_wiki"          "Wiki"
want_flag enable-projects          "$FEATURE_PROJECTS"        "$cur_projects"      "Projects tab"
want_flag enable-merge-commit      "$MERGE_COMMIT"            "$cur_merge"         "Merge commits"
want_flag enable-squash-merge      "$MERGE_SQUASH"            "$cur_squash"        "Squash merge"
want_flag enable-rebase-merge      "$MERGE_REBASE"            "$cur_rebase"        "Rebase merge"
want_flag delete-branch-on-merge   "$DELETE_BRANCH_ON_MERGE"  "$cur_delete_branch" "Delete branch on merge"

if [ "$SECRET_SCANNING" = "true" ] && [ "$cur_secret_scanning" != "enabled" ]; then
  PLAN+=("Secret scanning: $cur_secret_scanning -> enabled")
  EDIT_ARGS+=(--enable-secret-scanning)
fi
if [ "$SECRET_SCANNING" = "true" ] && [ "$cur_push_protection" != "enabled" ]; then
  PLAN+=("Secret scanning push protection: $cur_push_protection -> enabled")
  EDIT_ARGS+=(--enable-secret-scanning-push-protection)
fi

# ── Print it, then do it ────────────────────────────────────────────────────

printf 'repository   %s\n' "$REPO"
printf 'mode         %s\n\n' "$([ "$DRY_RUN" = "true" ] && echo 'dry run — nothing will be changed' || echo 'apply')"

if [ ${#PLAN[@]} -eq 0 ]; then
  echo "Already matches this file. Nothing to do."
  exit 0
fi

echo "The following would change:"
for line in "${PLAN[@]}"; do printf '  %s\n' "$line"; done
echo

if [ "$DRY_RUN" = "true" ]; then
  echo "Dry run: stopping here. Re-run without --dry-run to apply."
  exit 0
fi

# One call, so a partial failure leaves fewer half-states than a loop would.
echo "Applying..."
gh repo edit "$REPO" "${EDIT_ARGS[@]}"
echo "Done. Re-run with --dry-run to confirm it now reports nothing to do."

# ── The parts no CLI can do ─────────────────────────────────────────────────
cat <<'MANUAL'

Three settings have no gh flag and no API, and stay a human's job:

  Sponsorships   Settings -> General -> Features -> Sponsorships.
                 Leave OFF. It needs a .github/FUNDING.yml to point anywhere,
                 and a Sponsor button that leads nowhere reads as abandonment.

  Social preview Settings -> General -> Social preview.
                 The image every link to this repository renders as, on Slack,
                 on X and in a search result. Without one the card is a grey
                 octocat and looks like a scratch repository.

  Pages source   Settings -> Pages -> Build and deployment -> Source:
                 GitHub Actions. docs.yml deploys the site the Website field
                 above points at; with the source left on "Deploy from a
                 branch" that deployment fails and the Website field 404s.
MANUAL
