#!/usr/bin/env python3
"""Compare the engines available on this machine, on YOUR archive.

It exists because an isolated number has already lied in this pipeline: a
measurement over 60 documents said that turning off Vision's language
correction improved anchor preservation (+4), and across the whole cascade the
net was -227, because the worse text failed the gate and fell to worse engines.
The methodological lesson is that what decides is the behaviour **of the
cascade**, not one engine's isolated output.

So this script measures both side by side: per engine and per cascade.

    python scripts/compare_engines.py ~/archive --n 30

Do not commit its output: it contains text from your documents.
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from pathlib import Path

from autosxtract.cascade import Cascade, engine_order
from autosxtract.config import Config
from autosxtract.engines import base as engines
from autosxtract.pdf.render import render
from autosxtract.quality.anchors import anchors
from autosxtract.quality.stamp import useful_words


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive", type=Path, help="folder holding the PDFs")
    p.add_argument("--n", type=int, default=30, help="how many documents to sample")
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--seed", type=int, default=11, help="reproducible sample")
    args = p.parse_args()

    pdfs = sorted(args.archive.glob("*.pdf"))
    if not pdfs:
        print(f"no PDF in {args.archive}")
        return 1
    random.seed(args.seed)
    sample = random.sample(pdfs, min(args.n, len(pdfs)))
    ready = engine_order()
    print(f"{len(sample)} documents | engines: {', '.join(ready) or 'none'}\n")

    # ── per engine, in isolation ─────────────────────────────────────────
    print("PER ENGINE (page by page, without the cascade's gates)")
    print(f"  {'engine':12} {'ms/page':>8} {'words':>9} {'anchors':>8}")
    reference: dict[Path, set[str]] = {}
    for name in ready:
        engine = engines.get(name)
        times, words, found = [], [], []
        for path in sample:
            images = render(path.read_bytes(), dpi=args.dpi, max_pages=3)
            if not images:
                continue
            t0 = time.perf_counter()
            t = engine.transcribe(images, parallelism=1)
            if t is None:
                continue
            times.append((time.perf_counter() - t0) * 1000 / len(images))
            words.append(useful_words(t.text))
            a = anchors(t.text)
            found.append(len(a))
            reference.setdefault(path, set()).update(a)
        if times:
            print(
                f"  {name:12} {statistics.median(times):8.0f} "
                f"{statistics.median(words):9.0f} {statistics.median(found):8.0f}"
            )

    # ── the whole cascade ────────────────────────────────────────────────
    print("\nCASCADE (what actually gets persisted)")
    cascade = Cascade(Config(dpi=args.dpi))
    per_step: dict[str, int] = {}
    total_chars = 0
    total_lost = 0
    t0 = time.perf_counter()
    for path in sample:
        r = cascade.extract_file(path)
        per_step[r.step] = per_step.get(r.step, 0) + 1
        total_chars += len(r.text)
        # An anchor SOME engine saw and the cascade did not persist is the
        # silent damage no text metric detects.
        total_lost += len(reference.get(path, set()) - anchors(r.text))
    elapsed = time.perf_counter() - t0

    for step, n in sorted(per_step.items(), key=lambda kv: -kv[1]):
        print(f"  {step:22} {n:4d}  ({100 * n / len(sample):.1f}%)")
    print(f"\n  total time            {elapsed:.1f} s")
    print(f"  content               {total_chars} chars")
    print(f"  anchors not persisted {total_lost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
