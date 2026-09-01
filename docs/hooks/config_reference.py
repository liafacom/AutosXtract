"""Generate the configuration reference from the pydantic model, at build time.

A hand-copied table of forty fields is a table that goes stale, and the part
that must not go stale is precisely the part nobody notices: each field's
description carries the **measurement** that fixed its default. A reader who
changes ``min_agreement`` because the docs did not mention the 24 escalations
it was calibrated on has been misled by the documentation, not by the code.

So this file reads ``autosxtract.config.Config`` and emits the page. It runs as
an MkDocs hook (``hooks:`` in ``mkdocs.yml``), which means the page is produced
during ``mkdocs build`` and never exists on disk to drift from the model. It is
also runnable on its own::

    .venv/bin/python docs/hooks/config_reference.py > /tmp/configuration.md

which is how you check what a field's entry will look like without building the
whole site.

The grouping below is the one comment banner in ``config.py`` — the fields are
listed in declaration order inside each group, so the page and the module read
in the same sequence. A field that arrives without being added to ``GROUPS``
still appears, under "Other": a reference that silently omitted a knob would be
worse than one with an untidy heading.
"""

from __future__ import annotations

import re
import sys
from typing import Any

# ``docs/`` is not a package and the hook is imported by path, so the library
# has to be importable from the environment running mkdocs — which the docs
# workflow guarantees with ``pip install -e .``.
from autosxtract.config import Config

SRC_URI = "configuration.md"

#: ``(heading, prose, fields)``. The prose is what the module's banner comment
#: says, in the reader's direction rather than the maintainer's.
GROUPS: list[tuple[str, str, tuple[str, ...]]] = [
    (
        "Step order",
        "Which steps the cascade assembles, and in what order.",
        ("engines", "use_native"),
    ),
    (
        "Rasterising",
        "How a page becomes pixels. Every OCR step downstream is handed the "
        "result of these three, and is handed the *same* result — two engines "
        "compared on one document must see identical images, or the difference "
        "between them is preprocessing noise.",
        ("dpi", "grayscale", "max_pages"),
    ),
    (
        "The acceptance gate",
        "The single criterion, applied by [`quality/gate.py`](gates.md). The "
        "step that thinks it solved the document and the cascade that decides "
        "whether to pay for the next one read these same numbers.",
        (
            "min_useful_words",
            "min_chars_per_page",
            "min_confidence",
            "min_score",
            "native_accept_score",
        ),
    ),
    (
        "Gates between steps",
        "The four that stop the cascade from paying for a step it does not need.",
        (
            "coverage_gate",
            "consensus_gate",
            "agreement_gate",
            "min_agreement",
            "per_page_routing",
            "fix_orientation",
        ),
    ),
    (
        "Around an expensive step",
        "The five vetoes that run before a step marked `expensive`, and the "
        "replacement gate that judges what it produced.",
        (
            "expensive_step_vetoes",
            "replacement_gate",
            "veto_engine",
            "veto_max_pages",
            "min_reliable_words",
            "rebuild_prose",
        ),
    ),
    (
        "Line containment layers",
        "They need an engine that exposes line geometry (`read_page`). With "
        "any other engine the cascade records *engine without geometry* and "
        "moves on — nothing breaks, there is simply no layer.",
        (
            "layers",
            "layer2",
            "max_layer2_targets",
            "min_layer2_gain",
            "lexicon",
            "signature_detector",
            "page_routing",
        ),
    ),
    (
        "Engines and parallelism",
        "The three parallelism fields accept `None`, meaning *decide from this "
        "machine*, and that is the default: the same library runs on a two-core "
        "laptop and a seventy-two-core server, and one fixed number serves both "
        "badly. An explicit number is obeyed — what it is not, is a promise.",
        (
            "engine_options",
            "engine_parallelism",
            "page_parallelism",
            "document_parallelism",
            "concurrency_cap",
        ),
    ),
    (
        "Domain",
        "The two fields that point at data rather than at a number. This is the "
        "adaptation seam: see [a new pattern pack](extending/patterns.md).",
        ("language", "patterns", "stamps"),
    ),
]

#: Methods that resolve rather than store. They are on the page because reading
#: the field alone gives the wrong answer for all of them.
METHODS = (
    "pattern_set",
    "stamp_patterns",
    "pages_in_flight",
    "documents_in_flight",
    "batch_concurrency",
)


def _type_of(field: Any) -> str:
    annotation = field.annotation
    name = getattr(annotation, "__name__", None) or str(annotation)
    return name.replace("typing.", "").replace("autosxtract.patterns.", "")


def _default_of(field: Any) -> str:
    value = field.get_default(call_default_factory=True)
    return f"`{value!r}`"


