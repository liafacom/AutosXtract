"""The leak scanner's own correctness.

``scripts/privacy_check.py`` is the only check in this repository that prevents
something irreversible rather than merely a red CI: it runs first in
``pre-commit``, on every CI push, on the branch's own history and on the tree a
release tag points at. CLAUDE.md §9 records that it has already caught a real
case number that had reached the examples.

It had no test. A refactor that made ``valid_tax_id`` return ``False``
unconditionally would have turned the scanner permanently silent with a fully
green CI — the scan still runs, still reports "OK", and stops seeing anything.
That is the worst failure shape a guard can have, and it is the cheapest one to
close.

**No identifier appears in this file.** The valid ones are assembled at run time
by appending check digits to an arbitrary body, and the invalid ones by flipping
a digit of a valid one — so the complete values exist only in memory, and the
scanner reading this file finds nothing to report. That is what §9's convention
is protecting, and the test at the bottom verifies it holds for the whole
repository, this file included.

A validator can only be tested with inputs it should accept, so the arithmetic
here does produce structurally valid numbers. They are built from bodies chosen
for being unremarkable, they are never written down, and none is claimed to
correspond to anything.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

# Loaded by path: ``scripts/`` is not a package and is not on ``sys.path``. The
# scanner deliberately imports nothing outside the standard library — it has to
# keep working in a clone with no venv — so there is nothing else to arrange.
_SPEC = importlib.util.spec_from_file_location(
    "privacy_check",
    pathlib.Path(__file__).resolve().parents[2] / "scripts" / "privacy_check.py",
)
assert _SPEC and _SPEC.loader
privacy_check = importlib.util.module_from_spec(_SPEC)
# Registered BEFORE execution: ``@dataclass`` resolves annotations through
# ``sys.modules[cls.__module__]`` and raises on a module that is not there yet.
sys.modules["privacy_check"] = privacy_check
_SPEC.loader.exec_module(privacy_check)


# ── constructing valid identifiers, so none has to be quoted ─────────────


def _tax_id(body: str) -> str:
    """Append the two check digits to a 9-digit body, by the published rule."""
    digits = body
    for size in (9, 10):
        total = sum(int(digits[i]) * (size + 1 - i) for i in range(size))
        digits += str((total * 10) % 11 % 10)
    return digits


def _company_id(body: str) -> str:
    """Append the two check digits to a 12-digit body."""
    digits = body
    for size, weights in (
        (12, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
        (13, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]),
    ):
        total = sum(int(digits[i]) * weights[i] for i in range(size))
        remainder = total % 11
        digits += str(0 if remainder < 2 else 11 - remainder)
    return digits


def _case_check(number: str, rest: str) -> str:
    return f"{98 - (int(number + rest) * 100) % 97:02d}"


def _bump(digits: str, index: int = -1) -> str:
    """The same identifier with one digit changed — so the check digit fails."""
    replacement = str((int(digits[index]) + 1) % 10)
    return digits[:index] + replacement + (digits[index + 1 :] if index != -1 else "")


# ── the three validators ─────────────────────────────────────────────────


@pytest.mark.parametrize("body", ["111444777", "529982247", "012345678"])
def test_a_correctly_built_tax_id_is_recognised(body):
    assert privacy_check.valid_tax_id(_tax_id(body)) is True


@pytest.mark.parametrize("body", ["111444777", "529982247", "012345678"])
def test_one_wrong_digit_makes_a_tax_id_invalid(body):
    """Precision is the point: a scanner that fires on any 11 digits is a
    scanner somebody switches off, and then it guards nothing."""
    assert privacy_check.valid_tax_id(_bump(_tax_id(body))) is False


def test_a_repeated_digit_tax_id_is_refused():
    """``111.111.111-11`` satisfies the arithmetic and is not an identifier."""
    assert privacy_check.valid_tax_id("11111111111") is False


@pytest.mark.parametrize("body", ["112223330001", "334445550001"])
def test_a_correctly_built_company_id_is_recognised(body):
    assert privacy_check.valid_company_id(_company_id(body)) is True


@pytest.mark.parametrize("body", ["112223330001", "334445550001"])
def test_one_wrong_digit_makes_a_company_id_invalid(body):
    assert privacy_check.valid_company_id(_bump(_company_id(body))) is False


def test_a_repeated_digit_company_id_is_refused():
    assert privacy_check.valid_company_id("00000000000000") is False


def test_a_correctly_built_case_number_is_recognised():
    number, rest = "1234567", "2020812" + "0001"
    assert privacy_check.valid_case_number(number, _case_check(number, rest), rest) is True


def test_a_wrong_case_number_check_digit_is_refused():
    number, rest = "1234567", "2020812" + "0001"
    wrong = f"{(int(_case_check(number, rest)) + 1) % 100:02d}"
    assert privacy_check.valid_case_number(number, wrong, rest) is False


def test_a_non_numeric_case_number_does_not_raise():
    """The scanner runs on arbitrary files; a regex match is not a promise."""
    assert privacy_check.valid_case_number("abc", "xx", "yyy") is False


# ── the scan itself ──────────────────────────────────────────────────────


def _scan(tmp_path: pathlib.Path, text: str) -> list:
    target = tmp_path / "sample.txt"
    target.write_text(text, encoding="utf-8")
    report = privacy_check.Report()
    privacy_check.scan_content(target, report, tmp_path)
    return report.findings


def test_the_scan_finds_a_valid_identifier(tmp_path):
    """End to end: the validator is wired to the regex and to the report.

    Testing the validators alone would leave the wiring free to break — the
    scanner would keep running, find nothing, and say so cheerfully.
    """
    valid = _tax_id("529982247")
    findings = _scan(tmp_path, f"o numero e {valid} e nada mais\n")
    assert findings, "a valid identifier has to be found"


def test_the_scan_ignores_an_invalid_check_digit(tmp_path):
    """This is the convention the repository's own examples rely on."""
    assert not _scan(tmp_path, f"o numero e {_bump(_tax_id('529982247'))} e nada mais\n")


def test_the_repositorys_own_examples_stay_quiet(tmp_path):
    """CLAUDE.md §9: the identifiers in fixtures and docstrings are built with
    an INVALID check digit on purpose, so the scanner never has to be argued
    with. If this fails, an example acquired a valid check digit."""
    root = pathlib.Path(__file__).resolve().parents[2]
    report = privacy_check.Report()
    # Everything the scanner itself would read, via its own file collector —
    # not a glob of ``*.py``. The identifiers that matter live in the places a
    # ``.py`` glob misses: CLAUDE.md's own measurements, the ``why`` fields of
    # the pattern packs (§12 puts a measurement's evidence there), the docs and
    # the notebooks. Globbing Python only covered 98 of the 177 files.
    paths = privacy_check.collect(root, staged=False)
    assert len(paths) > 100, f"the collector returned only {len(paths)} files"
    for path in paths:
        privacy_check.scan_content(path, report, root)
    assert report.findings == []
