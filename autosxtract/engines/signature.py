"""A visual signature detector — Layer 1.5, and an honest warning.

It runs a YOLO exported to ONNX over the page and returns boxes. Layer 1 uses
them to mark as ``[signature]`` the line the recogniser produced while trying to
read a scribble over printed text.

**Read this before switching it on.** A stage-1 model — ``yolo11n`` trained on a
public signature dataset, mAP50 0.995 on the public validation set, 35 ms/page
on CPU — **did not transfer** to a scanned legal archive. Run over 895 pages:
171 (19%) with a detection, and most of them **false positives**. It fires on an
authenticity seal (confidence 0.92), a "DELIVERED" stamp, an ICP-Brasil logo, a
QR code, a coat of arms, and even on the printed word "SIGNATURES". And it
misses the target case: a cursive signature over a name produced no box at all,
not even at 0.12 confidence.

The reason is domain: the public dataset is contract signatures — thick
strokes, isolated, on a clean background. The real case is a thin cursive
scribble **over** printed text, on a degraded scan.

Two consequences, both in code:

1. **Off by default** (``Config.signature_detector=None``). Only someone
   pointing at their own model switches it on.
2. **A box never decides on its own.** ``quality.lines`` crosses the box with
   the text read: it only counts if some overlapping line is illegible, and it
   is discarded if any overlapping line is stamp text. That is the filter that
   makes an imperfect detector usable.

To train a stage 2 that works, the measured path is to annotate 200-400 pages of
**your** archive, including NEGATIVES — stamps, seals, logos and QR codes
labelled as not-a-signature. Without the negatives the model repeats the same
false positives.

The structural rule in ``quality.lines`` (a scribble above a name with a job
title nearby) always runs, with or without a detector, and costs nothing.
"""

from __future__ import annotations

import threading
from pathlib import Path

#: Input resolution of the exported model.
IMGSZ = 640
#: Minimum confidence. Raise it after looking at your own false positives.
CONF = 0.30
#: IoU for non-maximum suppression.
IOU = 0.45


class SignatureDetector:
    """A YOLO in ONNX. With no model file it goes inert — it never raises."""

    def __init__(
        self,
        model: str | Path,
        *,
        imgsz: int = IMGSZ,
        confidence: float = CONF,
        iou: float = IOU,
        threads: int = 1,
    ) -> None:
        self.model = Path(model)
        self.imgsz = imgsz
        self.confidence = confidence
        self.iou = iou
        self.threads = max(1, threads)
        self._session = None
        self._input = ""
        self._reason = ""
        self._load_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"SignatureDetector({str(self.model)!r}, conf={self.confidence})"

    def available(self) -> tuple[bool, str]:
        if self._session is not None:
            return True, f"yolo onnx: {self.model.name}"
        if self._reason:
            return False, self._reason
        if not self.model.is_file():
            self._reason = f"model missing: {self.model}"
            return False, self._reason
        with self._load_lock:
            if self._session is None:
                try:
                    import onnxruntime as ort

                    options = ort.SessionOptions()
                    options.intra_op_num_threads = self.threads
                    options.inter_op_num_threads = self.threads
                    self._session = ort.InferenceSession(
                        str(self.model), options, providers=["CPUExecutionProvider"]
                    )
                    self._input = self._session.get_inputs()[0].name  # type: ignore[attr-defined]
                except Exception as exc:
                    self._reason = f"detector did not load: {exc}"
                    return False, self._reason
        return True, f"yolo onnx: {self.model.name}"

    def detect(self, image: bytes) -> list[tuple[float, float, float, float, float]]:
        """``[(x1, y1, x2, y2, confidence), ...]`` in image pixels.

        An empty list when the detector is unavailable — which is different from
        "there is no signature", and is why Layer 1 never concludes anything
        from the absence of boxes.
        """
        ok, _reason = self.available()
        if not ok:
            return []
        try:
            import cv2
            import numpy as np
        except ImportError:
            return []

        arr = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            return []
        height, width = arr.shape[:2]

        # Letterbox: preserves the aspect ratio and centres on a 114-grey
        # background, which is the training convention. Resizing without
        # preserving it would deform the strokes and the model would be looking
        # at something else.
        scale = min(self.imgsz / width, self.imgsz / height)
        nw, nh = round(width * scale), round(height * scale)
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        dx, dy = (self.imgsz - nw) // 2, (self.imgsz - nh) // 2
        canvas[dy : dy + nh, dx : dx + nw] = cv2.resize(arr, (nw, nh))
        blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0

        try:
            output = self._session.run(None, {self._input: blob})[0]  # type: ignore[attr-defined]
        except Exception:
            return []

        # Ultralytics export: ``(1, 4+nc, N)``. Transpose to ``(N, 4+nc)``.
        pred = output[0]
        if pred.shape[0] < pred.shape[1]:
            pred = pred.T

        boxes, scores = [], []
        for row in pred:
            cx, cy, w, h = row[:4]
            score = float(row[4:].max())
            if score < self.confidence:
                continue
            boxes.append(
                [
                    (cx - w / 2 - dx) / scale,
                    (cy - h / 2 - dy) / scale,
                    (cx + w / 2 - dx) / scale,
                    (cy + h / 2 - dy) / scale,
                ]
            )
            scores.append(score)
        if not boxes:
            return []

        kept = _nms(np.array(boxes), np.array(scores), self.iou)
        return [
            (
                float(np.clip(boxes[i][0], 0, width)),
                float(np.clip(boxes[i][1], 0, height)),
                float(np.clip(boxes[i][2], 0, width)),
                float(np.clip(boxes[i][3], 0, height)),
                scores[i],
            )
            for i in kept
        ]


def _nms(boxes, scores, threshold: float) -> list[int]:
    """Non-maximum suppression — the model returns overlapping boxes."""
    import numpy as np

    x1, y1, x2, y2 = boxes.T
    area = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = scores.argsort()[::-1]
    kept: list[int] = []
    while order.size:
        i = order[0]
        kept.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = (xx2 - xx1).clip(0) * (yy2 - yy1).clip(0)
        iou = inter / (area[i] + area[order[1:]] - inter + 1e-9)
        order = order[1:][iou < threshold]
    return kept
