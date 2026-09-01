"""The pattern catalogue — every domain regex, outside the Python.

The library reads Brazilian legal PDFs, and until this package existed that
fact was spread across ten modules as ``re.compile`` calls: the conformity
stamp, the enclitic pronouns, the forensic abbreviations, the identity-card
markers, the legal lexicon. Each one was correct and each one was measured, and
between them they made a claim the code could not honour — that adapting the
library to another corpus was a matter of swapping the patterns. It was not: it
was a matter of editing Python in ten files and hoping the test suite noticed.

So the patterns are DATA now, in TOML, versioned with the package and layered:

    base.toml     nothing that describes a language — control bytes,
                  glyph-index runs, digit runs, markdown structure
    pt_br.toml    the corpus this library was measured on

and a user pack overrides whatever it names, entry by entry. It never has to
redefine the rest, because the bundled packs stay underneath it: a pack that
only replaces ``stamp.conformity`` is a legitimate, complete pack.

Resolution order, most specific first::

    Config.patterns          a PatternSet, or a path to a file or directory
    AUTOSXTRACT_PATTERNS     the same, from the environment
    the locale pack          chosen from Config.language
    base                     always underneath

**TOML, and why it is not JSON.** ``tomllib`` is in the standard library from
3.11, which is the floor this package already requires, so the catalogue costs
no new dependency. Its literal strings (``'''...'''``) carry a regex verbatim —
no escaping layer between what is written and what ``re`` compiles, which is
exactly the defect a JSON catalogue would introduce, since every backslash in
every pattern would have to be doubled by hand. And it takes comments, which
matters here more than usual: each entry keeps the measurement that fixed it in
a ``why`` field. That text is not decoration. It travelled here from the code
with the pattern, and an entry whose ``why`` no longer holds is an entry to
delete rather than to adjust in silence.

Compilation happens once per name and is cached on the set, so a pattern costs
what it cost when it was a module-level constant. The whole catalogue is
compiled once at resolution time as well — about sixty patterns, under a
millisecond — because the alternative is a malformed user pack surfacing as a
crash in the middle of a batch instead of at load.
"""

from __future__ import annotations

import functools
import os
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from importlib import resources
from pathlib import Path
from typing import Any

from autosxtract.exceptions import InvalidConfiguration

#: Where a user pack is named when nobody passes one explicitly. A path to a
#: file, or to a directory whose ``*.toml`` are merged in sorted order.
ENVIRONMENT_VARIABLE = "AUTOSXTRACT_PATTERNS"

#: The language-independent pack, always the floor of a resolution.
BASE_PACK = "base"
#: The pack that loads when ``Config.language`` names none that is bundled.
DEFAULT_PACK = "pt_br"

_FLAGS = {
    "ASCII": re.ASCII,
    "DOTALL": re.DOTALL,
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "UNICODE": re.UNICODE,
    "VERBOSE": re.VERBOSE,
}

#: The six shapes an entry can take. Exactly one of these keys decides the
#: kind, so a typo in a user pack is caught at load rather than at first use.
_KINDS = ("pattern", "patterns", "strings", "words", "map", "text")


@dataclass(frozen=True)
class Entry:
    """One catalogue entry: its value, its shape and the reason it exists.

    ``why`` is carried into the object rather than left as a TOML comment on
    purpose — it is what a reader needs in order to decide whether their corpus
    invalidates the entry, and ``patterns.why(name)`` puts it where the
    question is asked.
    """

    name: str
    kind: str
    origin: str
    why: str = ""
    pattern: str = ""
    flags: int = 0
    replacement: str | None = None
    items: tuple[str, ...] = ()
    vocabulary: frozenset[str] = frozenset()
    table: Mapping[str, str] = field(default_factory=dict)
    text: str = ""


