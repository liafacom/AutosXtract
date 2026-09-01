"""Where the PP-OCRv6 weights live, and how they get there.

A distinction that matters and sits at the centre of the library's design:
**extraction does no networking.** This module does — once, to download the
model, the same way ``pip install`` does. After that the machine can stay
offline forever.

Three ways to obtain the weights, in order of preference:

1. ``AUTOSXTRACT_MODELS`` points at a directory that already has them — the
   path for a closed environment, a container with no egress, and CI.
2. The local cache (``~/.cache/autosxtract/``), filled by a previous run.
3. A download from Hugging Face, on demand or via ``autosxtract download-models``.

``rapidocr`` ships an embedded PP-OCRv5 mobile and works without any of this.
The v6 *tiny* is smaller and newer; if the weights are not at hand, the engine
falls back to the embedded one rather than failing — degrade with a warning,
never break.
"""

from __future__ import annotations

import os
from pathlib import Path

# Official PaddlePaddle repositories on Hugging Face, already converted to
# ONNX — which is what ``rapidocr`` consumes without needing the Paddle runtime.
REPOS = {
    "det": "PaddlePaddle/PP-OCRv6_tiny_det_onnx",
    "rec": "PaddlePaddle/PP-OCRv6_tiny_rec_onnx",
}
_HF_BASE = "https://huggingface.co/{repo}/resolve/main/{file}"

# Final names in the cache. Stable: the engine composes them, and changing them
# would invalidate caches already filled on production machines.
FILES = {
    "det": "PP-OCRv6_tiny_det.onnx",
    "rec": "PP-OCRv6_tiny_rec.onnx",
    "keys": "PP-OCRv6_tiny_rec_keys.txt",
    "yml": "PP-OCRv6_tiny_rec_inference.yml",
}


def directory() -> Path:
    """This machine's model directory.

    ``AUTOSXTRACT_MODELS`` takes priority and is not created: if the operator
    pointed somewhere, it is because the weights are already there.
    """
    env = os.environ.get("AUTOSXTRACT_MODELS")
    if env:
        return Path(env).expanduser()
    root = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    target = Path(root).expanduser() / "autosxtract"
    target.mkdir(parents=True, exist_ok=True)
    return target


def paths() -> dict[str, Path]:
    """Where each piece of the model should be — whether it exists or not."""
    base = directory()
    return {key: base / name for key, name in FILES.items()}


def int8_paths() -> dict[str, Path] | None:
    """The INT8 weights, or ``None`` when they are not on disk.

    They live in ``int8/`` beside the FP32 ones and are **not** downloaded:
    quantisation is a choice with a measurable accuracy cost, so it is made by
    whoever exports the models, on their own archive, not by a library helping
    itself to a faster file.

    Returns ``None`` rather than paths that do not exist, because the caller
    has to be able to say "asked for INT8 and it is not here" out loud instead
    of running FP32 while reporting INT8.
    """
    base = directory() / "int8"
    found = {key: base / name for key, name in FILES.items()}
    if not all(found[k].is_file() for k in ("det", "rec")):
        return None
    # The dictionary is not quantised; fall back to the FP32 one when the INT8
    # export did not carry it along.
    if not found["keys"].is_file():
        found["keys"] = paths()["keys"]
    return found if found["keys"].is_file() else None


def complete() -> bool:
    """Are the three files the engine needs in place?"""
    p = paths()
    return all(p[k].is_file() for k in ("det", "rec", "keys"))


def _download(url: str, target: Path, timeout: float) -> None:
    import urllib.request

    partial = target.with_suffix(target.suffix + ".partial")
    with urllib.request.urlopen(url, timeout=timeout) as response:
        partial.write_bytes(response.read())
    # Renamed only at the end: an interrupted download never leaves a file with
    # the final name, which on the next run would look like a valid model.
    partial.replace(target)


def _extract_dictionary(yml: Path, target: Path) -> bool:
    """Pull the character list out of the recogniser's ``inference.yml``.

    ``rapidocr`` wants the dictionary as a file with one character per line;
    Paddle ships it embedded in the YAML. The search is recursive because the
    key moves between exporter versions.
    """
    try:
        import yaml
    except ImportError:
        return False

    def find(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if "character" in str(key).lower() and isinstance(value, list):
                    return value
                found = find(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = find(item)
                if found:
                    return found
        return None

    try:
        characters = find(yaml.safe_load(yml.read_text(encoding="utf-8")))
    except Exception:
        # A YAML from an unexpected version.
        return False
    if not characters:
        return False
    target.write_text("\n".join(characters), encoding="utf-8")
    return True


def download(*, timeout: float = 60.0, force: bool = False) -> dict[str, Path]:
    """Ensure the PP-OCRv6 tiny is in the cache and return the paths.

    Idempotent: what already exists is not downloaded again. Raises if the
    network fails — the caller decides whether that is fatal (the CLI) or a
    fall back to the embedded model (the engine).
    """
    target = paths()
    if complete() and not force:
        return target

    # The file name in the repository is always ``inference.*``; the local name
    # is what carries the model's identity.
    _download(_HF_BASE.format(repo=REPOS["det"], file="inference.onnx"), target["det"], timeout)
    _download(_HF_BASE.format(repo=REPOS["rec"], file="inference.onnx"), target["rec"], timeout)
    _download(_HF_BASE.format(repo=REPOS["rec"], file="inference.yml"), target["yml"], timeout)

    if not _extract_dictionary(target["yml"], target["keys"]):
        # Without the dictionary the recogniser decodes the wrong indices and
        # returns plausible, false text — worse than not running. Better to
        # delete the weights and let the engine fall back to the embedded one.
        for key in ("det", "rec"):
            target[key].unlink(missing_ok=True)
        raise RuntimeError(
            "could not extract the dictionary from inference.yml "
            "(install pyyaml: pip install pyyaml)"
        )
    return target
