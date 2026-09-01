"""Cascade steps — each one an attempt at extracting the document.

Four cover the whole pipeline shipped with the library, in the order they
usually appear:

``UnwrapStep``     is the file really a PDF? (RTF, BRy envelope, PKCS#7)
``NativeStep``     reads the PDF's text layer; not OCR, reading
``OCRStep``        wraps **any** OCR engine and applies the gates
``ScreeningStep``  drops an already-transcribed identity document

Remote ones live in ``autosxtract.steps.remote`` and are **never** in the
default cascade: ``DoclingStep`` and ``VLMStep`` require ``url`` in the
constructor. ``autosxtract.steps.docling_local`` holds the network-free variant.

A new step needs only ``name`` and ``run(ctx) -> StepResult``. Declaring
``expensive = True`` makes the cascade run the five vetoes before it and submit
the result to the replacement gate afterwards.

The two names in that sentence are contracts, not classes: ``Step`` is what the
cascade accepts and ``DocumentContext`` is what it hands over. Both are defined
in ``autosxtract.interfaces`` and re-exported here, so a step can be written —
and tested — without ``Context`` or a PDF existing anywhere near it.
"""

from autosxtract.steps.base import Context, DocumentContext, Step, StepResult
from autosxtract.steps.native import NativeStep, read_native_text
from autosxtract.steps.ocr import OCRStep
from autosxtract.steps.screening import ScreeningStep
from autosxtract.steps.unwrap import UnwrapStep

__all__ = [
    "Context",
    "DocumentContext",
    "NativeStep",
    "OCRStep",
    "ScreeningStep",
    "Step",
    "StepResult",
    "UnwrapStep",
    "read_native_text",
]
