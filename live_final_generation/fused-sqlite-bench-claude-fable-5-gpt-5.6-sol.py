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
