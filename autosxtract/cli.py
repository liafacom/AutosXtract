"""Command line — extract, diagnose and download models.

Three subcommands, and the middle one saves integrators the most time:

    autosxtract extract document.pdf
    autosxtract extract folder/*.pdf --json output.json
    autosxtract diagnose
    autosxtract download-models

``diagnose`` answers, without reading code, the question that comes up whenever
a result is surprising: **which steps does this machine have?** When the text
comes out worse than expected, the cause is almost always a missing engine, and
the diagnosis says which one and how to install it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from autosxtract import __version__
from autosxtract.cascade import Cascade, engine_order
from autosxtract.config import Config


def _cmd_extract(args: argparse.Namespace) -> int:
    config = Config(
        dpi=args.dpi,
        engines=args.engines.split(",") if args.engines else None,
        page_parallelism=args.parallelism,
        layers=not args.no_layers,
        page_routing=args.routes,
    )
    cascade = _build(config, args)
    if not args.files:
        print("no files", file=sys.stderr)
        return 2

    output = []
    for path in args.files:
        result = cascade.extract_file(path)
        output.append({"file": str(path), **result.to_dict()})
        if args.json:
            continue
        # Without --json the output is the text and nothing else, so
        # ``autosxtract extract x.pdf > x.txt`` does what one expects. The
        # provenance goes to stderr, where it does not pollute the redirection.
        print(f"{Path(path).name}: {result.provenance}", file=sys.stderr)
        print(result.text)

    if args.json:
        Path(args.json).write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{len(output)} document(s) -> {args.json}", file=sys.stderr)
    return 0


def _build(config: Config, args: argparse.Namespace) -> Cascade:
    """The cascade requested on the command line.

    Choosing a model from the CLI covers the case of measuring a swap without
    writing code — which is exactly when you want to measure.
    """
    if not (args.det or args.rec or args.rec_dir):
        return Cascade(config)
    from autosxtract.engines.paddle import PaddleEngine
    from autosxtract.steps import NativeStep, OCRStep

    engine = PaddleEngine(det=args.det or "tiny", rec=args.rec, rec_dir=args.rec_dir)
    return Cascade(config, steps=[NativeStep(), OCRStep(engine)])


def _has_geometry(engine) -> bool:
    """Does the engine implement the detailed contract? It decides whether the layers run."""
    from autosxtract.engines.base import OCREngine

    return type(engine).read_page is not OCREngine.read_page


def _cmd_diagnose(_args: argparse.Namespace) -> int:
    from autosxtract import platform, resources
    from autosxtract.config import Config
    from autosxtract.engines import base as engines
    from autosxtract.engines import models

    print(f"autosxtract {__version__}")
    print(f"machine    {platform.describe()}")
    print(f"resources  {resources.describe()}")

    cfg = Config()
    documents, pages = cfg.batch_concurrency()
    print(
        f"automatic parallelism: {pages} page(s) per document, "
        f"{documents} document(s) in flight (aggregate cap {resources.concurrency_cap()})"
    )
    print()
    print("engines:")
    for name, ok, reason in engines.diagnose():
        engine = engines.get(name)
        notes = []
        if not engine.scales_with_threads:
            notes.append("single queue: ignores threads")
        if ok and not _has_geometry(engine):
            notes.append("no line geometry: the layers do not run")
        suffix = f"  ({'; '.join(notes)})" if notes else ""
        print(f"  [{'x' if ok else ' '}] {name:12} {reason}{suffix}")
    print()
    print(f"cascade:   {' -> '.join(Cascade().names)}")
    if not engine_order():
        print()
        print("  WARNING: no OCR engine available. Only the native text layer")
        print("  will be read — a scanned PDF will come out empty. Install:")
        print("    pip install --force-reinstall autosxtract")
        print("    macOS, if pyobjc is broken: pip install 'autosxtract[apple]'")
    print()
    state = "complete" if models.complete() else "missing"
    print(f"models:    {models.directory()}  ({state})")
    return 0


def _cmd_download(_args: argparse.Namespace) -> int:
    from autosxtract.engines import models

    try:
        paths = models.download()
    except Exception as exc:
        # The message is this command's product.
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    for key, path in paths.items():
        if path.is_file():
            print(f"  {key:5} {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autosxtract", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("extract", help="extract text from one or more PDFs")
    p.add_argument("files", nargs="*", type=Path)
    p.add_argument("--dpi", type=int, default=150, help="render resolution (default 150)")
    p.add_argument("--engines", help="explicit order, comma-separated")
    p.add_argument("--det", help="PP-OCR detector tier (tiny/small/medium)")
    p.add_argument("--rec", help="recogniser tier; defaults to the detector's")
    p.add_argument("--rec-dir", dest="rec_dir", help="directory of your own recogniser")
    p.add_argument("--no-layers", action="store_true", help="turn line containment off")
    p.add_argument("--routes", action="store_true", help="classify each page's type")
    p.add_argument(
        "--parallelism",
        type=int,
        default=None,
        help="threads per document (default: decided by the machine)",
    )
    p.add_argument("--json", help="write the full result to this file")
    p.set_defaults(func=_cmd_extract)

    p = sub.add_parser("diagnose", help="what this machine can run")
    p.set_defaults(func=_cmd_diagnose)

    p = sub.add_parser("download-models", help="download the PP-OCRv6 tiny weights")
    p.set_defaults(func=_cmd_download)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
