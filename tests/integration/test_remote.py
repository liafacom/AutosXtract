"""Remote steps inside a cascade — against a fake server, never a socket.

The constructor contract is pinned in ``unit/test_remote_steps.py``. What is
asked here is the other half, and it is the half that failed in production: does
the DEFAULT cascade stay local, and does a remote step that is down become a
refused attempt with a reason rather than a document with no text?

The client is replaced, not the network stubbed. ``httpx`` is never imported by
these tests — the step's ``_client`` is monkeypatched before anything can build
one — which is what keeps them running in a bare ``[dev]`` environment where the
``remote`` extra is not installed.
"""

from __future__ import annotations

import json

import pytest

from autosxtract.cascade import Cascade
from autosxtract.config import Config
from autosxtract.steps.remote import DoclingStep, RemoteStep, VLMStep

# ── what the default cascade does (and does not) ─────────────────────────


def test_the_default_cascade_has_no_remote_step():
    for step in Cascade().steps:
        assert not isinstance(step, RemoteStep)
        assert not getattr(step, "expensive", False)


# ── behaviour against a fake server ──────────────────────────────────────


class _FakeResponse:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class _FakeClient:
    """Replaces ``httpx.Client`` without opening a single socket."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url, **kwargs):
        self.calls.append(url)
        return _FakeResponse({"choices": [{"message": {"content": self.text}}]})


def test_the_vlm_transcribes_and_strips_the_reasoning(pdf_scanned, monkeypatch):
    """A *thinking* model describes the page before transcribing it."""
    raw = (
        "O usuário deseja a transcrição desta página.\n"
        "Elementos identificados: - Topo direito: carimbo\n"
        "=== INICIO DA TRANSCRICAO ===\n"
        "CERTIDAO. Certifico que a intimacao do executado foi cumprida nos "
        "autos do processo 0001234-56.2020.8.12.0001 na data indicada, "
        "conforme determinado pela decisao anterior da vara civel.\n"
        "=== FIM DA TRANSCRICAO ==="
    )
    client = _FakeClient(raw)
    step = VLMStep(url="http://x/v1", model="m")
    monkeypatch.setattr(step, "_client", lambda: client)

    cascade = Cascade(Config(engines=[], expensive_step_vetoes=False), steps=[step])
    r = cascade.extract(pdf_scanned)

    assert r.step == "vlm"
    assert "CERTIDAO" in r.text
    assert "O usuário deseja" not in r.text
    assert "Elementos identificados" not in r.text
    assert client.calls == ["http://x/v1/chat/completions"]


def test_a_failed_vlm_batch_does_not_sink_the_document(pdf_scanned, monkeypatch):
    class Explode(_FakeClient):
        def post(self, url, **kwargs):
            raise RuntimeError("endpoint is down")

    step = VLMStep(url="http://x/v1", model="m")
    monkeypatch.setattr(step, "_client", lambda: Explode(""))
    cascade = Cascade(Config(engines=[], expensive_step_vetoes=False), steps=[step])
    r = cascade.extract(pdf_scanned)
    assert r.empty
    assert any("no batch answered" in a.reason for a in r.attempts)


def test_a_failed_docling_becomes_a_refused_attempt(pdf_scanned, monkeypatch):
    """A remote step never brings the cascade down — it becomes a reason."""

    class Explode:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, *a, **k):
            raise RuntimeError("connection refused")

    step = DoclingStep(url="http://docling:5001")
    monkeypatch.setattr(step, "_client", Explode)
    cascade = Cascade(Config(engines=[], expensive_step_vetoes=False), steps=[step])
    r = cascade.extract(pdf_scanned)
    assert any("connection refused" in a.reason for a in r.attempts)


def test_the_vlm_body_carries_the_model_and_the_budget(pdf_scanned, monkeypatch):
    """The budget is PER PAGE and multiplied by the batch.

    With a fixed per-batch ceiling, the last pages came back truncated.
    """
    captured: dict = {}

    class Capture(_FakeClient):
        def post(self, url, **kwargs):
            captured.update(kwargs.get("json") or {})
            return _FakeResponse({"choices": [{"message": {"content": "text"}}]})

    step = VLMStep(
        url="http://x/v1", model="my-ocr-0.9b", images_per_batch=1, max_tokens_per_page=1500
    )
    monkeypatch.setattr(step, "_client", lambda: Capture(""))
    Cascade(Config(engines=[], expensive_step_vetoes=False), steps=[step]).extract(pdf_scanned)

    assert captured["model"] == "my-ocr-0.9b"
    assert captured["max_tokens"] == 1500
    # The image travels as a data URI, never as a file path.
    content = captured["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert json.dumps(captured)  # the body is serialisable


# ── local Docling: the same engine, no network ───────────────────────────


def test_missing_local_docling_becomes_a_refused_attempt(pdf_scanned):
    """Without the library the step goes inert, and says how to install it."""
    from autosxtract.steps.docling_local import LocalDoclingStep

    step = LocalDoclingStep()
    ok, reason = step.available()
    if ok:  # pragma: no cover — only when the [docling] extra is installed
        pytest.skip("docling installed on this machine")
    assert "docling" in reason
    cascade = Cascade(Config(engines=[], expensive_step_vetoes=False), steps=[step])
    r = cascade.extract(pdf_scanned)
    assert any(a.step == "docling_local" and not a.accepted for a in r.attempts)