def _bounds_of(field: Any) -> str:
    """The pydantic constraints, in the notation the error message uses."""
    parts = []
    for item in field.metadata:
        for attribute, symbol in (("ge", "≥"), ("le", "≤"), ("gt", ">"), ("lt", "<")):
            bound = getattr(item, attribute, None)
            if bound is not None:
                parts.append(f"{symbol} {bound}")
    return ", ".join(parts)


def _describe(field: Any) -> str:
    """The field's own description, unwrapped into one paragraph.

    It is copied verbatim on purpose. Rewording it here would create a second
    place where the measurement is stated, and the two would diverge exactly
    once — the failure this whole file exists to make impossible.
    """
    return _inline_code(" ".join((field.description or "").split()))


def _inline_code(text: str) -> str:
    """``x`` is RST; Markdown wants `x`.

    The descriptions are written for the Python reader, where double backticks
    are the literal marker. Rendering them unconverted puts a stray pair of
    backticks around every default value on the page.
    """
    return re.sub(r"``([^`]+)``", r"`\1`", text)


def _field_block(name: str, field: Any) -> list[str]:
    lines = [f"### `{name}`", ""]
    bounds = _bounds_of(field)
    meta = f"`{_type_of(field)}` · default {_default_of(field)}"
    if bounds:
        meta += f" · {bounds}"
    lines += [meta, "", _describe(field), ""]
    return lines


def render() -> str:
    fields = dict(Config.model_fields)
    listed = {name for _, _, names in GROUPS for name in names}
    leftovers = tuple(name for name in fields if name not in listed)
    groups = [*GROUPS]
    if leftovers:
        groups.append(
            (
                "Other",
                "Fields that exist on the model and have not been filed under a "
                "heading here. That is a gap in `docs/hooks/config_reference.py`, "
                "not in the model.",
                leftovers,
            )
        )

    out = [
        "<!--",
        "  GENERATED at build time by docs/hooks/config_reference.py from",
        "  autosxtract.config.Config. Do not edit: edit the model's Field(",
        "  description=...) instead, which is where the measurement belongs.",
        "-->",
        "",
        "# Configuration reference",
        "",
        "Every knob the cascade has, with the measurement that fixed its default.",
        "",
        "This page is **generated from the pydantic model** during the site build,",
        "by `docs/hooks/config_reference.py`. Each description below is the field's",
        "own `description=` string, copied verbatim — there is no second place where",
        "a threshold is explained, so there is no second place for one to go stale.",
        "",
        "`Config` is **frozen** and rejects unknown keys (`extra='forbid'`): a typo",
        "in a field name is a `ValidationError` at construction rather than a setting",
        "that silently does nothing. To vary one field, use",
        "`config.model_copy(update={...})`.",
        "",
        "!!! note \"No field points at a network\"",
        "",
        "    There is no host, port, URL or credential on this model, and",
        "    `tests/test_config.py::test_no_field_points_at_a_network` is what keeps it",
        "    that way. All networking lives in the constructor of a step somebody wrote",
        "    by hand — see [ADR 0001](adr/0001-no-networking-in-the-default-cascade.md).",
        "",
        "```python",
        "from autosxtract import Cascade, Config",
        "",
        "cascade = Cascade(Config(dpi=150, min_agreement=0.60, engines=[\"paddle\"]))",
        "```",
        "",
    ]

    for heading, prose, names in groups:
        out += [f"## {heading}", "", prose, ""]
        for name in names:
            field = fields.get(name)
            if field is None:  # pragma: no cover — a field renamed in the model
                continue
            out += _field_block(name, field)

    out += [
        "## Methods, not fields",
        "",
        "Five things on `Config` resolve when they are called rather than when the",
        "object is built, and the reason is the same for all of them: **the machine",
        "that resolves may not be the one that serialised the configuration.** A",
        "preset stored in YAML and used in two environments has to answer differently",
        "in each, and a path resolved in the constructor points at a file that is not",
        "there.",
        "",
    ]
    for name in METHODS:
        method = getattr(Config, name)
        doc = _inline_code(" ".join((method.__doc__ or "").split("\n\n")[0].split()))
        out += [f"### `Config.{name}()`", "", doc, ""]

    return "\n".join(out).rstrip() + "\n"


# ── the MkDocs hook ──────────────────────────────────────────────────────


def on_files(files, config):  # noqa: ARG001 — the signature is MkDocs'
    """Add the generated page to the build, without writing it to disk.

    Writing it out would leave a file in the working tree that looks editable
    and is not, and the first person to edit it would lose their change on the
    next build with no error.
    """
    from mkdocs.structure.files import File

    files.append(File.generated(config, SRC_URI, content=render()))
    return files


if __name__ == "__main__":
    sys.stdout.write(render())
