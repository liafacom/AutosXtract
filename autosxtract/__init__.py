"""AutosXtract — cascading text extraction from PDFs.

A deliberately small public surface. Internal modules may evolve; these names
may not.

The idea in one sentence: every document descends steps from the cheapest to the
most expensive and **stops at the first one that produces acceptable text**,
with a single acceptance criterion and every step's provenance attached to the
result.

    from autosxtract import Cascade

    cascade = Cascade()
    r = cascade.extract_file("document.pdf")
    print(r.text)
    print(r.provenance)   # native: native(quality 0.42 below 0.75) -> vision(ok)

The OCR steps are chosen by the machine, and they are a CHAIN rather than a
single pick: **Apple Vision** first where it exists, then **PP-OCRv6 tiny**,
which is the only OCR step off Apple hardware.

    macOS            native -> vision -> paddle
    Linux/Windows    native ->           paddle

The library **does no networking** while extracting — no
external worker, no SSH tunnel, no endpoint. The only connection in the whole
package is the one-off download of the PP-OCRv6 weights, in ``engines.models``,
which is unnecessary once they are on disk.

Everything extensible is a contract, and the contracts live in one file,
``autosxtract.interfaces``: ``Engine`` and ``Step`` are the two extension
points, and ``Renderer``, ``DocumentContext``, ``PageSource``, ``Tokenizer``,
``StampStripper``, ``LexiconLike``, ``Scorer`` and ``Gate`` are the
collaborations underneath them. They are structural ``Protocol`` objects, so an
implementation inherits nothing — it merely has the methods — and they are
re-exported here because a name you are expected to implement should be
importable from the package you are extending.
"""

from autosxtract._version import __version__
from autosxtract.cascade import Cascade, engine_order, extract
from autosxtract.config import Config
from autosxtract.engines import OCREngine, available, diagnose, get, register
from autosxtract.exceptions import (
    AutosXtractError,
    EngineUnavailable,
    InvalidConfiguration,
    UnknownEngine,
    UnreadablePDF,
)
from autosxtract.formats import FileFormat, unwrap
from autosxtract.interfaces import (
    DocumentContext,
    Engine,
    Gate,
    GateVerdict,
    LexiconLike,
    PageSource,
    Renderer,
    Scorer,
    StampStripper,
    Step,
    Tokenizer,
)
from autosxtract.patterns import PatternSet
from autosxtract.platform import is_apple, vision_available
from autosxtract.quality.lexicon import Lexicon
from autosxtract.quality.lines import Containment, contain
from autosxtract.quality.routing import Route, route
from autosxtract.steps import (
    Context,
    NativeStep,
    OCRStep,
    ScreeningStep,
    StepResult,
    UnwrapStep,
)
from autosxtract.types import Attempt, Candidate, Line, Page, Result, Transcription

__all__ = [
    "Attempt",
    "AutosXtractError",
    "Candidate",
    "Cascade",
    "Config",
    "Containment",
    "Context",
    "DocumentContext",
    "Engine",
    "EngineUnavailable",
    "FileFormat",
    "Gate",
    "GateVerdict",
    "InvalidConfiguration",
    "Lexicon",
    "LexiconLike",
    "Line",
    "NativeStep",
    "OCREngine",
    "OCRStep",
    "Page",
    "PageSource",
    "PatternSet",
    "Renderer",
    "Result",
    "Route",
    "Scorer",
    "ScreeningStep",
    "StampStripper",
    "Step",
    "StepResult",
    "Tokenizer",
    "Transcription",
    "UnknownEngine",
    "UnreadablePDF",
    "UnwrapStep",
    "__version__",
    "available",
    "contain",
    "diagnose",
    "engine_order",
    "extract",
    "get",
    "is_apple",
    "register",
    "route",
    "unwrap",
    "vision_available",
]