@dataclass(frozen=True)
class PatternSet:
    """A resolved catalogue: named values, compiled on demand and kept.

    Immutable as far as its content goes — the two dictionaries below are
    caches, not state. Sharing one instance across a whole batch is the
    intended use, and is what keeps compilation to once per pattern per
    process.
    """

    entries: Mapping[str, Entry]
    origins: tuple[str, ...] = ()
    _compiled: dict[str, re.Pattern[str]] = field(default_factory=dict, repr=False, compare=False)
    _tables: dict[str, dict[int, str]] = field(default_factory=dict, repr=False, compare=False)

    # ── lookups ──────────────────────────────────────────────────────────

    def regex(self, name: str) -> re.Pattern[str]:
        """The compiled pattern under ``name``, compiled at most once."""
        cached = self._compiled.get(name)
        if cached is not None:
            return cached
        entry = self._entry(name, "pattern")
        compiled = _compile(entry.pattern, entry.flags, entry.name, entry.origin)
        self._compiled[name] = compiled
        return compiled

    def sub(self, name: str, text: str) -> str:
        """Apply the entry's own replacement — the fix travels with the pattern.

        A substitution is two halves of one decision, and splitting them across
        a data file and a call site is how a pack ends up matching the OCR's
        corrupted currency symbol and writing back the wrong one.
        """
        entry = self._entry(name, "pattern")
        if entry.replacement is None:
            raise InvalidConfiguration(
                f"pattern entry {name!r} has no replacement, so it cannot substitute "
                f"(defined in {entry.origin})"
            )
        return self.regex(name).sub(entry.replacement, text)

    def patterns(self, name: str) -> tuple[str, ...]:
        """A list of regexes the code needs one by one, still uncompiled.

        Kept as strings because the callers do different things with them: the
        stamp joins them into one alternation, the domain coverage reports
        WHICH of them matched.
        """
        return self._entry(name, "patterns").items

    def strings(self, name: str) -> tuple[str, ...]:
        """Literal strings, never compiled — the identity-card markers."""
        return self._entry(name, "strings").items

    def words(self, name: str) -> frozenset[str]:
        """A whitespace-separated block read as a set of words."""
        return self._entry(name, "words").vocabulary

    def mapping(self, name: str) -> Mapping[str, str]:
        """A character-for-character substitution table."""
        return self._entry(name, "map").table

    def translation(self, name: str) -> dict[int, str]:
        """The same table in ``str.translate`` form, built once."""
        cached = self._tables.get(name)
        if cached is None:
            cached = str.maketrans(dict(self.mapping(name)))
            self._tables[name] = cached
        return cached

    def text(self, name: str) -> str:
        """A plain string: a label, a prompt."""
        return self._entry(name, "text").text

    def why(self, name: str) -> str:
        """The measurement that fixed this entry, as its pack states it."""
        entry = self.entries.get(name)
        if entry is None:
            raise InvalidConfiguration(self._missing(name))
        return entry.why

    def names(self) -> tuple[str, ...]:
        """Every name the resolved catalogue defines, sorted."""
        return tuple(sorted(self.entries))

    def __contains__(self, name: object) -> bool:
        return name in self.entries

    # ── construction ─────────────────────────────────────────────────────

    def overlaid(self, other: PatternSet) -> PatternSet:
        """``other`` on top of this one, entry by entry.

        Entry-level and not file-level: a pack that names one entry replaces
        that entry and inherits everything else. File-level merging would force
        whoever wants a different stamp to copy the other fifty patterns, and a
        copy is a fork that stops receiving fixes.
        """
        merged = dict(self.entries)
        merged.update(other.entries)
        return PatternSet(merged, self.origins + other.origins)

    def validate(self) -> PatternSet:
        """Compile everything now, so a bad pack fails at load.

        Returns itself, so it can close a resolution expression. The cost is
        the compilation the process was going to pay anyway; what changes is
        WHEN a broken pattern is reported — at the top of the run, naming the
        entry and the file, instead of on the document that happened to reach
        it first.
        """
        for name, entry in self.entries.items():
            if entry.kind == "pattern":
                self.regex(name)
            elif entry.kind == "patterns":
                for item in entry.items:
                    _compile(item, 0, entry.name, entry.origin)
        return self

    # ── internals ────────────────────────────────────────────────────────

    def _entry(self, name: str, kind: str) -> Entry:
        entry = self.entries.get(name)
        if entry is None:
            raise InvalidConfiguration(self._missing(name))
        if entry.kind != kind:
            raise InvalidConfiguration(
                f"pattern entry {name!r} is a {entry.kind!r} entry but was asked for as "
                f"{kind!r} (defined in {entry.origin})"
            )
        return entry

    def _missing(self, name: str) -> str:
        origins = ", ".join(self.origins) or "nothing"
        return (
            f"the pattern catalogue has no entry {name!r}. The code needs it; "
            f"the packs loaded ({origins}) do not define it — a pack overrides entries, "
            f"it never removes them."
        )


