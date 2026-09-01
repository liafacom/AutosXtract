"""The stamp, and why it has to go before any measurement.

Every digital case-file system prints a conformity banner in the margin — "this
document is a copy of the original... verification code...". It sits in a font
with an intact encoding, so it **survives** even when the body of the page
produces nothing. That is 250 to 600 characters that sail past any size
threshold, and it was the dominant pattern in an audit of 1,339 documents: 227
cases where the extraction looked successful and all there was, was the stamp.

Measuring an extraction without removing the stamp is measuring the stamp.

**Adaptation point.** The patterns are ``stamp.conformity`` in the pattern
catalogue, and come from Brazilian court systems. Another domain ships its own
pack, or swaps the list through ``Config.stamps``, or instantiates ``Stamp``
directly — the rest of the library does not change, because everyone measures
through here.
"""

from __future__ import annotations

import functools
import re

# The catalogue is imported under another name because this module's public API
# already owns ``patterns``: ``Stamp(patterns=...)`` is the documented way to
# override the list, and it predates the catalogue.
from autosxtract import patterns as _catalogue
from autosxtract.patterns import default as catalogue

#: The bundled Brazilian court list, read from the pack that DEFINES it rather
#: than from the resolved catalogue: the name promises these patterns, not
#: whatever a user pack put in their place. ``conformity_patterns()`` is the one
#: that honours an override.
BRAZILIAN_COURT_PATTERNS: tuple[str, ...] = _catalogue.bundled(_catalogue.DEFAULT_PACK).patterns(
    "stamp.conformity"
)


def conformity_patterns() -> tuple[str, ...]:
    """The stamp patterns in force — a user pack's, or the bundled ones."""
    return catalogue().patterns("stamp.conformity")


class Stamp:
    """Strips the conformity banner and tokenises what is left.

    An immutable, cheap-to-share instance: the regex is compiled once.
    """

    __slots__ = ("_re", "patterns")

    def __init__(self, patterns: tuple[str, ...] | None = None) -> None:
        self.patterns = tuple(patterns) if patterns else conformity_patterns()
        self._re = re.compile("|".join(self.patterns), re.IGNORECASE | re.DOTALL)

    def strip(self, text: str) -> str:
        """Remove the stamp, leaving only the body of the page."""
        if not text:
            return ""
        return catalogue().regex("stamp.whitespace").sub(" ", self._re.sub(" ", text)).strip()

    def words(self, text: str) -> list[str]:
        """Alphabetic words outside the stamp, lowercased."""
        return [w.lower() for w in catalogue().regex("stamp.word").findall(self.strip(text))]

    def count(self, text: str) -> int:
        """How many useful words the text has outside the stamp."""
        return len(self.words(text))

    def vocabulary(self, text: str) -> set[str]:
        """The set of useful words — input to the engine comparison."""
        return set(self.words(text))


def default(patterns: tuple[str, ...] | None = None) -> Stamp:
    """A shared instance for a given set of patterns.

    ``None`` means "whatever the catalogue says", and it is resolved HERE rather
    than inside the cache: with the cache keyed on ``None`` a process that
    installed its own pack kept measuring against the pack it had at the first
    call.
    """
    return _shared(tuple(patterns) if patterns else conformity_patterns())


@functools.cache
def _shared(patterns: tuple[str, ...]) -> Stamp:
    """Cached because compiling the regex is the only cost, and the cascade
    calls this once per step per document."""
    return Stamp(patterns)


def strip_stamp(text: str, patterns: tuple[str, ...] | None = None) -> str:
    """Module shortcut — equivalent to ``default(patterns).strip(text)``."""
    return default(patterns).strip(text)


def useful_words(text: str, patterns: tuple[str, ...] | None = None) -> int:
    """Module shortcut — equivalent to ``default(patterns).count(text)``."""
    return default(patterns).count(text)
