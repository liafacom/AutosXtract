"""PP-OCR — step 2 off Apple hardware, and the model swap point.

The default is **PP-OCRv6 tiny**, and the choice is measured: with the
bottleneck in CPU, what decides is not benchmark accuracy but how many pages
per second the machine sustains. The larger variants buy little for a cost that
shows up directly on the cascade's clock.

**But the default is only the default.** This engine was written to be
reconfigured, because a different archive wants a different model:

    from autosxtract.engines.paddle import PaddleEngine

    PaddleEngine()                              # PP-OCRv6 tiny (default)
    PaddleEngine(det="tiny", rec="medium")      # small detector + large recogniser
    PaddleEngine(rec_dir="/my/finetuned_rec")   # your model, trained on your archive
    PaddleEngine(quantized=True)                # INT8, if you exported it
    PaddleEngine(preprocess="otsu")             # binarise before reading
    PaddleEngine(providers=["CoreMLExecutionProvider", "CPUExecutionProvider"])

Why ``det`` and ``rec`` are separate: **accuracy lives in the recogniser.**
Detecting *where* there is text is an easier task than reading *what* is
written, so "small detector with large recogniser" tends to be the
best-returning trade — and it only exists if the two are distinct parameters.

Two implementation paths, and the engine picks on its own:

``paddleocr``   when the package is installed. It gives access to the three
                official tiers, to INT8 and to a fine-tuned recogniser, and it
                returns **per-line geometry** — which is what enables the
                containment layers.
``rapidocr``    the lightweight alternative (ONNX Runtime only). It also
                returns geometry, and it is what the library uses when
                ``paddleocr`` is absent.

If neither is installed the step goes inert and the cascade moves on.
"""

from __future__ import annotations

import contextlib

from autosxtract.engines import models
from autosxtract.engines.base import OCREngine, register
from autosxtract.types import Line, Page

#: Official PP-OCRv6 tiers, smallest to largest (1.5M / 7.7M / 34.5M
#: parameters). ``tiny`` is the library default.
TIERS = ("tiny", "small", "medium")


