"""The pattern catalogue: the packs, the resolution order and the guard rails.

Two of these tests exist to catch a specific way of breaking the library that
no other test would notice.

``test_every_name_the_code_asks_for_exists`` walks the source for every
``patterns.default().regex("...")`` and friends and demands the data define it.
Before the catalogue a deleted regex was a ``NameError`` at import; now it is a
missing key at the moment the document reaches it, which on a batch means half
the archive processed and a crash on the other half.

``test_the_bundled_pack_classifies_what_it_always_classified`` pins the
BEHAVIOUR of the pt-BR pack rather than its content. The patterns were moved out
of the code by machine and verified byte for byte, and this is what keeps them
that way: a well-meaning tidy-up of a regex in the TOML shows up here as a
document that stops being recognised.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from autosxtract import patterns
from autosxtract.config import Config
from autosxtract.exceptions import InvalidConfiguration

#: The package source, from ``tests/unit/`` — three levels up is the repository.
SOURCE = Path(__file__).resolve().parents[2] / "autosxtract"

#: The accessors on a ``PatternSet``. A name reaching one of these is a name the
#: code cannot run without.
ACCESSORS = frozenset(
    {"regex", "sub", "patterns", "strings", "words", "mapping", "translation", "text", "why"}
)


@pytest.fixture(autouse=True)
def _clean_catalogue():
    """Every test starts from the bundled packs and leaves them behind it.

    The catalogue is process-wide on purpose — the quality modules take no
    configuration — so a test that installs a pack and forgets to remove it
    silently rewrites the rules for everything that runs afterwards.
    """
    before = os.environ.get(patterns.ENVIRONMENT_VARIABLE)
    patterns.reset()
    yield
    if before is None:
        os.environ.pop(patterns.ENVIRONMENT_VARIABLE, None)
    else:
        os.environ[patterns.ENVIRONMENT_VARIABLE] = before
    patterns.reset()


# ── the bundled packs ────────────────────────────────────────────────────


def test_the_bundled_packs_load_and_compile():
    """Both packs, every entry. ``validate`` is what makes this exhaustive."""
    assert set(patterns.available_packs()) >= {"base", "pt_br"}
    for pack in patterns.available_packs():
        loaded = patterns.bundled(pack).validate()
        assert loaded.names(), pack


def test_base_carries_nothing_that_names_a_language():
    """The point of splitting the packs, checked where it can rot.

    ``base`` is what a corpus in another language inherits untouched. A
    Portuguese word landing in it would be inherited too, silently, and the
    split would become decoration.
    """
    portuguese = ("digitalmente", "verifica", "assinad", "documento", "processo", "juiz")
    for name, entry in patterns.bundled("base").entries.items():
        haystack = " ".join([entry.pattern, entry.text, *entry.items]).lower()
        for word in portuguese:
            assert word not in haystack, f"{name} carries {word!r}"


def test_every_entry_says_why_it_exists():
    """The measurement travels with the pattern or it is lost.

    It was lost once already: the comments above the ``re.compile`` calls were
    the only record of what each pattern had been measured against, and moving
    the pattern without them would have thrown that away.
    """
    for pack in patterns.available_packs():
        for name, entry in patterns.bundled(pack).entries.items():
            assert len(entry.why) > 40, f"{pack}:{name} has no explanation"


def _names_asked_for() -> set[str]:
    found: set[str] = set()
    for file in SOURCE.rglob("*.py"):
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in ACCESSORS or not node.args:
                continue
            first = node.args[0]
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and "." in first.value
            ):
                found.add(first.value)
    return found


def test_every_name_the_code_asks_for_exists():
    """Delete an entry the code needs and this is what breaks, not a document."""
    asked = _names_asked_for()
    # A floor, so that a refactor which stops asking for anything at all — the
    # failure mode this test cannot otherwise see — shows up as a failure.
    assert len(asked) >= 50
    resolved = patterns.resolve()
    missing = sorted(name for name in asked if name not in resolved)
    assert not missing, f"the code asks for entries no pack defines: {missing}"


def test_asking_for_the_wrong_shape_says_so():
    """A word list is not a regex, and the message has to say which it is."""
    with pytest.raises(InvalidConfiguration) as error:
        patterns.resolve().regex("lexicon.builtin")
    assert "lexicon.builtin" in str(error.value)
    assert "words" in str(error.value)


def test_an_unknown_name_names_the_packs_that_were_loaded():
    with pytest.raises(InvalidConfiguration) as error:
        patterns.resolve().regex("prose.no_such_rule")
    assert "prose.no_such_rule" in str(error.value)
    assert "bundled:pt_br" in str(error.value)


# ── resolution order ─────────────────────────────────────────────────────

OVERRIDE = """
[stamp.conformity]
why = "A pack of one entry, which is a complete pack: the rest is inherited."
patterns = ['CONFIDENTIAL - INTERNAL USE']

