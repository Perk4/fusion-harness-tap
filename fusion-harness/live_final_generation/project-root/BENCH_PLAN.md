# BENCH_PLAN — SQLite Bulk Insert Benchmark (fused design)

Fusion of two independent designs: **[ARCHITECT] anthropic/claude-fable-5** and **[BUILDER] openai/gpt-5.6-sol**. Where the designs disagreed, the simpler one was chosen (reasons inline and in the closing section). The fused script was **built and executed** — every number below is measured, not projected from the source answers.

- Fused runnable script: `/tmp/fused-sqlite-bench-claude-fable-5-gpt-5.6-sol.py` (also embedded in full at the end of this plan)
- Run with: `uv run /tmp/fused-sqlite-bench-claude-fable-5-gpt-5.6-sol.py`
- One astral-uv single-file script (PEP 723 header, `dependencies = []`), Python stdlib only
- Measured total wall time: **6.8 s** — well inside the 3-minute budget

## Method

**Self-isolating architecture** [ARCHITECT]. The script is both orchestrator and worker: it re-execs itself (`sys.executable __file__ --worker NAME`) once per strategy, so every strategy runs in a **fresh process against a fresh temp database**. Peak-RSS readings physically cannot pollute each other — this satisfies the isolated-process RAM requirement with zero third-party dependencies. [BUILDER] independently arrived at the same fresh-subprocess-per-trial isolation, so this is consensus architecture.

**Peak RAM** = whole-process `resource.getrusage(...).ru_maxrss`, normalized (bytes on macOS, KB×1024 on Linux) [both]. A **no-op calibration worker** measures bare-interpreter RSS (~20.3 MB here) so the table reports both absolute peak and delta-over-baseline [ARCHITECT].

**Timing boundary** [consensus]: the clock covers row generation + bind + insert + commit; connection setup, schema creation, and validation sit outside the timer. Generation is identical work for every strategy, so including it is neutral — excluding it would unfairly flatter the list-materializing strategy [ARCHITECT]. WAL runs additionally pay for `wal_checkpoint(TRUNCATE)` *inside* the timed region, so WAL is not credited with "finishing" while a million rows still sit in the `-wal` sidecar [BUILDER].

### Strategies (7)

| # | Strategy | What it does | Source |
|---|----------|--------------|--------|
| 1 | `naive_autocommit` | per-row implicit transaction — the baseline (sampled, see below) | both |
| 2 | `one_big_txn_loop` | `BEGIN` + `execute()` loop + one `COMMIT` | both |
| 3 | `executemany_list` | one txn, all 1M tuples materialized first — the classic mistake, kept to expose its RAM cost | [ARCHITECT] |
| 4 | `executemany_gen` | one txn, `executemany` fed a generator | both |
| 5 | `wal_tuned_gen` | `journal_mode=WAL` + `synchronous=NORMAL` + strategy 4 (WAL tuning combined with the predicted Python-bound winner, per the request) | both |
| 6 | `max_tuned_gen` | `journal_mode=OFF` + `synchronous=OFF` + strategy 4 — fastest way to push Python-resident rows | [ARCHITECT] |
| 7 | `set_based_ctes` | **the "beats all" candidate**: `INSERT … SELECT` over a recursive CTE that generates the *identical* rows inside SQLite — zero Python→SQLite binding crossings; run at OFF/OFF so it competes at the same durability tier as #6 | [BUILDER] |

Chosen over discarded alternatives:
- [BUILDER]'s set-based candidate replaces [ARCHITECT]'s `sqlite3` CLI `.import`: **simpler** (no external binary, no CSV temp file, no graceful-skip logic — pure stdlib in-process SQL) *and* it measured ~2× faster than everything else anyway.
- [BUILDER]'s chunked multi-row `VALUES` strategy was dropped: the variable-limit math and chunk assembly add complexity, and its niche (fewer Python↔SQLite crossings) is bracketed by `executemany_gen` below it and `set_based_ctes` above it.
- [ARCHITECT]'s 64 MB `cache_size` pragma was dropped from the tuned strategies in favor of [BUILDER]'s bounded-default-cache stance: **simpler**, and [ARCHITECT]'s own measurements showed the big cache costs ~50 MB of resident memory for essentially zero speed gain. (Fused result: `wal_tuned_gen` peaks at 24 MB instead of ARCHITECT's 71 MB.)

## Fairness controls