@register(
    name="paddle",
    priority=20,
    extra="paddle",
    description="PP-OCR on ONNX — configurable model, default PP-OCRv6 tiny",
)
class PaddleEngine(OCREngine):
    """PP-OCR over ONNX Runtime, with the model chosen by the integrator."""

    def __init__(
        self,
        *,
        det: str = "tiny",
        rec: str | None = None,
        rec_dir: str | None = None,
        det_dir: str | None = None,
        quantized: bool = False,
        preprocess: str | None = None,
        providers: list[str] | None = None,
        threads: int = 1,
        languages: tuple[str, ...] = ("pt", "en"),
        download_if_missing: bool = True,
        backend: str | None = None,
    ) -> None:
        super().__init__()
        if det not in TIERS and det_dir is None:
            raise ValueError(f"invalid det: {det!r}; use one of {TIERS} or pass det_dir")
        self.det = det
        #: ``None`` = the same tier as detection. Separate on purpose: accuracy
        #: lives in the recogniser, so "small det + large rec" is the
        #: best-returning trade.
        self.rec = rec or det
        self.rec_dir = rec_dir
        self.det_dir = det_dir
        self.quantized = quantized
        #: ``None`` | ``"otsu"`` | ``"adaptive"``. Binarising helps on a faded
        #: scan and HURTS on a native document — which is why it is not default.
        self.preprocess = preprocess
        self.providers = providers
        self.threads = max(1, threads)
        self.languages = tuple(languages)
        self.download_if_missing = download_if_missing
        #: ``None`` = decide alone (paddleocr if present, otherwise rapidocr).
        self.backend = backend
        #: Filled in at load time: which model actually came up.
        self.model_in_use = ""
        #: The isolated recogniser for Layer 2. ``False`` marks "tried and it
        #: does not work", so the attempt is not repeated per crop.
        self._crop_rec = None

    def __repr__(self) -> str:
        target = self.rec_dir or f"PP-OCRv6 {self.det}/{self.rec}"
        return f"PaddleEngine({target}{', INT8' if self.quantized else ''})"

    # ── backend choice ───────────────────────────────────────────────────
    def _backend(self) -> str:
        if self.backend:
            return self.backend
        import importlib.util

        if importlib.util.find_spec("paddleocr") is not None:
            return "paddleocr"
        return "rapidocr"

    def _engine_config(self) -> dict:
        providers = self.providers or ["CPUExecutionProvider"]
        return {
            "providers": providers,
            "intra_op_num_threads": self.threads,
            "inter_op_num_threads": self.threads,
        }

    def _load(self):
        if self._backend() == "paddleocr":
            return self._load_paddleocr()
        return self._load_rapidocr()

    def _load_paddleocr(self):
        import os

        os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "huggingface")
        from paddleocr import PaddleOCR

        kw: dict = {
            "text_detection_model_name": f"PP-OCRv6_{self.det}_det",
            "text_recognition_model_name": f"PP-OCRv6_{self.rec}_rec",
            "engine": "onnxruntime",
            "engine_config": self._engine_config(),
            # Case-file scans are already upright, and every extra classifier is
            # another pass over the page.
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
        }
        if self.det_dir:
            kw["text_detection_model_dir"] = self.det_dir
        if self.rec_dir:
            kw["text_recognition_model_dir"] = self.rec_dir
        if self.quantized:
            base = models.directory() / "int8"
            kw["text_detection_model_dir"] = str(base / f"PP-OCRv6_{self.det}_det")
            kw["text_recognition_model_dir"] = str(base / f"PP-OCRv6_{self.rec}_rec")

        engine = PaddleOCR(**kw)
        self.model_in_use = self.rec_dir or (
            f"PP-OCRv6 {self.det}/{self.rec}" + (" INT8" if self.quantized else "")
        )
        return ("paddleocr", engine)

    def _load_rapidocr(self):
        from rapidocr import RapidOCR

        params = self._rapidocr_params()
        engine = RapidOCR(params=params) if params else RapidOCR()
        return ("rapidocr", engine)

    def _rapidocr_params(self) -> dict:
        """Point ``rapidocr`` at the v6 tiny weights, if they exist.

        An empty dict means "use the embedded one" — heavier, but always
        present. ``rapidocr`` does not expose the three official tiers; to pick
        a tier, use the ``paddleocr`` backend.
        """
        if self.rec_dir or self.det_dir:
            p = {}
            if self.det_dir:
                p["Det.model_path"] = self.det_dir
            if self.rec_dir:
                p["Rec.model_path"] = self.rec_dir
            self.model_in_use = "custom model (rapidocr)"
            return p
        if self.det != "tiny":
            self.model_in_use = f"rapidocr embedded (tier {self.det} needs the paddleocr backend)"
            return {}
        if not models.complete() and self.download_if_missing:
            # With no network we carry on with the embedded model: downloading
            # is a convenience, not a requirement — extraction cannot depend on
            # connectivity.
            with contextlib.suppress(Exception):
                models.download()
        if not models.complete():
            self.model_in_use = "rapidocr embedded (v6 tiny weights missing)"
            return {}

        paths = models.paths()
        if self.quantized:
            # ``quantized`` used to be read ONLY by the paddleocr backend. With
            # rapidocr — the backend most installs actually get — it was
            # silently ignored: the flag was accepted, INT8 was reported in the
            # repr, and FP32 ran. A configuration that is accepted and does
            # nothing is worse than one that is refused.
            int8 = models.int8_paths()
            if int8 is None:
                self.model_in_use = (
                    "PP-OCRv6 tiny (INT8 REQUESTED but not on disk; "
                    f"export it to {models.directory() / 'int8'})"
                )
            else:
                paths = int8
                self.model_in_use = "PP-OCRv6 tiny INT8"
                return {
                    "Det.model_path": str(paths["det"]),
                    "Rec.model_path": str(paths["rec"]),
                    "Rec.rec_keys_path": str(paths["keys"]),
                }
        else:
            self.model_in_use = "PP-OCRv6 tiny"
        return {
            "Det.model_path": str(paths["det"]),
            "Rec.model_path": str(paths["rec"]),
            "Rec.rec_keys_path": str(paths["keys"]),
        }

    # ── reading ──────────────────────────────────────────────────────────
    def _preprocess_image(self, image: bytes):
        """The BGR array to hand the engine, with the requested preprocessing."""
        import cv2
        import numpy as np

        arr = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if arr is None or not self.preprocess:
            return arr
        grey = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        if self.preprocess == "otsu":
            _, grey = cv2.threshold(grey, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        elif self.preprocess == "adaptive":
            grey = cv2.adaptiveThreshold(
                grey, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
            )
        return cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)

    def read_page(self, image: bytes) -> Page | None:
        """Read the page returning it **line by line, with polygon and score**.

        This is what enables the containment layers. Both backends expose the
        geometry; if one day one does not, returning ``None`` here makes the
        cascade fall back to the simple contract without losing the extraction.
        """
        loaded = self.model
        if loaded is None:
            raise RuntimeError(self._reason or "no PP-OCR backend available")
        backend, engine = loaded

        arr = self._preprocess_image(image)
        if arr is None:
            return None

        if backend == "paddleocr":
            return self._page_paddleocr(engine, arr)
        return self._page_rapidocr(engine, arr)

    @staticmethod
    def _dimensions(arr, lines: list[Line]) -> tuple[float, float]:
        """The page dimensions. Prefer the image to the polygons' extent: the
        latter underestimates the sheet when the text does not reach the edges,
        and the layers use the width to decide what counts as margin."""
        if arr is not None and getattr(arr, "shape", None):
            return float(arr.shape[1]), float(arr.shape[0])
        points = [p for line in lines if line.poly for p in line.poly]
        if not points:
            return 0.0, 0.0
        return max(p[0] for p in points) + 1, max(p[1] for p in points) + 1

    def _page_paddleocr(self, engine, arr) -> Page | None:
        output = engine.predict(arr)
        if not output:
            return None
        d = output[0]
        texts = list(d.get("rec_texts") or [])
        if not texts:
            return Page([], *self._dimensions(arr, []))
        scores = list(d.get("rec_scores") or [])
        polys = d.get("rec_polys")
        if polys is None:
            polys = d.get("dt_polys")
        lines = [
            Line(
                text=t,
                score=float(scores[i]) if i < len(scores) else 1.0,
                poly=_normalize_poly(polys[i]) if polys is not None and i < len(polys) else None,
            )
            for i, t in enumerate(texts)
        ]
        return Page(lines, *self._dimensions(arr, lines))

    def _page_rapidocr(self, engine, arr) -> Page | None:
        import cv2

        output = engine(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB))
        texts, scores, polys = _normalize_output(output)
        lines = [
            Line(
                text=t,
                score=float(scores[i]) if i < len(scores) else 1.0,
                poly=_normalize_poly(polys[i]) if polys and i < len(polys) else None,
            )
            for i, t in enumerate(texts)
        ]
        return Page(lines, *self._dimensions(arr, lines))

    def recognize_crop(self, image: bytes) -> tuple[str, float] | None:
        """Recogniser only, no detection — Layer 2's cheap path.

        Measured: with detection, re-reading one page costs ~3 s; without it,
        tens of milliseconds. The crop ALREADY is a line, so detecting inside it
        is looking for what was just found.
        """
        loaded = self.model
        if loaded is None:
            return None
        backend, _engine = loaded
        try:
            import cv2
            import numpy as np
        except ImportError:
            return None
        arr = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            return None

        rec = self._recognizer()
        if rec is None:
            return None

        if backend == "paddleocr":
            try:
                output = rec.predict([arr])
            except Exception:
                return None
            if not output:
                return None
            text = (output[0].get("rec_text") or "").strip()
            score = float(output[0].get("rec_score") or 0.0)
            return (text, score) if text else None

        try:
            output = rec(cv2.cvtColor(arr, cv2.COLOR_BGR2RGB), use_det=False, use_cls=False)
        except Exception:
            return None
        texts, scores, _polys = _normalize_output(output)
        if not texts:
            return None
        return " ".join(texts), (sum(scores) / len(scores) if scores else 0.0)

    def _recognizer(self):
        """Layer 2's isolated recogniser, loaded once per engine.

        **It has to be a separate instance.** Measured: calling the main
        ``rapidocr`` with ``use_det=False`` leaves detection off PERMANENTLY on
        that object — the next whole-page read returned 1 line where it had
        returned 56, and the document came out with 1 character instead of
        3,900.

        The defect is of the worst kind: silent, order-dependent, and only
        visible from the second page processed onwards. One re-read crop
        spoiled every following page of the batch.
        """
        if self._crop_rec is not None:
            return self._crop_rec or None
        loaded = self.model
        backend = loaded[0] if loaded else ""
        try:
            if backend == "paddleocr":
                from paddleocr import TextRecognition

                self._crop_rec = TextRecognition(
                    model_name=f"PP-OCRv6_{self.rec}_rec",
                    engine="onnxruntime",
                    engine_config=self._engine_config(),
                )
            else:
                from rapidocr import RapidOCR

                params = self._rapidocr_params()
                self._crop_rec = RapidOCR(params=params) if params else RapidOCR()
        except Exception:
            self._crop_rec = False
        return self._crop_rec or None

    def available(self) -> tuple[bool, str]:
        ok, reason = super().available()
        if not ok:
            return ok, reason
        return True, self.model_in_use or f"PP-OCR ({self._backend()})"


