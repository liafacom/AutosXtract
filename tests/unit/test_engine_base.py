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


# ── the page index has to line up with the images (CLAUDE.md §15) ────────


class _GeometryEngine(OCREngine):
    """Answers in DETAIL, and raises on whichever page it is told to."""

    name = "geometry"

    def __init__(self, bad: bytes = b"") -> None:
        super().__init__()
        self.bad = bad

    def available(self):
        return True, "fake"

    def read_page(self, image: bytes):
        from autosxtract.types import Line, Page

        if image == self.bad:
            raise RuntimeError("refused the image")
        return Page(lines=[Line(text=image.decode(), score=0.9)], width=100.0, height=100.0)

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        raise AssertionError("read_page answered; the simple contract must not be reached")


def test_detailed_pages_are_dropped_when_one_page_raised():
    """``Transcription.pages`` is filled only when EVERY page answered in detail.

    The comparison used to be against the pages that ANSWERED, not against the
    pages that were SENT. A page that raises is counted in neither, so the
    equality survived the hole and the list came back compacted: three entries
    for a five-page document. ``layers.apply`` pairs that list positionally
    against the images, so page 3's line geometry was cropped out of page 2's
    image — the signature detector ran on the wrong sheet and Layer 2 could
    substitute text read from the wrong page into the output.

    Empty is the honest answer: without geometry the layers are skipped and the
    reason reaches the provenance.
    """
    t = _GeometryEngine(bad=b"p2").transcribe([b"p1", b"p2", b"p3"], parallelism=1)
    assert t is not None
    assert (t.pages_sent, t.pages_answered) == (3, 2)
    assert t.pages == [], "a compacted page list is worse than none"


def test_detailed_pages_survive_when_every_page_answered():
    """The guard must not throw away a list that IS aligned."""
    t = _GeometryEngine().transcribe([b"p1", b"p2", b"p3"], parallelism=1)
    assert t is not None
    assert [p.text for p in t.pages] == ["p1", "p2", "p3"]


def test_page_texts_keep_the_slot_of_a_page_that_failed():
    """``text`` cannot be split back into pages; ``page_texts`` can be indexed.

    A page that failed, and a page that legitimately read nothing, both leave no
    trace in the joined text — so per-page routing cannot use it to put an OCR'd
    page back in its place among the native ones. One slot per page SENT is what
    makes that possible, and a dropped slot is how a mixed PDF silently comes
    back with the attachment and none of the pages around it.
    """
    t = _GeometryEngine(bad=b"p2").transcribe([b"p1", b"p2", b"p3"], parallelism=1)
    assert t is not None
    assert t.page_texts == ["p1", "", "p3"]
    assert len(t.page_texts) == t.pages_sent


def test_page_texts_keep_the_slot_of_a_page_that_read_nothing():
    """A page that ANSWERED and was blank keeps its slot too.

    This is the realistic case — a blank sheet in the middle of a mixed filing —
    and it takes a different branch from the raising one: the page is counted in
    ``pages_answered`` and contributes nothing to ``text``. Dropping its slot
    here shifts every later page by one, and per-page routing then files the
    OCR'd pages under the wrong page numbers.
    """

    class Blanks(OCREngine):
        name = "blanks"

        def available(self):
            return True, "fake"

        def transcribe_page(self, image: bytes) -> tuple[str, float]:
            return ("" if image == b"p2" else image.decode()), 90.0

    t = Blanks().transcribe([b"p1", b"p2", b"p3"], parallelism=1)
    assert t is not None
    assert t.pages_answered == 3
    assert t.page_texts == ["p1", "", "p3"]
