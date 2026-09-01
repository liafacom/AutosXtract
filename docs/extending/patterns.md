# Extending: a new pattern pack

The library reads Brazilian legal PDFs. Until `autosxtract/patterns/` existed,
that fact was spread across ten modules as `re.compile` calls — the conformity
stamp, the enclitic pronouns, the forensic abbreviations, the identity-card
markers, the legal lexicon. Each one was correct and each one was measured, and
between them they made a claim the code could not honour: **that adapting the
library to another corpus was a matter of swapping the patterns.** It was not. It
was a matter of editing Python in ten files and hoping the test suite noticed.

So the patterns are **data** now: 66 entries in TOML, versioned with the package,
layered, and overridable entry by entry.

```
autosxtract/patterns/__init__.py       the loader, the overlay, the resolution
autosxtract/patterns/data/base.toml    35 entries — nothing that describes a language
autosxtract/patterns/data/pt_br.toml   31 entries — the corpus this library was measured on
```

This is the adaptation seam named in CLAUDE.md §12, and it is now a real one
rather than a promise. See [ADR 0008](../adr/0008-patterns-are-data.md).

## Resolution order

Most specific first. **Later layers win, entry by entry**; everything below stays
in force.

| # | source | how you set it |
|---|---|---|
| 1 | `Config.patterns` | a `PatternSet`, or a path to a `.toml` file or a directory of them |
| 2 | `AUTOSXTRACT_PATTERNS` | the same, from the environment |
| 3 | the **locale pack** | chosen from `Config.language` (`pt-BR` → `pt_br`) |
| 4 | `base` | always underneath |

```python
config.pattern_set()          # the resolved catalogue for this configuration
config.stamp_patterns()       # `stamps` if given, otherwise the catalogue's
```

`Config.language` selects a bundled pack by tag: `pt-BR` finds `pt_br`, `pt`
finds `pt` if it exists. **A language with no bundled pack falls back to the
default one**, and that is deliberate rather than lenient — before this catalogue
existed the patterns were Portuguese whatever `Config.language` said, and raising
here would break a configuration that works today. Shipping a pack for the new
language, or pointing `AUTOSXTRACT_PATTERNS` at one, is how that fallback is left
behind.

!!! warning "A `PatternSet` passed directly bypasses the layering"

    `resolve()` returns a `PatternSet` **untouched** — whoever built it has
    already decided, and the bundled packs are *not* placed underneath it. Pass a
    **path** if you want the layering; pass an object only when you assembled it
    yourself, for instance with `patterns.resolve(...).overlaid(...)`.

## Entry-by-entry merging

This is the property that makes a pack maintainable. A pack that names one entry
replaces **that entry** and inherits everything else:

```python
from autosxtract import patterns

mine = patterns.load("my_pack.toml")
mine.names()                      # ('stamp.conformity',)  — one entry

resolved = patterns.resolve("my_pack.toml", language="pt-BR")
resolved.origins                  # ('bundled:base', 'bundled:pt_br', 'my_pack.toml')
len(resolved.entries)             # 66 — mine on top of the other 65
```

File-level merging would force whoever wants a different stamp to copy the other
sixty-five patterns, **and a copy is a fork that stops receiving fixes.** A pack
that redefines one entry is a legitimate, complete pack.

The corollary: **a pack overrides entries, it never removes them.** Asking for a
name nothing defines is an error that says so, naming the packs that were loaded:

```
InvalidConfiguration: the pattern catalogue has no entry 'stamp.nonexistent'.
The code needs it; the packs loaded (bundled:base, bundled:pt_br) do not
define it — a pack overrides entries, it never removes them.
```

## The TOML entry shapes

An entry is a table named `[section.name]`. **Exactly one** of six keys decides
its kind, so a typo in a pack is caught at load rather than at first use.

### `pattern` — one regex

```toml
[metrics.glyph_index]
why = '''
A font with no ToUnicode table makes the extractor return the glyph index
instead of the character (g40g86g87g72). Measured: 1,171 characters of junk
scoring 0.85.
'''
pattern = '(?:g\d{1,4}){4,}'
flags = ["UNICODE"]        # optional: ASCII, DOTALL, IGNORECASE, MULTILINE, UNICODE, VERBOSE
```

Read with `set.regex("metrics.glyph_index")`, compiled at most once per name.

An entry may carry a literal `replacement`, and then it can substitute on its
own:

```toml
[prose.currency_glued]
why = 'R$30.068,67 -> R$ 30.068,67. Measured: 6 of 15 amounts arrived glued.'
pattern = 'R\$(?=\d)'
replacement = 'R$ '
```

```python
patterns.resolve().sub("prose.currency_glued", "R$30.068,67")   # 'R$ 30.068,67'
```

