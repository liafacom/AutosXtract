"""The context a step is given, and what a step gives back.

A step is one attempt at extracting the document. It receives a
``DocumentContext``, returns a ``Candidate`` when it produced acceptable text
and ``None`` when it did not — and, in returning ``None``, it leaves a record of
**why**.

**This is the library's second extension point** (the first is engines). A new
step is a class with one method:

    class MyStep:
        name = "my_step"

        def run(self, ctx: DocumentContext) -> StepResult:
            ...

and it joins the cascade through ``Cascade(steps=[...])``. Nothing else changes.

The contract it satisfies is ``interfaces.Step``, and the one it is handed is
``interfaces.DocumentContext``. Annotating against those rather than against
``Context`` is what makes the sentence above true rather than aspirational: a
step written to the protocol can be exercised over a thirty-line fake, with no
PDF, no PyMuPDF and no engine installed.

``Context`` is the implementation the cascade builds. It exists so the whole
cascade pays **once** for what is expensive and shared: opening the PDF, reading
the page profile, rasterising. A step that rasterises on its own is not wrong,
it is paying twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from autosxtract.config import Config
from autosxtract.interfaces import DocumentContext, Renderer, Step, Tokenizer
from autosxtract.pdf.pages import without_text as _pages_without_text
from autosxtract.pdf.profile import PageProfile
from autosxtract.pdf.profile import profile as _pdf_profile
from autosxtract.pdf.render import render as _rasterise
from autosxtract.types import Attempt, Candidate

#: ``Step`` and ``DocumentContext`` are re-exported from here because this is
#: where whoever writes a step arrives; they are *defined* in
#: ``autosxtract.interfaces``, next to every other contract in the library, so
#: that the list of extension points can be read in one sitting.
__all__ = ["Context", "DocumentContext", "Step", "StepResult"]


@dataclass
class Context:
    """The document being processed and everything already learned about it.

    Mutable on purpose: it is the blackboard where steps leave what they found.
    The readings recorded here — including the **refused** ones — feed the
    consensus and agreement gates, which cost nothing precisely because the
    information is already in hand when the decision arrives.

    Its two collaborators arrive as constructor arguments rather than as
    module-level imports, and both defaults are the concrete objects that were
    hard-wired here before. The point is not configurability for its own sake:
    it is that rasterising and tokenising are the two things a step cannot avoid
    touching, so they were the two that made a step impossible to test without a
    real PDF and the Brazilian stamp patterns.
    """

    pdf_bytes: bytes
    config: Config
    identifier: str = ""

    #: How pages become pixels. ``pdf.render.render`` by default; anything
    #: satisfying ``interfaces.Renderer`` otherwise.
    renderer: Renderer = field(default=_rasterise, repr=False)
    #: What counts as a word. ``None`` means "the stamp stripper built from
    #: ``config.stamps``", which is resolved per call rather than in the
    #: constructor: the patterns belong to the configuration, and freezing them
    #: here would make a later ``config`` change silently ineffective.
    tokenizer: Tokenizer | None = field(default=None, repr=False)

    # Filled on demand; nobody reads these directly.
    _profile: PageProfile | None = field(default=None, repr=False)
    _pages_without_text: list[int] | bool | None = field(default=False, repr=False)
    _render_cache: dict[tuple, list[bytes]] = field(default_factory=dict, repr=False)

    #: How many useful words each engine read — including the refused ones. It
    #: is the consensus gate's vote.
    readings: dict[str, int] = field(default_factory=dict)
    #: The text each engine produced, for the agreement gate.
    texts: dict[str, str] = field(default_factory=dict)
    #: What the orientation fix did, or why it could not run. Empty means it was
    #: never asked. A step copies it into its details so the record answers
    #: "was this page turned, and by how much?" — a question that used to have
    #: no answer either way, because the degrees were discarded at the call site
    #: and an unavailable OSD returned the image untouched with no note.
    orientation: dict = field(default_factory=dict)
    _orientation_ready: bool | None = field(default=None, repr=False)

    @property
    def profile(self) -> PageProfile:
        """What the page has drawn on it. Read once per document."""
        if self._profile is None:
            self._profile = _pdf_profile(self.pdf_bytes)
        return self._profile

    @property
    def pages_without_text(self) -> list[int] | None:
        """Indices of pages with no native text; ``None`` if unreadable."""
        if self._pages_without_text is False:
            self._pages_without_text = _pages_without_text(self.pdf_bytes)
        return self._pages_without_text  # type: ignore[return-value]

    def images(self, *, indices: list[int] | None = None) -> list[bytes]:
        """Rasterised pages, cached by the combination of parameters.

        Two engines on the same document receive exactly the same pixels —
        which is what makes the comparison between them evidence rather than
        preprocessing noise.
        """
        cfg = self.config
        # ``if indices is not None``, never ``if indices``. An empty list is a
        # legitimate request that renders NOTHING, and it is falsy — so it used
        # to hash to the same key as "render every page" and then poison it: the
        # next ``images()`` on that document returned [] for the life of the
        # context, every OCR step reported "no page rasterised", and the
        # provenance blamed the engines.
        key = (
            cfg.dpi,
            cfg.grayscale,
            cfg.max_pages,
            tuple(indices) if indices is not None else None,
        )
        if key not in self._render_cache:
            images = self.renderer(
                self.pdf_bytes,
                dpi=cfg.dpi,
                max_pages=cfg.max_pages,
                grayscale=cfg.grayscale,
                indices=indices,
            )
            if cfg.fix_orientation:
                images = self._upright(images, indices)
            self._render_cache[key] = images
        return self._render_cache[key]

    def _upright(self, images: list[bytes], indices: list[int] | None) -> list[bytes]:
        """Turn sideways pages upright, and leave a record either way.

        The availability check runs **once per document**, not once per page: it
        starts a process to read Tesseract's version, and paying that per page of
        a 64-page scan would cost more than the OSD it guards.
        """
        from autosxtract.pdf import orientation

        if self._orientation_ready is None:
            ok, reason = orientation.available()
            self._orientation_ready = ok
            if not ok:
                # The one place this must not do is nothing. An operator who
                # asked for the correction and did not get it has to find out
                # from the record, not from the text being worse than expected.
                self.orientation["unavailable"] = reason
        if not self._orientation_ready:
            return images

        turned: list[bytes] = []
        rotated: dict[int, int] = {}
        for n, image in enumerate(images):
            fixed, degrees = orientation.fix(image)
            turned.append(fixed)
            if degrees:
                rotated[indices[n] if indices is not None else n] = degrees
        if rotated:
            self.orientation.setdefault("rotated", {}).update(rotated)
        return turned

    def replace_bytes(self, new_bytes: bytes) -> None:
        """Swap the document being processed — used by the unwrap step.

        It invalidates the derived caches: the profile, the pages and the
        renders belonged to the envelope, not to the payload that came out of
        it. Forgetting this would make the following steps measure the wrong
        file.
        """
        self.pdf_bytes = new_bytes
        self._profile = None
        self._pages_without_text = False
        self._render_cache.clear()
        # The page numbers in ``rotated`` indexed the envelope's pages, not the
        # payload's. Whether the TOOL is available does not change with the
        # bytes, so ``_orientation_ready`` survives.
        self.orientation.pop("rotated", None)

    def best_text(self) -> str:
        """The longest text any step has produced for this document.

        It is what the late steps use as "what we already have" — screening to
        decide whether it is a card, the vetoes to decide whether escalating is
        worth it. Volume is enough here: the fine quality choice belongs to the
        final contest, and anticipating it would create a second competing
        criterion.
        """
        return max(self.texts.values(), key=len, default="")

    def record_reading(self, engine: str, text: str) -> None:
        """Note what an engine read, whether it was accepted or not."""
        from autosxtract.quality.stamp import default

        self.texts[engine] = text
        self.readings[engine] = (self.tokenizer or default(self.config.stamp_patterns())).count(
            text
        )


@dataclass(frozen=True)
class StepResult:
    """What a step returns: the verdict and the text, which are distinct things.

    The distinction fixes the costliest defect of the naive cascade. A step may
    have produced text **and** been refused — and that text cannot be thrown
    away: if no later step does better, it is still the best reading the
    document has. Measured on a real archive, discarding it left 682 documents
    with zero characters while the PDF had a text layer.

    That is why ``candidate`` is filled in even when ``attempt.accepted`` is
    false: the verdict decides whether the cascade **stops**; the candidate
    enters the contest regardless.
    """

    attempt: Attempt
    candidate: Candidate | None = None

    @property
    def accepted(self) -> bool:
        return self.attempt.accepted
