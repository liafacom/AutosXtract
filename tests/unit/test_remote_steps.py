"""The remote steps' constructor contract — no socket, no document, no cascade.

What these tests pin down is an architectural invariant, not a detail: **the
library must not be able to reach the network by accident**. In the previous
architecture the engine that resolved 64% of the documents lived behind a
tunnel, and its going down silently degraded the text — 488 documents
re-extracted down the worse path, 28,239 characters lost, and nobody noticed.

The invariant is enforced in the constructor and nowhere else: ``url`` is
required, there is no discovery, and ``Config`` carries no field that could hold
an address. That is all answerable without building a cascade, which is why it
lives in the unit slice; what the assembled default cascade does with these
steps is ``integration/test_remote.py``.
"""

from __future__ import annotations

import pytest

from autosxtract.config import Config
from autosxtract.steps.remote import DoclingStep, RemoteStep, VLMStep


def test_the_config_carries_no_address_or_credential():
    """Networking lives in the step's constructor, never in the cascade config."""
    forbidden = {"host", "port", "url", "endpoint", "token", "key", "api", "secret"}
    for field in Config.model_fields:
        assert not (set(field.lower().split("_")) & forbidden), field


# ── constructor contract ─────────────────────────────────────────────────


def test_the_url_is_mandatory():
    """There is no environment-variable discovery and no built-in default."""
    with pytest.raises(ValueError, match="url"):
        DoclingStep(url="")
    with pytest.raises(ValueError, match="url"):
        VLMStep(url="", model="whatever")


def test_the_model_is_mandatory_for_the_vlm():
    with pytest.raises(ValueError, match="model"):
        VLMStep(url="http://x", model="")


def test_the_token_never_appears_in_the_repr():
    """The extraction's result circulates; a credential must not travel with it."""
    step = VLMStep(url="http://x", model="m", token="secret-abc123")
    assert "secret" not in repr(step)
    assert "***" in repr(step)


def test_the_parameters_stay_on_the_instance():
    step = VLMStep(
        url="https://llm.example/v1/",
        model="Qwen2.5-VL-7B",
        token="t",
        dpi=300,
        images_per_batch=4,
        parallelism=8,
        max_tokens_per_page=1500,
    )
    assert step.url == "https://llm.example/v1"  # trailing slash removed
    assert step.model == "Qwen2.5-VL-7B"
    assert step.dpi == 300
    assert step.images_per_batch == 4
    assert step.parallelism == 8


def test_remote_steps_are_expensive():
    """That is what makes the cascade run the vetoes before and the gate after."""
    assert DoclingStep(url="http://x").expensive
    assert VLMStep(url="http://x", model="m").expensive


# ── options sent to docling-serve ────────────────────────────────────────


def test_docling_asks_for_json_as_well_as_markdown():
    """Without ``json`` the orphaned-text recovery has nothing to recover.

    On a scanned page the OCR text ends up outside ``body`` and vanishes from
    the markdown; the structured document is the only place it survives.
    """
    step = DoclingStep(url="http://x")
    assert "json" in step.options["to_formats"]
    assert "md" in step.options["to_formats"]


def test_fast_table_mode_is_the_default():
    """Measured: 1.12x faster AND with more text (29,956 against 25,517)."""
    assert DoclingStep(url="http://x").options["table_mode"] == "fast"


def test_force_ocr_stays_out_of_the_first_pass():
    step = DoclingStep(url="http://x")
    assert "force_ocr" not in step.options
    assert step.force_options["force_ocr"] == "true"


# ── local Docling: the same engine, no network ───────────────────────────


def test_local_docling_is_not_remote():
    """It runs in-process: it does not inherit RemoteStep and needs no url."""
    from autosxtract.steps.docling_local import LocalDoclingStep

    step = LocalDoclingStep()
    assert not isinstance(step, RemoteStep)
    assert not hasattr(step, "url")
    assert step.expensive


def test_local_docling_loads_no_model_on_construction():
    """Assembling a cascade to find the PDF is native must not cost 2 GB."""
    from autosxtract.steps.docling_local import LocalDoclingStep

    assert LocalDoclingStep()._pool is None


def test_the_converter_returns_to_the_pool_even_on_failure():
    """A converter that does not return silently removes process capacity."""
    import queue

    from autosxtract.steps.docling_local import LocalDoclingStep

    class BrokenConverter:
        def convert(self, path):
            raise RuntimeError("native dependency missing")

    step = LocalDoclingStep(workers=1)
    step._pool = queue.Queue()
    step._pool.put(BrokenConverter())

    with pytest.raises(RuntimeError, match="native dependency"):
        step._convert(b"%PDF-1.7")
    assert step._pool.qsize() == 1
