"""Numeric anchors — what must not vanish when switching steps.

A more expensive step sometimes recovers a page the previous one could not
read, and sometimes rewrites a page that was already read — corrupting digits
along the way. Measured on a real archive, always where it hurts most: a VIN
``9XXYZ32E41A099887`` became ``9XXYZ3ZE41A099887``, protocol ``882167`` became
``882187``, case number ``001.06.012345-6`` became ``001.00.012345-6``.

No text-quality metric detects that: both forms are equally plausible as text.
What detects it is comparing the **sets** of verifiable tokens before and
after — set comparison, not positional, because the new step legitimately
reorders the layout.

Pure module: no I/O and no configuration. What a verifiable token LOOKS like is
data — the ``anchors.*`` entries of the pattern catalogue — because the shape of
an identifier is the one thing that changes with the corpus.
"""

from __future__ import annotations

from autosxtract import patterns

# Below this it is not an identifier: it is a currency amount, a loose date or
# an item number.
_MIN_PUNCTUATED_DIGITS = 8


def anchors(text: str | None) -> set[str]:
    """The verifiable tokens of a text, normalised for comparison.

    A punctuated identifier becomes its digits alone, so ``001.06.012345-6``
    and ``001-06-012345/6`` are the same anchor — swapping ``.`` for ``-`` or
    ``/`` between steps is not a loss, only a digit difference is. A
    ``dd/mm/yyyy`` date falls through the same path (three groups, eight
    digits) and needs no pattern of its own.

    The separator must be one of the three: a step returning ``001 06 012345
    6`` with spaces breaks the grouping and the long anchor disappears. That is
    a known, deliberate limitation — accepting spaces would turn two
    neighbouring numbers in a table into an identifier that does not exist.
    """
    if not text:
        return set()
    catalogue = patterns.default()
    found: set[str] = set()
    for m in catalogue.regex("anchors.alphanumeric").finditer(text.upper()):
        found.add(m.group(0))
    for m in catalogue.regex("anchors.punctuated").finditer(text):
        digits = catalogue.regex("anchors.non_digit").sub("", m.group(0))
        if len(digits) >= _MIN_PUNCTUATED_DIGITS:
            found.add(digits)
    for m in catalogue.regex("anchors.digit_run").finditer(text):
        found.add(m.group(0))
    return found


def lost(previous: str | None, new: str | None) -> set[str]:
    """Anchors that existed in the previous text and vanished in the new one.

    An anchor contained in another does not count as lost: the new step may
    write ``0001234-56.2020.8.12.0001`` where the previous one had only
    ``0001234``, and that is a gain of information.

    Containment is tested anchor by anchor, **never** against the concatenation
    of them all: joining the new ones into a single string creates matches
    straddling the boundary between two of them and absolves a digit that did
    disappear. Measured: with ``12345`` and ``67890`` present, the
    concatenation contains ``234567`` and the gate let the corruption through —
    on a page full of numbers, which is the whole use case.
    """
    before = anchors(previous)
    if not before:
        return set()
    after = anchors(new)
    if not after:
        return before
    return {a for a in before if not any(a in d for d in after)}
