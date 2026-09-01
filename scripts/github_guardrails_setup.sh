#!/usr/bin/env bash
#
# The gate on `main`, applied from the files that describe it.
#
# Branch protection is the one piece of this project's configuration that can be
# weakened by a single click, by one person, with no diff and no reviewer. That
# is why it lives in `.github/rulesets/*.json` — reviewed like code, owned by
# `.github/CODEOWNERS` like code — and why this script exists: to put those
# files onto GitHub without anybody retyping them into a settings page.
#
#   scripts/github_guardrails_setup.sh --dry-run        print the plan, touch nothing
#   scripts/github_guardrails_setup.sh                  print the plan, then apply it
#   scripts/github_guardrails_setup.sh --check-names SHA  verify the required check names
#
# Idempotent: it reads the current state first, matches each ruleset by NAME,
# and updates it in place rather than creating a second one. Run it twice and
# the second run reports nothing to do.
#
# What it deliberately does NOT touch, because another file owns it:
#   * description, topics, features, merge buttons,
#     secret scanning and push protection   — scripts/github_project_setup.sh
#   * labels                                — .github/labels.yml
#   * PyPI Trusted Publishing               — RELEASING.md, a human with 2FA
#
# The reasoning behind every rule it applies is in .github/GUARDRAILS.md and
# .github/rulesets/README.md. This file is the mechanism, not the argument.
#
# Requires: gh (GitHub CLI), authenticated, with ADMIN rights on the repository.
# Everything here is an administrative endpoint; write access is not enough.

set -euo pipefail

REPO_DEFAULT="liafacom/AutosXtract"

# Resolved from this file's location so the script works from any directory.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
RULESET_DIR="$ROOT/.github/rulesets"

REPO="$REPO_DEFAULT"
DRY_RUN="false"
CHECK_NAMES_SHA=""

