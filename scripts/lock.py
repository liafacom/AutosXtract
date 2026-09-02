#!/usr/bin/env python3
"""Regenerate ``constraints/dev.txt`` from the environment that is working now.

Run it with the interpreter whose environment you want to freeze::

    .venv/bin/python scripts/lock.py        # or: make lock

Why this exists instead of ``pip freeze > constraints/dev.txt``: a freeze
records **everything the venv happens to contain** — the ``twine`` somebody
installed to push a release, a leftover from an experiment — and a newcomer
would then be pinned to tools the project never asked for. This walks the
declared dependency graph of ``autosxtract[dev]`` from the installed metadata
and writes only what is genuinely reachable from ``pyproject.toml``.

What it deliberately does NOT do:

* It does not touch ``pyproject.toml``. The runtime ranges there stay open —
  see the header this script writes into the file for the consequence of
  narrowing them.
* It does not invent versions for packages that are not installed here. A
  Linux machine cannot know which ``pyobjc-framework-Vision`` a Mac should
  get, and pinning a guess is worse than not pinning: it turns a working
  install into a resolver error on a platform nobody tested.
"""

from __future__ import annotations

import importlib.metadata as metadata
import platform
import sys
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "constraints" / "dev.txt"

# The environment bootstrap builds by default: the library plus the dev extra.
# The heavy optional extras (docling's ~2 GB of models, paddleocr, onnxtr) are
# NOT pinned here — see the header written below.
ROOT_EXTRAS = frozenset({"dev"})

# Never pinned: they are the installer, not a dependency of the project, and a
# pin on them fights `pip install --upgrade pip` in every CI log.
EXCLUDE = {"autosxtract", "pip", "setuptools", "wheel", "distribute"}


def canonical(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def walk(
    name: str,
    extras: frozenset[str],
    found: dict[str, str],
    missing: set[str],
    seen: set[tuple[str, frozenset[str]]] | None = None,
) -> None:
    """Depth-first over the *installed* metadata, honouring PEP 508 markers.

    ``seen`` is not an optimisation. Without it a cycle in installed metadata —
    they exist in the wild — recurses to ``RecursionError``, and a diamond is
    re-walked once per path rather than once per node, so the cost is exponential
    in depth. It works on ``autosxtract[dev]`` because that graph is shallow,
    which is luck rather than a property.

    The memo is keyed on ``(name, extras)`` and not on the name alone: the same
    distribution reached with different extras pulls in different requirements,
    so collapsing them would drop pins.
    """
    if seen is None:
        seen = set()
    key = canonical(name)
    if (key, extras) in seen:
        return
    seen.add((key, extras))
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        # Declared but not installed: an extra nobody asked for, or a
        # dependency that does not apply here. Not an error — just not ours
        # to pin.
        missing.add(key)
        return

    version = dist.version
    if key not in EXCLUDE:
        found[key] = version

    for raw in dist.requires or []:
        req = Requirement(raw)
        if req.marker is not None:
            # A requirement guarded by `extra == "x"` is only ours if we asked
            # for that extra; one guarded by sys_platform is only ours if the
            # marker matches THIS machine.
            wanted = extras or frozenset({""})
            if not any(req.marker.evaluate({"extra": e}) for e in wanted):
                continue
        walk(req.name, frozenset(req.extras), found, missing, seen)


def main() -> int:
    found: dict[str, str] = {}
    missing: set[str] = set()
    walk("autosxtract", ROOT_EXTRAS, found, missing)

    if not found:
        print(
            "error: autosxtract is not installed in this interpreter\n"
            f"       ({sys.executable})\n"
            "       Run `make setup` first — the lock is a photograph of a "
            "working environment,\n"
            "       and there is nothing here to photograph.",
            file=sys.stderr,
        )
        return 1

    # MAJOR.MINOR, deliberately without the patch. The interpreter's patch
    # release does not take part in resolution — markers and wheel tags key on
    # `3.13`, not on `3.13.5` — so recording it claimed a precision the file
    # does not have, and made a REQUIRED check hostage to CPython's release
    # calendar: `setup-python: "3.13"` picks up the newest patch, and the
    # `pinned` job then failed on a comment line while all 51 pins were
    # identical. Measured on the first push: 3.13.5 against the runner's
    # 3.13.15, zero pins different.
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    lines = [
        "# ── DEV constraints — pins for the DEVELOPMENT environment and CI ────────",
        "#",
        "# Regenerate with `make lock`, never by hand. Generated by scripts/lock.py",
        (
            f"# from a known-good environment: Python {py} on {platform.system()}"
            f" ({platform.machine()})."
        ),
        "#",
        "# THIS FILE DOES NOT NARROW THE LIBRARY'S DEPENDENCIES, and must never be",
        "# read as if it did. `pyproject.toml` keeps `pymupdf>=1.24`, `numpy>=1.24`",
        "# and the rest OPEN on purpose: a library that pins its runtime deps is",
        "# unusable downstream — it makes itself uninstallable next to any project",
        "# that pinned a different patch release of the same package, and the person",
        "# who pays is a user who never asked us to have an opinion about their",
        "# resolver. Applications pin; libraries declare ranges. Both are right.",
        "#",
        "# What this file is for: making the DEV environment identical on two",
        "# machines, so that a test that fails on yours fails on mine. It is passed",
        "# with `-c`, which caps versions WITHOUT adding installs — a package listed",
        "# here that nothing requires is simply never installed.",
        "#",
        "#     pip install -e '.[dev]' -c constraints/dev.txt",
        "#",
        "# Scope, and its two deliberate holes:",
        "#",
        "#   1. Only `autosxtract[dev]` is covered — what `scripts/bootstrap.sh`",
        "#      installs by default and what CI's quality job installs. The heavy",
        "#      optional extras (docling ~2 GB, paddleocr, onnxtr, veto) are not",
        "#      pinned, because pinning what we never install would be pinning a",
        "#      guess.",
        "#   2. Apple-only wheels (pyobjc-framework-Vision, ocrmac) are absent: this",
        "#      file was generated off Apple hardware and a version invented here",
        "#      would be a version nobody has run. The README already lists 'a",
        "#      lockfile generated for another sys_platform' as a way to end up with",
        "#      a silently amputated cascade — this file refuses to become one. Every",
        "#      pin below is platform-neutral, so it is inert where it does not apply",
        "#      rather than wrong.",
        "#",
        "# No hashes on purpose: `--require-hashes` is all-or-nothing and forbids the",
        "# editable install of the project itself, which is the whole point of a dev",
        "# environment. Version pinning is what reproducibility needs here; hash",
        "# pinning is a supply-chain control that belongs on the release pipeline,",
        "# where nothing is editable.",
        "",
    ]
    for name in sorted(found):
        lines.append(f"{name}=={found[name]}")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(found)} pins from Python {py} on {platform.system()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
