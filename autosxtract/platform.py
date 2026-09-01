"""What kind of machine this is, and which OCR engine it can run well.

This is the library's only hardware-dependent decision, and it exists because
of a measurement: Apple's ``VNRecognizeTextRequest`` runs on-device on a small,
specialised model with hardware acceleration that has no x86 equivalent — 2.5
pages per second on a laptop, preserving 92% of the words and **100% of the
numeric anchors** at the median of 60 audited documents. Off Apple hardware the
best measured substitute is PP-OCRv6 served through ONNX.

Detection happens in two layers, and both matter:

1. **System** — ``platform.system() == "Darwin"``. Cheap, but not enough: a
   macOS box without ``pyobjc-framework-Vision`` installed cannot run Vision.
2. **Importability** — the ``Vision`` module actually loads. Only that proves
   the step exists.

Nothing here touches the network. The choice is local by construction: **there
is no external worker, SSH tunnel or remote endpoint anywhere in this
library** — that was exactly the pain point of the previous architecture, where
a worker going down silently degraded extraction.

(The module is named after the concept, shadowing the standard library's
``platform`` only inside this package. Python 3 absolute imports mean the
``import platform`` below still reaches the stdlib.)
"""

from __future__ import annotations

import functools
import platform


def is_apple() -> bool:
    """Is this an Apple machine (macOS)?

    System only — it does not say whether Vision is installed. To decide the
    step, use ``vision_available``.
    """
    return platform.system() == "Darwin"


@functools.cache
def vision_available() -> bool:
    """Does the Vision framework load in **this** process?

    Cached: the cost is importing two pyobjc bundles and the answer does not
    change during the process's life. This is the question that decides step 2.
    """
    if not is_apple():
        return False
    try:
        import Vision  # noqa: F401
    except Exception:
        # An incomplete pyobjc is unavailability, not an error.
        return False
    try:
        from Foundation import NSData
    except ImportError:
        try:
            from AppKit import NSData  # noqa: F401
        except ImportError:
            return False
    return True


@functools.cache
def describe() -> str:
    """One line about the machine, for logs and the CLI's ``diagnose``."""
    system = platform.system()
    arch = platform.machine()
    if is_apple():
        version = platform.mac_ver()[0] or "?"
        state = "available" if vision_available() else "missing"
        return f"macOS {version} ({arch}), Vision {state}"
    return f"{system} ({arch})"
