"""Steps that talk to an external service — **by explicit instantiation**.

This is the only part of the library that opens a socket, and it was designed so
that cannot happen by accident:

- None of these steps is in the default cascade. ``Cascade()`` assembles only
  local steps, and ``Config`` has not a single host, port, URL or credential
  field.
- Each one requires ``url`` in the constructor. There is no discovery through an
  environment variable, no built-in default, no silent fallback to a known
  endpoint.
- Whoever wants them builds them and passes them: ``Cascade(steps=[...])``.

The reason is a measurement, not a preference. In the previous architecture the
engine that resolved 64% of the documents lived behind an SSH tunnel, and its
going down **silently degraded the text** — 488 documents re-extracted down the
worse path, 19.5 min instead of 4.9, 28,239 characters lost, and nobody noticed
until someone checked. A remote step nobody declared must not exist.

They are all ``expensive = True``, which makes the cascade run the five vetoes
from ``quality.vetoes`` before calling them, and submit the result to
``quality.rejection`` afterwards.

Requires ``httpx``: ``pip install 'autosxtract[remote]'``.
"""

from __future__ import annotations

import base64
import time
from concurrent.futures import ThreadPoolExecutor

from autosxtract.interfaces import DocumentContext
from autosxtract.quality.response import DEFAULT_PROMPT, response_blocks
from autosxtract.quality.scoring import score_text
from autosxtract.steps.base import StepResult
from autosxtract.steps.docling_json import final_text, text_by_page
from autosxtract.types import Attempt, Candidate

# Wait before the second poll (the first is immediate); it doubles from there up
# to the ceiling. The ceiling is small on purpose: with 3 s the poll instants
# would land at 0.75 / 1.75 / 3.75 / 6.75, and a conversion finishing in 2.9 s
# would be discovered at 3.75 s — worse than the fixed interval it replaced.
# With a 0.5 s ceiling detection is always quick and the cost is one dictionary
# lookup over the wire every half second.
_POLL_INITIAL = 0.25
_POLL_CEILING = 0.5


def _default_options(language: str) -> dict[str, list[str] | str]:
    """What to send ``docling-serve``, and why.

    Without explicit options the service applies its own defaults, and two of
    them are expensive:

    - ``to_formats`` **must** include ``json``. On a scanned page the OCR text
      ends up orphaned outside ``body`` and vanishes from the markdown; the
      structured document is the only place it survives. Asking for ``md`` alone
      leaves the orphaned-text recovery with nothing to recover.
    - ``table_mode`` drops from ``accurate`` (the service default) to ``fast``.
      Measured on 10 documents against the real service: 1.12x faster **and with
      more text** (29,956 against 25,517 characters), preserving 100% of the
      slow variant's words. This is not trading quality for speed — the slow
      mode was not yielding more content.

    Lists travel in ``multipart/form-data`` as repeated fields; serialising them
    with ``json.dumps`` makes the service answer HTTP 422.
    """
    return {"to_formats": ["md", "json"], "ocr_lang": [language], "table_mode": "fast"}


class RemoteStep:
    """The base for steps that speak HTTP: credential, timeout and client.

    ``token`` never appears in ``repr``, in a log or in provenance — the
    extraction's result circulates, and a credential must not circulate with it.
    """

    name = "remote"
    #: The cascade runs the vetoes before and the rejection gate after.
    expensive = True

    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        timeout: float = 120.0,
        headers: dict[str, str] | None = None,
        verify_ssl: bool = True,
    ) -> None:
        if not url:
            raise ValueError(f"{type(self).__name__} requires a url")
        self.url = url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.verify_ssl = verify_ssl

    def __repr__(self) -> str:
        return f"{type(self).__name__}(url={self.url!r}, token={'***' if self._token else None})"

    def _client(self):
        try:
            import httpx
        except ImportError as exc:
            raise RuntimeError(
                "httpx missing; install with pip install 'autosxtract[remote]'"
            ) from exc
        headers = dict(self.headers)
        if self._token:
            headers.setdefault("Authorization", f"Bearer {self._token}")
        return httpx.Client(timeout=self.timeout, headers=headers, verify=self.verify_ssl)


