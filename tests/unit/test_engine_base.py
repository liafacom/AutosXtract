"""The base engine's contract with the document, exercised on fake engines.

``OCREngine.transcribe`` is what every engine inherits, and it decides two
things the rest of the library cannot recover from if they are wrong: whether a
page that blew up sinks the document, and whether "read nothing" is reported as
the same fact as "could not be reached". Both are pinned here with engines of
ten lines, so nothing is measured except the base class.
"""

from __future__ import annotations

from autosxtract.engines.base import OCREngine


class FlakyEngine(OCREngine):
    """Fails on the second page — the case that must not sink the document."""

    name = "flaky"

    def available(self):
        return True, "fake"

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        if image == b"bad":
            raise RuntimeError("unreadable page")
        return "content", 90.0


def test_a_bad_page_does_not_sink_the_document():
    t = FlakyEngine().transcribe([b"good", b"bad", b"good"], parallelism=1)
    assert t is not None
    assert t.pages_sent == 3
    assert t.pages_answered == 2
    assert not t.complete  # the caller must be able to see the hole
    # And the hole says WHY it is there.
    assert any("unreadable page" in f for f in t.failures)


def test_a_wholly_failed_document_says_the_engine_failed():
    """ "Read nothing" and "could not be reached" are different facts.

    They look identical in the text, and only one of them is an emergency. This
    used to come back as ``None``, which the step reported as "engine returned
    no text" — the DOCUMENT blamed for the ENGINE being down. That is how a dead
    worker degrades an archive in silence.
    """
    t = FlakyEngine().transcribe([b"bad"], parallelism=1)
    assert t is not None
    assert t.pages_answered == 0
    assert t.failures == ["RuntimeError: unreadable page"]


class _BlankEngine(OCREngine):
    """Reads every page fine, and every page is genuinely empty."""

    name = "blank"

    def _load(self):
        return object()

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        return "", 0.0


def test_pages_that_are_simply_empty_still_return_none():
    """The other side of the distinction: nothing failed, there is nothing
    there. That IS an answer about the document, and it must not be dressed up
    as an engine failure."""
    t = _BlankEngine().transcribe([b"page"], parallelism=1)
    assert t is not None
    assert t.pages_answered == 1
    assert t.failures == []
    assert t.empty


def test_an_exception_with_no_message_still_names_itself():
    """``ConnectionResetError()`` stringifies to "", and a reason nobody can
    read is the same as no reason at all — which is what we are fixing."""

    class _Mute(OCREngine):
        name = "mute"

        def _load(self):
            return object()

        def transcribe_page(self, image: bytes) -> tuple[str, float]:
            raise ConnectionResetError()

    t = _Mute().transcribe([b"page"], parallelism=1)
    assert t is not None
    assert t.failures == ["ConnectionResetError"]


def test_no_pages_returns_none():
    assert FlakyEngine().transcribe([]) is None


# ── engines with a single hardware queue ─────────────────────────────────


def test_apple_engines_declare_a_single_queue():
    """Threads add no throughput there: 1 to 12 threads, constant throughput.

    The declaration is a class attribute, so it is readable — and therefore
    checkable — on any platform. Nothing here needs Apple hardware; what needs
    it is the measurement behind the number.
    """
    from autosxtract.engines.vision import OcrmacEngine, VisionEngine

    assert not VisionEngine.scales_with_threads
    assert not OcrmacEngine.scales_with_threads


def test_cpu_engines_scale():
    from autosxtract.engines.paddle import PaddleEngine

    assert PaddleEngine.scales_with_threads


def test_a_single_queue_ignores_the_requested_parallelism():
    """The engine has the last word: the configurer cannot see the hardware queue."""
    from concurrent.futures import ThreadPoolExecutor

    class SingleQueue(OCREngine):
        name = "single_queue"
        scales_with_threads = False

        def available(self):
            return True, "fake"

        def transcribe_page(self, image):
            return "text", 90.0

    engine = SingleQueue()
    created = []
    original = ThreadPoolExecutor.__init__

    def spy(self, *a, **kw):
        created.append(kw.get("max_workers"))
        return original(self, *a, **kw)

    ThreadPoolExecutor.__init__ = spy
    try:
        engine.transcribe([b"a", b"b", b"c"], parallelism=12)
    finally:
        ThreadPoolExecutor.__init__ = original
    # No pool was opened: with an effective value of 1 the sweep is sequential.
    assert created == []