usage() {
  cat <<'USAGE'
Usage: scripts/github_guardrails_setup.sh [options]

  --dry-run             Print the plan and exit without changing anything.
  --repo OWNER/NAME     Act on another repository — a fork, for a rehearsal.
                        Defaults to liafacom/AutosXtract.
  --check-names SHA     Ask GitHub which check runs that commit actually
                        produced, and diff them against the required contexts
                        in .github/rulesets/main.json. Read-only. Use a commit
                        from a pull request whose CI has finished.
  -h, --help            This text.

Applies:
  * every ruleset in .github/rulesets/*.json  (created, or updated by name)
  * Dependabot alerts and Dependabot security updates
  * private vulnerability reporting — the link SECURITY.md and the issue
    templates send people to, which 404s until it is on
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN="true"; shift ;;
    --repo) [ $# -ge 2 ] || { echo "--repo needs OWNER/NAME" >&2; exit 2; }
            REPO="$2"; shift 2 ;;
    --check-names) [ $# -ge 2 ] || { echo "--check-names needs a commit sha" >&2; exit 2; }
            CHECK_NAMES_SHA="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

die() { printf '\n%s\n\n' "$*" >&2; exit 1; }

# ── Refuse early, and say what to do about it ───────────────────────────────
# A script that half-runs against a live repository and then discovers it cannot
# authenticate is worse than one that never started: the plan it printed no
# longer describes the state it left behind.

command -v gh >/dev/null 2>&1 || die \
"gh (the GitHub CLI) is not installed, and every step here goes through it.

  macOS          brew install gh
  Debian/Ubuntu  see https://github.com/cli/cli/blob/trunk/docs/install_linux.md

Then:  gh auth login

Nothing has been changed. If you would rather not install anything, every rule
in .github/rulesets/ can be imported by hand:
  Settings -> Rules -> Rulesets -> New ruleset - Import a ruleset"

gh auth status >/dev/null 2>&1 || die \
"gh is installed but not authenticated, so nothing can be read or written.

  gh auth login

The account must have ADMIN rights on $REPO — rulesets, Dependabot settings and
private vulnerability reporting are all administrative endpoints, and write
access is refused with a 403 that does not say so in those words.

Nothing has been changed."

command -v python3 >/dev/null 2>&1 || die \
"python3 is missing. It is used to read and rewrite the ruleset JSON — jq is
deliberately not required, because it is not installed on every machine that
has gh.

Nothing has been changed."

[ -d "$RULESET_DIR" ] || die "no $RULESET_DIR — run this from a clone of the repository."

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ── --check-names: the failure mode this whole exercise turns on ────────────
# A required status check is matched by NAME. A name that never reports does not
# fail the merge — it hangs it, forever, on a status GitHub is still waiting
# for. The names for a matrix job carry the matrix values, `quality (3.11)` and
# not `quality`, and they change the moment somebody adds a `name:` to a job.
# This is how you find that out before it silently protects nothing.

if [ -n "$CHECK_NAMES_SHA" ]; then
  echo "Required contexts declared in .github/rulesets/main.json:"
  python3 - "$RULESET_DIR/main.json" <<'PY' | tee "$TMP/declared.txt"
import json, sys
doc = json.load(open(sys.argv[1]))
for rule in doc.get("rules", []):
    if rule.get("type") == "required_status_checks":
        for check in rule["parameters"]["required_status_checks"]:
            print(check["context"])
PY
  echo
  echo "Check runs GitHub reports for $CHECK_NAMES_SHA:"
  gh api "repos/$REPO/commits/$CHECK_NAMES_SHA/check-runs" --paginate \
    --jq '.check_runs[].name' | sort -u | tee "$TMP/actual.txt"
  echo
  missing="$(comm -23 <(sort -u "$TMP/declared.txt") <(sort -u "$TMP/actual.txt") || true)"
  if [ -n "$missing" ]; then
    echo "DECLARED BUT NEVER REPORTED — each of these blocks every merge forever:"
    printf '%s\n' "$missing" | sed 's/^/  /'
    echo
    echo "Fix the context in main.json to match the name above, or remove it."
    exit 1
  fi
  echo "Every declared context reported. The rule matches something."
  exit 0
fi

# ── The plan ────────────────────────────────────────────────────────────────
# Read the current state first, so what is printed is what would CHANGE and not
# a list of everything the script is capable of. That is the difference between
# a plan somebody reads and a plan somebody scrolls past.

echo "repository   $REPO"
if [ "$DRY_RUN" = "true" ]; then
  echo "mode         dry run — nothing will be changed"
else
  echo "mode         apply"
fi
echo

gh api "repos/$REPO/rulesets" --paginate > "$TMP/existing.json" 2>/dev/null \
  || die "cannot read the rulesets of $REPO. The token is authenticated but is
probably not an admin on that repository — every endpoint here needs admin.

Nothing has been changed."

PLAN=()
FILES=()
ACTIONS=()

shopt -s nullglob
for file in "$RULESET_DIR"/*.json; do
  name="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$file")"
  existing_id="$(python3 - "$TMP/existing.json" "$name" <<'PY'
import json, sys
name = sys.argv[2]
for ruleset in json.load(open(sys.argv[1])):
    if ruleset.get("name") == name:
        print(ruleset["id"])
        break
PY
)"
  if [ -n "$existing_id" ]; then
    PLAN+=("ruleset \"$name\" exists (id $existing_id) -> update in place from $(basename "$file")")
    ACTIONS+=("PUT repos/$REPO/rulesets/$existing_id")
  else
    PLAN+=("ruleset \"$name\" does not exist -> create it from $(basename "$file")")
    ACTIONS+=("POST repos/$REPO/rulesets")
  fi
  FILES+=("$file")
done
shopt -u nullglob

[ ${#FILES[@]} -gt 0 ] || die "no ruleset JSON found in $RULESET_DIR."

# Dependabot alerts. Free everywhere; the API answers 204 when on and 404 when
# off, which is why the state is read with a status code rather than a body.
alerts_on="$(gh api "repos/$REPO/vulnerability-alerts" --silent >/dev/null 2>&1 && echo yes || echo no)"
[ "$alerts_on" = "yes" ] \
  && PLAN+=("Dependabot alerts: already enabled") \
  || PLAN+=("Dependabot alerts: disabled -> enable")

# Dependabot security updates has no read endpoint at all — enabling it is
# idempotent, so it is simply always sent and reported as such.
PLAN+=("Dependabot security updates: enable (idempotent; GitHub exposes no way to read the current value)")

pvr_on="$(gh api "repos/$REPO" --jq '.security_and_analysis.private_vulnerability_reporting.status // "unknown"' 2>/dev/null || true)"
# An empty answer is not the same as "disabled": it means the field was absent,
# which is what a repository plan without the feature looks like. Say "unknown"
# rather than printing a blank and implying the current value is known.
pvr_on="${pvr_on:-unknown}"
if [ "$pvr_on" = "enabled" ]; then
  PLAN+=("Private vulnerability reporting: already enabled")
else
  PLAN+=("Private vulnerability reporting: $pvr_on -> enable (SECURITY.md and the issue templates link to it; it 404s while off)")
fi

echo "Plan:"
for line in "${PLAN[@]}"; do printf '  %s\n' "$line"; done
echo

echo "Rules that would be enforced on the default branch:"
python3 - "$RULESET_DIR/main.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
print(f"  enforcement: {doc['enforcement']}   target: {doc['target']}   "
      f"refs: {', '.join(doc['conditions']['ref_name']['include'])}")
for rule in doc.get("rules", []):
    kind = rule["type"]
    params = rule.get("parameters", {})
    if kind == "required_status_checks":
        checks = params["required_status_checks"]
        strict = params.get("strict_required_status_checks_policy")
        print(f"  {kind}: {len(checks)} required, branch-up-to-date={strict}")
        for check in checks:
            print(f"      {check['context']}")
    elif params:
        print(f"  {kind}: " + ", ".join(f"{k}={v}" for k, v in params.items()))
    else:
        print(f"  {kind}")
for actor in doc.get("bypass_actors", []):
    print(f"  BYPASS: {actor['actor_type']} id={actor['actor_id']} mode={actor['bypass_mode']}")
PY
echo

if [ "$DRY_RUN" = "true" ]; then
  echo "Dry run: stopping here. Re-run without --dry-run to apply."
  exit 0
fi

# ── Apply ───────────────────────────────────────────────────────────────────

echo "Applying..."

for index in "${!FILES[@]}"; do
  file="${FILES[$index]}"
  action="${ACTIONS[$index]}"
  method="${action%% *}"
  path="${action#* }"

  # An exported ruleset carries fields the create/update endpoints do not
  # accept — `id`, `source`, `source_type`, `created_at`, `_links`,
  # `current_user_can_bypass`. They are what makes the file importable through
  # the web UI, and sending them back is how a 422 with an unhelpful message
  # happens. Filter to what the API takes, and to nothing else.
  python3 - "$file" > "$TMP/body.json" <<'PY'
import json, sys
accepted = {"name", "target", "enforcement", "bypass_actors", "conditions", "rules"}
doc = json.load(open(sys.argv[1]))
json.dump({k: v for k, v in doc.items() if k in accepted}, sys.stdout)
PY

  printf '  %s %s\n' "$method" "$path"
  gh api -X "$method" "$path" --input "$TMP/body.json" >/dev/null
done

if [ "$alerts_on" != "yes" ]; then
  echo "  PUT repos/$REPO/vulnerability-alerts"
  gh api -X PUT "repos/$REPO/vulnerability-alerts" --silent
fi

echo "  PUT repos/$REPO/automated-security-fixes"
gh api -X PUT "repos/$REPO/automated-security-fixes" --silent

if [ "$pvr_on" != "enabled" ]; then
  echo "  PUT repos/$REPO/private-vulnerability-reporting"
  # Not fatal: on a private repository this endpoint is refused, and the rest of
  # the guardrails are still worth having. Say so instead of dying at the end.
  gh api -X PUT "repos/$REPO/private-vulnerability-reporting" --silent \
    || echo "    refused — private vulnerability reporting is a public-repository feature. See .github/GUARDRAILS.md."
fi

cat <<MANUAL

Done. Re-run with --dry-run: it should now report the rulesets as already
existing and nothing left to enable.

Two things this cannot finish on its own:

  1. VERIFY THE CHECK NAMES. Until a pull request has run its CI once, nothing
     proves the contexts in main.json match what GitHub actually reports — and
     a context that never reports blocks every merge instead of protecting one.
     Open a throwaway pull request, wait for CI, then:

         scripts/github_guardrails_setup.sh --check-names <the head commit sha>

  2. SETTINGS -> RULES -> INSIGHTS is where a bypass shows up with a name
     against it. It is the only record that the gate was opened, so it is worth
     looking at after a release. Nothing enforces that it is read.
MANUAL
