"""How many cores this machine really has — and why the question is subtle.

The library needs this to pick parallelism when nobody picked it. Getting it
wrong breaks nothing, but it costs in both directions: too low wastes a big
machine; too high floods a small one with threads that fight over the same core
and multiply memory on top.

``os.cpu_count()`` **lies inside a container**, which is where this pipeline
usually runs: it reports the host's cores, not the container's quota. A pod
with 2 CPUs on a 72-core machine gets told 72 — and opens 72 threads to fight
over 2.

So the reading is the most restrictive of three sources:

    affinity      ``sched_getaffinity`` — honours ``taskset`` and cpusets
    cgroup quota  v2 ``cpu.max`` and v1 ``cpu.cfs_quota_us`` — honours ``--cpus``
    cpu_count     last resort, when neither of the others answers

None of them covers every case alone. ``taskset -c 0,1`` shows up only in the
affinity; ``docker run --cpus=2`` only in the quota.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

#: Ceiling for automatically chosen parallelism. Above this the measured gain
#: is marginal and the memory cost is not: from 1 to 4 threads throughput rises
#: 1.5x; from 4 to 16, only 1.14x — and that on a 72-core machine. Anyone with
#: the hardware for more asks explicitly.
AUTO_CEILING = 4

#: Multiplier for the aggregate concurrency cap in batch processing. The
#: product ``documents x pages`` grows without anyone noticing: 4 x 8 is 32
#: pages in flight, each holding a rendered image and the model's activations.
#: On a small machine the memory limit arrives before the CPU limit.
CONCURRENCY_FACTOR = 2


def _by_affinity() -> int | None:
    """Cores this process may run on. Honours ``taskset`` and cpusets."""
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:
        # macOS and Windows do not expose it.
        return None
    except OSError:
        return None


def _by_cgroup() -> int | None:
    """The container's CPU quota, in cores. ``None`` when there is no quota.

    Reads cgroup v2 and v1. A quota of ``200000/100000`` means "2 CPUs"; the
    value is rounded up because half a CPU still executes, and rounding down
    would yield zero for a fractional quota.
    """
    v2 = Path("/sys/fs/cgroup/cpu.max")
    try:
        if v2.is_file():
            raw, period_v2 = v2.read_text().split()
            if raw != "max":
                return max(1, -(-int(raw) // int(period_v2)))
    except (OSError, ValueError):
        pass

    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0 and period > 0:
            return max(1, -(-quota // period))
    except (OSError, ValueError):
        pass
    return None


@functools.cache
def cores() -> int:
    """Cores usable by this process. Never fewer than 1.

    Cached: the answer does not change during the process's life, and the
    reading touches the filesystem.
    """
    candidates = [n for n in (_by_affinity(), _by_cgroup(), os.cpu_count()) if n]
    return max(1, min(candidates)) if candidates else 1


def default_parallelism(ceiling: int = AUTO_CEILING) -> int:
    """How many threads to use when nobody chose.

    Never exceeds the available cores or the ceiling. On a 2-core machine it
    returns 2; on a 72-core one it returns the ceiling, because the measured
    curve flattens well before that.
    """
    return max(1, min(ceiling, cores()))


def concurrency_cap(factor: int = CONCURRENCY_FACTOR) -> int:
    """Maximum pages in flight across every document in the batch."""
    return max(1, cores() * factor)


def describe() -> str:
    """One line about the resources, for the CLI's ``diagnose``."""
    parts = [f"{cores()} usable core(s)"]
    affinity, quota, total = _by_affinity(), _by_cgroup(), os.cpu_count()
    if total and affinity and affinity < total:
        parts.append(f"affinity limits to {affinity} of {total}")
    if quota:
        parts.append(f"cgroup quota: {quota}")
    return "; ".join(parts)
