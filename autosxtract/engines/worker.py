"""Apple Vision reached over the network — the only way Linux gets it.

**This engine is deliberately NOT in the registry.** ``engine_order`` will never
select it, ``Cascade()`` will never assemble it, and ``Config`` holds no field
that could point at it. It exists only for whoever writes the URL by hand:

    from autosxtract.engines.worker import VisionWorkerEngine
    from autosxtract.steps.ocr import OCRStep

    worker = VisionWorkerEngine(url="unix:/run/vision.sock")
    cascade = Cascade(steps=[NativeStep(), OCRStep(worker), OCRStep(get("paddle"))])

The reason for that severity is the incident this whole library was written
against: the engine resolving 64% of the documents lived behind an SSH tunnel,
and its going down **silently degraded the text** — 488 documents re-extracted
down the worse path, 28,239 characters lost, discovered only because somebody
checked. A remote step nobody declared must not exist.

Why it exists at all is a different measurement, and it is the one that decides
the Linux cascade. Over 60 documents rendered identically, PP-OCRv6 against
Vision:

    MODEL              TIME (60 docs)   ENTITIES vs VISION
    ------------------------------------------------------
    PP-OCRv6 tiny         44.0 s        -21
    PP-OCRv6 small        92.3 s        not measured
    PP-OCRv6 medium      233.6 s          0  (ties, 5x slower)
    Apple Vision         ~27.6 s          —

"Entity" means a well-formed CNJ, CPF, CNPJ or date — a case number broken into
four pieces counts zero, not four. The tiny reads the same VOLUME as Vision
(13,202 words against 13,200): it does not read less, **it gets the digits
wrong**, which is the worst way to fail for whoever consumes the output. In CPU,
no model replaces Apple Vision without losing something that matters.

So on Linux there are two honest options, and the choice belongs to whoever
deploys: pay PP-OCRv6's digit errors, or point this engine at a Mac. What is not
an option is not knowing which one is happening — hence
:meth:`available`, which reports the reason in words, and the fact that the
worker's absence degrades to the local cascade LOUDLY, in the provenance.

Requires ``httpx``: ``pip install 'autosxtract[remote]'``.
"""

from __future__ import annotations

import threading

from autosxtract.engines.base import OCREngine
from autosxtract.types import Line, Page