# ── parsing ──────────────────────────────────────────────────────────────


def _compile(pattern: str, flags: int, name: str, origin: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, flags)
    except re.error as exc:
        raise InvalidConfiguration(
            f"pattern entry {name!r} in {origin} is not a valid regular expression: {exc}"
        ) from exc


def _flags(spec: Any, name: str, origin: str) -> int:
    if spec is None:
        return 0
    if not isinstance(spec, list):
        raise InvalidConfiguration(f"pattern entry {name!r} in {origin}: 'flags' must be a list")
    value = 0
    for flag in spec:
        try:
            value |= _FLAGS[str(flag).upper()]
        except KeyError:
            raise InvalidConfiguration(
                f"pattern entry {name!r} in {origin}: unknown flag {flag!r}. "
                f"Known flags: {', '.join(sorted(_FLAGS))}"
            ) from None
    return value


def _entry_from(name: str, spec: Mapping[str, Any], origin: str) -> Entry:
    present = [key for key in _KINDS if key in spec]
    if len(present) != 1:
        raise InvalidConfiguration(
            f"pattern entry {name!r} in {origin} must carry exactly one of "
            f"{', '.join(_KINDS)} — it carries {len(present)}"
        )
    kind = present[0]
    entry = Entry(name=name, kind=kind, origin=origin, why=str(spec.get("why", "")).strip())

    if kind == "pattern":
        replacement = spec.get("replacement")
        return replace(
            entry,
            pattern=str(spec["pattern"]),
            flags=_flags(spec.get("flags"), name, origin),
            replacement=None if replacement is None else str(replacement),
        )
    if kind in ("patterns", "strings"):
        value = spec[kind]
        if not isinstance(value, list):
            raise InvalidConfiguration(
                f"pattern entry {name!r} in {origin}: {kind!r} must be a list of strings"
            )
        return replace(entry, items=tuple(str(item) for item in value))
    if kind == "words":
        return replace(entry, vocabulary=frozenset(str(spec["words"]).split()))
    if kind == "map":
        table = spec["map"]
        if not isinstance(table, dict):
            raise InvalidConfiguration(
                f"pattern entry {name!r} in {origin}: 'map' must be a table of "
                f"character = replacement"
            )
        return replace(entry, table={str(k): str(v) for k, v in table.items()})
    return replace(entry, text=str(spec["text"]))


def _parse(document: str, origin: str) -> PatternSet:
    try:
        raw = tomllib.loads(document)
    except tomllib.TOMLDecodeError as exc:
        raise InvalidConfiguration(f"{origin} is not valid TOML: {exc}") from exc

    entries: dict[str, Entry] = {}
    for section, body in raw.items():
        if not isinstance(body, dict):
            raise InvalidConfiguration(
                f"{origin}: '{section}' must be a table of entries, as in [{section}.some_name]"
            )
        for name, spec in body.items():
            if not isinstance(spec, dict):
                raise InvalidConfiguration(
                    f"{origin}: '{section}.{name}' must be a table, as in [{section}.{name}]"
                )
            full = f"{section}.{name}"
            entries[full] = _entry_from(full, spec, origin)
    return PatternSet(entries, (origin,))


# ── loading ──────────────────────────────────────────────────────────────


def _data_directory() -> resources.abc.Traversable:
    # ``importlib.resources`` and not ``__file__`` arithmetic: the packs have to
    # be found the same way from a wheel, a zip and a source checkout, and path
    # maths silently finds nothing in the first two.
    return resources.files(__name__).joinpath("data")


@functools.cache
def bundled(pack: str = DEFAULT_PACK) -> PatternSet:
    """One pack shipped inside the package, parsed once."""
    file = _data_directory().joinpath(f"{pack}.toml")
    if not file.is_file():
        raise InvalidConfiguration(
            f"there is no bundled pattern pack named {pack!r}; "
            f"the package ships {', '.join(available_packs())}"
        )
    return _parse(file.read_text(encoding="utf-8"), f"bundled:{pack}")


