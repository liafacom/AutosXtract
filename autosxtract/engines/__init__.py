"""OCR engines — what actually reads pixels and returns text.

Importing this package registers every engine shipped with the library. None of
them imports its heavy dependency at the top of the file: loading is lazy and
locked, so importing ``autosxtract`` in an environment without ``rapidocr`` or
``pyobjc`` costs nothing and does not break.

To add an engine, see ``autosxtract.engines.base.register`` for the registry
and ``autosxtract.interfaces.Engine`` for the contract it has to satisfy.
"""

# The imports below exist for the side effect of registering each engine.
# ``noqa: F401`` because the name is unused — the registration is the point.
from autosxtract.engines import onnx as _onnx  # noqa: F401
from autosxtract.engines import paddle as _paddle  # noqa: F401
from autosxtract.engines import tesseract as _tesseract  # noqa: F401
from autosxtract.engines import vision as _vision  # noqa: F401
from autosxtract.engines.base import (
    Engine,
    EngineInfo,
    OCREngine,
    available,
    compatible,
    diagnose,
    get,
    register,
    registered,
)

__all__ = [
    "Engine",
    "EngineInfo",
    "OCREngine",
    "available",
    "compatible",
    "diagnose",
    "get",
    "register",
    "registered",
]
