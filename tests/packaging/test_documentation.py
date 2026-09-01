"""The documentation promises an API — this test checks it exists.

Documentation that ages silently is worse than no documentation: readers trust
it. Here the README is read as the source and every name it mentions is checked
against the code, so renaming something without updating the text breaks CI
rather than breaking the user.
"""

from __future__ import annotations

import contextlib
import io
from pathlib import Path

import pytest

#: The repository root, from ``tests/packaging/``.
ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"


@pytest.fixture(scope="module")
def readme() -> str:
    if not README.is_file():
        pytest.skip("README missing (installed without the repository)")
    return README.read_text(encoding="utf-8")


def test_the_promised_api_exists():
    """The names the README uses in its examples."""
    import autosxtract

    for name in ("Cascade", "Config", "Result", "Lexicon", "OCREngine", "register"):
        assert hasattr(autosxtract, name), name


def test_the_result_attributes_mentioned_exist():
    """A dataclass field with no default is NOT a class attribute — the check
    has to look at the declared fields, not ``hasattr`` on the type."""
    from autosxtract import Result

    fields = set(Result.__dataclass_fields__)
    for field in ("text", "step", "score", "attempts"):
        assert field in fields, field
    for member in ("provenance", "to_dict", "empty"):
        assert hasattr(Result, member), member


def test_the_cascade_methods_mentioned_exist():
    from autosxtract import Cascade

    for method in ("extract", "extract_file", "extract_batch", "names"):
        assert hasattr(Cascade, method), method


def _help(*argv: str) -> str:
    from autosxtract import cli

    buffer = io.StringIO()
    with (
        contextlib.suppress(SystemExit),
        contextlib.redirect_stdout(buffer),
        contextlib.redirect_stderr(buffer),
    ):
        cli.main([*argv, "--help"])
    return buffer.getvalue()


def test_the_documented_subcommands_exist():
    help_text = _help()
    for sub in ("extract", "diagnose", "download-models"):
        assert sub in help_text, sub


def test_the_documented_flags_exist():
    help_text = _help("extract")
    for flag in ("--json", "--dpi", "--det", "--rec", "--rec-dir", "--no-layers", "--engines"):
        assert flag in help_text, flag


def test_the_extras_mentioned_in_the_readme_exist(readme):
    """An extra that is mentioned but not declared becomes a failing install."""
    import re
    from importlib.metadata import metadata

    declared = set(metadata("autosxtract").get_all("Provides-Extra") or [])
    if not declared:
        pytest.skip("package installed without metadata")
    mentioned = set(re.findall(r"autosxtract\[([a-z,]+)\]", readme))
    for group in mentioned:
        for extra in group.split(","):
            assert extra in declared, f"the README mentions [{extra}], undeclared by the package"


def test_the_environment_variable_mentioned_is_read(readme):
    from autosxtract.engines import models

    if "AUTOSXTRACT_MODELS" in readme:
        import inspect

        assert "AUTOSXTRACT_MODELS" in inspect.getsource(models)


def test_the_readme_version_matches_the_package(readme):
    """The ``diagnose`` sample output carries the version; it ages."""
    import autosxtract

    if "autosxtract 0." in readme:
        assert f"autosxtract {autosxtract.__version__}" in readme
