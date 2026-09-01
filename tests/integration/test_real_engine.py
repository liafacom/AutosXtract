"""The cascade against the real engine installed on this machine.

These tests are skipped when there is no OCR engine — which is the default CI
case. Running them locally is what proves the engine contract closes with the
real implementation, and not only with the fakes.
"""

from __future__ import annotations

import pytest

from autosxtract.cascade import Cascade, engine_order
from autosxtract.config import Config

no_engine = pytest.mark.skipif(not engine_order(), reason="no OCR engine installed on this machine")


@no_engine
@pytest.mark.slow
def test_a_scanned_page_is_read_by_the_real_engine(pdf_scanned):
    """The synthetic image has dark bands, not letters: the engine finds no text.

    What is checked here is not OCR accuracy but that the cascade descends,
    calls the real engine and closes with provenance — no exception, no hang.
    """
    r = Cascade().extract(pdf_scanned)
    assert r.attempts[0].step == "native"
    assert len(r.attempts) > 1
    assert all(a.reason for a in r.attempts)


@no_engine
@pytest.mark.slow
def test_native_text_does_not_call_the_real_engine(pdf_with_text):
    """The cheap path has to stay cheap even with an engine installed."""
    r = Cascade().extract(pdf_with_text)
    assert r.step == "native"
    assert len(r.attempts) == 1


def test_a_batch_preserves_the_file_to_result_mapping(tmp_path, pdf_with_text):
    paths = []
    for i in range(3):
        p = tmp_path / f"document_{i}.pdf"
        p.write_bytes(pdf_with_text)
        paths.append(p)
    results = Cascade(Config(engines=[])).extract_batch(paths)
    assert set(results) == {"document_0.pdf", "document_1.pdf", "document_2.pdf"}
    assert all(r.step == "native" for r in results.values())