def _normalize_poly(poly) -> tuple[tuple[float, float], ...] | None:
    """Accepts the various polygon shapes the backends return."""
    if poly is None:
        return None
    try:
        points = [(float(p[0]), float(p[1])) for p in poly]
    except (TypeError, IndexError, ValueError):
        try:  # a box (x1, y1, x2, y2)
            x1, y1, x2, y2 = (float(v) for v in poly)
        except Exception:
            return None
        return ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    return tuple(points) if points else None


def _normalize_output(output) -> tuple[list[str], list[float], list]:
    """Accepts ``rapidocr`` 3.x output and 1.x output.

    3.x returns an object with ``txts``/``scores``/``boxes``; 1.x returned the
    tuple ``(list, times)`` with ``[[bbox, text, score], ...]``. Accepting both
    avoids tying the library to the exact version installed.
    """
    txts = getattr(output, "txts", None)
    if txts is not None:
        raw = getattr(output, "scores", None) or []
        boxes = getattr(output, "boxes", None)
        boxes = list(boxes) if boxes is not None else []
        texts, scores, polys = [], [], []
        for i, t in enumerate(txts):
            if not (t or "").strip():
                continue
            texts.append(t)
            scores.append(float(raw[i]) if i < len(raw) else 1.0)
            polys.append(boxes[i] if i < len(boxes) else None)
        return texts, scores, polys

    result = output[0] if isinstance(output, tuple) else output
    if not result:
        return [], [], []
    texts, scores, polys = [], [], []
    for item in result:
        if len(item) >= 3 and (item[1] or "").strip():
            polys.append(item[0])
            texts.append(item[1])
            scores.append(float(item[2]))
    return texts, scores, polys