- **Identical data** [both]: every strategy inserts the same deterministic rows `(i, i*0.5, "payload-{i:012d}")` — one Python definition, no RNG. `i*0.5` is exact in floating point, so SQL-generated and Python-generated values are bit-identical.
- **Identical schema** [both]: `CREATE TABLE t (a INTEGER, b REAL, c TEXT)` (INTEGER/REAL/TEXT storage classes covered), fresh temp DB per worker, deleted afterward including `-wal`/`-shm`. [ARCHITECT]'s 3-column schema chosen over [BUILDER]'s 6-column `events` table as the simpler design that still exercises the same code paths.
- **Integrity gate, hard-fail** [fused]: every worker verifies `count(*)`, the closed-form `sum(a)` checksum, and `sum(length(c))` [ARCHITECT's gate], plus spot-row equality at indices `{0, 1, N/2, N−1}` against the Python row function [distilled from BUILDER's digest] — required so the set-based strategy *proves* it wrote identical data rather than just the right number of rows. No strategy can win by writing less or writing different bytes. This is simpler than [BUILDER]'s 11-field digest + `quick_check` while closing the same loophole.
- **Honest sampling, declared up front** [both]: `naive_autocommit` is fsync-bound (one journal sync per row); a full run would take ~3 minutes alone. It runs **20,000 real rows scaled ×50**, marked `*` in the table. Everything else runs the full 1,000,000. [ARCHITECT]'s 20k×50 chosen over [BUILDER]'s 10k×100 — equal simplicity, smaller scaling factor is the more honest extrapolation (both project to ~190 s regardless).
- **Baseline excluded from the memory verdict** [both, independently]: the sampled baseline never held 1M rows of work, so it cannot win the RAM axis.
- **Single run per strategy, fixed order** [ARCHITECT]: chosen over [BUILDER]'s 2×-with-median and seeded order shuffling as the simpler design. Justification: two full executions of the fused benchmark showed per-strategy spread <0.05 s while the winner gaps are ≥0.19 s, and process isolation already removes state carryover.
- **Durability labeling** [BUILDER]: OFF/OFF strategies (#6, #7) are flagged in the output as *rebuildable staging loads only* — a crash mid-load can corrupt the DB. They race in the same heats but carry the warning label.

## Exact output format

```
SQLite bulk insert benchmark  |  N=1,000,000 rows  |  py <ver>  sqlite <ver>  <platform>

  [done] <strategy>: <t>s (<rows> rows[ sampled])      ← one line per isolated process

Strategy                Time 1M rows   Speedup    Peak RSS   RSS -base
----------------------------------------------------------------------
<name>                       <t>s[*]     <x>x       <MB>MB      <MB>MB   ← sorted fastest-first
----------------------------------------------------------------------
* sampled at 20,000 rows, honestly scaled x50   |   base RSS <MB>MB (no-op interpreter)
note: max_tuned_gen and set_based_ctes run journal_mode=OFF/synchronous=OFF -> rebuildable staging loads only.

Speed Winner : <name>  (<t>s, <x>x vs naive)
Memory Winner: <name>  (<MB>MB peak, +<MB>MB over baseline)
```

Table layout is [ARCHITECT]'s (fewer columns, speedup included, sorted fastest-first — simpler than [BUILDER]'s 7-column trial-level table); the `Speed Winner:`/`Memory Winner:` terminal lines are [BUILDER]'s exact phrasing.

## Measured results (fused run: py 3.12.13, sqlite 3.50.4, macOS / Apple Silicon)

| Strategy | Time 1M rows | Speedup | Peak RSS | RSS −base |
|---|---:|---:|---:|---:|
| **set_based_ctes** | **0.17s** | **1126.2x** | 24.3 MB | 4.1 MB |
| max_tuned_gen | 0.37s | 518.4x | 24.1 MB | 3.9 MB |
| executemany_gen | 0.38s | 508.8x | 24.1 MB | 3.9 MB |
| **wal_tuned_gen** | 0.40s | 475.6x | **23.9 MB** | **3.7 MB** |
| executemany_list | 0.49s | 393.5x | 226.8 MB | 206.6 MB |
| one_big_txn_loop | 0.51s | 374.9x | 24.0 MB | 3.8 MB |
| naive_autocommit | 191.15s* | 1.0x | 22.7 MB | 2.5 MB |

\* sampled at 20,000 rows, scaled ×50. Base RSS 20.2 MB (no-op interpreter). Total wall time 6.8 s.

