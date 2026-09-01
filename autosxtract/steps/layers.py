"""Applying the containment layers to what an engine read.

This lives here rather than in ``quality.lines`` for a boundary reason: that
module **measures** and knows nothing about engines or images; this one
**orchestrates** — it crops the page, calls the signature detector, re-runs the
recogniser on the targets.

Layer 2 uses the engine itself to re-read a crop, preferring its
``recognize_crop`` path. Using the whole-page path instead would pay for one
extra detection per crop, and that is not a rounding error: measured, it takes
the layer from tens of milliseconds to ~3 s per document.
"""

from __future__ import annotations

from typing import cast

from autosxtract.config import Config
from autosxtract.interfaces import Engine, LexiconLike
from autosxtract.quality.lines import Containment, contain, reassemble
from autosxtract.types import Page, Transcription


def _crop(image: bytes, bbox, *, vertical_margin: float = 0.0, enhance: bool = False):
    """Crop the box out of the image. ``None`` when it cannot be cropped.

    ``vertical_margin`` shrinks the crop top and bottom — that is what removes
    part of a signature stroke crossing the line without taking the text with it.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None
    arr = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        return None
    height, width = arr.shape[:2]
    x1, y1, x2, y2 = (int(v) for v in bbox)
    if vertical_margin:
        m = int((y2 - y1) * vertical_margin)
        y1, y2 = y1 + m, y2 - m
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(width, x2), min(height, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    crop = arr[y1:y2, x1:x2]
    if enhance:
        grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        grey = cv2.createCLAHE(2.0, (8, 8)).apply(grey)
        crop = cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)
    return crop


def _to_png(arr) -> bytes | None:
    try:
        import cv2
    except ImportError:
        return None
    ok, buffer = cv2.imencode(".png", arr)
    return buffer.tobytes() if ok else None


def _rotate(arr, direction: int):
    import numpy as np

    return np.rot90(arr, direction)


def _reread(engine: Engine, png: bytes) -> tuple[str, float] | None:
    """Re-read a crop by the cheapest path the engine offers.

    It prefers ``recognize_crop`` — the crop already is a line, and detecting
    inside it is looking for what was just found. Measured: with detection Layer
    2 costs ~3 s per document; without it, tens of milliseconds.
    """
    try:
        direct = engine.recognize_crop(png)
    except Exception:
        # A bad crop does not bring the page down — it just does not recover the line.
        return None
    if direct is not None:
        text, score = direct
        return (text.strip(), score) if text.strip() else None

    try:
        reread = engine.read_page(png)
    except Exception:
        return None
    if reread is None or not reread.lines:
        return None
    # A crop may yield more than one line; join them in order and use the mean
    # score, which is what gets compared with the original.
    text = " ".join(x.text.strip() for x in reread.lines if x.text.strip())
    score = sum(x.score for x in reread.lines) / len(reread.lines)
    return (text, score) if text else None


def reread_targets(
    engine: Engine,
    image: bytes,
    page: Page,
    containment: Containment,
    *,
    max_targets: int = 10,
    min_gain: float = 0.08,
) -> tuple[Containment, int]:
    """Layer 2: re-read the targets and rebuild the text. ``(containment, recovered)``.

    Two strategies, by target class:

    ``vertical``   rotate 90 degrees **both** ways and keep the better one. An
                   upright protocol stamp is illegible sideways and perfectly
                   legible rotated — it is the case that pays best.
    ``illegible``  crop 18% tighter vertically (removing part of the stroke
                   crossing it) and also try adaptive contrast.

    A line is only replaced if the new score beats the original by ``min_gain``.
    Swapping on a tie is noise, and noise here rewrites text that was correct.
    """
    if not containment.targets or max_targets <= 0:
        return containment, 0

    by_index = {line.i: line for line in containment.lines}
    # Prioritise the vertical stamp: the rotated recovery pays more than the
    # tight crop, and the target ceiling is small.
    targets = sorted(
        containment.targets,
        key=lambda i: 0 if by_index.get(i) and by_index[i].kind == "vertical" else 1,
    )

    recovered: dict[int, str] = {}
    for i in targets[:max_targets]:
        line = by_index.get(i)
        if line is None or line.bbox is None or i >= len(page.lines):
            continue
        base = page.lines[i].score

        if line.kind == "vertical":
            crop = _crop(image, line.bbox)
            candidates = [_rotate(crop, 1), _rotate(crop, -1)] if crop is not None else []
        else:
            candidates = [
                _crop(image, line.bbox, vertical_margin=0.18),
                _crop(image, line.bbox, vertical_margin=0.18, enhance=True),
            ]

        best_text, best_score = None, base + min_gain
        for candidate in candidates:
            if candidate is None:
                continue
            png = _to_png(candidate)
            if png is None:
                continue
            read = _reread(engine, png)
            if read is None:
                continue
            text, score = read
            if text and score > best_score:
                best_text, best_score = text, score
        if best_text:
            recovered[i] = best_text

    if not recovered:
        return containment, 0
    return reassemble(containment, recovered), len(recovered)


def apply(
    engine: Engine,
    images: list[bytes],
    transcription: Transcription,
    config: Config,
    *,
    lexicon: LexiconLike | None = None,
) -> tuple[str, dict]:
    """Run the layers over every page and return ``(text, report)``.

    The report is aggregated — the counts add up and the trusted fraction is a
    weighted mean — because the decision to escalate belongs to the document,
    not the page: an expensive step pays for itself per document, not per sheet.

    The vocabulary is taken in order of specificity: the argument, then
    ``config.lexicon``, then the built-in floor. It is a parameter because the
    built-in list is exactly that — a floor. Anyone with a validated archive
    builds a measurably better one, and this is the seam that lets them.
    """
    from autosxtract.quality.lexicon import Lexicon

    # ``quality.lines`` and ``quality.routing`` are still annotated against the
    # concrete ``Lexicon``, while at runtime they touch nothing but ``coverage``,
    # ``tokens`` and ``in`` — which is the whole of ``LexiconLike``. The cast
    # marks that seam instead of hiding it: this module accepts the contract, and
    # the two it calls have simply not been widened to it yet.
    known = cast(Lexicon, lexicon or config.lexicon or Lexicon.builtin())
    detector = _detector(config)

    parts: list[str] = []
    counts: dict[str, int] = {
        "lines_total": 0,
        "lines_illegible": 0,
        "lines_suspect": 0,
        "lines_signature": 0,
        "lines_vertical": 0,
        "lines_recovered": 0,
    }
    trusted: list[float] = []
    escalate = False
    routes: list[str] = []

    for index, page in enumerate(transcription.pages):
        image = images[index] if index < len(images) else b""
        boxes = None
        if detector is not None and image:
            boxes = detector.detect(image)

        containment = contain(page, lexicon=known, signature_boxes=boxes)
        recovered = 0
        if config.layer2 and image and containment.targets:
            containment, recovered = reread_targets(
                engine,
                image,
                page,
                containment,
                max_targets=config.max_layer2_targets,
                min_gain=config.min_layer2_gain,
            )

        if config.page_routing:
            from autosxtract.quality.routing import route

            routes.append(route(page, lexicon=known).kind)

        report = containment.report()
        for key, value in report.items():
            if key in counts and isinstance(value, int):
                counts[key] += value
        counts["lines_recovered"] += recovered
        trusted.append(containment.trusted_fraction)
        escalate = escalate or containment.needs_escalation
        if containment.text.strip():
            parts.append(containment.text)

    # The counts add up; the trusted fraction is a per-page mean; the action
    # belongs to the document, not the sheet.
    final: dict = dict(counts)
    final["trusted_fraction"] = round(sum(trusted) / len(trusted), 3) if trusted else 1.0
    final["needs_escalation"] = escalate
    final["suggested_action"] = (
        "escalate" if escalate else "ok" if counts["lines_illegible"] == 0 else "accept_with_holes"
    )
    if routes:
        final["routes"] = routes
    return "\n\n".join(parts), final


def _detector(config):
    """The configured signature detector, or ``None``."""
    if not config.signature_detector:
        return None
    from autosxtract.engines.signature import SignatureDetector

    detector = SignatureDetector(config.signature_detector, threads=config.pages_in_flight())
    ok, _reason = detector.available()
    return detector if ok else None