**The fix travels with the pattern on purpose.** A substitution is two halves of
one decision, and splitting them across a data file and a call site is how a pack
ends up matching the OCR's corrupted currency symbol and writing back the wrong
one.

### `patterns` — a list of regexes, kept separate

```toml
[stamp.conformity]
why = 'The conformity banner. 250 to 600 characters that sail past any size threshold.'
patterns = [
    '(?im)^\s*CERTIFIED COPY.*$',
    '(?im)^\s*Verification code[: ].*$',
]
```

Read with `set.patterns(name)`, as **strings**, still uncompiled — because the
callers do different things with them: the stamp joins them into one alternation,
the domain coverage reports *which* of them matched. They are still validated at
load.

### `strings` — literal strings, never compiled

```toml
[screening.identity_marks]
why = 'Markers printed on an identity card. Literals: a regex here would be a bug.'
strings = ["REPUBLICA FEDERATIVA", "VALIDA EM TODO O TERRITORIO"]
```

### `words` — a whitespace-separated block read as a set

```toml
[metrics.stopwords]
why = 'Function words. Their absence is what says the text is not this language at all.'
words = '''
de a o que e do da em um para
'''
```

Read with `set.words(name)` → a `frozenset`.

### `map` — a character-for-character table

```toml
[metrics.character_fixes]
why = '''
The non-breaking space reads as a character and not a separator, so a whole page
of them counts as one enormous word; the soft hyphen is invisible and splits
words for every consumer downstream. Both are extractor artefacts, never content.
'''

[metrics.character_fixes.map]
"\u00A0" = " "
"\u00AD" = ""
```

The table is a **sub-table** (`[section.name.map]`), and the keys are written
as `\uXXXX` escapes on purpose: a non-breaking space and a soft hyphen are
invisible in a diff, and a reviewer cannot approve what they cannot see.

Read with `set.mapping(name)`, or with `set.translation(name)` for a
`str.translate` table built once.

### `text` — a plain string

```toml
[response.prompt]
why = '''
The transcription prompt. It is domain data, not code: it is written in the
corpus language, and the delimiters it asks for are what `response.delimited`
reads back.
'''
text = '''Transcreva FIELMENTE todo o texto visivel em cada pagina.
...'''
```

A label, a prompt, a delimiter — read with `set.text(name)`. The shipped
`response.prompt` is the real one, in Portuguese, and that is the point: a prompt
is corpus data and has no business being a string constant in Python.

### `why` is not a comment

Every entry carries `why`, and it is parsed into the `Entry` object rather than
left as a TOML comment, because it is what a reader needs in order to decide
whether *their* corpus invalidates the entry:

```python
patterns.resolve().why("stamp.conformity")
```

**That text travelled here from the code along with the pattern. An entry whose
`why` no longer holds is an entry to delete, not to adjust in silence.** A review
will ask for it.

## A complete, runnable example

Save this as `my_pack.toml`:

```toml
# A pattern pack that redefines one entry. Everything else keeps coming from
# the bundled packs underneath — this file does not have to restate it.

[stamp.conformity]
why = '''
Our archive's banner, measured on 1,200 exports: 3 templates, all of them
opening with "CERTIFIED COPY". The bundled Brazilian court patterns never
matched, so every extraction was measured WITH the banner in it.
'''
patterns = [
    '(?im)^\s*CERTIFIED COPY.*$',
    '(?im)^\s*Verification code[: ].*$',
]
```

```python
import os
from autosxtract import Config, patterns

mine = patterns.load("my_pack.toml")
print(mine.names())                       # ('stamp.conformity',)

resolved = patterns.resolve("my_pack.toml", language="pt-BR")
print(resolved.origins)                   # ('bundled:base', 'bundled:pt_br', 'my_pack.toml')
print(len(resolved.entries))              # 66
print(resolved.patterns("stamp.conformity"))
print(resolved.regex("prose.enclitic").pattern[:40])   # still inherited

# 1. through the configuration
print(Config(patterns="my_pack.toml").stamp_patterns())

# 2. through the environment
os.environ["AUTOSXTRACT_PATTERNS"] = "my_pack.toml"
patterns.reset()                          # the caches are per process
print(Config().stamp_patterns())

del os.environ["AUTOSXTRACT_PATTERNS"]
patterns.reset()
print(Config().stamp_patterns()[0][:40])  # back to the bundled Brazilian ones

# 3. process-wide, for the quality layer
patterns.use(patterns.resolve("my_pack.toml"))
print(patterns.default().origins)
patterns.reset()                          # undoes use() and clears every cache

print(patterns.available_packs())         # ('base', 'pt_br')
print(patterns.pack_for_language("de-DE"))  # 'pt_br' — no bundled German pack
```