[prose.sentence_end]
why = "A different notion of where a sentence ends, to prove the merge is per entry."
pattern = '[.!?]\\s*$'
"""


def _pack(tmp_path: Path, body: str = OVERRIDE, name: str = "mine.toml") -> Path:
    file = tmp_path / name
    file.write_text(body, encoding="utf-8")
    return file


def test_a_user_pack_overrides_entry_by_entry(tmp_path):
    """Two entries replaced, sixty inherited — that is what makes a small pack
    usable at all, and what stops it becoming a fork of the bundled one."""
    resolved = patterns.resolve(_pack(tmp_path))
    assert resolved.patterns("stamp.conformity") == ("CONFIDENTIAL - INTERNAL USE",)
    assert resolved.regex("prose.sentence_end").pattern == r"[.!?]\s*$"
    # Inherited from pt_br and from base, untouched.
    assert "processo" in resolved.words("lexicon.builtin")
    assert resolved.regex("anchors.digit_run").pattern == r"\d{5,}"
    assert resolved.why("stamp.conformity").startswith("A pack of one entry")


def test_a_directory_of_packs_merges_in_order(tmp_path):
    _pack(tmp_path, OVERRIDE, "10-base.toml")
    _pack(
        tmp_path,
        "[stamp.conformity]\nwhy = 'The later file wins, so a pack can be layered.'\n"
        "patterns = ['LATER']\n",
        "20-later.toml",
    )
    resolved = patterns.resolve(tmp_path)
    assert resolved.patterns("stamp.conformity") == ("LATER",)
    assert resolved.regex("prose.sentence_end").pattern == r"[.!?]\s*$"


def test_the_environment_variable_is_read(tmp_path):
    os.environ[patterns.ENVIRONMENT_VARIABLE] = str(_pack(tmp_path))
    patterns.reset()
    assert patterns.default().patterns("stamp.conformity") == ("CONFIDENTIAL - INTERNAL USE",)


def test_an_explicit_pack_beats_the_environment(tmp_path):
    """The order the docstring promises, at the one place the two can disagree."""
    os.environ[patterns.ENVIRONMENT_VARIABLE] = str(_pack(tmp_path))
    explicit = _pack(
        tmp_path,
        "[stamp.conformity]\nwhy = 'Named in the configuration, so it is what was meant.'\n"
        "patterns = ['EXPLICIT']\n",
        "explicit.toml",
    )
    patterns.reset()
    resolved = Config(patterns=str(explicit)).pattern_set()
    assert resolved.patterns("stamp.conformity") == ("EXPLICIT",)
    # And the environment's pack is still underneath, for what the explicit one
    # does not name.
    assert resolved.regex("prose.sentence_end").pattern == r"[.!?]\s*$"


def test_a_pattern_set_passed_in_is_used_as_it_is(tmp_path):
    built = patterns.load(_pack(tmp_path))
    assert Config(patterns=built).pattern_set() is built


def test_a_language_with_no_pack_keeps_the_default_one():
    """Not leniency: before the catalogue the patterns were Portuguese whatever
    ``language`` said, and raising here would break a working configuration."""
    assert patterns.pack_for_language("fr-FR") == patterns.DEFAULT_PACK
    assert patterns.pack_for_language("pt-BR") == "pt_br"
    assert patterns.pack_for_language(None) == patterns.DEFAULT_PACK
    assert "lexicon.builtin" in Config(language="en").pattern_set()


# ── a broken pack fails at load, naming the entry ────────────────────────


def test_an_invalid_regex_names_the_entry(tmp_path):
    file = _pack(
        tmp_path,
        "[prose.title]\nwhy = 'An unbalanced group, which is the commonest way to break a pack.'\n"
        "pattern = '^(unclosed'\n",
    )
    with pytest.raises(InvalidConfiguration) as error:
        patterns.resolve(file)
    message = str(error.value)
    assert "prose.title" in message
    assert str(file) in message


def test_an_invalid_regex_in_a_list_names_the_entry(tmp_path):
    file = _pack(
        tmp_path,
        "[stamp.conformity]\nwhy = 'A list entry is validated item by item, like a lone one.'\n"
        "patterns = ['fine', '*broken']\n",
    )
    with pytest.raises(InvalidConfiguration) as error:
        patterns.resolve(file)
    assert "stamp.conformity" in str(error.value)


def test_an_entry_with_no_shape_is_refused(tmp_path):
    file = _pack(
        tmp_path, "[prose.title]\nwhy = 'A typo where the value should be.'\nregex = 'x'\n"
    )
    with pytest.raises(InvalidConfiguration) as error:
        patterns.resolve(file)
    assert "prose.title" in str(error.value)


def test_an_unknown_flag_is_refused(tmp_path):
    file = _pack(
        tmp_path,
        "[prose.title]\nwhy = 'A flag that does not exist should not be ignored in silence.'\n"
        "pattern = 'x'\nflags = ['IGNORECASE', 'LOOSE']\n",
    )
    with pytest.raises(InvalidConfiguration) as error:
        patterns.resolve(file)
    assert "LOOSE" in str(error.value)


def test_a_missing_pack_says_where_it_looked(tmp_path):
    with pytest.raises(InvalidConfiguration) as error:
        patterns.resolve(tmp_path / "absent.toml")
    assert "absent.toml" in str(error.value)


def test_malformed_toml_names_the_file(tmp_path):
    file = _pack(tmp_path, "[prose.title\n")
    with pytest.raises(InvalidConfiguration) as error:
        patterns.resolve(file)
    assert str(file) in str(error.value)


# ── the cost stays what it was ───────────────────────────────────────────


def test_a_pattern_is_compiled_once():
    """The property that lets the modules ask for a pattern per line.

    As module-level constants they compiled at import; the catalogue has to
    match that, or the containment layers pay a compilation per line of every
    page.
    """
    resolved = patterns.resolve()
    assert resolved.regex("lines.junk") is resolved.regex("lines.junk")
    assert resolved.translation("prose.homoglyphs") is resolved.translation("prose.homoglyphs")


def test_the_same_configuration_resolves_to_the_same_set():
    """Otherwise every call would re-read and re-compile the packs."""
    assert patterns.resolve() is patterns.resolve()
    assert Config().pattern_set() is Config().pattern_set()


# ── behaviour: the pt-BR pack still classifies what it classified ────────


def test_the_bundled_pack_classifies_what_it_always_classified():
    """One case per module that owned a regex, with the verdicts it gave before
    the patterns left the code."""
    # The modules, not the names ``quality/__init__`` re-exports: ``anchors``
    # is both a module and the function inside it.
    from autosxtract.quality import markers, prose, screening
    from autosxtract.quality.anchors import anchors, lost
    from autosxtract.quality.stamp import strip_stamp, useful_words

    # anchors: the VIN, the punctuated case number and the long digit run.
    found = anchors("VIN 9XXYZ32E41A099887 autos 001.06.012345-6 protocolo 882167")
    assert "9XXYZ32E41A099887" in found
    assert "001060123456" in found
    assert "882167" in found
    assert lost("protocolo 882167", "protocolo 882187") == {"882167"}

    # stamp: the banner goes, the body stays, and what is left is not content.
    banner = (
        "Este documento e copia do original assinado digitalmente por FULANO. "
        "Para conferir o original acesse o site e informe o codigo de verificacao "
        "8A2F91C. fls. 42"
    )
    assert useful_words(banner) < 12
    assert "requerente" in strip_stamp(banner + "\nO requerente pede a citacao.")

    # screening: the identity-card marks, with the density that separates them.
    card = "FILIACAO NATURALIDADE DATA DE EXPEDICAO POLEGAR DIREITO ASSINATURA DO TITULAR"
    assert screening.is_identity_document(card)
    assert not screening.is_identity_document(
        "O requerente juntou copia de sua carteira de identidade aos autos do processo."
    )

    # prose: the abbreviation that does not end a sentence, the currency symbol
    # the OCR corrupted, and the stamp line moved to the end.
    rebuilt = prose.rebuild_prose("nos autos sob n.\n676.149 do processo")
    assert rebuilt == "nos autos sob n. 676.149 do processo"
    assert "R$ 30.068,67" in prose.normalize("valor de R$30.068,67 pago")
    assert "R$ 1.500,00" in prose.normalize("valor de RS 1.500,00 pago")
    assert prose.STAMP_FOOTER in prose.normalize(
        "corpo do texto\nEste documento é cópia do original\nmais texto"
    )

    # markers: the degenerate loop of a vision model.
    assert markers.is_degenerate_loop("[ILEGÍVEL] [ILEGÍVEL] [ASSINATURA] [ILEGÍVEL]")
    assert not markers.is_degenerate_loop(
        "O requerente pede a citacao do requerido nos autos. [ASSINATURA]"
    )


def test_a_replaced_stamp_pack_changes_what_is_measured(tmp_path):
    """The adaptation the catalogue exists for, end to end: a pack, no code."""
    from autosxtract.quality.stamp import strip_stamp

    file = _pack(
        tmp_path,
        "[stamp.conformity]\nwhy = 'Another domain prints another banner; only the list moves.'\n"
        "patterns = ['CONFIDENTIAL - INTERNAL USE']\n",
    )
    os.environ[patterns.ENVIRONMENT_VARIABLE] = str(file)
    patterns.reset()

    text = "CONFIDENTIAL - INTERNAL USE\nquarterly sales report"
    assert "CONFIDENTIAL" not in strip_stamp(text)
    # And the Brazilian banner, absent from the new list, now survives.
    assert "verificacao" in strip_stamp("codigo de verificacao 8A2F91C").lower()
