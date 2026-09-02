"""The PyMuPDF serialisation — CLAUDE.md §6, and not negotiable.

PyMuPDF **crashes the process** with several threads: a segfault in
``page_get_textpage``, reproduced with 489 PDFs across 12 threads. ``try/except``
does not protect you, because a segmentation fault is not a Python exception —
which is exactly why this has to be a structural test rather than a stress test.
A stress test that happens not to crash proves nothing, and one that does crash
takes the runner with it and reports nothing at all.

So what is pinned here is the STRUCTURE: the lock is reentrant, it actually
serialises, and every function in ``pdf/`` that opens a document acquires it.
The last one is checked by reading the source, because that is the only check
that stays true for a function somebody adds next month.

Before this file, ``pdf/lock.py`` had no test at all: replacing the ``RLock``
with a no-op, or dropping a ``with pdf_lock():`` from one module, left the whole
suite green and brought the segfault back in production only.
"""

from __future__ import annotations

import ast
import pathlib
import threading
import time

from autosxtract.pdf.lock import pdf_lock

_PACKAGE = pathlib.Path(__file__).resolve().parents[2] / "autosxtract"
_PDF_DIR = _PACKAGE / "pdf"
#: Every module in the package that opens a PyMuPDF document. ``pdf/`` is the
#: layer that owns the file, but two callers outside it open documents of their
#: own — ``steps/native.py`` reads the text layer and ``engines/tesseract.py``
#: rasterises for the witness — and a sweep scoped to ``pdf/*.py`` would have
#: declared a clean result while never reading either. §6 is about the process
#: segfaulting, and the process does not care which package the call came from.
_OPENERS = [
    *sorted(_PDF_DIR.glob("*.py")),
    _PACKAGE / "steps" / "native.py",
    _PACKAGE / "engines" / "tesseract.py",
]


def test_the_lock_is_reentrant():
    """Nested acquisition is normal here: ``subdocument`` holds it and calls
    ``count``. A plain ``Lock`` would deadlock the first time that happened."""
    with pdf_lock(), pdf_lock():
        pass


def test_it_actually_serialises():
    """Two threads must not be inside the guarded region at the same time.

    The critical section has to contain a **yield point**, or this test measures
    the GIL rather than the lock: an increment and a decrement a few bytecodes
    apart are effectively atomic, and the first version of this test passed
    200/200 with ``pdf_lock`` replaced by a bare ``yield``. The ``sleep`` is what
    forces the interleaving a missing lock would produce.
    """
    inside = 0
    peak = 0
    guard = threading.Lock()

    def worker() -> None:
        nonlocal inside, peak
        for _ in range(5):
            with pdf_lock():
                with guard:
                    inside += 1
                    peak = max(peak, inside)
                # The yield point. Without a real lock every thread is in here.
                time.sleep(0.005)
                with guard:
                    inside -= 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert peak == 1, f"{peak} threads were inside the guarded region at once"


# ── every document opened in pdf/ is opened under the lock ───────────────


def _functions_that_open(path: pathlib.Path) -> list[tuple[str, bool]]:
    """``(function name, opens a document under a ``with pdf_lock()``)``.

    Read from the AST rather than by grepping, so that a ``mupdf().open`` moved
    out of the ``with`` block by one indentation level is still caught.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, bool]] = []

    for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        # ``mupdf()`` is reached two ways, and both have to count: directly, as
        # ``mupdf().open(...)``, and through a local — ``pymupdf = mupdf()``
        # followed by ``pymupdf.open(...)``, which is what ``steps/native.py``
        # and ``pdf/profile.py`` do. A checker that only knew the first form
        # would report a clean sweep while covering half the call sites.
        aliases = {
            target.id
            for node in ast.walk(func)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "mupdf"
            for target in node.targets
            if isinstance(target, ast.Name)
        }

        def _is_mupdf_open(node: ast.AST, aliases: set[str] = aliases) -> bool:
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                return False
            if node.func.attr != "open":
                return False
            receiver = node.func.value
            if isinstance(receiver, ast.Name):
                return receiver.id in aliases
            return (
                isinstance(receiver, ast.Call)
                and isinstance(receiver.func, ast.Name)
                and receiver.func.id == "mupdf"
            )

        opens = [node for node in ast.walk(func) if _is_mupdf_open(node)]
        if not opens:
            continue
        guarded = {
            id(node)
            for with_stmt in ast.walk(func)
            if isinstance(with_stmt, ast.With)
            and any(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Name)
                and item.context_expr.func.id == "pdf_lock"
                for item in with_stmt.items
            )
            for node in ast.walk(with_stmt)
        }
        out.append((func.name, all(id(node) in guarded for node in opens)))
    return out


def test_every_module_opens_documents_under_the_lock():
    """The measured cost of serialising is ~4% (37.2 s on 4 threads against
    38.6 s on 24). The useful parallelism is per DOCUMENT, and one unguarded
    ``open`` is enough to bring the segfault back."""
    unguarded: list[str] = []
    checked = 0
    for path in _OPENERS:
        for name, guarded in _functions_that_open(path):
            checked += 1
            if not guarded:
                unguarded.append(f"{path.name}::{name}")
    assert checked > 0, "the AST walk found no mupdf().open at all — it stopped checking"
    assert unguarded == []
