# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Benchmark seven SQLite bulk-insert strategies on speed and peak RAM.

Run with:
    uv run bench.py

The orchestrator re-executes this file once per strategy. Each worker uses a
fresh process and a fresh SQLite database, so process peak-RSS measurements
cannot leak from one strategy into another. The run writes RESULTS.md next to
this script from fresh measurements every time.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import resource
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterator

N = 1_000_000
NAIVE_SAMPLE_N = 20_000
SCHEMA = "CREATE TABLE t (a INTEGER, b REAL, c TEXT)"
INSERT = "INSERT INTO t VALUES (?, ?, ?)"
RESULTS_PATH = Path(__file__).resolve().with_name("RESULTS.md")

SET_BASED_SQL = """
WITH RECURSIVE seq(i) AS (
    SELECT 0
    UNION ALL
    SELECT i + 1 FROM seq WHERE i + 1 < ?
)
INSERT INTO t
SELECT i, i * 0.5, printf('payload-%012d', i)
FROM seq
"""

Row = tuple[int, float, str]
StrategyFunction = Callable[[sqlite3.Connection, int], None]


def make_row(i: int) -> Row:
    """Return the sole canonical definition of one benchmark row."""
    return (i, i * 0.5, f"payload-{i:012d}")


def rows(n: int) -> Iterator[Row]:
    """Generate identical deterministic data for every Python-bound strategy."""
    for i in range(n):
        yield make_row(i)


# ---------------------------------------------------------------- strategies

def s_naive_autocommit(conn: sqlite3.Connection, n: int) -> None:
    """Baseline: every INSERT is its own durable transaction."""
    conn.isolation_level = None
    for row in rows(n):
        conn.execute(INSERT, row)


def s_one_big_txn_loop(conn: sqlite3.Connection, n: int) -> None:
    conn.execute("BEGIN")
    for row in rows(n):
        conn.execute(INSERT, row)
    conn.commit()


def s_executemany_list(conn: sqlite3.Connection, n: int) -> None:
    # Deliberately materialized so the benchmark measures the classic RAM cost.
    data = list(rows(n))
    conn.execute("BEGIN")
    conn.executemany(INSERT, data)
    conn.commit()


def s_executemany_gen(conn: sqlite3.Connection, n: int) -> None:
    conn.execute("BEGIN")
    conn.executemany(INSERT, rows(n))
    conn.commit()


def s_wal_tuned_gen(conn: sqlite3.Connection, n: int) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("BEGIN")
    conn.executemany(INSERT, rows(n))
    conn.commit()
    # Include write-back cost instead of ending with the rows in a WAL sidecar.
    busy, _wal_pages, _checkpointed = conn.execute(
        "PRAGMA wal_checkpoint(TRUNCATE)"
    ).fetchone()
    if busy:
        raise RuntimeError("WAL checkpoint was unexpectedly busy")


def s_max_tuned_gen(conn: sqlite3.Connection, n: int) -> None:
    """Maximum Python-bound speed; safe only for a rebuildable staging DB."""
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("BEGIN")
    conn.executemany(INSERT, rows(n))
    conn.commit()


def s_set_based_ctes(conn: sqlite3.Connection, n: int) -> None:
    """Generate identical rows inside SQLite, avoiding per-row Python binds."""
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("BEGIN")
    conn.execute(SET_BASED_SQL, (n,))
    conn.commit()


STRATEGIES: dict[str, tuple[StrategyFunction, int]] = {
    "naive_autocommit": (s_naive_autocommit, NAIVE_SAMPLE_N),
    "one_big_txn_loop": (s_one_big_txn_loop, N),
    "executemany_list": (s_executemany_list, N),
    "executemany_gen": (s_executemany_gen, N),
    "wal_tuned_gen": (s_wal_tuned_gen, N),
    "max_tuned_gen": (s_max_tuned_gen, N),
    "set_based_ctes": (s_set_based_ctes, N),
}


# ------------------------------------------------------------------- workers

def rss_bytes() -> int:
    """Return this process's measured high-water resident set size in bytes."""
    ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(ru_maxrss if sys.platform == "darwin" else ru_maxrss * 1024)


