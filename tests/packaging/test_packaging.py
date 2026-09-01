"""What ``pip install autosxtract`` brings — pinned in a test.

The engine choice happens in TWO independent layers, and confusing them is easy:

    install    a PEP 508 marker in pyproject, evaluated by pip
    runtime    platform.py plus the engine registry

This file covers the first. It reads the **installed** package's metadata rather
than the source file: that is what actually reaches a user's machine, and it is
where a wrong marker would hide.
"""

from __future__ import annotations

from importlib.metadata import requires

import pytest


@pytest.fixture(scope="module")
def dependencies() -> list[str]:
    required = requires("autosxtract")
    if not required:
        pytest.skip("package not installed (running outside an installed environment)")
    # Extras carry "; extra == 'name'"; only the mandatory ones matter here.
    return [d for d in required if "extra ==" not in d]


def _line(dependencies: list[str], name: str) -> str:
    found = [d for d in dependencies if d.lower().startswith(name)]
    assert found, f"{name} is not among the mandatory dependencies: {dependencies}"
    return found[0]


def test_the_core_carries_no_marker(dependencies):
    """PyMuPDF and pydantic go on every machine — step 1 and the config."""
    assert ";" not in _line(dependencies, "pymupdf")
    assert ";" not in _line(dependencies, "pydantic")


def test_imaging_goes_on_every_platform(dependencies):
    """They used to ride along on rapidocr's dependency and were therefore
    missing on macOS, where the engine is Vision — Layer 2 simply did not run,
    silently."""
    for package in ("numpy", "pillow", "opencv-python-headless"):
        assert ";" not in _line(dependencies, package), package


def test_vision_is_only_installed_on_apple(dependencies):
    assert 'sys_platform == "darwin"' in _line(dependencies, "pyobjc-framework-vision").replace(
        "'", '"'
    )


def test_paddle_is_installed_everywhere(dependencies):
    """PP-OCRv6 carries NO marker — it is a step of the cascade on every machine.

    On a Mac it is not Vision's substitute, it is the step below it. A marker
    here made the Apple cascade ``native -> vision`` and nothing more: no third
    step when Vision refuses the page, and no second independent reading, so the
    agreement gate could never fire. The 200 MB of ONNX Runtime is the price of
    the chain being complete by default.
    """
    for package in ("rapidocr", "onnxruntime"):
        assert ";" not in _line(dependencies, package), package


def test_only_vision_is_platform_gated(dependencies):
    """Exactly one mandatory dependency may carry a platform marker.

    pyobjc does not exist off Apple, so Vision has no choice. Everything else
    installs everywhere: a marker on another line would silently shorten
    somebody's cascade, which is the failure this file exists to catch.
    """
    gated = [d for d in dependencies if ";" in d]
    # The metadata normalises the distribution name to lower case, so compare
    # in the form pip actually writes it.
    assert [d.split(";")[0].strip().lower() for d in gated] == ["pyobjc-framework-vision>=10.0"]
    assert '== "darwin"' in gated[0].replace("'", '"')


@pytest.mark.paddle
@pytest.mark.slow
def test_the_default_install_yields_a_cascade_with_ocr():
    """The README's promise: ``pip install autosxtract`` and that is it.

    It holds for the machine the suite runs on. In an environment where the
    engine was uninstalled by hand the test warns, which is the right behaviour
    — that is exactly the state ``autosxtract diagnose`` exists to reveal.

    Marked ``paddle`` because it asserts the PP-OCR stack is really there, and
    ``slow`` because finding out loads it. It is meant to FAIL rather than skip
    where the default install was honoured, so the marker is a way of saying "I
    took the engine out on purpose", not a way of not looking.
    """
    from autosxtract.cascade import Cascade, engine_order

    assert engine_order(), (
        "no OCR engine available; the default install should bring one. "
        "Run `autosxtract diagnose` to see why."
    )
    assert len(Cascade().names) >= 2


@pytest.mark.paddle
@pytest.mark.slow
def test_paddle_is_a_step_of_the_apple_cascade():
    """On a Mac the chain is ``native -> vision -> paddle``, with no extra.

    This is the runtime half of ``test_paddle_is_installed_everywhere``: the
    marker being gone is only worth something if the registry then puts the
    engine in the order. Vision registers ahead of paddle by priority (10 vs
    20), so on Apple hardware both are there and Vision goes first.

    Not ``apple``: the assertion that matters — paddle is a step on EVERY
    platform — is the one that runs on Linux. Only the ordering below it needs
    a Mac, and it is guarded rather than deselected.
    """
    from autosxtract.cascade import engine_order
    from autosxtract.platform import is_apple

    order = engine_order()
    assert "paddle" in order, f"paddle should be a step on every platform; got {order}"
    if is_apple():
        assert order.index("vision") < order.index("paddle")