class DoclingStep(RemoteStep):
    """Conversion through ``docling-serve`` — the intermediate step.

    It costs ~4 s per document with ``force_ocr`` and resolves 1 to 2% of an
    archive: the documents the cheap engines read badly and that do not justify a
    vision model. Measured on the 8 tax-query documents of one case file, it
    reads less than half of what a VLM does (406 against 942 real characters),
    but 11x faster — and on a tabular document it comes out **better**, because
    it preserves the structure.

    The ``force_ocr`` retry costs one extra conversion, paid **only** on the
    documents that would otherwise end up with zero characters.
    """

    name = "docling"

    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        timeout: float = 60.0,
        conversion_timeout: int = 180,
        poll_ceiling: float = _POLL_CEILING,
        force_ocr_if_empty: bool = True,
        per_page: bool = True,
        ocr_language: str = "pt",
        options: dict[str, list[str] | str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(url=url, token=token, timeout=timeout, **kwargs)
        self.conversion_timeout = conversion_timeout
        self.poll_ceiling = poll_ceiling
        self.force_ocr_if_empty = force_ocr_if_empty
        self.per_page = per_page
        self.options = dict(options or _default_options(ocr_language))
        # ``force_ocr`` stays OUT of the first pass: on a scanned page it
        # changes nothing (OCR already runs; the defect is in the export) and
        # forcing it on every document would multiply the archive's conversion
        # cost.
        self.force_options = dict(self.options, force_ocr="true")

    def run(self, ctx: DocumentContext) -> StepResult:
        t0 = time.perf_counter()
        details: dict = {}
        try:
            target, missing = self._target(ctx)
            if missing is not None:
                details["converted_pages"] = missing
            text, recovered, structured = self._convert(target, self.options)
            if self.force_ocr_if_empty and len(text.strip()) < 32:
                forced, forced_recovered, forced_structured = self._convert(
                    target, self.force_options
                )
                if len(forced.strip()) > len(text.strip()):
                    text, recovered, structured = forced, forced_recovered, forced_structured
                    details["force_ocr"] = True
            if recovered:
                # The markdown came back empty and the text was reassembled from
                # the structured document. Without this note, a server
                # regression would look like a document with no content.
                details["orphaned_text_recovered"] = True
            if missing is not None and text.strip():
                text = self._reassemble(ctx, text, missing, structured)
        except Exception as exc:
            # A remote step never brings the cascade down: the failure becomes a
            # reason in the provenance and the document keeps what it had.
            ms = (time.perf_counter() - t0) * 1000
            return StepResult(Attempt(self.name, False, f"failed: {exc}"[:160], 0, ms, details))

        ms = (time.perf_counter() - t0) * 1000
        if not text.strip():
            return StepResult(Attempt(self.name, False, "empty conversion", 0, ms, details))
        ctx.record_reading(self.name, text)
        return StepResult(
            Attempt(self.name, True, "converted", len(text), ms, details),
            Candidate(self.name, text, score_text(text)["score"], ms, details),
        )

    def _target(self, ctx: DocumentContext) -> tuple[bytes, list[int] | None]:
        """What to send: the whole document, or only the pages without native text.

        In a mixed PDF — part digitally generated, part scanned attachment —
        converting everything is waste, and this step charges per page. Measured:
        of the 419 pages that went through OCR on a real case file, 54 (12.9%)
        already had native text.

        ``(bytes, None)`` when there is nothing to save.
        """
        from autosxtract.pdf.pages import count, subdocument

        if not self.per_page:
            return ctx.pdf_bytes, None
        missing = ctx.pages_without_text
        if not missing or len(missing) >= count(ctx.pdf_bytes):
            return ctx.pdf_bytes, None
        cut = subdocument(ctx.pdf_bytes, missing)
        if cut is None:
            return ctx.pdf_bytes, None
        return cut, missing

    @staticmethod
    def _reassemble(
        ctx: DocumentContext, converted: str, missing: list[int], structured: dict | None = None
    ) -> str:
        """Return each converted page to its position in the document.

        Concatenating the native text with the converted one scrambles the
        reading in a PDF where native and scanned pages alternate — and a wrong
        order is worse than a wasted conversion.
        """
        from autosxtract.steps.native import read_native_text

        _, native = read_native_text(ctx.pdf_bytes)
        if not native:
            return converted
        # The subdocument numbers its pages 1 to N; the real position in the
        # document is ``missing[n-1]``.
        #
        # The preferred source is the structured document, which says which page
        # each passage belongs to. Without it, splitting the markdown into
        # paragraphs is an approximation — hence a last resort only.
        by_page = text_by_page(structured)
        if by_page:
            by_index = {
                missing[n - 1]: block for n, block in by_page.items() if 1 <= n <= len(missing)
            }
        else:
            blocks = [b for b in converted.split("\n\n") if b.strip()]
            by_index = {missing[i]: block for i, block in enumerate(blocks) if i < len(missing)}
        out: list[str] = []
        for i, page in enumerate(native):
            if i in by_index:
                out.append(by_index[i])
            elif page["text"].strip():
                out.append(page["text"])
        return "\n\n".join(out) if out else converted

    def _convert(self, pdf_bytes: bytes, options: dict) -> tuple[str, bool, dict | None]:
        with self._client() as client:
            response = client.post(
                f"{self.url}/v1/convert/file/async",
                files={"files": ("document.pdf", pdf_bytes, "application/pdf")},
                data=options,
            )
            response.raise_for_status()
            task = response.json().get("task_id")
            if not task:
                raise RuntimeError("docling-serve returned no task_id")

            # First poll immediate, then progressive backoff.
            deadline = time.monotonic() + self.conversion_timeout
            wait = 0.0
            while time.monotonic() < deadline:
                if wait:
                    time.sleep(wait)
                wait = min(max(wait * 2, _POLL_INITIAL), self.poll_ceiling)
                try:
                    state = (
                        client.get(f"{self.url}/v1/status/poll/{task}").json().get("task_status")
                    )
                except Exception:
                    # A lost poll is not a failure of the task.
                    continue
                if state == "success":
                    break
                if state == "failure":
                    raise RuntimeError(f"task {task} finished with failure")
            else:
                raise RuntimeError(f"timeout after {self.conversion_timeout}s (task {task})")

            document = client.get(f"{self.url}/v1/result/{task}").json().get("document") or {}
            md = document.get("md_content") or ""
            # Empty markdown (or only an image marker) with a filled structured
            # document means the OCR text was orphaned outside ``body``.
            # Reassemble from it; otherwise keep the markdown.
            structured = document.get("json_content")
            text, recovered = final_text(md, structured)
            if not text.strip():
                text = document.get("text_content") or ""
            return text, recovered, structured


class VLMStep(RemoteStep):
    """Transcription by a vision model, through an OpenAI-compatible API.

    The most expensive step there is: measured at 47.4 s per document (maximum
    83.8 s) with a 27B model. It exists for the **residue** — 1.6 to 1.7% of an
    archive's documents — never for the common case, which is why the five
    vetoes run before it.

    About the model: a 27-billion-parameter model transcribing a sheet of paper
    is measured waste. Specialised OCR models in the 0.5-3B range (GLM-OCR 0.9B,
    PaddleOCR-VL 0.9B, dots.ocr 1.7B, DeepSeek-OCR 3B, GOT-OCR2.0 0.58B) are
    built for exactly this case and promise ~100x — from 759 s of engine time to
    ~7 s across the 16 documents that escalated. That is why ``model`` is a
    parameter, not a constant.

    Small batches by default: a document page is dense, and sending many at once
    makes the model truncate the last ones within the token budget. The budget is
    **per page** and multiplied by the batch size — with a fixed per-batch
    ceiling, the last pages came back cut off mid-way.
    """

    name = "vlm"

    def __init__(
        self,
        *,
        url: str,
        model: str,
        token: str | None = None,
        prompt: str = DEFAULT_PROMPT,
        dpi: int = 200,
        images_per_batch: int = 2,
        max_tokens_per_page: int = 2000,
        parallelism: int = 1,
        max_pages: int = 32,
        temperature: float = 0.0,
        fix_rotation: bool = True,
        path: str = "/chat/completions",
        **kwargs,
    ) -> None:
        super().__init__(url=url, token=token, **kwargs)
        if not model:
            raise ValueError("VLMStep requires a model")
        self.model = model
        self.prompt = prompt
        self.dpi = dpi
        self.images_per_batch = max(1, images_per_batch)
        self.max_tokens_per_page = max_tokens_per_page
        self.parallelism = max(1, parallelism)
        self.max_pages = max_pages
        self.temperature = temperature
        self.fix_rotation = fix_rotation
        self.path = path

    def run(self, ctx: DocumentContext) -> StepResult:
        from autosxtract.pdf.render import render

        t0 = time.perf_counter()
        # Its own DPI: the expensive step deserves higher resolution than the
        # cheap ones, which is why it does not reuse the context's cache.
        images = render(ctx.pdf_bytes, dpi=self.dpi, max_pages=self.max_pages, grayscale=False)
        if not images:
            return StepResult(Attempt(self.name, False, "no page rasterised"))

        if self.fix_rotation:
            from autosxtract.pdf.orientation import fix

            images = [fix(i)[0] for i in images]

        batches = [
            images[i : i + self.images_per_batch]
            for i in range(0, len(images), self.images_per_batch)
        ]
        if self.parallelism > 1 and len(batches) > 1:
            # ``map`` rather than ``as_completed``: batch order is page order,
            # and reassembling out of order would scramble the document.
            with ThreadPoolExecutor(max_workers=min(self.parallelism, len(batches))) as pool:
                responses = list(pool.map(self._transcribe_batch, batches))
        else:
            responses = [self._transcribe_batch(batch) for batch in batches]

        parts: list[str] = []
        failed_batches = 0
        answered = 0
        for batch, blocks in zip(batches, responses, strict=True):
            if not blocks:
                failed_batches += 1
                continue
            parts.extend(blocks)
            # Coverage is measured in PAGES SENT in the batch, not in blocks
            # returned: the model does not always obey "one block per page", and
            # counting blocks made a 2-page batch answered in a single block look
            # like a partial transcription — which rejected the replacement and
            # turned the step into a no-op against precisely the disobedient
            # model it was meant to compensate for.
            answered += len(batch)

        ms = (time.perf_counter() - t0) * 1000
        if not parts:
            return StepResult(Attempt(self.name, False, "no batch answered", 0, ms))

        text = "\n\n".join(parts)
        details = {
            "model": self.model,
            "pages_sent": len(images),
            "pages_answered": answered,
            "failed_batches": failed_batches,
            "blocks": len(parts),
        }
        ctx.record_reading(self.name, text)
        return StepResult(
            Attempt(self.name, True, "transcribed", len(text), ms, details),
            Candidate(self.name, text, score_text(text)["score"], ms, details),
        )

    def _transcribe_batch(self, batch: list[bytes]) -> list[str]:
        content: list[dict] = [{"type": "text", "text": self.prompt}]
        for image in batch:
            b64 = base64.b64encode(image).decode("ascii")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            )
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": self.temperature,
            # Proportional to the batch: N pages need N budgets.
            "max_tokens": self.max_tokens_per_page * len(batch),
        }
        try:
            with self._client() as client:
                response = client.post(f"{self.url}{self.path}", json=body)
                response.raise_for_status()
                data = response.json()
            raw = data["choices"][0]["message"]["content"]
        except Exception:
            # A lost batch does not bring the document down.
            return []
        return response_blocks(raw)