class VisionWorkerEngine(OCREngine):
    """Apple Vision running on another machine, one page per request.

    The protocol is the one ``ops/tools/mac_vision_ocr`` serves: ``POST /ocr``
    with the page image as the body, answering
    ``{"texto", "linhas", "confianca_media"}``. Any worker honouring that shape
    fits — the engine knows HTTP, not Apple.
    """

    name = "vision_worker"
    extra = "remote"
    #: Unlike the in-process Vision engine, this one DOES gain from a little
    #: parallelism — the network round-trip overlaps with the model's work on
    #: the far side. How much is a property of the worker on the other end, so
    #: it is a constructor argument, not a constant: see ``page_parallelism``.
    scales_with_threads = True

    def __init__(
        self,
        *,
        url: str,
        timeout: float = 60.0,
        language: str = "pt-BR",
        level: str = "accurate",
        correction: bool = True,
        max_concurrent: int = 12,
        page_parallelism: int = 2,
    ) -> None:
        """``url`` is required and has no default — see the module docstring.

        ``unix:/path/to.sock`` talks to the worker over a Unix socket. That form
        exists because in the environment this came from the container is walled
        off from the host by a firewall — it reaches neither the bridge gateway
        nor the external IP — and a socket in a bind-mounted directory crosses
        the boundary without touching firewall, sshd or network at all.

        ``correction`` defaults to **on**, and the reason is a reversal worth
        recording. Vision's linguistic post-processing does mangle judicial text
        — it turns "TJMS" into "tums" — and an isolated measurement on 60
        documents said turning it off was better (+4 anchors). Turning it off
        also more than doubles the worker's throughput, 2.5 -> 5.4 pages/s.

        It was tried in production over 935 documents and **reverted**. The
        slightly worse text fails the acceptance gate more often, so 102
        documents fell to worse engines (84 to ONNX, at 75% anchor preservation
        against Vision's 100%) and the balance closed at -227 anchors and -4,981
        characters. The three worst-hit documents lost 93, 73 and 52 anchors —
        whole CNJ case numbers. The isolated measurement had looked only at
        Vision's own output, never at what the cascade does with worse text.

        ``max_concurrent`` caps whole DOCUMENTS in flight from this process. It
        began at 4 to contain a segmentation fault that later turned out to be
        PyMuPDF under concurrency — fixed in ``pdf.lock`` — so the 4 was a scar
        from a problem that no longer exists. Measured against a real worker,
        throughput does not saturate there: 3.10 req/s at 4, 3.14 at 8, 3.49 at
        12, 3.70 at 16, still climbing. It sits at 12 rather than 16 because the
        worker on the other end is somebody's workstation, not dedicated
        infrastructure. Zero disables the cap.

        ``page_parallelism`` is pages in flight within ONE document, and the two
        multiply. The default of 2 is measured — with 4, a 15-page filing
        produced 5 timeouts, because Vision serialises on the macOS side and
        high concurrency inside one document only queues up and runs the clock
        out.

        That measurement describes **one** worker on **one** Mac, which is why
        this is an argument and not a constant. A beefier machine, a different
        Vision generation or a worker that fans out internally moves the number,
        and whoever runs it is the one who can measure it. Raise it and measure:
        ``scripts/compare_engines.py`` reports the cascade's behaviour, not just
        the engine's, which is the difference that has already inverted a
        conclusion here.
        """
        super().__init__()
        if not url:
            raise ValueError("VisionWorkerEngine requires an explicit url")
        self.url = url
        self.timeout = timeout
        self.language = language
        self.level = level
        self.correction = correction
        self.page_parallelism = max(1, page_parallelism)
        self._gate = threading.Semaphore(max_concurrent) if max_concurrent > 0 else None

    # ── loading ──────────────────────────────────────────────────────────
    def _load(self):
        """ONE client, alive for the whole process, shared across threads.

        Not an optimisation — a correctness fix. The earlier version opened
        ``with httpx.Client(..., transport=t)`` per page while reusing the same
        transport object, so leaving the ``with`` closed the connection pool
        other threads were still using: "[Errno 9] Bad file descriptor" on 23
        pages. With a single thread it never showed; it surfaced the moment the
        step moved ahead of the expensive one and saw the archive in parallel.
        ``httpx.Client`` is thread-safe and pools — not closing it per call is
        the correct use.
        """
        import httpx

        if self.url.startswith("unix:"):
            transport = httpx.HTTPTransport(uds=self.url[len("unix:") :])
            base = "http://vision-worker"
        else:
            transport = None
            base = self.url.rstrip("/")
        return httpx.Client(timeout=self.timeout, transport=transport), base

    # ── transcription ────────────────────────────────────────────────────
    def transcribe(self, pages: list[bytes], *, parallelism: int = 4, **kwargs):
        """The document, with the pages in flight held to this engine's number.

        The engine has a say about its own parallelism, because whoever
        configures the cascade does not know what sits on the far side of the
        socket — the base class offers only an all-or-nothing switch, and here
        the honest answer is a number.

        A say, not the last word: ``page_parallelism`` comes from the
        constructor, so whoever deploys can raise it for a worker that takes it.
        A ceiling nobody can lift is a measurement pretending to be a law.
        """
        return super().transcribe(
            pages, parallelism=min(parallelism, self.page_parallelism), **kwargs
        )

    def _request(self, image: bytes) -> dict:
        """One page over the wire, under the documents-in-flight cap."""
        if self._gate is not None:
            self._gate.acquire()
        try:
            return self._post(image)
        finally:
            if self._gate is not None:
                self._gate.release()

    def _post(self, image: bytes) -> dict:
        client, base = self.model
        response = client.post(
            f"{base}/ocr",
            params={
                "lang": self.language,
                "level": self.level,
                "correction": "1" if self.correction else "0",
            },
            content=image,
            headers={"Content-Type": "image/png"},
        )
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, dict) else {}

    def read_page(self, image: bytes) -> Page | None:
        """One page, line by line — when the worker sends the geometry.

        A worker answering ``linhas`` without polygons still transcribes fine;
        what is lost is the containment layers, and the reason shows up in
        ``diagnose`` rather than as silence.

        Confidence arrives on the **0-100** scale — the same one
        ``confianca_media`` uses in ``transcribe_page``, and the same one
        ``Transcription.mean_confidence`` carries — and ``Line`` wants 0-1, so it
        is divided here. This is the one line in the file that has to be right:
        without the division every line scores 40 to 95 on a 0-1 scale, so
        nothing is ever ``illegible`` or ``suspect``, ``_looks_like_scribble``
        never fires, the structural signature rule goes dead, and Layer 2 can
        never beat an original that already "scores" 95. The engine keeps
        working and every threshold below it stops meaning anything.
        """
        body = self._request(image)
        rows = body.get("linhas")
        if not isinstance(rows, list) or not rows:
            return None
        lines: list[Line] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = (row.get("texto") or "").strip()
            if not text:
                continue
            lines.append(
                Line(
                    text=text,
                    score=float(row.get("confianca") or 0.0) / 100.0,
                    poly=_polygon(row.get("poligono")),
                )
            )
        if not lines:
            return None
        return Page(
            lines=lines,
            width=float(body.get("largura") or 0.0),
            height=float(body.get("altura") or 0.0),
        )

    def transcribe_page(self, image: bytes) -> tuple[str, float]:
        """The simple contract, for a worker that answers text and nothing else.

        It must NOT delegate to ``read_page``: the base class already tried that
        one and only calls this because it came back empty, so reusing it would
        put a third request on the wire for every page. Costing one round-trip
        per page is the point of this engine; costing three is a regression
        nobody would see except in the worker's log.
        """
        body = self._request(image)
        return (body.get("texto") or ""), float(body.get("confianca_media") or 0.0)

    # ── availability ─────────────────────────────────────────────────────
    def available(self) -> tuple[bool, str]:
        """``(can_run, reason)`` — the client builds, the worker is not pinged.

        Reaching out here would make ``diagnose`` and every cascade assembly pay
        a network round-trip, and it would still say nothing about the worker
        being up when the page is actually sent. A worker that is down surfaces
        as a refused attempt on the document, with the reason, which is where it
        can be acted on.
        """
        if self.model is None:
            return False, f"{self.name} unavailable: {self._reason or 'did not load'}"
        return True, f"ok ({self.url})"


def _polygon(raw) -> tuple[tuple[float, float], ...] | None:
    """``[[x, y], ...]`` from the worker into the shape ``Line`` expects.

    Anything malformed becomes ``None`` — an engine without geometry, which the
    layers already handle — rather than an exception. A bad polygon is not worth
    losing the page's text over.
    """
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    points: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            points.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            return None
    return tuple(points)
