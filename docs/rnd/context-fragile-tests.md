# Context-fragile tests — wall-clock assumptions in `tests/` (fix-later list)

> **Read-only sweep (W99 verim+hızlandırma paketi).** Nothing below was
> modified in this wave — this is the ranked backlog for a dedicated
> deterministic-hardening wave. Sweep method: grep `tests/` for
> `perf_counter`, `time.time()` comparisons, timing-bound assertions, and
> sleep-based synchronization; read each hit in context; keep only tests whose
> RESULT can change under machine load (score-threshold assertions like
> `assert value < 0.34` are pure arithmetic and were cleared).

## The chunk-12 lesson (why this list exists)

During a full gate in this session, **chunk 12 went RED on a wall-clock
assertion while concurrent work loaded the container — re-run alone, it was
green.** The test was using *elapsed time as a proxy* for a property that is
actually deterministic; under load the proxy lies. The durable fix is always
the same: **replace the timing proxy with the deterministic invariant it
stands for** (count the operations, freeze the clock, poll for the state —
never assert the stopwatch). The standing operational rule recorded in
`docs/PROGRESS.md` says the same thing from the other side:

> "Gate'i GERÇEKTEN yalnız koştur: gate#2 ile eşzamanlı 10 read-only ajan bile
> yük-duyarlı flakiness üretti (pin_doctest/scaffold iki koşuda yer
> değiştirdi)."

Both halves hold until this list is burned down: **run the gate alone** (the
process rule), and **make these tests load-immune** (the durable fix).
Findings are keyed by file+line, not chunk number — chunk membership shifts
whenever a test file is added (today, with 1141 files in 16 chunks, the #1
finding partitions into chunk 14).

## Ranked findings (highest flake risk first)

| # | Test | Wall-clock assumption | Deterministic fix direction |
|---|------|----------------------|-----------------------------|
| 1 | `tests/test_simplification_scan_perf_eyml.py:283-294` | Measures two `perf_counter` spans and asserts a **speedup ratio** `factor >= 1.5` (in-memory scan vs temp-dir rescan). Both numerator and denominator move under load; the ratio can dip below 1.5 with zero code change. | Assert the invariant the speedup comes FROM: the in-memory path performs **no per-file temp-dir writes/re-reads** (count filesystem calls with a shim), keeping the existing equal-output assertion. Timing print can stay informational. |
| 2 | `tests/test_swarm_stability.py:15-35` | Real `threading` timer (0.5s) raced against `time.sleep(0.6)` — a **100ms margin** decides whether the callback fired / was cancelled in time. Also `:69-118`: work must complete inside 0.5–2.0s deadlines. | Inject/freeze the timer clock (the pattern `tests/test_swarm_coordinator_charz.py` already uses) or wait on an `Event` set by the callback; assert *fired/not-fired*, never *fired-within-margin*. |
| 3 | `tests/test_mcp_http_server.py:36`, `tests/test_marketplace.py:18` | `time.sleep(0.3)  # Let server start` before the first HTTP request — a fixed-sleep startup race; under load the socket may not be listening yet (connection refused). | Poll-connect with a bounded retry loop (the `_wait_for_server` helper in `tests/test_distributed_swarm.py:18-26` is the in-repo pattern), or have `start_in_thread()` signal readiness via an `Event`. |
| 4 | `tests/test_distributed_swarm.py:153-158` (circuit breaker half-open) | `time.sleep(0.15)` to cross a recovery window — a fixed-sleep margin over a real-time threshold. Same file `:66-74,182-186` and `tests/test_distributed_swarm_edges.py:235,256` use fixed startup sleeps (0.02–0.3s) for socket servers. | Inject the breaker's clock (monkeypatch its time source past the window — the `tests/test_self_healing_termination.py:197-206` pattern); replace startup sleeps with the poll-connect helper. |
| 5 | `tests/test_recursive_agent.py:26-35` | Threaded sub-agents (each `time.sleep(0.01)`) must ALL finish inside `wait_for_sub_agents(timeout=1.0)` — completion-within-deadline under load. | Make the fake sub-agents synchronous (no sleep), or wait on completion events and assert the *results*, with the timeout only as a hang-guard (generous, e.g. ≥30s). |
| 6 | `tests/test_error_handling.py:45-51` | `@with_timeout(1.0)` around an instant function asserts it *completes within 1s of wall clock* — a scheduler stall fails it. (`:53-60`, the raises-side, is the safe direction: sleep(1) vs 0.1s timeout.) | Widen the success-side budget to hang-guard scale, or fake the timer used by `with_timeout` so "did not time out" is decided by the injected clock. |
| 7 | `tests/test_incremental_analyzer.py:25` | `time.sleep(0.01)` to make the second write get a NEWER mtime — breaks on coarse-mtime filesystems and is a hidden clock dependency. | Set mtimes explicitly with `os.utime`, or (better) key change detection on content hash so the test needs no clock at all. |
| 8 | `tests/test_command_runner.py:38-46` | Asserts the 1s timeout FIRES against a 10s sleep — safe direction, wide margin; listed for completeness (also burns ~1s of suite wall time). | Optional: shrink to 0.2s timeout vs 10s sleep to keep the margin ratio while saving wall time. |

## Cleared during the sweep (not fragile — the target patterns)

- `tests/test_swarm_coordinator_charz.py` — **frozen monotonic clock**
  (`time.sleep`/`time.time` faked) makes every elapsed string deterministic.
  This is the exemplar the fixes above should copy.
- `tests/test_self_healing_termination.py:197-206` — `perf_counter`
  monkeypatched to fixed values; timing logic tested with zero wall clock.
- `tests/test_adaptive_runner.py:130-137` — bounds on a *computed* backoff
  value, not a measured duration; deterministic.
- The hundreds of `< 0.5` / `>= 0.34`-style threshold assertions — pure
  arithmetic on deterministic scores, no clock involved.

## Fix-wave ground rules (when this list is picked up)

1. One test file per commit, suite-gated — these are behavior-preserving test
   refactors, but the never-fake-green discipline applies to tests too.
2. Never widen an assertion to "make it pass" — replace the proxy with the
   invariant, or inject the clock. A loosened timing bound is still a timing
   bound.
3. After each fix, the test must pass **under load** (run it while a verify
   chunk runs) — that is the acceptance criterion the chunk-12 case defines.
