"""Rebuild prose from text the OCR broke line by line.

Every OCR engine returns one line per VISUAL line on the page. A sentence
spanning eight lines on paper becomes eight lines of text, and the result is
not prose: it is a list. Measured on a real archive, **85% of the lines do not
end in punctuation** — they are fragments, not sentences.

This is not cosmetic. It breaks everything that consumes the text downstream:
sentence splitting, proximity windows looking for a signal and a date in the
SAME sentence, amount and date regexes that tolerate few spaces between tokens,
and an LLM reading loose fragments.

The rules are deliberately conservative: when in doubt, they keep the break.
Joining wrongly glues two distinct sentences together and creates a statement
nobody wrote — worse than ugly text.

The rules below describe Portuguese, which is the corpus language, and none of
them is written here: they are the ``prose.*`` entries of the pattern catalogue.
What lives in this file is the ORDER the rules are applied in, which is where
the damage would come from — joining wrongly is worse than not joining.
"""

from __future__ import annotations

import re

from autosxtract import patterns

STAMP_FOOTER = "[digital conformity stamp]"


def _homoglyphs(text: str) -> str:
    """Swap characters from other alphabets for their Latin equivalent."""
    return text.translate(patterns.default().translation("prose.homoglyphs"))


def _fix_thousands(m: re.Match[str]) -> str:
    """``9,159.70`` -> ``9.159,70``. Only impossible forms reach this."""
    raw = m.group(0)
    body, _, cents = raw.rpartition(raw[-3])
    return body.replace(",", ".") + "," + cents


def _split_stamp(text: str) -> tuple[str, list[str]]:
    """Take the stamp lines out of the body and return them separately."""
    catalogue = patterns.default()
    body: list[str] = []
    stamps: list[str] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        if catalogue.regex("prose.stamp_line").search(line):
            key = catalogue.regex("prose.whitespace").sub(" ", line).strip()
            if key and key not in seen:
                seen.add(key)
                stamps.append(key)
            continue
        body.append(line)
    return "\n".join(body), stamps


def _join(previous: str, following: str) -> str | None:
    """How to join two lines, or ``None`` to keep the break."""
    catalogue = patterns.default()
    structure = catalogue.regex("prose.structure")
    a, b = previous.rstrip(), following.lstrip()
    if not a or not b:
        return None
    if structure.match(previous) or structure.match(following):
        return None
    # A split number: glue with no space. This covers case numbers and payment
    # slips, which are exactly the tokens downstream extraction looks for.
    if catalogue.regex("prose.split_number").search(a) and b[:1].isdigit():
        return a + b
    # A hyphen at the end of the line has two opposite causes, and confusing
    # them corrupts the text:
    #
    # - typographic hyphenation ("consti-\ntuição") -> the hyphen GOES;
    # - enclisis ("mantê-\nlos") -> the hyphen belongs to the language and STAYS.
    #
    # The enclitic pronoun is a closed set, so the distinction is safe. Always
    # removing would produce "mantêlos"; always keeping would produce
    # "consti-tuição". Neither is acceptable.
    hyphen = catalogue.regex("prose.line_break_hyphen")
    if hyphen.search(a) and b[:1].islower():
        if catalogue.regex("prose.enclitic").match(b):
            return a + b
        return hyphen.sub(r"\1", a) + b
    # A full stop does NOT always end a sentence: forensic text is full of
    # abbreviations ("n.", "art.", "fls.", "Sr.", "B."). Treating every stop as
    # an ending broke sentences mid-way.
    abbreviation = catalogue.regex("prose.abbreviation")
    if catalogue.regex("prose.sentence_end").search(a) and not abbreviation.search(a):
        return None
    # After an abbreviation, a digit on the next line is certainly a
    # continuation ("sob n." + "676.149").
    if abbreviation.search(a) and b[:1].isdigit():
        return a + " " + b
    # Here the previous line did NOT close a sentence, so the sentence
    # continues. Requiring the next one to start lowercase was too
    # conservative: legal Portuguese capitalises heavily, and the rule left 78%
    # of the lines still broken. The strong signal is the PREVIOUS line's, not
    # the following one's.
    if catalogue.regex("prose.title").match(b):
        return None
    return a + " " + b


def rebuild_prose(text: str) -> str:
    """Join lines that continue the same sentence.

    Preserves paragraph breaks, markdown structure and any case where the
    continuation is not evident.
    """
    if not text:
        return ""
    page_number = patterns.default().regex("prose.page_number_only")
    out: list[str] = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if page_number.match(line):
            # A page marker inside the body interrupts the sentence; it goes
            # without leaving a break, so the two halves meet.
            continue
        if not line.strip():
            out.append("")
            continue
        if out and out[-1]:
            joined = _join(out[-1], line)
            if joined is not None:
                out[-1] = joined
                continue
        out.append(line)
    return "\n".join(out)


def normalize(text: str) -> str:
    """Deterministic, safe normalisations over the extracted text.

    Only unambiguous rules get in, each verified against a real archive. These
    were deliberately left OUT, by measurement:

    - **re-accenting** — it would corrupt proper names; the right path is to
      double the accent in whatever consumes the text, not in the text;
    - **splitting joined words** — every occurrence was in a decorative header,
      and the rule would merge proper names;
    - **fixing an ambiguous decimal separator** — no case in the archive; a
      speculative rule would only risk corrupting a correct amount;
    - **``rn`` -> ``m``** — it would destroy "governo", "interno", "Bernardo".
    """
    if not text:
        return ""
    catalogue = patterns.default()
    t, stamps = _split_stamp(_homoglyphs(text))
    # The symbol split from the number by a line break. Rejoining BEFORE the
    # unwrap is what keeps a lone currency line from becoming a stray paragraph.
    t = catalogue.sub("prose.currency_split", t)
    t = rebuild_prose(t)
    # The symbol glued to the number, then the symbol the OCR misread. Each
    # carries its own replacement in the catalogue, because a pattern and the
    # text that replaces it are two halves of one decision.
    t = catalogue.sub("prose.currency_glued", t)
    t = catalogue.sub("prose.wrong_currency_symbol", t)
    # Forms IMPOSSIBLE in the corpus language. There is no ambiguity and the
    # right reading is unique, but it depends on which separator ends up last,
    # so the replacement is computed rather than stored.
    t = catalogue.regex("prose.english_thousands").sub(_fix_thousands, t)
    t = catalogue.sub("prose.section_mark", t)
    t = catalogue.regex("prose.horizontal_space").sub(" ", t)
    t = catalogue.regex("prose.blank_lines").sub("\n\n", t).strip()
    if stamps:
        # The stamp goes to the end, in its own block. It is NOT discarded: it
        # carries the digitisation date, which sometimes matters. What it must
        # not do is sit mid-sentence, competing with the content.
        t += "\n\n" + STAMP_FOOTER + "\n" + "\n".join(stamps)
    return t
