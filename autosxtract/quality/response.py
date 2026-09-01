"""Extracting the transcription from a vision model's response.

*Thinking* models emit reasoning before the transcription ("The user wants...",
"Elements identified: - Top right..."). Measured on a 27B model, that preamble
runs past 400 characters and **describes** the page instead of transcribing it.
Persisting it contaminates the output with text that is not in the document.

Three layers, most reliable first: the delimiters the prompt asks for, the
``</think>`` close, and finally the opening paragraphs of meta-commentary. With
none of them matching, it returns the text as it came — better to deliver
something with noise at the start than to return nothing.

The prompt and the three layers are ``response.*`` in the pattern catalogue: a
prompt is written in the corpus language, and what a model says before obeying
it is written in the same one.

Pure module: text only, no network.
"""

from __future__ import annotations

from autosxtract import patterns

#: The prompt sent to a vision model. It is written in the corpus language and
#: it names the delimiters ``response.delimited`` reads back, so the two travel
#: together in the catalogue: changing one without the other silently loses
#: every transcription.
DEFAULT_PROMPT = patterns.default().text("response.prompt")


def clean_response(raw: str | None) -> str:
    """Only the transcription, discarding the model's reasoning.

    **Every** delimited block is used, in the order it appears: a batch of N
    pages yields N blocks, and keeping only the first discarded the rest.
    """
    if not raw:
        return ""
    catalogue = patterns.default()
    text = catalogue.regex("response.md_fence").sub("", raw.strip())

    blocks = [m.group("body").strip() for m in catalogue.regex("response.delimited").finditer(text)]
    blocks = [b for b in blocks if b]
    if blocks:
        return "\n\n".join(blocks)

    if "</think>" in text.lower():
        text = catalogue.regex("response.after_think").sub("", text, count=1)

    return catalogue.regex("response.leading_meta").sub("", text, count=1).strip()


def response_blocks(raw: str | None) -> list[str]:
    """The delimited blocks of the response — one per transcribed page.

    With no delimiter at all, the whole text counts as a single block: for
    counting purposes that is equivalent to one page.
    """
    cleaned = clean_response(raw)
    if not cleaned:
        return []
    catalogue = patterns.default()
    text = catalogue.regex("response.md_fence").sub("", (raw or "").strip())
    blocks = [m.group("body").strip() for m in catalogue.regex("response.delimited").finditer(text)]
    blocks = [b for b in blocks if b]
    return blocks or [cleaned]
