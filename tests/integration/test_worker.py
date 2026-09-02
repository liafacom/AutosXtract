"""The remote Vision worker — the only way a Linux box gets Apple Vision.

Two things are pinned here, and they pull in opposite directions on purpose.

The engine must be REACHABLE: on 60 documents PP-OCRv6 tiny loses 21 entities
(CNJ, CPF, CNPJ, dates) against Vision, reading the same volume of words — it
does not read less, it gets the digits wrong. On CPU there is no substitute.

And it must be UNREACHABLE BY ACCIDENT: the previous architecture kept the
engine that resolved 64% of documents behind a tunnel, and its going down
silently degraded the text. Whoever wants the network writes the URL.
"""

from __future__ import annotations

import json

import pytest

from autosxtract.cascade import Cascade, engine_order
from autosxtract.engines import base as engines
from autosxtract.engines.worker import VisionWorkerEngine

# ── it cannot arrive on its own ──────────────────────────────────────────


def test_the_worker_is_not_in_the_registry():
    """Not registered means ``engine_order`` can never choose it."""
    assert "vision_worker" not in [i.name for i in engines.registered()]
    assert "vision_worker" not in engine_order()
    assert "vision_worker" not in Cascade().names


def test_the_url_is_mandatory():
    with pytest.raises(ValueError, match="url"):
        VisionWorkerEngine(url="")


# ── the protocol ─────────────────────────────────────────────────────────


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return json.loads(json.dumps(self._body))


class _Client:
    """Stands in for ``httpx.Client``, recording what was sent."""

    def __init__(self, body: dict) -> None:
        self.body = body
        self.calls: list[dict] = []

    def post(self, url, *, params, content, headers):
        self.calls.append({"url": url, "params": params, "content": content})
        return _Response(self.body)


def _engine(body: dict, **kwargs) -> tuple[VisionWorkerEngine, _Client]:
    engine = VisionWorkerEngine(url="http://mac:8099", **kwargs)
    client = _Client(body)
    engine._model = (client, "http://mac:8099")
    return engine, client


def test_it_reads_lines_with_geometry():
    """Geometry is what enables the containment layers; it must survive."""
    engine, _ = _engine(
        {
            "linhas": [
                {
                    "texto": "Processo 0010650-62.2001",
                    "confianca": 95.0,
                    "poligono": [[10, 20], [200, 20], [200, 40], [10, 40]],
                },
                {"texto": "   ", "confianca": 10.0},
            ],
            "largura": 1200,
            "altura": 1600,
        }
    )
    page = engine.read_page(b"png")
    assert page is not None
    # The blank line is dropped, not counted against the confidence.
    assert len(page.lines) == 1
    assert page.lines[0].poly == ((10.0, 20.0), (200.0, 20.0), (200.0, 40.0), (10.0, 40.0))
    assert page.text == "Processo 0010650-62.2001"
    assert (page.width, page.height) == (1200.0, 1600.0)


def test_confidence_is_converted_to_the_zero_to_one_scale():
    """``Line`` wants 0-1. Forgetting makes every line look perfect and the
    layer thresholds inert — which is a silent failure, the worst kind.

    The input has to be on the protocol's scale for this to prove anything. The
    earlier version fed ``0.5`` — already 0-1 — and asserted ``0.5`` back, so it
    passed just as happily with no conversion at all: the assertion was an
    identity, and the one line it existed to pin was free to be deleted.
    """
    engine, _ = _engine({"linhas": [{"texto": "a", "confianca": 50.0}]})
    page = engine.read_page(b"png")
    assert page is not None
    assert page.lines[0].score == 0.5
    assert page.mean_confidence == 50.0


def test_a_worker_without_geometry_still_transcribes():
    """``read_page`` returning ``None`` costs the layers, not the extraction."""
    engine, client = _engine({"texto": "conteudo lido", "confianca_media": 88.0})
    assert engine.read_page(b"png") is None
    assert engine.transcribe_page(b"png") == ("conteudo lido", 88.0)
    # And ``transcribe_page`` does not re-ask what ``read_page`` already asked:
    # one request each, never three for the same page.
    assert len(client.calls) == 2


def test_a_malformed_polygon_does_not_lose_the_text():
    engine, _ = _engine(
        {"linhas": [{"texto": "vale", "confianca": 90.0, "poligono": [[1, 2], "lixo"]}]}
    )
    page = engine.read_page(b"png")
    assert page is not None
    assert page.lines[0].poly is None
    assert page.text == "vale"


def test_it_posts_to_the_worker_ocr_endpoint():
    engine, client = _engine({"texto": "x", "confianca_media": 1.0})
    engine.transcribe_page(b"png")
    assert client.calls[0]["url"] == "http://mac:8099/ocr"
    assert client.calls[0]["params"]["lang"] == "pt-BR"


# ── the lessons that cost an incident each ───────────────────────────────


