"""Step 2's choice belongs to the machine — the only hardware-dependent decision.

``platform.py`` answers three questions and touches nothing else: is this Apple
hardware, does Vision load here, and what machine is this. Which engines the
cascade then assembles out of those answers is a different layer, and lives in
``integration/test_assembly.py``.
"""

from __future__ import annotations

import platform as stdlib_platform

from autosxtract import platform


def test_is_apple_reflects_the_system():
    assert platform.is_apple() == (stdlib_platform.system() == "Darwin")


def test_vision_only_exists_on_apple():
    """Off Apple the answer must be a definite no, not a maybe.

    On Apple hardware this asserts nothing — ``vision_available()`` there
    depends on pyobjc being whole, which is the runtime layer's business.
    """
    if not platform.is_apple():
        assert not platform.vision_available()


def test_describe_names_the_machine():
    assert stdlib_platform.machine() in platform.describe()
