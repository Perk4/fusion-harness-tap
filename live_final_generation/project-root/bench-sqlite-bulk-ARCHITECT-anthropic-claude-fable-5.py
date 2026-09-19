# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
SQLite bulk-insert benchmark: 1,000,000 rows, speed + peak RAM, per-strategy
process isolation. Stdlib only. Run:  uv run bench-sqlite-bulk-ARCHITECT-anthropic-claude-fable-5.py

Design (ARCHITECT / anthropic-claude-fable-5):
  * Orchestrator re-execs THIS file as a subprocess per strategy
    (`--worker NAME`), so peak RSS readings never pollute each other.
  * Every strategy inserts IDENTICAL deterministic data into an IDENTICAL
    fresh schema, verified by count + checksum.
  * Timing covers the full insert phase (row generation + bind + commit),
    identical work for all strategies.
  * The naive autocommit baseline is fsync-bound (~50-200 rows/ms is
    impossible; it does one journal sync per row). It is SAMPLED at 20,000
    rows and honestly scaled x50; the table flags it with '*'.
  * Peak RAM = ru_maxrss of the worker process (normalized to bytes across
    macOS/Linux), plus a no-op calibration worker so a delta over
    interpreter baseline is reported.
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
NAIVE_SAMPLE_N = 20_000  # honest sample; scaled x(N/NAIVE_SAMPLE_N) in report
SCHEMA = "CREATE TABLE t (a INTEGER, b REAL, c TEXT)"
INSERT = "INSERT INTO t VALUES (?,?,?)"
EXPECTED_SUM = lambda n: n * (n - 1) // 2  # sum of column a for n rows


# ---------------------------------------------------------------- data ----
def rows(n):
    """Identical deterministic data for every strategy."""
    for i in range(n):
        yield (i, i * 0.5, f"payload-{i:012d}")


# ---------------------------------------------------------- strategies ----
def s_naive_autocommit(conn, n):
    conn.isolation_level = None  # every INSERT commits (journal sync per row)
    for r in rows(n):
        conn.execute(INSERT, r)


def s_one_big_txn_loop(conn, n):
    conn.execute("BEGIN")
    for r in rows(n):
        conn.execute(INSERT, r)
    conn.commit()


def s_executemany_list(conn, n):
    data = list(rows(n))  # deliberately materialized: shows the RAM cost
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
    conn.execute("PRAGMA cache_size=-64000")  # 64 MB page cache
    conn.execute("BEGIN")
    conn.executemany(INSERT, rows(n))
    conn.commit()


def s_max_tuned_gen(conn, n):
    """Predicted overall speed winner within stdlib: one txn +
    executemany(generator) + journaling/sync disabled for the load."""
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("BEGIN")
    conn.executemany(INSERT, rows(n))
    conn.commit()


STRATEGIES = {
    "naive_autocommit": (s_naive_autocommit, NAIVE_SAMPLE_N),
    "one_big_txn_loop": (s_one_big_txn_loop, N),
    "executemany_list": (s_executemany_list, N),
    "executemany_gen": (s_executemany_gen, N),
    "wal_tuned_gen": (s_wal_tuned_gen, N),
    "max_tuned_gen": (s_max_tuned_gen, N),
}

# Optional bonus (external `sqlite3` CLI, skipped gracefully if absent).
# Same identical data, same isolation, timing includes writing the CSV.
CLI_STRATEGY = "cli_dot_import"


def run_cli_import(dbpath, n):
    import csv
    import shutil

    exe = shutil.which("sqlite3")
    if not exe:
        return False
    csvpath = dbpath + ".csv"
    with open(csvpath, "w", newline="") as f:
        w = csv.writer(f)
        for r in rows(n):
            w.writerow(r)
    subprocess.run(
        [exe, dbpath, SCHEMA + ";", ".mode csv", f".import {csvpath} t"],
        check=True, capture_output=True,
    )
    os.remove(csvpath)
    return True


# --------------------------------------------------------------- worker ----
def rss_bytes(who=resource.RUSAGE_SELF):
    v = resource.getrusage(who).ru_maxrss
    return v if sys.platform == "darwin" else v * 1024  # KB on Linux


def worker(name):
    if name == "calibration":  # no-op: interpreter + sqlite3 import baseline
        print(json.dumps({"name": name, "rows": 0, "seconds": 0.0,
                          "peak_rss": rss_bytes(), "ok": True}))
        return

    dbpath = tempfile.mktemp(suffix=".db", dir=tempfile.gettempdir())
    try:
        if name == CLI_STRATEGY:
            t0 = time.perf_counter()
            ok = run_cli_import(dbpath, N)
            dt = time.perf_counter() - t0
            if not ok:
                print(json.dumps({"name": name, "skipped": True}))
                return
            n = N
        else:
            fn, n = STRATEGIES[name]
            conn = sqlite3.connect(dbpath)
            conn.execute(SCHEMA)
            t0 = time.perf_counter()
            fn(conn, n)
            dt = time.perf_counter() - t0
            conn.close()

        vconn = sqlite3.connect(dbpath)
        cnt, chk = vconn.execute("SELECT count(*), sum(a) FROM t").fetchone()
        vconn.close()
        peak = max(rss_bytes(), rss_bytes(resource.RUSAGE_CHILDREN))
        print(json.dumps({
            "name": name, "rows": cnt, "seconds": dt, "peak_rss": peak,
            "ok": cnt == n and chk == EXPECTED_SUM(n),
        }))
    finally:
        for p in (dbpath, dbpath + "-wal", dbpath + "-shm", dbpath + ".csv"):
            if os.path.exists(p):
                os.remove(p)


# ----------------------------------------------------------- orchestrator --
def spawn(name):
    out = subprocess.run([sys.executable, os.path.abspath(__file__),
                          "--worker", name],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def main():
    print(f"SQLite bulk insert benchmark  |  N={N:,} rows  |  "
          f"py {sys.version.split()[0]}  sqlite {sqlite3.sqlite_version}  "
          f"{sys.platform}\n")

    base = spawn("calibration")
    results = []
    order = list(STRATEGIES) + [CLI_STRATEGY]
    for name in order:
        r = spawn(name)
        if r.get("skipped"):
            print(f"  [skip] {name} (sqlite3 CLI not on PATH)")
            continue
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

    fastest = min(results, key=lambda r: r["scaled"])
    # memory winner among full-speed strategies (exclude the naive baseline)
    fast = [r for r in results if not r["sampled"]]
    leanest = min(fast, key=lambda r: (r["peak_rss"], r["scaled"]))
    print(f"\nSPEED WINNER : {fastest['name']}  "
          f"({fastest['scaled']:.2f}s, {naive / fastest['scaled']:.0f}x vs naive)")
    print(f"MEMORY WINNER: {leanest['name']}  "
          f"({leanest['peak_rss'] / 1e6:.1f}MB peak, "
          f"+{(leanest['peak_rss'] - base['peak_rss']) / 1e6:.1f}MB over baseline)")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
    else:
        main()
