"""Prose rebuilding: 85% of OCR lines do not end in punctuation."""

from __future__ import annotations

from autosxtract.quality.prose import STAMP_FOOTER, normalize, rebuild_prose


def test_joins_a_line_that_continues_the_sentence():
    broken = "O requerente vem a presenca\nde Vossa Excelencia requerer"
    assert rebuild_prose(broken) == "O requerente vem a presenca de Vossa Excelencia requerer"


def test_keeps_the_break_after_a_sentence_end():
    assert "\n" in rebuild_prose("Primeira frase.\nSegunda frase aqui")


def test_an_abbreviation_does_not_end_a_sentence():
    """ "portador da C.I sob n." + "676.149" was being broken mid-way."""
    assert rebuild_prose("portador do documento sob n.\n676.149 SSP") == (
        "portador do documento sob n. 676.149 SSP"
    )


def test_typographic_hyphenation_loses_the_hyphen():
    assert rebuild_prose("consti-\ntuicao") == "constituicao"


def test_enclisis_keeps_the_hyphen():
    """Always removing gives "mantêlos"; always keeping gives "consti-tuição"."""
    assert rebuild_prose("mante-\nlos em juizo") == "mante-los em juizo"


def test_a_split_number_joins_without_a_space():
    assert rebuild_prose("processo 0001234-\n56.2020") == "processo 0001234-56.2020"


def test_markdown_structure_is_never_merged():
    table = "| coluna | outra |\n| a | b |"
    assert rebuild_prose(table) == table


def test_a_title_stays_on_its_own_line():
    text = "texto corrido sem ponto\nJUIZO DE DIREITO DA VARA CIVEL"
    assert "\n" in rebuild_prose(text)


def test_a_lone_page_marker_goes_without_breaking_the_sentence():
    assert rebuild_prose("a frase continua\nfls. 42\nna linha seguinte") == (
        "a frase continua na linha seguinte"
    )


def test_a_misread_currency_symbol_is_fixed():
    """The amount IS in the text and the consumer's regex does not see it."""
    assert "R$ 1.234,56" in normalize("pagou RS 1.234,56 na data")


def test_a_legitimate_word_does_not_become_a_currency_symbol():
    """The monetary lookahead is what makes the substitution safe."""
    assert "RESSALVADO" in normalize("RESSALVADO o entendimento")
    assert "RECURSO" in normalize("RECURSO conhecido")


def test_english_thousands_are_impossible_in_portuguese():
    assert "9.159,70" in normalize("valor de 9,159.70 reais")


def test_the_stamp_goes_to_the_end_and_does_not_vanish():
    """It carries the digitisation date; what it must not do is sit mid-sentence."""
    text = "O juiz decidiu\nEste documento e copia do original\nque a parte seja citada"
    output = normalize(text)
    assert "O juiz decidiu que a parte seja citada" in output
    assert STAMP_FOOTER in output
    assert "copia do original" in output


def test_a_cyrillic_homoglyph_becomes_latin():
    assert normalize("АCORDАO") == "ACORDAO"


def test_empty_text():
    assert normalize("") == ""
    assert rebuild_prose("") == ""
