"""Library exceptions.

They all descend from ``AutosXtractError`` so integrators can catch the whole
family without enumerating cases. The project rule is that **a missing engine
is never an exception**: an absent engine leaves its step inert and the cascade
moves on — the absence of a tool is not evidence about the document.
"""

from __future__ import annotations


class AutosXtractError(Exception):
    """Root of every error raised by this library."""


class UnreadablePDF(AutosXtractError):
    """The bytes do not open as a PDF, not even after every attempt."""


class EngineUnavailable(AutosXtractError):
    """An explicitly named engine is not installed or fails to load.

    Only raised when someone **names** the engine. The automatically assembled
    cascade never sees it: it skips the step and records why.
    """


class UnknownEngine(AutosXtractError):
    """An engine name that is not in the registry."""


class InvalidConfiguration(AutosXtractError):
    """A combination of parameters that does not describe a runnable cascade."""
