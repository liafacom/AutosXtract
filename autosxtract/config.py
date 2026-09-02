"""Cascade configuration — every number that governs it, in one place.

The defaults are not guesses: each is annotated with the measurement that fixed
it. Changing them is legitimate; changing them without measuring is what this
file tries to prevent.

No field points at a network. There is no host, port, URL or credential — the
library runs entirely on the local machine, by architectural decision.

Two fields point at DATA rather than at a number — ``lexicon`` and ``patterns``
— and that is the seam for another corpus: the vocabulary a line is judged
against, and the regexes everything is matched with. Neither requires editing a
line of this library.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from autosxtract import resources
from autosxtract.patterns import PatternSet, resolve


class Config(BaseModel):
    """The cascade's runtime parameters."""

    model_config = {"frozen": True, "extra": "forbid", "arbitrary_types_allowed": True}

    # ── step order ───────────────────────────────────────────────────────
    engines: list[str] | None = Field(
        default=None,
        description=(
            "Explicit order of OCR engines. ``None`` lets the platform decide: "
            "Vision first on Apple hardware, PP-OCRv6 elsewhere."
        ),
    )
    use_native: bool = Field(
        default=True,
        description=(
            "Read the PDF's text layer before any OCR. Measured: 31% of a real "
            "archive's documents are resolved here, at 13.4 ms — free against "
            "the ~400 ms of any OCR."
        ),
    )

    # ── rasterising ──────────────────────────────────────────────────────
    dpi: int = Field(
        default=150,
        ge=36,
        le=600,
        description=(
            "Render resolution for OCR. 150 is the minimum that preserves "
            "numeric anchors: at 100 DPI preservation falls to 85.5%, losing "
            "dates and tax numbers in 35 of 60 documents."
        ),
    )
    grayscale: bool = Field(
        default=True,
        description=(
            "Rasterise in a single channel. The resolution does not change — "
            "only chrominance is discarded, and a scanned document carries "
            "almost none. It saves ~84 ms per document in the encoder."
        ),
    )
    max_pages: int = Field(
        default=64, ge=1, description="Ceiling on rasterised pages per document."
    )

    # ── acceptance gate ──────────────────────────────────────────────────
    min_useful_words: int = Field(
        default=12,
        ge=0,
        description=(
            "Floor of alphabetic words outside the stamp. Below this, what is "
            "left is not content. Derived from an audit of 1,339 documents: 403 "
            "had text that looked fine and was only the digital signature stamp."
        ),
    )
    min_chars_per_page: int = Field(
        default=200,
        ge=0,
        description="Minimum density. A page of text yields hundreds of characters.",
    )
    min_confidence: float = Field(
        default=70.0,
        ge=0.0,
        le=100.0,
        description=(
            "Engine confidence floor. It does NOT arbitrate quality — measured "
            "on 60 audited documents, OCR confidence does not separate a good "
            "reading from an unsafe one. It only guards against degenerate "
            "output."
        ),
    )
    min_score: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Below this text-quality score the step is refused.",
    )
    native_accept_score: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description=(
            "Score from which the native text ends the cascade without paying "
            "for OCR. It comes with the coverage caveat: a high score describes "
            "the text that came out, not the fraction of the page left behind."
        ),
    )

    # ── gates between steps ──────────────────────────────────────────────
    coverage_gate: bool = Field(
        default=True,
        description=(
            "Refuse the native text when there is a large image in a region "
            "with no text. In a filing that embeds an official letter as an "
            "image, the native text is flawless and the attachment — the actual "
            "content — is never read."
        ),
    )
    consensus_gate: bool = Field(
        default=True,
        description=(
            "Declare the page empty when independent engines agree there is no "
            "content. One dissenter is enough to escalate."
        ),
    )
    agreement_gate: bool = Field(
        default=True,
        description=(
            "Stop when two engines read THE SAME THING — proof that the reading "
            "is complete, not that the page is short."
        ),
    )
    min_agreement: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description=(
            "Vocabulary Jaccard from which two readings agree. Calibrated on 24 "
            "real escalations: 13 cases landed between 0.00 and 0.48 and 11 "
            "between 0.65 and 0.80 — the threshold sits in the gap."
        ),
    )
    per_page_routing: bool = Field(
        default=True,
        description=(
            "In a mixed PDF, OCR only the pages without native text. Measured: "
            "of the 419 pages that went through OCR on a real case file, 54 "
            "(12.9%) already had text."
        ),
    )
    fix_orientation: bool = Field(
        default=True,
        description=(
            "Detect and correct a sideways page BEFORE OCR, with Tesseract's "
            "OSD (needs the [veto] extra; without it the correction is skipped "
            "and the reason goes to the provenance and to diagnose). On by "
            "default because a rotated page is read badly by every engine, and "
            "everything downstream then judges a bad reading caused by an input "
            "defect it cannot see. UNMEASURED on this project's archive: the "
            "cost is one OSD pass per rasterised page, so a document resolved "
            "by the native text layer pays nothing, and no number here yet says "
            "what it buys. Measure with scripts/compare_engines.py before "
            "relying on it, and turn it off if your scans are known upright."
        ),
    )

    # ── expensive-step gates ─────────────────────────────────────────────
    expensive_step_vetoes: bool = Field(
        default=True,
        description=(
            "Run the five vetoes before a step marked ``expensive``. Measured "
            "on 19 escalated documents: they save 27.2 minutes of the expensive "
            "step and the largest content lost is a 124-character stamp."
        ),
    )
    replacement_gate: bool = Field(
        default=True,
        description=(
            "Submit an expensive step's text to the anchor and coverage gate "
            "before letting it replace what already exists. Length alone gets "
            "both of the costliest cases wrong."
        ),
    )
    veto_engine: str | None = Field(
        default="tesseract",
        description=(
            "The local engine that acts as WITNESS for vetoes 3 to 5. It must "
            "be of a different architecture from those already run — a second "
            "engine of the same family is not independent evidence. ``None`` "
            "turns off the three vetoes that depend on it."
        ),
    )
    veto_max_pages: int = Field(
        default=3,
        ge=1,
        description="Pages the witness reads. Measuring 3 already separates the archive.",
    )
    min_reliable_words: int = Field(
        default=3,
        ge=0,
        description=(
            "Floor of legible words for the witness to declare there IS text. "
            "Measured on 489 documents: below 3 the expensive step yielded at "
            "most 124 characters; from 7 upwards, at least 257. The band is "
            "empty."
        ),
    )
    rebuild_prose: bool = Field(
        default=True,
        description=(
            "Join the lines the OCR broke at each visual line of the page. "
            "Measured: 85% of the lines do not end in punctuation, and without "
            "this the text is a list of fragments, not prose."
        ),
    )

    # ── line containment layers ──────────────────────────────────────────
    #
    # They only work with an engine that exposes line geometry (``read_page``).
    # With the others the cascade records "engine without geometry" and moves
    # on — nothing breaks, there is simply no layer.
    layers: bool = Field(
        default=True,
        description=(
            "Contain stamps, signatures and junk line by line. Measured on 895 "
            "pages: entity recall 0.902 -> 0.921, median CER 0.132 -> 0.129, and "
            "p50 latency FALLS from 298 to 236 ms. 79 pages improve, 4 get "
            "worse (all already bad), clean pages are untouched."
        ),
    )
    layer2: bool = Field(
        default=True,
        description=(
            "Re-read the targets: rotate the vertical line 90 degrees, crop the "
            "dirty line tighter. It costs ~30 ms at p50 and is what recovers the "
            "protocol stamp instead of merely marking it."
        ),
    )
    max_layer2_targets: int = Field(
        default=10,
        ge=0,
        description="Ceiling on re-reads per page — it bounds the latency tail.",
    )
    min_layer2_gain: float = Field(
        default=0.08,
        ge=0.0,
        description=(
            "How far the re-reading's score must beat the original's to replace "
            "the line. Swapping on a tie is noise."
        ),
    )
    lexicon: Any | None = Field(
        default=None,
        description=(
            "The ``Lexicon`` legibility is judged against. ``None`` uses the "
            "built-in one — a floor of legal Portuguese. Building your own from "
            "validated texts is measurably better: with a small lexicon, "
            "correct text falls into ``suspect`` more often (the safe side of "
            "the error, but it escalates pages for nothing)."
        ),
    )
    signature_detector: str | None = Field(
        default=None,
        description=(
            "Path to a YOLO in ONNX for signature detection (Layer 1.5). "
            "``None`` leaves only the structural rule, which always runs. Off "
            "by default because a model trained on a public signature dataset "
            "did NOT transfer: 19% of pages with a detection, most of them "
            "false positives on seals, stamps, logos and QR codes."
        ),
    )
    page_routing: bool = Field(
        default=False,
        description=(
            "Classify the page type (table / stamped_digital / degraded / "
            "normal) and record it in the provenance. It does not change the "
            "extraction — it is a signal for whoever consumes it."
        ),
    )

    # ── parallelism ──────────────────────────────────────────────────────
    #
    # The three fields below accept ``None``, meaning "decide from the machine".
    # That is the default because the same library runs on a 2-core laptop and a
    # 72-core server, and one fixed number serves both badly.
    #
    # An explicit number is OBEYED — whoever knows what they are doing decides.
    # What it is not, is a promise: the measured curve flattens early. On a
    # 2-core machine, 8 threads deliver 1.54 pages/s against 1.68 for 2 threads,
    # with 4x more pages in flight. On 72 cores, going from 4 to 16 threads gains
    # 1.14x.
    engine_options: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Constructor arguments for a SPECIFIC engine, by name. The registry "
            "builds engines with no arguments, so everything their constructors "
            "accept — PP-OCR's tier, the INT8 flag, the thread count, the "
            "preprocessing, the execution providers — was unreachable from an "
            "assembled cascade. A knob that cannot be turned from outside is "
            "not a knob. "
            "``{'paddle': {'quantized': True}}`` asks for INT8 weights; "
            "``{'paddle': {'det': 'small', 'rec': 'medium'}}`` picks a tier. "
            "Different options are a different engine and load their own model."
        ),
    )
    engine_parallelism: dict[str, int] | None = Field(
        default=None,
        description=(
            "Pages in flight for a SPECIFIC engine, by name — the caller's last "
            "word over the engine's own statement about itself. An engine "
            "declares ``scales_with_threads = False`` when it knows a single "
            "hardware queue sits behind it (Apple's Neural Engine serves one "
            "request at a time), and that declaration is a good DEFAULT because "
            "whoever configures the cascade cannot see behind the engine. "
            "It is a bad law: it was measured on one machine, and registered "
            "engines are built with no arguments, so without this there is no "
            "way at all to tune them. ``{'vision': 4}`` overrides one; the "
            "others keep deciding for themselves."
        ),
    )
    page_parallelism: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Threads per document in OCR. ``None`` resolves to "
            "``min(4, cores)``. PyMuPDF is OUTSIDE this count: it is serialised "
            "by a process lock, because it crashes the process under "
            "concurrency (segfault in ``page_get_textpage``). An engine with a "
            "single hardware queue — Apple's — ignores this number and uses 1: "
            "measured from 1 to 12 threads, constant throughput and latency "
            "from 430 ms to 3,492 ms."
        ),
    )
    document_parallelism: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Documents in flight during batch processing. ``None`` resolves to ``min(4, cores)``."
        ),
    )
    concurrency_cap: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Maximum pages in flight across ALL documents of a batch. ``None`` "
            "resolves to ``cores x 2``; ``0`` turns the cap off. It exists "
            "because the product ``documents x pages`` grows without anyone "
            "noticing — 4 x 8 is 32 simultaneous pages, each holding a rendered "
            "image and the model's activations. On a small machine the memory "
            "limit arrives before the CPU limit."
        ),
    )

    # ── domain ───────────────────────────────────────────────────────────
    language: str = Field(
        default="pt-BR",
        description=(
            "Preferred OCR engine language, and the pack of the pattern "
            "catalogue that goes with it. A tag with no bundled pack keeps the "
            "default one — which is what the library did before the catalogue "
            "existed, when the patterns were Portuguese whatever this said."
        ),
    )
    patterns: Any | None = Field(
        default=None,
        description=(
            "The pattern catalogue: a ``PatternSet``, or a path to a TOML file "
            "or a directory of them. It overrides the bundled packs ENTRY BY "
            "ENTRY, so a pack that redefines one stamp inherits the other sixty "
            "patterns and keeps receiving their fixes. ``None`` resolves "
            "``AUTOSXTRACT_PATTERNS``, then the pack for ``language``, then the "
            "neutral base."
        ),
    )
    stamps: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Stamp patterns (regexes) to strip before measuring the extraction. "
            "``None`` takes ``stamp.conformity`` from the catalogue — the "
            "Brazilian court ones, unless a pack replaced them. It stays a field "
            "of its own because it is the override reached for most often: the "
            "stamp survives when the body of the page produces nothing, so it "
            "has to go before the measurement, and saying so should not require "
            "writing a pack."
        ),
    )

    # ── the catalogue ────────────────────────────────────────────────────

    def pattern_set(self) -> PatternSet:
        """The resolved catalogue for this configuration.

        A method rather than a field for the same reason the parallelism knobs
        resolve in a method: the machine that reads the pack may not be the one
        that serialised the configuration, and a path resolved at construction
        would point at a file that is not there.
        """
        return resolve(self.patterns, language=self.language)

    def stamp_patterns(self) -> tuple[str, ...]:
        """The stamp list in force — ``stamps`` if given, the catalogue's if not.

        The one path through which ``stamps`` and the catalogue can disagree,
        and it resolves in favour of the explicit field: whoever named the
        patterns in the configuration meant those.
        """
        return self.stamps if self.stamps else self.pattern_set().patterns("stamp.conformity")

    # ── parallelism resolution ───────────────────────────────────────────
    #
    # Methods, not computed fields: the machine that RESOLVES may not be the one
    # that serialised the configuration. A preset stored in YAML and used in two
    # environments has to give different answers in each.

    def pages_in_flight(self) -> int:
        """Threads per document, already resolved for this machine."""
        if self.page_parallelism is not None:
            return self.page_parallelism
        return resources.default_parallelism()

    def documents_in_flight(self) -> int:
        """Simultaneous documents in a batch, already resolved for this machine."""
        if self.document_parallelism is not None:
            return self.document_parallelism
        return resources.default_parallelism()

    def batch_concurrency(self) -> tuple[int, int]:
        """``(documents, pages)`` already limited by the aggregate cap.

        The cap cuts the PAGES before the DOCUMENTS. That is deliberate:
        reducing documents in flight raises total time predictably, while
        reducing pages per document costs almost nothing — the per-document
        thread curve flattens well before the memory ceiling.
        """
        documents = self.documents_in_flight()
        pages = self.pages_in_flight()
        cap = (
            self.concurrency_cap
            if self.concurrency_cap is not None
            else resources.concurrency_cap()
        )
        if cap <= 0 or documents * pages <= cap:
            return documents, pages
        return documents, max(1, cap // documents)
