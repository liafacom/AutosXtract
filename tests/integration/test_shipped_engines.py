"""What the registry holds against what THIS machine can actually run.

The registry is platform-independent by design — every engine is registered
everywhere, and only ``compatible()`` and ``available()`` narrow it down. That
separation is the whole reason a Linux box can be told, in words, why Vision is
not among its steps instead of finding an empty cascade.

These tests are integration because they ask the machine: ``diagnose()`` loads
each compatible engine, which is the most expensive thing the suite does.
"""

from __future__ import annotations

import platform

import pytest

from autosxtract.engines import base as engines


def test_the_shipped_engines_are_registered():
    names = {i.name for i in engines.registered()}
    assert {"vision", "paddle", "tesseract"} <= names


def test_priority_puts_vision_first():
    """Measured on 60 documents: 92% of words and 100% of anchors, against 53%."""
    order = [i.name for i in engines.registered()]
    assert order.index("vision") < order.index("paddle")
    assert order.index("paddle") < order.index("tesseract")


def test_apple_engines_stay_out_on_linux():
    compatible = {i.name for i in engines.compatible()}
    if platform.system() == "Darwin":
        assert "vision" in compatible
    else:
        assert "vision" not in compatible
        assert "paddle" in compatible


@pytest.mark.slow
def test_the_diagnosis_explains_every_absence():
    """Marked ``slow``: ``diagnose`` LOADS every compatible engine.

    On a cold machine that means downloading the PP-OCRv6 weights. It is the
    price of the answer being about this machine rather than about the registry.
    """
    for _name, ok, reason in engines.diagnose():
        assert reason
        if not ok:
            # The message must say what to do, not just that it failed.
            assert "requires" in reason or "unavailable" in reason
