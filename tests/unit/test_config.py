"""Configuration is immutable and refuses unknown fields — on purpose.

A typo in a parameter name that passes silently is the cheapest way to run for
months with a gate switched off without knowing.

The fields are checked here; whether the cascade then HONOURS them is a
different question, asked in ``integration/test_assembly.py`` — a knob nothing
consults is the defect ``engine_options`` was added to fix.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autosxtract.config import Config


def test_the_defaults_are_the_measured_ones():
    c = Config()
    assert c.dpi == 150  # at 100 DPI anchor preservation falls to 85.5%
    assert c.min_useful_words == 12
    assert c.min_agreement == 0.60
    assert c.grayscale is True


def test_an_unknown_field_is_an_error():
    with pytest.raises(ValidationError):
        Config(dpi_typo=300)


def test_the_config_is_immutable():
    c = Config()
    with pytest.raises(ValidationError):
        c.dpi = 300


def test_the_limits_are_validated():
    with pytest.raises(ValidationError):
        Config(dpi=0)
    with pytest.raises(ValidationError):
        Config(min_agreement=1.5)


def test_no_field_points_at_a_network():
    """An architectural invariant: extraction does no networking.

    If anyone ever adds a host, a port or a URL, this test breaks — and the
    conversation happens before the merge rather than after the incident.

    It compares name PARTS rather than substrings: ``page_routing`` contains
    "rout" and would give a false impression of a violation.
    """
    forbidden = {"host", "port", "url", "endpoint", "token", "key", "api", "secret"}
    for field in Config.model_fields:
        assert not (set(field.lower().split("_")) & forbidden), field


# ── parallelism belongs to whoever runs it ───────────────────────────────


def test_every_parallelism_knob_is_honoured_when_set():
    """An explicit number is OBEYED, on every axis.

    The library measures its defaults on the hardware it was written for, and
    that hardware is not everyone's. A number that cannot be raised is a
    measurement pretending to be a law: it makes the library slower than it
    needs to be on a big machine and heavier than it should be on a small one.

    ``resources`` decides only when nobody said anything.
    """
    cfg = Config(document_parallelism=16, page_parallelism=3, concurrency_cap=0)
    assert cfg.documents_in_flight() == 16
    assert cfg.pages_in_flight() == 3
    # cap 0 = no aggregate ceiling, so the product passes through untouched.
    assert cfg.batch_concurrency() == (16, 3)


def test_none_means_decide_from_the_machine():
    """The default, and the reason the fields are ``| None`` rather than ints.

    Resolution is a METHOD and not a value computed in the constructor: the
    machine that resolves may not be the one that serialised the config.
    """
    cfg = Config()
    assert cfg.document_parallelism is None
    assert cfg.page_parallelism is None
    assert cfg.documents_in_flight() >= 1
    assert cfg.pages_in_flight() >= 1


def test_the_aggregate_cap_cuts_pages_before_documents():
    """``documents x pages`` reaches 32 in flight from values that look modest,
    and each page in flight holds a rendered image plus the model's activations.

    Cutting documents raises total time predictably; cutting pages per document
    costs almost nothing, because the per-document thread curve flattens well
    before the memory ceiling.
    """
    cfg = Config(document_parallelism=4, page_parallelism=8, concurrency_cap=8)
    documents, pages = cfg.batch_concurrency()
    assert documents == 4  # untouched
    assert pages == 2  # cut to fit the cap


def test_the_cap_never_starves_a_document():
    """Even an absurd cap leaves one page in flight — zero would deadlock."""
    cfg = Config(document_parallelism=10, page_parallelism=10, concurrency_cap=1)
    assert cfg.batch_concurrency() == (10, 1)


def test_the_override_only_touches_the_engine_it_names():
    """Naming one engine's parallelism must not silently answer for the others."""
    cfg = Config(engine_parallelism={"vision": 4})
    assert (cfg.engine_parallelism or {}).get("paddle") is None
