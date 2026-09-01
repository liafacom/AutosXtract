"""Parallelism: the same library on a 2-core laptop and a 72-core server.

The measured curve is what justifies the defaults. On 2 cores throughput
plateaus at 2 threads (1.68 pages/s) and 8 delivers 1.54 — less, with 4x more
pages in flight. On 72 cores, going from 4 to 16 threads gains 1.14x. One fixed
number serves both badly, and a high number is never a promise.
"""

from __future__ import annotations

import pytest

from autosxtract import resources
from autosxtract.config import Config


@pytest.fixture
def machine(monkeypatch):
    """Pretend a core count, clearing the detection cache."""

    def define(n: int) -> None:
        resources.cores.cache_clear()
        monkeypatch.setattr(resources, "_by_affinity", lambda: n)
        monkeypatch.setattr(resources, "_by_cgroup", lambda: None)
        monkeypatch.setattr("os.cpu_count", lambda: n)

    yield define
    resources.cores.cache_clear()


# ── detection ────────────────────────────────────────────────────────────


def test_it_never_returns_less_than_one(machine):
    machine(0)
    assert resources.cores() >= 1


def test_the_most_restrictive_source_wins(monkeypatch):
    """``os.cpu_count`` LIES in a container: it reports the host, not the quota."""
    resources.cores.cache_clear()
    monkeypatch.setattr(resources, "_by_affinity", lambda: 72)
    monkeypatch.setattr(resources, "_by_cgroup", lambda: 2)
    monkeypatch.setattr("os.cpu_count", lambda: 72)
    assert resources.cores() == 2
    resources.cores.cache_clear()


def test_affinity_also_limits(monkeypatch):
    """``taskset -c 0,1`` shows in the affinity and not in the quota."""
    resources.cores.cache_clear()
    monkeypatch.setattr(resources, "_by_affinity", lambda: 2)
    monkeypatch.setattr(resources, "_by_cgroup", lambda: None)
    monkeypatch.setattr("os.cpu_count", lambda: 72)
    assert resources.cores() == 2
    resources.cores.cache_clear()


# ── automatic resolution ─────────────────────────────────────────────────


def test_a_small_machine_does_not_overflow(machine):
    machine(2)
    assert resources.default_parallelism() == 2
    assert Config().pages_in_flight() == 2


def test_a_large_machine_stops_at_the_ceiling(machine):
    """From 4 to 16 threads the measured gain is 1.14x — not worth the memory."""
    machine(72)
    assert resources.default_parallelism() == resources.AUTO_CEILING
    assert Config().pages_in_flight() == 4


def test_a_single_core_machine(machine):
    machine(1)
    assert Config().batch_concurrency() == (1, 1)


# ── explicit choice ──────────────────────────────────────────────────────


def test_an_explicit_number_is_obeyed(machine):
    """Whoever knows what they are doing decides."""
    machine(2)
    assert Config(page_parallelism=8).pages_in_flight() == 8


def test_the_aggregate_cap_cuts_the_product(machine):
    """4 x 8 is 32 pages in flight, each holding an image and activations."""
    machine(2)  # aggregate cap = 4
    documents, pages = Config(document_parallelism=4, page_parallelism=8).batch_concurrency()
    assert documents * pages <= 4


def test_the_cap_cuts_pages_and_not_documents(machine):
    """Cutting documents raises total time; cutting pages costs almost nothing."""
    machine(2)
    documents, pages = Config(document_parallelism=4, page_parallelism=8).batch_concurrency()
    assert documents == 4
    assert pages == 1


def test_the_cap_can_be_turned_off(machine):
    machine(2)
    assert Config(
        document_parallelism=4, page_parallelism=8, concurrency_cap=0
    ).batch_concurrency() == (4, 8)


def test_a_large_machine_is_not_cut(machine):
    machine(72)  # aggregate cap = 144
    assert Config(document_parallelism=4, page_parallelism=8).batch_concurrency() == (4, 8)


def test_the_config_is_portable_between_machines(machine):
    """The same YAML preset must answer differently in each environment.

    That is why resolution is a method rather than a field computed in the
    constructor.
    """
    config = Config()
    machine(72)
    large = config.pages_in_flight()
    machine(2)
    assert config.pages_in_flight() == 2 < large


# ── cgroup reading (containers) ──────────────────────────────────────────


def test_cgroup_v2_with_a_quota(tmp_path, monkeypatch):
    """``docker run --cpus=2`` becomes ``200000 100000`` in ``cpu.max``."""
    file = tmp_path / "cpu.max"
    file.write_text("200000 100000")
    monkeypatch.setattr(resources, "Path", lambda p: file if "cpu.max" in p else tmp_path / "x")
    assert resources._by_cgroup() == 2


def test_cgroup_v2_without_a_quota(tmp_path, monkeypatch):
    """``max`` means "no limit" — it is not a core count."""
    file = tmp_path / "cpu.max"
    file.write_text("max 100000")
    monkeypatch.setattr(resources, "Path", lambda p: file if "cpu.max" in p else tmp_path / "x")
    assert resources._by_cgroup() is None


def test_a_fractional_quota_rounds_up(tmp_path, monkeypatch):
    """Half a CPU still executes; rounding down would give zero."""
    file = tmp_path / "cpu.max"
    file.write_text("50000 100000")
    monkeypatch.setattr(resources, "Path", lambda p: file if "cpu.max" in p else tmp_path / "x")
    assert resources._by_cgroup() == 1


def test_a_missing_cgroup_does_not_break(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "Path", lambda p: tmp_path / "does-not-exist")
    assert resources._by_cgroup() is None
