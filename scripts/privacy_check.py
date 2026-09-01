#!/usr/bin/env python3
"""Scan for sensitive artefacts before publishing.

In this project that is not a formality. The repository sits a few directories
away from **the real documents the library extracts** — and from the text it
produces out of them. One distracted ``git add -A`` is enough to leak a whole
case file: the suite's fixtures are synthetic precisely so there is no
temptation to commit a real PDF "just to reproduce the bug".

Precision matters more than raw recall — a scanner that shouts at every
14-digit number is switched off in the first week. That is why Brazilian tax
IDs, company IDs and case numbers are validated by their **check digit**, not
merely by their shape.

Usage:
    python scripts/privacy_check.py .
    python scripts/privacy_check.py . --staged     # only what is in the git index
    python scripts/privacy_check.py . --json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── extensions that should never enter the repository ────────────────────
# ``.pdf`` heads the list on purpose: it is the library's input format, and a
# single archive file committed by mistake is a real document published.
FORBIDDEN_EXT = {
    ".pdf",
    ".csv",
    ".xlsx",
    ".jsonl",
    ".parquet",
    ".pkl",
    ".pickle",
    ".joblib",
    ".npz",
    # Model weights: downloaded into ``~/.cache/autosxtract``, never committed.
    ".onnx",
    ".bin",
    ".model",
}
#: Where synthetic fixtures may legitimately live.
ALLOWED_IN = ("tests/fixtures/", "examples/data/")

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "htmlcov",
}

#: Paths and names that give away the institutional installation the library
#: came from. Not secrets, but they have no place in a public package — and
#: their presence signals a passage copied without review.
INTERNAL_PATHS = [
    r"/home/[a-z_][a-z0-9_-]*/(data|datasets|acervo|pdfs)\b",  # privacy-check: allow
    r"/home/[a-z_][a-z0-9_-]*/[a-z0-9_-]*-private\b",  # privacy-check: allow
]

#: Internal service addresses. The library is local by architecture: a
#: hard-coded host here is exactly the defect ``steps/remote.py`` exists to
#: prevent — a url is always a constructor parameter.
INTERNAL_ADDRESSES = [
    (r"https?://[a-z0-9.-]*\.ufms\.br", "institutional endpoint"),  # privacy-check: allow
    (r"https?://\d{1,3}(\.\d{1,3}){3}", "hard-coded IP address"),  # privacy-check: allow
]

#: Lines marked like this are ignored — so the scanner itself can define the
#: patterns it looks for without accusing itself.
IGNORE_MARK = "privacy-check: allow"

SECRETS = [
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"\bsk-[A-Za-z0-9]{20,}", "OpenAI-style API key"),
    (r"\bghp_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS credential"),
    (r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    (
        r"(?i)\b(api[_-]?key|token|senha|password)\s*[:=]\s*['\"][^'\"]{16,}['\"]",
        "embedded credential",
    ),
]

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
ALLOWED_EMAIL = re.compile(
    r"(noreply@|example\.(com|org)|@autosxtract|localhost|\.@[a-z]|@attrs\.)"
)

TAX_ID = re.compile(r"\b(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})\b")
COMPANY_ID = re.compile(r"\b(\d{2})\.?(\d{3})\.?(\d{3})/?(\d{4})-?(\d{2})\b")
CASE_NUMBER = re.compile(r"\b(\d{7})-?(\d{2})\.?(\d{4})\.?(\d)\.?(\d{2})\.?(\d{4})\b")


# ── check-digit validation: this is what gives precision ─────────────────
def valid_tax_id(d: str) -> bool:
    if len(set(d)) == 1:
        return False
    for size in (9, 10):
        total = sum(int(d[i]) * (size + 1 - i) for i in range(size))
        digit = (total * 10) % 11 % 10
        if digit != int(d[size]):
            return False
    return True


def valid_company_id(d: str) -> bool:
    if len(set(d)) == 1:
        return False
    for size, weights in (
        (12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
        (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
    ):
        total = sum(int(d[i]) * weights[i] for i in range(size))
        remainder = total % 11
        digit = 0 if remainder < 2 else 11 - remainder
        if digit != int(d[size]):
            return False
    return True


def valid_case_number(number: str, check: str, rest: str) -> bool:
    """Case-number check digit: ``98 - (NNNNNNN YYYY J TR OOOO * 100 mod 97)``."""
    try:
        return int(check) == 98 - (int(number + rest) * 100) % 97
    except ValueError:
        return False


@dataclass
class Finding:
    file: str
    line: int
    kind: str
    excerpt: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    files_read: int = 0

    def add(self, file, line, kind, excerpt) -> None:
        self.findings.append(Finding(str(file), line, kind, excerpt[:90]))


def _mask(s: str) -> str:
    """Never prints the whole value — the report is an artefact too."""
    return s[:4] + "*" * max(0, len(s) - 6) + s[-2:] if len(s) > 6 else "***"


def scan_content(path: Path, report: Report, root: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    report.files_read += 1
    relative = path.relative_to(root)

    for n, line in enumerate(text.splitlines(), 1):
        if IGNORE_MARK in line:
            continue
        for pattern, label in SECRETS:
            if re.search(pattern, line):
                report.add(relative, n, label, line.strip())
        for pattern, label in INTERNAL_ADDRESSES:
            if re.search(pattern, line):
                report.add(relative, n, label, line.strip())
        for pattern in INTERNAL_PATHS:
            if re.search(pattern, line):
                report.add(relative, n, "internal path", line.strip())
        for m in EMAIL.finditer(line):
            if not ALLOWED_EMAIL.search(m.group()):
                report.add(relative, n, "e-mail", _mask(m.group()))
        for m in TAX_ID.finditer(line):
            digits = "".join(m.groups())
            if valid_tax_id(digits):
                report.add(relative, n, "tax id (valid check digit)", _mask(digits))
        for m in COMPANY_ID.finditer(line):
            digits = "".join(m.groups())
            if valid_company_id(digits):
                report.add(relative, n, "company id (valid check digit)", _mask(digits))
        for m in CASE_NUMBER.finditer(line):
            g = m.groups()
            if valid_case_number(g[0], g[1], g[2] + g[3] + g[4] + g[5]):
                report.add(relative, n, "case number (valid check digit)", _mask("".join(g)))


def collect(root: Path, staged: bool) -> list[Path]:
    if staged:
        output = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        return [root / line for line in output.splitlines() if (root / line).is_file()]
    files = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if IGNORED_DIRS & set(p.relative_to(root).parts):
            continue
        files.append(p)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--staged", action="store_true", help="only files in the git index")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    report = Report()

    for file in collect(root, args.staged):
        relative = file.relative_to(root).as_posix()
        if file.suffix.lower() in FORBIDDEN_EXT and not relative.startswith(ALLOWED_IN):
            report.add(relative, 0, "data/model artefact", file.suffix)
            continue
        if file.stat().st_size > 2_000_000:
            continue
        scan_content(file, report, root)

    if args.as_json:
        print(
            json.dumps(
                {
                    "files_read": report.files_read,
                    "findings": [f.__dict__ for f in report.findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"privacy_check: {report.files_read} files inspected in {root}")
        if not report.findings:
            print("OK — no sensitive artefact found.")
        else:
            print(f"\n{len(report.findings)} FINDING(S):\n")
            for f in report.findings:
                where = f"{f.file}:{f.line}" if f.line else f.file
                print(f"  [{f.kind}] {where}\n      {f.excerpt}")
            print("\nFix before publishing (CLAUDE.md section 9).")
    return 1 if report.findings else 0


if __name__ == "__main__":
    sys.exit(main())
