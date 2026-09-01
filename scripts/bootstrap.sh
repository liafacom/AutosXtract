#!/usr/bin/env bash
#
# One command between `git clone` and a working, identical development
# environment. Re-runnable: running it twice changes nothing except bringing an
# out-of-date venv back in line with constraints/dev.txt.
#
#     ./scripts/bootstrap.sh                  # core + dev, what CI's quality job has
#     ./scripts/bootstrap.sh --extras veto    # plus the Tesseract witness
#     PYTHON=python3.11 ./scripts/bootstrap.sh    # reproduce a CI matrix leg
#     VENV=/tmp/throwaway ./scripts/bootstrap.sh  # a venv that is not the repo's
#
# It ends by running `autosxtract diagnose`, and that last line is not
# decoration: what this library does to a document depends on which engines the
# machine actually has, and the cascade is a CHAIN, not a choice —
#
#     macOS          native -> vision -> paddle
#     Linux/Windows  native ->           paddle
#
# A newcomer who never sees that output has no way to know whether the surprise
# in their extraction is the code or their box. A missing step does not announce
# itself; this script makes it announce itself once, at the start.
#
# Every failure below exits with a sentence and a command to run. A traceback
# from inside pip tells a newcomer nothing about what they are missing.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="${VENV:-.venv}"
CONSTRAINTS="constraints/dev.txt"
PYTHON_VERSION_FILE=".python-version"
MIN_MAJOR=3
MIN_MINOR=11          # `requires-python = ">=3.11"` in pyproject.toml.

EXTRAS=""
INSTALL_HOOKS=1
RUN_DIAGNOSE=1

# ── output helpers ───────────────────────────────────────────────────────
# Colour only when stdout is a terminal: a CI log full of escape codes is
# harder to read than one without them.
if [ -t 1 ]; then
    B=$(printf '\033[1m'); DIM=$(printf '\033[2m'); RED=$(printf '\033[31m'); OFF=$(printf '\033[0m')
else
    B=""; DIM=""; RED=""; OFF=""
fi

step() { printf '%s==>%s %s\n' "$B" "$OFF" "$1"; }
note() { printf '%s    %s%s\n' "$DIM" "$1" "$OFF"; }
die()  { printf '\n%serror:%s %s\n' "$RED$B" "$OFF" "$1" >&2; shift; for l in "$@"; do printf '       %s\n' "$l" >&2; done; exit 1; }

usage() {
    cat <<'USAGE'
usage: scripts/bootstrap.sh [--extras a,b] [--no-hooks] [--no-diagnose]

  --extras LIST   comma-separated optional extras to add to [dev]
                  (apple, paddle, paddleocr, veto, onnx, remote, docling)
  --no-hooks      skip `pre-commit install`
  --no-diagnose   skip the closing cascade report (not recommended)

environment:
  PYTHON   interpreter to build the venv with (default: from .python-version)
  VENV     where to put the venv           (default: .venv)
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --extras) [ $# -ge 2 ] || die "--extras needs a value, e.g. --extras veto"; EXTRAS="$2"; shift 2 ;;
        --extras=*) EXTRAS="${1#*=}"; shift ;;
        --no-hooks) INSTALL_HOOKS=0; shift ;;
        --no-diagnose) RUN_DIAGNOSE=0; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; die "unknown argument: $1" ;;
    esac
done

# ── 1. the interpreter ───────────────────────────────────────────────────
# .python-version is the version this project develops on. It is a preference,
# not a requirement: the library supports 3.11 to 3.13 and CI proves it on all
# three, so a machine that only has another supported minor is fine and is told
# so rather than blocked.
WANTED=""
[ -f "$PYTHON_VERSION_FILE" ] && WANTED="$(tr -d '[:space:]' < "$PYTHON_VERSION_FILE")"

pick_python() {
    if [ -n "${PYTHON:-}" ]; then printf '%s' "$PYTHON"; return; fi
    if [ -n "$WANTED" ] && command -v "python${WANTED}" >/dev/null 2>&1; then
        printf 'python%s' "$WANTED"; return
    fi
    for c in python3.13 python3.12 python3.11 python3 python; do
        command -v "$c" >/dev/null 2>&1 && { printf '%s' "$c"; return; }
    done
    printf ''
}

PY_BIN="$(pick_python)"
[ -n "$PY_BIN" ] || die "no Python interpreter found on PATH." \
    "This project needs Python ${MIN_MAJOR}.${MIN_MINOR} or newer." \
    "Linux:  sudo apt install python${WANTED:-3.13} python${WANTED:-3.13}-venv" \
    "macOS:  brew install python@${WANTED:-3.13}"
