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
        key = (cfg.dpi, cfg.grayscale, cfg.max_pages, tuple(indices) if indices else None)
        if key not in self._render_cache:
            images = self.renderer(
                self.pdf_bytes,
                dpi=cfg.dpi,
                max_pages=cfg.max_pages,
                grayscale=cfg.grayscale,
                indices=indices,
            )
            if cfg.fix_orientation:
                from autosxtract.pdf.orientation import fix

                images = [fix(i)[0] for i in images]
            self._render_cache[key] = images
        return self._render_cache[key]

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