def verify(db_path: Path, n: int) -> bool:
    """Prove row count, checksums, lengths, and representative rows match."""
    conn = sqlite3.connect(db_path)
    try:
        count, checksum, text_length = conn.execute(
            "SELECT count(*), sum(a), sum(length(c)) FROM t"
        ).fetchone()
        valid = (
            count == n
            and checksum == n * (n - 1) // 2
            and text_length == 20 * n
        )
        for i in (0, 1, n // 2, n - 1):
            actual = conn.execute(
                "SELECT a, b, c FROM t WHERE a = ?", (i,)
            ).fetchone()
            valid = valid and actual is not None and tuple(actual) == make_row(i)
        return bool(valid)
    finally:
        conn.close()


def worker(name: str) -> None:
    if name == "calibration":
        print(
            json.dumps(
                {
                    "name": name,
                    "rows": 0,
                    "seconds": 0.0,
                    "peak_rss": rss_bytes(),
                    "ok": True,
                }
            )
        )
        return

    function, n = STRATEGIES[name]
    with tempfile.TemporaryDirectory(prefix=f"sqlite-bulk-{name}-") as temp_dir:
        db_path = Path(temp_dir) / "benchmark.sqlite3"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(SCHEMA)
            started = time.perf_counter()
            function(conn, n)
            seconds = time.perf_counter() - started
        finally:
            conn.close()

        valid = verify(db_path, n)
        result = {
            "name": name,
            "rows": n,
            "seconds": seconds,
            "peak_rss": rss_bytes(),
            "ok": valid,
        }
        print(json.dumps(result, separators=(",", ":")))


def spawn(name: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--worker", name],
        check=True,
        capture_output=True,
        text=True,
        timeout=220,
    )
    output_lines = completed.stdout.strip().splitlines()
    if not output_lines:
        raise RuntimeError(f"worker {name} produced no result")
    return json.loads(output_lines[-1])


# ---------------------------------------------------------------- reporting

def measured_rows(result: dict[str, Any]) -> str:
    suffix = " (sampled)" if result["sampled"] else ""
    return f"{result['rows']:,}{suffix}"


def build_results_markdown(
    results: list[dict[str, Any]],
    base_rss: int,
    total_wall_seconds: float,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    baseline = next(r for r in results if r["name"] == "naive_autocommit")
    baseline_time = float(baseline["scaled_seconds"])
    ordered = sorted(results, key=lambda result: result["scaled_seconds"])
    fastest = ordered[0]
    full_runs = [result for result in results if not result["sampled"]]
    leanest = min(
        full_runs,
        key=lambda result: (result["peak_rss"], result["scaled_seconds"]),
    )

    lines = [
        "# SQLite Bulk Insert Benchmark Results",
        "",
        (
            f"Fresh measurements: **{N:,} target rows**, Python "
            f"{platform.python_version()}, SQLite {sqlite3.sqlite_version}, "
            f"{platform.platform()}."
        ),
        "",
        (
            "The timer includes row generation, binding, insertion, and commit. "
            "WAL timing also includes `wal_checkpoint(TRUNCATE)`. Each strategy "
            "ran in a fresh process against a fresh database."
        ),
        "",
        "| Strategy | Measured rows | Time 1M rows (s) | Speedup vs naive | Peak RAM (MB) | RSS over base (MB) |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for result in ordered:
        scaled = float(result["scaled_seconds"])
        peak_mb = int(result["peak_rss"]) / 1_000_000
        delta_mb = (int(result["peak_rss"]) - base_rss) / 1_000_000
        time_mark = "*" if result["sampled"] else ""
        lines.append(
            f"| `{result['name']}` | {measured_rows(result)} | "
            f"{scaled:.4f}{time_mark} | {baseline_time / scaled:.2f}x | "
            f"{peak_mb:.3f} | {delta_mb:.3f} |"
        )

    fastest_time = float(fastest["scaled_seconds"])
    leanest_peak_mb = int(leanest["peak_rss"]) / 1_000_000
    leanest_delta_mb = (int(leanest["peak_rss"]) - base_rss) / 1_000_000
    lines.extend(
        [
            "",
            (
                f"\\* `naive_autocommit` ran {NAIVE_SAMPLE_N:,} real rows; its "
                f"measured time was scaled by {N // NAIVE_SAMPLE_N}. Its RAM "
                "reading is measured, not scaled, and it is excluded from the "
                "memory-winner decision."
            ),
            "",
            (
                "`max_tuned_gen` and `set_based_ctes` use "
                "`journal_mode=OFF`/`synchronous=OFF`; they are for rebuildable "
                "staging loads only."
            ),
            "",
            f"Bare-worker peak RSS calibration: **{base_rss / 1_000_000:.3f} MB**.",
            f"Total benchmark wall time: **{total_wall_seconds:.3f} s**.",
            "",
            (
                f"**Speed Winner: `{fastest['name']}`** — {fastest_time:.4f} s, "
                f"{baseline_time / fastest_time:.2f}x faster than naive."
            ),
            (
                f"**Memory Winner: `{leanest['name']}`** — "
                f"{leanest_peak_mb:.3f} MB peak RSS, "
                f"{leanest_delta_mb:+.3f} MB over the calibration worker."
            ),
            "",
        ]
    )
    return "\n".join(lines), fastest, leanest


def definition_of_done_gate(
    results: list[dict[str, Any]],
    markdown: str,
    fastest: dict[str, Any],
    leanest: dict[str, Any],
) -> None:
    """Hard-fail unless fresh measurements satisfy the benchmark contract."""
    expected = set(STRATEGIES)
    actual = {str(result["name"]) for result in results}
    if actual != expected:
        raise AssertionError(f"strategy mismatch: expected {expected}, got {actual}")
    if not all(result["ok"] for result in results):
        failed = [result["name"] for result in results if not result["ok"]]
        raise AssertionError(f"integrity verification failed: {failed}")
    if not all(
        float(result["seconds"]) > 0 and int(result["peak_rss"]) > 0
        for result in results
    ):
        raise AssertionError("every strategy must have measured positive time and RSS")
    for result in results:
        required_rows = NAIVE_SAMPLE_N if result["name"] == "naive_autocommit" else N
        if result["rows"] != required_rows:
            raise AssertionError(f"wrong row count for {result['name']}")
        if result["name"] not in markdown:
            raise AssertionError(f"RESULTS.md omitted {result['name']}")
    baseline = next(r for r in results if r["name"] == "naive_autocommit")
    speedup = float(baseline["scaled_seconds"]) / float(fastest["scaled_seconds"])
    if speedup < 5.0:
        raise AssertionError(f"fastest strategy achieved only {speedup:.2f}x")
    if fastest["name"] not in markdown or leanest["name"] not in markdown:
        raise AssertionError("winner declaration missing from RESULTS.md")
    if "Speed Winner:" not in markdown or "Memory Winner:" not in markdown:
        raise AssertionError("RESULTS.md lacks winner lines")
    if leanest["name"] == "naive_autocommit":
        raise AssertionError("sampled baseline cannot be Memory Winner")


def main() -> None:
    total_started = time.perf_counter()
    print(
        f"SQLite bulk insert benchmark | N={N:,} rows | "
        f"Python {platform.python_version()} | SQLite {sqlite3.sqlite_version}"
    )
    print("Each strategy runs in a fresh isolated worker process.\n")

    calibration = spawn("calibration")
    results: list[dict[str, Any]] = []
    for name in STRATEGIES:
        result = spawn(name)
        if not result["ok"]:
            raise RuntimeError(f"integrity check failed for {name}")
        scale = N / int(result["rows"])
        result["scaled_seconds"] = float(result["seconds"]) * scale
        result["sampled"] = scale != 1.0
        results.append(result)
        sample_note = " sampled" if result["sampled"] else ""
        print(
            f"[done] {name}: {result['seconds']:.4f}s, "
            f"{result['rows']:,} rows{sample_note}, "
            f"peak {result['peak_rss'] / 1_000_000:.3f} MB"
        )

    total_wall_seconds = time.perf_counter() - total_started
    markdown, fastest, leanest = build_results_markdown(
        results, int(calibration["peak_rss"]), total_wall_seconds
    )
    definition_of_done_gate(results, markdown, fastest, leanest)
    RESULTS_PATH.write_text(markdown, encoding="utf-8")

    print(f"\nWrote {RESULTS_PATH}")
    print(
        f"Speed Winner: {fastest['name']} "
        f"({fastest['scaled_seconds']:.4f}s measured/scaled to 1M)"
    )
    print(
        f"Memory Winner: {leanest['name']} "
        f"({leanest['peak_rss'] / 1_000_000:.3f} MB measured peak RSS)"
    )
    print("Definition-of-Done gate: PASS")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(sys.argv[2])
    elif len(sys.argv) == 1:
        main()
    else:
        raise SystemExit("usage: uv run bench.py [--worker STRATEGY]")