command -v "$PY_BIN" >/dev/null 2>&1 || die "PYTHON=$PY_BIN is not an executable on PATH."

FOUND="$("$PY_BIN" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)" \
    || die "\`$PY_BIN\` exists but could not report its version — it is probably not a Python."
FOUND_MAJOR="${FOUND%%.*}"; rest="${FOUND#*.}"; FOUND_MINOR="${rest%%.*}"

# The readable version of "ERROR: Package requires a different Python", which
# is what pip would say three screens later.
if [ "$FOUND_MAJOR" -lt "$MIN_MAJOR" ] || { [ "$FOUND_MAJOR" -eq "$MIN_MAJOR" ] && [ "$FOUND_MINOR" -lt "$MIN_MINOR" ]; }; then
    die "Python $FOUND is too old (\`$PY_BIN\`). autosxtract needs ${MIN_MAJOR}.${MIN_MINOR} or newer." \
        "The project develops on ${WANTED:-3.13}; CI covers 3.11, 3.12 and 3.13." \
        "" \
        "Install one and point this script at it:" \
        "  Linux:  sudo apt install python${WANTED:-3.13} python${WANTED:-3.13}-venv" \
        "  macOS:  brew install python@${WANTED:-3.13}" \
        "  then:   PYTHON=python${WANTED:-3.13} ./scripts/bootstrap.sh"
fi

step "Python $FOUND ($(command -v "$PY_BIN"))"
if [ -n "$WANTED" ] && [ "${FOUND_MAJOR}.${FOUND_MINOR}" != "$WANTED" ]; then
    note "the project develops on $WANTED (.python-version); $FOUND is supported but"
    note "the pins in $CONSTRAINTS were resolved on $WANTED — a wheel may differ."
fi

# ── 2. system dependencies the wheels cannot bring ───────────────────────
# Only Tesseract, and only when asked for: it is the veto witness, and it is a
# BINARY. pytesseract installs happily without it and then fails at the first
# page, which reads like a bug in the library.
case ",$EXTRAS," in
    *,veto,*|*,all,*)
        command -v tesseract >/dev/null 2>&1 || die \
            "the \`veto\` extra needs the Tesseract binary, and it is not on PATH." \
            "pytesseract is only a wrapper: it installs cleanly and then fails on the" \
            "first page, which looks like a defect in autosxtract and is not." \
            "" \
            "  Linux:  sudo apt install tesseract-ocr tesseract-ocr-por" \
            "  macOS:  brew install tesseract tesseract-lang" \
            "" \
            "Or bootstrap without it: ./scripts/bootstrap.sh"
        note "tesseract found: $(command -v tesseract)"
        ;;
esac

# ── 3. the venv ──────────────────────────────────────────────────────────
# Never deleted automatically. Somebody may be running the suite out of it right
# now, and a script that silently removes a directory it did not create is a
# script nobody runs twice.
#
# Two creators, tried in order, because `python -m venv` is not as universal as
# it looks: on Debian and Ubuntu — and therefore in most containers — `ensurepip`
# ships in a SEPARATE apt package, and without it `venv` builds a directory and
# then dies seeding pip. `virtualenv` carries its own pip and does not care.
# Falling back to it turns "install a system package as root" into "nothing to
# do" for the commonest broken image there is.
make_venv() {
    # Both streams silenced: when ensurepip is missing, `venv` prints half a
    # page of apt advice that die() below says better and in context.
    if "$PY_BIN" -m venv "$VENV" >/dev/null 2>&1; then
        return 0
    fi
    # `venv` leaves a half-built directory behind; the pyvenv.cfg test keeps
    # this rm pointed at something we just created and nothing else.
    [ -f "$VENV/pyvenv.cfg" ] && rm -rf "$VENV"
    note "python -m venv failed (no ensurepip?) — trying virtualenv"
    # virtualenv wherever this machine happens to keep it: the chosen
    # interpreter, the PATH, or the repository's own venv, which has it as a
    # pre-commit dependency.
    for seeder in "$PY_BIN" "$REPO_ROOT/.venv/bin/python"; do
        if [ -x "$seeder" ] || command -v "$seeder" >/dev/null 2>&1; then
            if "$seeder" -m virtualenv --quiet -p "$PY_BIN" "$VENV" 2>/dev/null; then
                return 0
            fi
        fi
    done
    if command -v virtualenv >/dev/null 2>&1; then
        virtualenv --quiet -p "$PY_BIN" "$VENV" && return 0
    fi
    return 1
}