@functools.cache
def available_packs() -> tuple[str, ...]:
    """The packs the installed package carries, sorted.

    Cached because ``default()`` runs it on every call and the quality layer
    calls ``default()`` per line: without the cache the containment layers list
    a directory once per line of every page.
    """
    return tuple(
        sorted(
            item.name[: -len(".toml")]
            for item in _data_directory().iterdir()
            if item.name.endswith(".toml")
        )
    )


@functools.cache
def load(path: str | Path) -> PatternSet:
    """A user pack from a file, or every ``*.toml`` of a directory.

    A directory is merged in sorted order, so a pack can be split by concern
    the way the bundled one is. Cached by path: the file is read once per
    process, which is what makes a pattern set cheap to ask for repeatedly.
    """
    target = Path(path).expanduser()
    if target.is_dir():
        files = sorted(target.glob("*.toml"))
        if not files:
            raise InvalidConfiguration(f"the pattern directory {target} holds no .toml file")
    elif target.is_file():
        files = [target]
    else:
        raise InvalidConfiguration(f"the pattern pack {target} does not exist")

    return _overlay(_parse(f.read_text(encoding="utf-8"), str(f)) for f in files)


def _overlay(sets: Iterable[PatternSet]) -> PatternSet:
    result: PatternSet | None = None
    for pattern_set in sets:
        result = pattern_set if result is None else result.overlaid(pattern_set)
    if result is None:  # pragma: no cover — the callers always pass at least one
        return PatternSet({}, ())
    return result


def pack_for_language(language: str | None) -> str:
    """Which bundled pack a language tag selects.

    ``pt-BR`` finds ``pt_br``, ``pt`` finds ``pt`` if it exists. A language
    with NO bundled pack falls back to the default one, and that is deliberate
    rather than lenient: before this catalogue existed the patterns were
    Portuguese whatever ``Config.language`` said, and raising here would break
    a configuration that works today. Shipping a pack for the new language, or
    pointing ``AUTOSXTRACT_PATTERNS`` at one, is how that fallback is left
    behind.
    """
    if not language:
        return DEFAULT_PACK
    packs = available_packs()
    candidate = language.replace("-", "_").lower()
    if candidate in packs:
        return candidate
    root = candidate.split("_")[0]
    if root in packs:
        return root
    return DEFAULT_PACK


@functools.cache
def _resolved(pack: str, environment: str | None, source: str | None) -> PatternSet:
    layers = [bundled(BASE_PACK)]
    if pack != BASE_PACK:
        layers.append(bundled(pack))
    if environment:
        layers.append(load(environment))
    if source:
        layers.append(load(source))
    return _overlay(layers).validate()


def resolve(source: Any = None, *, language: str | None = None) -> PatternSet:
    """The catalogue this configuration asks for, resolved and validated.

    ``source`` is a ``PatternSet`` — returned untouched, whoever built it has
    already decided — or a path to a file or directory that overrides
    everything else.
    """
    if isinstance(source, PatternSet):
        return source
    environment = os.environ.get(ENVIRONMENT_VARIABLE) or None
    return _resolved(
        pack_for_language(language),
        environment,
        None if source is None else str(source),
    )


_installed: PatternSet | None = None


def default() -> PatternSet:
    """The process-wide catalogue the quality layer reads.

    The quality modules measure text and take no configuration — that is the
    property that lets the same criterion judge every step — so they cannot be
    handed a pattern set per call. They read this one, which resolves from the
    environment and the default language on first use, and which ``use()``
    replaces for a process that wants something else.
    """
    return _installed if _installed is not None else resolve()


def use(pattern_set: PatternSet | None) -> None:
    """Install a catalogue as the process default; ``None`` restores resolution."""
    global _installed
    _installed = pattern_set


def reset() -> None:
    """Forget every cached pack and any installed default.

    For tests and for a process that edited a pack on disk and wants it read
    again — nothing else invalidates the caches, because a catalogue that
    reloaded itself mid-batch would classify the first half of the documents by
    one rule and the second half by another.
    """
    use(None)
    _resolved.cache_clear()
    load.cache_clear()
    bundled.cache_clear()
    available_packs.cache_clear()


__all__ = [
    "BASE_PACK",
    "DEFAULT_PACK",
    "ENVIRONMENT_VARIABLE",
    "Entry",
    "PatternSet",
    "available_packs",
    "bundled",
    "default",
    "load",
    "pack_for_language",
    "reset",
    "resolve",
    "use",
]
