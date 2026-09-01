"""The lexicon decides what counts as the corpus language — hence injectable."""

from __future__ import annotations

from autosxtract.quality.lexicon import Lexicon


def test_the_builtin_separates_prose_from_junk():
    lx = Lexicon.builtin()
    assert lx.coverage("O requerente vem requerer a citacao do requerido") > 0.6
    assert lx.coverage("kdjf wqpo zzxc mmnb qwrt") == 0.0


def test_a_line_with_no_word_is_not_punished():
    """A case number and a date are not words; punishing them would discard
    exactly what matters most to preserve."""
    assert Lexicon.builtin().coverage("0001234-56.2020.8.12.0001") == 1.0


def test_a_custom_lexicon_adds_to_the_builtin():
    lx = Lexicon.from_words(["renavam", "chassi"])
    assert "renavam" in lx
    assert "processo" in lx  # the built-in is still there


def test_a_custom_lexicon_can_replace_the_builtin():
    lx = Lexicon.from_words(["renavam"], add_builtin=False)
    assert "renavam" in lx
    assert "processo" not in lx


def test_from_texts_drops_what_appears_rarely(tmp_path):
    """An OCR error rarely repeats three times; without the cut the lexicon
    learns the very errors it should detect."""
    (tmp_path / "a.txt").write_text("penhora penhora penhora rabisco", encoding="utf-8")
    lx = Lexicon.from_texts(tmp_path.glob("*.txt"), add_builtin=False)
    assert "penhora" in lx
    assert "rabisco" not in lx


def test_an_unreadable_file_does_not_break(tmp_path):
    lx = Lexicon.from_texts([tmp_path / "missing.txt"], add_builtin=False)
    assert isinstance(lx, Lexicon)
