# 0010 — Parallelism is decided by the machine, not by the code

**Status:** accepted · **Relates to:** CLAUDE.md §14

## Context

The same library runs on a two-core laptop and a seventy-two-core server. One
fixed thread count serves both badly, and the measured curve is not the one
intuition draws: it flattens early, and past the plateau more threads deliver
*less*.

## Decision

`page_parallelism`, `document_parallelism` and `concurrency_cap` accept `None`,
meaning **decide from this machine**, and that is the default. An explicit number
is obeyed — whoever knows what they are doing decides. What it is not, is a
promise.

Resolution is a **method** (`config.pages_in_flight()`), not a field computed in
the constructor: the machine that resolves may not be the one that serialised the
configuration.

## Consequences

- **`os.cpu_count()` lies inside a container.** It reports the host, not the
  quota. `resources.cores()` crosses affinity, cgroup v1/v2 and `cpu_count` and
  keeps the smallest — none of the three alone covers `taskset` **and**
  `--cpus`.
- **The product multiplies silently.** `documents × pages` reaches 32 pages in
  flight from values that look modest, each holding a rendered image and the
  model's activations. The aggregate cap cuts the **pages**, never the documents:
  cutting documents raises total time predictably, cutting pages costs almost
  nothing.
- **The engine has the last word.** Whoever configures the cascade cannot see
  whether a hardware queue sits behind it, so `Engine.scales_with_threads = False`
  makes the engine use one thread. `OCRStep` records the **effective** value in
  the provenance when it differs from the requested one — clamping silently would
  be the same antipattern as a hidden network call.
- That declaration is a good default and a bad law: it was measured on one
  machine, and registered engines are built with no arguments. `engine_parallelism`
  is the operator's override.

## Evidence

PP-OCRv6 tiny, 12 real pages, the same machine restricted with `taskset`:

| threads | 72 cores | 2 cores |
|---|---|---|
| 1 | 1.36 pg/s | 1.44 pg/s |
| 2 | 1.74 | **1.68** ← plateau |
| 4 | **1.99** | 1.58 |
| 8 | 2.18 | 1.54 ← worse than 2 threads |
| 16 | 2.27 | 1.71 |

On 2 cores, asking for 8 threads delivers **less** than 2 (1.54 against 1.68)
with four times more pages in flight. On 72, going from 4 to 16 gains 1.14×.

Apple's Neural Engine, 1 to 12 threads: **constant throughput at ~2.5 pages/s,
latency from 430 ms to 3,492 ms.** A single hardware queue turns parallelism into
stacked waiting.
