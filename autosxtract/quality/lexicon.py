"""The vocabulary a line is judged readable against.

The containment layers ask "is this line the corpus language?" by comparing
tokens to a lexicon. Its quality decides the quality of the classification, and
that is why it is **injectable**: the one built in here is a reasonable floor
for Brazilian legal Portuguese, not a truth.

Anyone with their own archive should build their own — it is measurably
better. The cheapest way is to count tokens from already-validated texts and
keep those appearing 3 or more times:

    from autosxtract import Config
    from autosxtract.quality.lexicon import Lexicon

    mine = Lexicon.from_texts(Path("validated").glob("*.txt"))
    Config(lexicon=mine)

One warning worth more than the list itself: **a lexicon that is too small
makes correct text look like junk.** The layers were calibrated with a lexicon
derived from a real archive, with thousands of types. With the built-in one the
thresholds still hold, but average coverage drops and more lines fall into
``suspect`` — which is the safe side of the error (the text passes, the page
merely loses confidence).

The built-in list itself is not written here: it is ``lexicon.builtin`` in the
pattern catalogue, next to everything else that describes the corpus rather than
the algorithm.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from autosxtract import patterns


def short_words() -> frozenset[str]:
    """Function words of two letters or fewer, which live apart on purpose.

    The tokeniser requires 3+ characters, but the re-segmentation of
    run-together words needs the particles in order to split
    ``ESTADODEMATOGROSSODOSUL`` correctly.
    """
    return patterns.default().words("lexicon.short_words")


def builtin_words() -> frozenset[str]:
    """The built-in floor, straight from the catalogue's ``lexicon.builtin``."""
    return patterns.default().words("lexicon.builtin")


@dataclass(frozen=True)
class Lexicon:
    """A set of known words, with the two lookups the layers perform."""

    words: frozenset[str]

    def __contains__(self, word: str) -> bool:
        return word.lower() in self.words

    def coverage(self, text: str) -> float:
        """Fraction of the line's tokens that the lexicon knows.

        ``1.0`` for a line with no alphabetic token — a case number and a date
        are not words, and punishing them for being absent from the lexicon
        would classify exactly what matters most to preserve as junk.
        """
        tokens = self.tokens(text)
        if not tokens:
            return 1.0
        return sum(t in self.words for t in tokens) / len(tokens)

    def tokens(self, text: str) -> list[str]:
        return [t.lower() for t in patterns.default().regex("lexicon.token").findall(text)]

    @classmethod
    def builtin(cls) -> Lexicon:
        """The floor: Portuguese function words plus legal vocabulary."""
        return cls(builtin_words() | short_words())

    @classmethod
    def from_texts(
        cls, files: Iterable[str | Path], *, minimum: int = 3, add_builtin: bool = True
    ) -> Lexicon:
        """Build from already-validated texts.

        ``minimum`` drops what appears rarely: an OCR error rarely repeats three
        times, and without that cut the lexicon learns the very errors it is
        supposed to detect.
        """
        from collections import Counter

        counts: Counter[str] = Counter()
        for file in files:
            try:
                counts.update(
                    t.lower()
                    for t in patterns.default()
                    .regex("lexicon.token")
                    .findall(Path(file).read_text(encoding="utf-8"))
                )
            except OSError:
                continue
        words = {w for w, n in counts.items() if n >= minimum}
        if add_builtin:
            words |= builtin_words() | short_words()
        return cls(frozenset(words))

    @classmethod
    def from_words(cls, words: Iterable[str], *, add_builtin: bool = True) -> Lexicon:
        """Build from a ready-made list."""
        collected = {w.lower() for w in words}
        if add_builtin:
            collected |= builtin_words() | short_words()
        return cls(frozenset(collected))