if [ -x "$VENV/bin/python" ]; then
    HAVE="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    if [ "$HAVE" != "${FOUND_MAJOR}.${FOUND_MINOR}" ]; then
        die "$VENV already exists and is Python $HAVE, but you asked for ${FOUND_MAJOR}.${FOUND_MINOR}." \
            "Refusing to delete a venv this script did not create — tests may be running in it." \
            "" \
            "  rm -rf $VENV && ./scripts/bootstrap.sh    # to rebuild it" \
            "  VENV=.venv-$WANTED ./scripts/bootstrap.sh # to keep both"
    fi
    step "reusing $VENV (Python $HAVE)"
else
    step "creating $VENV"
    make_venv || die \
        "could not create a virtual environment with \`$PY_BIN\`." \
        "Neither \`-m venv\` nor \`virtualenv\` worked. On Debian and Ubuntu the venv" \
        "module ships apart from the interpreter, and that is nearly always the reason:" \
        "" \
        "  sudo apt install python${FOUND_MAJOR}.${FOUND_MINOR}-venv" \
        "" \
        "Without root, install virtualenv instead and re-run:" \
        "  pipx install virtualenv     # or: python3 -m pip install --user virtualenv"
fi
VPY="$VENV/bin/python"

# ── 4. the install ───────────────────────────────────────────────────────
# `-c constraints/dev.txt` is what makes two machines identical. It caps
# versions without adding installs, so it stays inert for anything the platform
# does not resolve — the Apple wheels on Linux, for one.
[ -f "$CONSTRAINTS" ] || die "$CONSTRAINTS is missing." \
    "It is generated from a known-good environment; regenerate it with \`make lock\`."

TARGET=".[dev]"
[ -n "$EXTRAS" ] && TARGET=".[dev,${EXTRAS}]"

step "upgrading pip"
"$VPY" -m pip install --quiet --disable-pip-version-check --upgrade pip

step "installing $TARGET against $CONSTRAINTS"
note "editable: the venv follows the working tree, no reinstall after an edit"
"$VPY" -m pip install --disable-pip-version-check -e "$TARGET" -c "$CONSTRAINTS" || die \
    "the install failed." \
    "If the resolver complains about a pin, the constraints file was generated on" \
    "another Python or another platform. Regenerate it there with \`make lock\`," \
    "or bootstrap on ${WANTED:-3.13}, which is what it was resolved against."

# ── 4b. one cv2, and the right one ───────────────────────────────────────
# `opencv-python` and `opencv-python-headless` install the SAME import name.
# pyproject.toml asks for the headless build on purpose; rapidocr asks for the
# desktop one, and whichever pip unpacks LAST owns `cv2`. When the desktop build
# wins on a machine with no libGL — every slim container, most CI images — the
# import fails, `paddle` drops out of the cascade and `native` is all that is
# left. Measured here: 3 tests red and a scanned PDF that comes out empty
# "correctly".
#
# Reasserting the headless build is not a preference, it is restoring what
# pyproject.toml already declared; --no-deps keeps it from disturbing anything
# else that was just resolved.
if ! "$VPY" -c 'import cv2' >/dev/null 2>&1; then
    step "reasserting opencv-python-headless (cv2 came out unimportable)"
    "$VPY" -m pip install --quiet --disable-pip-version-check \
        --force-reinstall --no-deps opencv-python-headless -c "$CONSTRAINTS"
    "$VPY" -c 'import cv2' >/dev/null 2>&1 || die \
        "cv2 does not import in $VENV even with the headless build." \
        "$("$VPY" -c 'import cv2' 2>&1 | tail -1)" \
        "" \
        "Without cv2 the OCR step goes inert and the cascade silently shortens to" \
        "\`native\` — a scanned PDF then comes out empty. On a slim image:" \
        "  sudo apt install libgl1 libglib2.0-0"
fi

# ── 5. the hooks ─────────────────────────────────────────────────────────
# Installed by default, and the reason is in .pre-commit-config.yaml: the
# privacy scan is the only check here that prevents a leak rather than merely a
# red CI. A hook nobody installed protects nobody.
if [ "$INSTALL_HOOKS" -eq 1 ]; then
    if [ -d .git ]; then
        step "installing the git hooks"
        "$VPY" -m pre_commit install
    else
        note "not a git working tree — skipping the hooks"
    fi
fi

# ── 6. what this machine can actually do ─────────────────────────────────
if [ "$RUN_DIAGNOSE" -eq 1 ]; then
    step "cascade on this machine"
    "$VPY" -m autosxtract.cli diagnose
fi

printf '\n%sready.%s  next: %smake test%s   (targets: %smake help%s)\n' \
    "$B" "$OFF" "$B" "$OFF" "$B" "$OFF"
if [ "$VENV" = ".venv" ]; then
    printf '        the Makefile calls %s directly, so activating is optional.\n' "$VPY"
fi