Key findings the fused design makes visible:
1. **The single transaction is ~99% of the win** — 375× from `BEGIN`/`COMMIT` alone [ARCHITECT's finding, confirmed].
2. **Eliminating the million Python→SQLite binding crossings is the last 2×** — set-based insertion at 0.17 s [BUILDER's finding, confirmed on the identical schema].
3. **`executemany_list` is strictly dominated**: slower than the generator *and* ~200 MB heavier [ARCHITECT's finding, confirmed].
4. **Memory is a four-way statistical tie** among all streaming strategies (23.9–24.3 MB, within ±0.4 MB across repeat runs): once you stream rows instead of materializing them, SQLite's bounded page cache makes peak RSS nearly strategy-invariant.

## Declared Winners

- **Speed Winner: `set_based_ctes`** — `INSERT … SELECT` over a recursive CTE, OFF/OFF pragmas: **0.17 s for 1M rows, ~1126× over naive autocommit.** Caveats carried from [BUILDER]: rebuildable-staging durability only, and it applies only when rows are derivable in SQL. For arbitrary Python-resident rows, the practical speed winner is `max_tuned_gen` (0.37 s), with `wal_tuned_gen` (0.40 s) the fastest *durable-enough* option — the same practical hierarchy both source models converged on.
- **Memory Winner: `wal_tuned_gen`** — **23.9 MB peak, +3.7 MB over a bare interpreter**, as selected by the declared rule (minimum peak RSS among full-1M runs, speed as tiebreak) in both verification runs. Honest note: this is a statistical tie with `one_big_txn_loop`, `executemany_gen`, and `max_tuned_gen` (all within 0.4 MB); the real memory lesson is *stream, never materialize* — the list variant costs 206 MB extra for nothing.

---

## Consensus & Divergence

**Consensus (both models, independently):** fresh-subprocess isolation per strategy with `ru_maxrss` for peak RSS; one deterministic Python-defined dataset and one schema for all strategies; timing bounded to the insert phase with setup/validation outside; sampling the naive baseline with declared linear scaling; excluding the sampled baseline from the memory verdict; integrity verification that hard-fails; labeling OFF/OFF as unsafe-for-production; and the headline conclusion that *one big transaction is most of the win* while *the memory winner is the streaming single-transaction family* (both declared `one transaction + execute` their memory winner; the fused measurement shows that whole family tied within noise, with `wal_tuned_gen` taking it by 0.1–0.2 MB under the fused rule).

**Divergences and rulings** (simpler option preferred per the fusion brief):
- *Beats-all candidate*: [BUILDER gpt-5.6-sol]'s set-based `INSERT…SELECT` **kept**; [ARCHITECT claude-fable-5]'s CLI `.import` **discarded** — set-based is simpler (no external binary, CSV staging, or skip logic) and empirically faster; the CLI route also strains the "stdlib only" spirit.
- *Speed winner dispute*: [ARCHITECT] declared `max_tuned_gen`, [BUILDER] declared OFF/OFF `INSERT-SELECT`. Settled by running both on the identical fused schema: **[BUILDER]'s pick wins** (0.17 s vs 0.37 s).
- *Schema & data*: [ARCHITECT]'s 3-column table **kept** over [BUILDER]'s 6-column `events` table — simpler, same storage classes exercised.
- *Repeats & trial ordering*: [ARCHITECT]'s single run in fixed order **kept** over [BUILDER]'s median-of-2 with seeded shuffle — simpler, and measured run-to-run spread (<0.05 s) is far below decision margins.
- *Verification*: [ARCHITECT]'s count+checksum gate **kept as the base**, extended with a slim length-digest + spot-row check distilled from [BUILDER]'s 11-field digest — the minimum needed to prove the SQL-generated rows are byte-identical; [BUILDER]'s full digest and `PRAGMA quick_check` **discarded** as redundant for this schema.
- *Cache tuning*: [ARCHITECT]'s 64 MB `cache_size` **discarded** in favor of [BUILDER]'s bounded-cache stance — simpler, and ARCHITECT's own data showed +50 MB RSS for no speed benefit.
- *WAL checkpoint in timed region*: [BUILDER]'s control **adopted** — not a simplification but a fairness correction; without it WAL under-reports its true cost.
- *Baseline sample size*: [ARCHITECT]'s 20k×50 **kept** over [BUILDER]'s 10k×100 — equal complexity, smaller extrapolation factor.
- *Also discarded*: [BUILDER]'s multi-row `VALUES` strategy (complexity without a podium finish — dominated on both ends), [BUILDER]'s Windows `PeakWorkingSetSize` branch (POSIX `ru_maxrss` is simpler; noted as an easy portability extension), and [ARCHITECT]'s `executemany_list`… no — that one was **kept**: three extra lines that buy the single most vivid RAM lesson in the table.

---

## Appendix — the fused script (verbatim, as executed)

```python
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
FUSED SQLite bulk-insert benchmark (claude-fable-5 + gpt-5.6-sol).

1,000,000 rows. Speed + peak RAM. Stdlib only. Run:
    uv run /tmp/fused-sqlite-bench-claude-fable-5-gpt-5.6-sol.py

Architecture (from ARCHITECT/claude-fable-5): the script re-execs ITSELF
once per strategy (`--worker NAME`), so every strategy runs in a fresh
process and peak RSS readings cannot pollute each other. A no-op
calibration worker measures bare-interpreter RSS for a delta column.

Beyond-the-list candidate (from BUILDER/gpt-5.6-sol): set-based
INSERT ... SELECT over a recursive CTE that generates the IDENTICAL rows
inside SQLite, verified by digest + spot-check against the Python rows.
WAL runs pay for wal_checkpoint(TRUNCATE) inside the timed region.
"""

import json
import os
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time

N = 1_000_000
NAIVE_SAMPLE_N = 20_000            # honest sample; scaled x(N/sample) in report
SCHEMA = "CREATE TABLE t (a INTEGER, b REAL, c TEXT)"
INSERT = "INSERT INTO t VALUES (?,?,?)"

SET_BASED_SQL = """
WITH RECURSIVE seq(i) AS (
    SELECT 0
    UNION ALL
    SELECT i + 1 FROM seq WHERE i + 1 < ?
)
INSERT INTO t SELECT i, i * 0.5, printf('payload-%012d', i) FROM seq
"""


# ---------------------------------------------------------------- data ----
def make_row(i):
    return (i, i * 0.5, f"payload-{i:012d}")


def rows(n):
    """Identical deterministic data for every strategy."""
    for i in range(n):
        yield make_row(i)


# ---------------------------------------------------------- strategies ----
def s_naive_autocommit(conn, n):
    conn.isolation_level = None    # every INSERT commits: journal sync per row
    for r in rows(n):
        conn.execute(INSERT, r)


def s_one_big_txn_loop(conn, n):
    conn.execute("BEGIN")
    for r in rows(n):
        conn.execute(INSERT, r)
    conn.commit()


def s_executemany_list(conn, n):
    data = list(rows(n))           # deliberately materialized: shows RAM cost
    conn.execute("BEGIN")
    conn.executemany(INSERT, data)
    conn.commit()


def s_executemany_gen(conn, n):
    conn.execute("BEGIN")
    conn.executemany(INSERT, rows(n))
    conn.commit()


def s_wal_tuned_gen(conn, n):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("BEGIN")
    conn.executemany(INSERT, rows(n))
    conn.commit()
    # Fairness (BUILDER): WAL must not finish with 1M rows still in the -wal
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def s_max_tuned_gen(conn, n):
    """Python-bound speed candidate: one txn + executemany(generator) +
    journaling/sync disabled for the load. Rebuildable staging only."""
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("BEGIN")
    conn.executemany(INSERT, rows(n))
    conn.commit()


def s_set_based(conn, n):
    """Beyond-the-list candidate (BUILDER): SQLite generates the identical
    rows itself; zero Python->SQLite binding crossings. OFF/OFF pragmas so
    it is compared at the same durability tier as max_tuned_gen."""
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("BEGIN")
    conn.execute(SET_BASED_SQL, (n,))
    conn.commit()


STRATEGIES = {
    "naive_autocommit": (s_naive_autocommit, NAIVE_SAMPLE_N),
    "one_big_txn_loop": (s_one_big_txn_loop, N),
    "executemany_list": (s_executemany_list, N),
    "executemany_gen":  (s_executemany_gen, N),
    "wal_tuned_gen":    (s_wal_tuned_gen, N),
    "max_tuned_gen":    (s_max_tuned_gen, N),
    "set_based_ctes":   (s_set_based, N),
}


# --------------------------------------------------------------- worker ----
def rss_bytes():
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return v if sys.platform == "darwin" else v * 1024  # KB on Linux


def verify(dbpath, n):
    """Integrity gate (fused): count + checksum for everyone [ARCHITECT],
    plus length-digest and spot-row equality so the SQL-generated data is
    provably identical to the Python data [BUILDER]."""
    conn = sqlite3.connect(dbpath)
    cnt, chk, clen = conn.execute(
        "SELECT count(*), sum(a), sum(length(c)) FROM t").fetchone()
    ok = (cnt == n and chk == n * (n - 1) // 2 and clen == 20 * n)
    for i in (0, 1, n // 2, n - 1):
        got = conn.execute("SELECT a, b, c FROM t WHERE a=?", (i,)).fetchone()
        ok = ok and got is not None and tuple(got) == make_row(i)
    conn.close()
    return ok


def worker(name):
    if name == "calibration":      # interpreter + sqlite3 import baseline
        print(json.dumps({"name": name, "rows": 0, "seconds": 0.0,
                          "peak_rss": rss_bytes(), "ok": True}))
        return
    fn, n = STRATEGIES[name]
    dbpath = tempfile.mktemp(suffix=".db", dir=tempfile.gettempdir())
    try:
        conn = sqlite3.connect(dbpath)
        conn.execute(SCHEMA)
        t0 = time.perf_counter()   # timer: generation + bind + insert + commit
        fn(conn, n)
        dt = time.perf_counter() - t0
        conn.close()
        ok = verify(dbpath, n)     # validation outside the timer
        print(json.dumps({"name": name, "rows": n, "seconds": dt,
                          "peak_rss": rss_bytes(), "ok": ok}))
    finally:
        for p in (dbpath, dbpath + "-wal", dbpath + "-shm"):
            if os.path.exists(p):
                os.remove(p)


# ----------------------------------------------------------- orchestrator --
def spawn(name):
    out = subprocess.run([sys.executable, os.path.abspath(__file__),
                          "--worker", name],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def main():
    t_total = time.perf_counter()
    print(f"SQLite bulk insert benchmark  |  N={N:,} rows  |  "
          f"py {sys.version.split()[0]}  sqlite {sqlite3.sqlite_version}  "
          f"{sys.platform}\n")

    base = spawn("calibration")
    results = []
    for name in STRATEGIES:        # fixed, deterministic order
        r = spawn(name)
        assert r["ok"], f"integrity check FAILED for {name}"
        scale = N / r["rows"]
        r["scaled"] = r["seconds"] * scale
        r["sampled"] = scale > 1.0
        results.append(r)
        print(f"  [done] {name}: {r['seconds']:.3f}s "
              f"({r['rows']:,} rows{' sampled' if r['sampled'] else ''})")

    naive = next(r["scaled"] for r in results if r["name"] == "naive_autocommit")
    print(f"\n{'Strategy':<22}{'Time 1M rows':>14}{'Speedup':>10}"
          f"{'Peak RSS':>12}{'RSS -base':>12}")
    print("-" * 70)
    for r in sorted(results, key=lambda r: r["scaled"]):
        mark = "*" if r["sampled"] else " "
        print(f"{r['name']:<22}{r['scaled']:>12.2f}s{mark}"
              f"{naive / r['scaled']:>9.1f}x"
              f"{r['peak_rss'] / 1e6:>10.1f}MB"
              f"{(r['peak_rss'] - base['peak_rss']) / 1e6:>10.1f}MB")
    print("-" * 70)
    print(f"* sampled at {NAIVE_SAMPLE_N:,} rows, honestly scaled "
          f"x{N // NAIVE_SAMPLE_N}   |   base RSS "
          f"{base['peak_rss'] / 1e6:.1f}MB (no-op interpreter)")
    print("note: max_tuned_gen and set_based_ctes run journal_mode=OFF/"
          "synchronous=OFF -> rebuildable staging loads only.")

    fastest = min(results, key=lambda r: r["scaled"])
    full = [r for r in results if not r["sampled"]]   # baseline excluded
    leanest = min(full, key=lambda r: (r["peak_rss"], r["scaled"]))
    print(f"\nSpeed Winner : {fastest['name']}  "
          f"({fastest['scaled']:.2f}s, {naive / fastest['scaled']:.0f}x vs naive)")
    print(f"Memory Winner: {leanest['name']}  "
          f"({leanest['peak_rss'] / 1e6:.1f}MB peak, "
          f"+{(leanest['peak_rss'] - base['peak_rss']) / 1e6:.1f}MB over baseline)")
    print(f"\ntotal benchmark wall time: {time.perf_counter() - t_total:.1f}s")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
    else:
        main()
```