def test_pages_in_flight_default_to_the_measured_number():
    """With 4, a 15-page filing produced 5 timeouts on the worker; with 2 it
    keeps up. The engine holds the cascade to its own number by default."""
    engine, client = _engine({"linhas": [{"texto": "x", "confianca": 90.0}]})
    assert engine.page_parallelism == 2
    engine.transcribe([b"a", b"b", b"c", b"d"], parallelism=8)
    # One round-trip per page and no more: the whole point of the engine.
    assert len(client.calls) == 4
    # Sorted, and not in the order they were written. With page_parallelism == 2
    # the pages are DISPATCHED by two threads, so the order they reach the fake
    # client in belongs to the scheduler, not to the document. Asserting the
    # sequence here pinned thread interleaving and went red on a runner that
    # happened to deliver [a, c, b, d] — a green suite that depended on luck.
    #
    # What ``transcribe`` promises is that the RESULT comes back in input order,
    # which it keeps with ``map``; that promise is pinned where it can be
    # checked honestly, in test_cascade.py::test_page_order_is_preserved.
    assert sorted(c["content"] for c in client.calls) == [b"a", b"b", b"c", b"d"]


def test_documents_in_flight_are_capped():
    """The worker on the other end is somebody's workstation, not dedicated
    infrastructure — throughput was still climbing at 16 when 12 was chosen."""
    assert VisionWorkerEngine(url="http://mac")._gate is not None
    assert VisionWorkerEngine(url="http://mac", max_concurrent=0)._gate is None


def test_linguistic_correction_is_on_by_default():
    """Turning it off was tried in production over 935 documents and reverted:
    -227 anchors and 102 documents falling to worse engines."""
    engine, client = _engine({"texto": "x", "confianca_media": 1.0})
    engine.transcribe_page(b"png")
    assert client.calls[0]["params"]["correction"] == "1"


def test_a_unix_socket_url_is_accepted():
    """The container that this came from reaches no host IP; a bind-mounted
    socket crosses the boundary without firewall, sshd or network.

    The only test in this file that reaches ``_load``, and therefore the only
    one that needs ``httpx``: every other one hands the engine a fake client.
    ``httpx`` ships in the ``remote`` extra, not in ``dev`` — without the guard
    this passed on the maintainer's machine and failed on a clean install, which
    is the same class of accident the engine itself exists to prevent.
    """
    pytest.importorskip("httpx", reason="the [remote] extra: available() builds the client")
    engine = VisionWorkerEngine(url="unix:/run/vision.sock")
    assert engine.available()[0]
    assert "/run/vision.sock" in engine.available()[1]


# ── a dead worker must not look like a blank page ────────────────────────


def test_an_unreachable_worker_is_reported_as_a_failure_not_as_empty():
    """The whole reason this engine is opt-in, in one test.

    A Mac that stops serving and a sheet with nothing on it produce the same
    empty string. Reporting the second when the truth is the first is how the
    previous architecture re-extracted 488 documents down the worse path and
    lost 28,239 characters without anyone noticing.
    """
    from autosxtract.config import Config
    from autosxtract.steps.base import Context
    from autosxtract.steps.ocr import OCRStep

    class _Dead(VisionWorkerEngine):
        def _post(self, image: bytes) -> dict:
            raise ConnectionResetError(104, "Connection reset by peer")

    engine = _Dead(url="unix:/run/gone.sock")
    engine._model = (object(), "http://x")

    transcription = engine.transcribe([b"pagina"], parallelism=1)
    assert transcription is not None
    assert transcription.pages_answered == 0
    assert transcription.failures
    assert "ConnectionResetError" in transcription.failures[0]

    # And the step says so, instead of blaming the document.
    step = OCRStep(engine)
    ctx = Context(pdf_bytes=b"", config=Config(), identifier="x")
    ctx.images = lambda **kw: [b"pagina"]  # type: ignore[method-assign]
    result = step.run(ctx)
    assert not result.attempt.accepted
    assert "engine failed" in result.attempt.reason
    assert "no text" not in result.attempt.reason


def test_the_page_parallelism_can_be_raised_by_whoever_deploys():
    """The measured 2 describes ONE worker on ONE Mac — it is a default, not a
    law. A beefier machine, another Vision generation or a worker that fans out
    internally moves the number, and only whoever runs it can measure that.

    A ceiling nobody can lift is a measurement pretending to be a law, and it
    would make the library unusable on hardware it was never measured on.
    """
    engine, client = _engine({"linhas": [{"texto": "x", "confianca": 90.0}]}, page_parallelism=6)
    assert engine.page_parallelism == 6
    engine.transcribe([b"a", b"b", b"c"], parallelism=6)
    assert len(client.calls) == 3


def test_it_never_goes_below_one():
    """Zero or a negative would deadlock the pool rather than serialise it."""
    assert VisionWorkerEngine(url="http://mac", page_parallelism=0).page_parallelism == 1
    assert VisionWorkerEngine(url="http://mac", page_parallelism=-3).page_parallelism == 1


def test_the_cascade_can_still_ask_for_less():
    """The engine's number is a ceiling on ITS side, not a floor: a cascade
    tuned down for a small machine is obeyed."""
    engine, client = _engine({"linhas": [{"texto": "x", "confianca": 90.0}]}, page_parallelism=8)
    engine.transcribe([b"a", b"b"], parallelism=1)
    assert len(client.calls) == 2