```
('stamp.conformity',)
('bundled:base', 'bundled:pt_br', 'my_pack.toml')
66
('(?im)^\\s*CERTIFIED COPY.*$', '(?im)^\\s*Verification code[: ].*$')
(?:l[oa]s?|lhes?|n[oa]s?|m[eo]|te|se|v[o
('(?im)^\\s*CERTIFIED COPY.*$', '(?im)^\\s*Verification code[: ].*$')
('(?im)^\\s*CERTIFIED COPY.*$', '(?im)^\\s*Verification code[: ].*$')
(?:Este\s+documento\s+[ée]\s+(?:c[oó]pia
('bundled:base', 'bundled:pt_br', 'my_pack.toml')
('base', 'pt_br')
pt_br
```

From the shell, with no code at all:

```bash
export AUTOSXTRACT_PATTERNS=/path/to/my_pack.toml     # a file, or a directory of *.toml
autosxtract extract document.pdf
```

A **directory** is merged in sorted order, so a pack can be split by concern the
way the bundled one is.

## Why the whole catalogue compiles at load

`resolve()` ends in `validate()`, which compiles every entry immediately. The cost
is the compilation the process was going to pay anyway — about sixty patterns,
under a millisecond. What changes is **when** a broken pattern is reported: at the
top of the run, naming the entry and the file, instead of on the document that
happened to reach it first.

```
InvalidConfiguration: pattern entry 'stamp.conformity' in bad.toml is not a
valid regular expression: missing ), unterminated subpattern at position 0
```

Asking for an entry as the wrong kind fails the same way, and says where it was
defined:

```
InvalidConfiguration: pattern entry 'stamp.conformity' is a 'patterns' entry
but was asked for as 'pattern' (defined in bundled:pt_br)
```

## Caching, and the one call that clears it

`bundled`, `load`, `available_packs` and the resolution itself are all
`functools.cache`d. Compilation happens once per name and is kept on the set, so
a pattern costs what it cost when it was a module-level constant, and sharing one
`PatternSet` across a whole batch is the intended use.

`patterns.reset()` forgets every cached pack and any installed default. It is for
tests, and for a process that edited a pack on disk and wants it read again.
**Nothing else invalidates the caches**, because a catalogue that reloaded itself
mid-batch would classify the first half of the documents by one rule and the
second half by another.

## Why TOML and not JSON

`tomllib` is in the standard library from Python 3.11, which is the floor this
package already requires, so the catalogue **costs no new dependency**.

Its literal strings (`'''…'''`) carry a regex **verbatim** — there is no escaping
layer between what is written and what `re` compiles. That is precisely the
defect a JSON catalogue would introduce: every backslash in every pattern would
have to be doubled by hand, and a pattern that looks right and is wrong is the
worst kind.

And it takes comments, which matters here more than usual.

## What a review will check

1. **Every entry carries its `why`.** See above.
2. **`base.toml` describes no language.** Control bytes, glyph-index runs, digit
   runs, markdown structure, homoglyph confusions. The moment a Portuguese — or
   English, or German — word appears there, the layering stops meaning anything
   and the seam is closed again.
3. **A language-specific rule outside this package is a design regression.** If
   you are writing `re.compile` with a domain word inside `quality/`, that is the
   bug: the whole point of the catalogue is that the ten modules which used to
   hold those calls no longer do.
4. **A pattern that fires on one archive and not another is a pack, not a new
   built-in.** Widening the bundled `pt_br` patterns needs a count: how many
   documents gained, how many lost, out of how many.

## The other half of the seam: the lexicon

Patterns say what a stamp looks like; the [lexicon](../interfaces.md#lexiconlike)
says what the language looks like. It works the same way — a floor you are
expected to replace:

```python
from pathlib import Path
from autosxtract import Config
from autosxtract.quality.lexicon import Lexicon

mine = Lexicon.from_texts(Path("validated").glob("*.txt"))   # minimum=3
Config(lexicon=mine)
```

`from_texts` drops what appears fewer than three times **on purpose**: an OCR
error rarely repeats three times, and without that cut the lexicon learns the
very errors it exists to detect. Build it from validated text only.

## Porting to another language, end to end

1. Copy `pt_br.toml` and translate the **entries that describe a language** —
   the stopwords, the enclitics, the abbreviations, the domain vocabulary, the
   stamp. Leave `base.toml` alone; it already applies.
2. Rewrite each `why` with **your** measurement. An inherited justification for a
   pattern you changed is worse than none.
3. Point at it with `AUTOSXTRACT_PATTERNS` or `Config(patterns=…)` while you
   iterate; contribute it as `data/<tag>.toml` when it is measured, and
   `Config.language` will select it.
4. Build a lexicon from validated text in that language.
5. Measure the **cascade**, not one pattern. An isolated measurement has already
   lied here: turning off Vision's language correction improved anchors across 60
   documents (+4) and worsened them across the whole cascade (−227), because the
   worse text failed the gate and fell to worse engines.
