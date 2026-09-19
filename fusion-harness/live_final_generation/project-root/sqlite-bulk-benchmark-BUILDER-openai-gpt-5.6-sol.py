#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# ///
"""SQLite bulk-insert benchmark: elapsed time and process peak RSS.

Run:
    uv run sqlite-bulk-benchmark-BUILDER-openai-gpt-5.6-sol.py

Every timed trial executes in a fresh child process against a fresh database.
The deliberately slow autocommit case uses a prefix sample and reports a
clearly marked linear projection to one million rows.
"""

from __future__ import annotations

import argparse
import gc
import itertools
import json
import os
import platform
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

IDENTITY = "BUILDER-openai-gpt-5.6-sol"
DEFAULT_ROWS = 1_000_000
DEFAULT_BASELINE_ROWS = 10_000
DEFAULT_REPEATS = 2
EXECUTEMANY_BATCH_ROWS = 10_000
MULTI_VALUES_TARGET_ROWS = 500
COLUMN_COUNT = 6

INSERT_ONE = """
INSERT INTO events
    (id, account_id, created_at, amount_cents, status, payload)
VALUES (?, ?, ?, ?, ?, ?)
"""

SCHEMA = """
CREATE TABLE events (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL,
    created_at   INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('new', 'paid', 'sent', 'void')),
    payload      TEXT NOT NULL
)
"""

SET_BASED_INSERT = """
WITH RECURSIVE
seq(i) AS (
    VALUES(0)
    UNION ALL
    SELECT i + 1 FROM seq WHERE i + 1 < ?
),
generated(i, mix) AS (
    SELECT i, (i * 1103515245 + 12345) % 2147483648
    FROM seq
)
INSERT INTO events
    (id, account_id, created_at, amount_cents, status, payload)
SELECT
    i,
    mix % 100003,
    1700000000 + i,
    (mix % 2000001) - 1000000,
    CASE i % 4
        WHEN 0 THEN 'new'
        WHEN 1 THEN 'paid'
        WHEN 2 THEN 'sent'
        ELSE 'void'
    END,
    printf(
        'event-%010d-%010x-abcdefghijklmnopqrstuvwxyz0123456789',
        i,
        mix
    )
FROM generated
"""

DIGEST_SQL = """
SELECT
    count(*),
    sum(id),
    sum(account_id),
    sum(created_at),
    sum(amount_cents),
    sum(length(status)),
    sum(length(payload)),
    min(id),
    max(id),
    min(payload),
    max(payload)
FROM events
"""


@dataclass(frozen=True)
class Strategy:
    key: str
    label: str
    journal_mode: str
    synchronous: str
    implementation: str
    durability: str
    sampled: bool = False


STRATEGIES: tuple[Strategy, ...] = (
    Strategy(
        "naive_autocommit",
        "naive autocommit",
        "DELETE",
        "FULL",
        "naive",
        "durable",
        sampled=True,
    ),
    Strategy(
        "one_big_transaction",
        "one transaction + execute",
        "DELETE",
        "FULL",
        "one_transaction",
        "durable",
    ),
    Strategy(
        "executemany_streamed",
        "streamed executemany batches",
        "DELETE",
        "FULL",
        "executemany",
        "durable",
    ),
    Strategy(
        "wal_multi_values",
        "WAL/NORMAL + multi-VALUES",
        "WAL",
        "NORMAL",
        "multi_values",
        "consistent; latest commit power-loss risk",
    ),
    Strategy(
        "off_multi_values",
        "OFF/OFF + multi-VALUES",
        "OFF",
        "OFF",
        "multi_values",
        "rebuildable staging only",
    ),
    Strategy(
        "wal_set_based",
        "WAL/NORMAL + INSERT-SELECT",
        "WAL",
        "NORMAL",
        "set_based",
        "consistent; latest commit power-loss risk",
    ),
    Strategy(
        "off_set_based",
        "OFF/OFF + INSERT-SELECT",
        "OFF",
        "OFF",
        "set_based",
        "rebuildable staging only",
    ),
)
STRATEGY_BY_KEY = {strategy.key: strategy for strategy in STRATEGIES}


Row = tuple[int, int, int, int, str, str]
Digest = tuple[int | str, ...]


def make_row(i: int) -> Row:
    """The sole Python definition of benchmark data."""
    mix = (i * 1103515245 + 12345) % 2147483648
    status = ("new", "paid", "sent", "void")[i % 4]
    return (
        i,
        mix % 100003,
        1700000000 + i,
        (mix % 2000001) - 1000000,
        status,
        f"event-{i:010d}-{mix:010x}-abcdefghijklmnopqrstuvwxyz0123456789",
    )


def generated_rows(start: int, stop: int) -> Iterator[Row]:
    for i in range(start, stop):
        yield make_row(i)


def expected_digest(row_count: int) -> Digest:
    count = 0
    id_sum = account_sum = created_sum = amount_sum = 0
    status_length_sum = payload_length_sum = 0
    min_payload: str | None = None
    max_payload: str | None = None
    for row in generated_rows(0, row_count):
        row_id, account_id, created_at, amount, status, payload = row
        count += 1
        id_sum += row_id
        account_sum += account_id
        created_sum += created_at
        amount_sum += amount
        status_length_sum += len(status)
        payload_length_sum += len(payload)
        if min_payload is None or payload < min_payload:
            min_payload = payload
        if max_payload is None or payload > max_payload:
            max_payload = payload
    return (
        count,
        id_sum,
        account_sum,
        created_sum,
        amount_sum,
        status_length_sum,
        payload_length_sum,
        0 if row_count else None,
        row_count - 1 if row_count else None,
        min_payload,
        max_payload,
    )


def peak_rss_bytes() -> int:
    if os.name == "nt":
        # ctypes is standard library. PeakWorkingSetSize is the Windows
        # equivalent of process peak RSS.
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = (
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            )

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = wintypes.HANDLE
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            get_current_process(), ctypes.byref(counters), counters.cb
        )
        if not ok:
            raise ctypes.WinError()
        return int(counters.PeakWorkingSetSize)

    import resource

    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux and the BSDs report KiB.
    if sys.platform == "darwin":
        return int(raw)
    return int(raw) * 1024


def setup_connection(db_path: Path, strategy: Strategy) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, isolation_level=None, timeout=60.0)
    connection.execute("PRAGMA page_size=4096")
    actual_journal = connection.execute(
        f"PRAGMA journal_mode={strategy.journal_mode}"
    ).fetchone()[0]
    if str(actual_journal).upper() != strategy.journal_mode:
        raise RuntimeError(
            f"requested journal_mode={strategy.journal_mode}, got {actual_journal}"
        )
    connection.execute(f"PRAGMA synchronous={strategy.synchronous}")

    # Common controls: bounded cache, no mmap RSS ambiguity, disk-backed temp
    # structures, and spill enabled. These are identical for every strategy.
    connection.execute("PRAGMA cache_size=-2048")
    connection.execute("PRAGMA cache_spill=ON")
    connection.execute("PRAGMA temp_store=FILE")
    connection.execute("PRAGMA mmap_size=0")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(SCHEMA)
    return connection


def finish_commit(connection: sqlite3.Connection, strategy: Strategy) -> None:
    connection.commit()
    # Include WAL's eventual write-back cost, rather than declaring victory
    # while the complete database still resides in a large sidecar file.
    if strategy.journal_mode == "WAL":
        result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if result[0] != 0:
            raise RuntimeError(f"WAL checkpoint was busy: {result!r}")


def insert_naive(connection: sqlite3.Connection, row_count: int, strategy: Strategy) -> None:
    # isolation_level=None makes every statement its own transaction.
    for row in generated_rows(0, row_count):
        connection.execute(INSERT_ONE, row)


def insert_one_transaction(
    connection: sqlite3.Connection, row_count: int, strategy: Strategy
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    for row in generated_rows(0, row_count):
        connection.execute(INSERT_ONE, row)
    finish_commit(connection, strategy)


def insert_executemany(
    connection: sqlite3.Connection, row_count: int, strategy: Strategy
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    for start in range(0, row_count, EXECUTEMANY_BATCH_ROWS):
        stop = min(start + EXECUTEMANY_BATCH_ROWS, row_count)
        # An iterator, not a list: batching does not materialize input rows.
        connection.executemany(INSERT_ONE, generated_rows(start, stop))
    finish_commit(connection, strategy)


def insert_multi_values(
    connection: sqlite3.Connection, row_count: int, strategy: Strategy
) -> None:
    try:
        variable_limit = connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)
    except AttributeError:
        variable_limit = 999
    batch_rows = max(
        1, min(MULTI_VALUES_TARGET_ROWS, variable_limit // COLUMN_COUNT)
    )
    placeholder = "(" + ",".join("?" for _ in range(COLUMN_COUNT)) + ")"

    connection.execute("BEGIN IMMEDIATE")
    for start in range(0, row_count, batch_rows):
        stop = min(start + batch_rows, row_count)
        batch = list(generated_rows(start, stop))
        statement = (
            "INSERT INTO events "
            "(id, account_id, created_at, amount_cents, status, payload) VALUES "
            + ",".join(itertools.repeat(placeholder, len(batch)))
        )
        bindings = [value for row in batch for value in row]
        connection.execute(statement, bindings)
    finish_commit(connection, strategy)


def insert_set_based(
    connection: sqlite3.Connection, row_count: int, strategy: Strategy
) -> None:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(SET_BASED_INSERT, (row_count,))
    finish_commit(connection, strategy)


IMPLEMENTATIONS = {
    "naive": insert_naive,
    "one_transaction": insert_one_transaction,
    "executemany": insert_executemany,
    "multi_values": insert_multi_values,
    "set_based": insert_set_based,
}


def worker(strategy_key: str, db_path: Path, row_count: int) -> int:
    strategy = STRATEGY_BY_KEY[strategy_key]
    if db_path.exists():
        db_path.unlink()
    connection = setup_connection(db_path, strategy)
    implementation = IMPLEMENTATIONS[strategy.implementation]

    gc_was_enabled = gc.isenabled()
    gc.disable()
    started_ns = time.perf_counter_ns()
    try:
        implementation(connection, row_count, strategy)
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        if gc_was_enabled:
            gc.enable()
    elapsed_ns = time.perf_counter_ns() - started_ns

    # Snapshot peak before the untimed validation query.
    rss_bytes = peak_rss_bytes()
    digest = tuple(connection.execute(DIGEST_SQL).fetchone())
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    connection.close()

    print(
        json.dumps(
            {
                "strategy": strategy.key,
                "rows": row_count,
                "elapsed_seconds": elapsed_ns / 1_000_000_000,
                "peak_rss_bytes": rss_bytes,
                "digest": digest,
                "quick_check": quick_check,
            },
            separators=(",", ":"),
        )
    )
    return 0


def format_seconds_list(results: Sequence[dict[str, object]]) -> str:
    return ",".join(f"{float(result['elapsed_seconds']):.3f}" for result in results)


def format_rss_list(results: Sequence[dict[str, object]]) -> str:
    mib = 1024 * 1024
    return ",".join(f"{int(result['peak_rss_bytes']) / mib:.1f}" for result in results)


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def print_table(
    grouped: dict[str, list[dict[str, object]]],
    total_rows: int,
    expected_by_count: dict[int, Digest],
) -> tuple[Strategy, Strategy]:
    headers = (
        "Strategy",
        "Mode",
        "Rows/run",
        "Trial time(s)",
        "Time@1M(s)",
        "Peak RAM/run MiB",
        "Data",
    )
    rows: list[tuple[str, ...]] = []
    normalized_times: dict[str, float] = {}
    peak_by_strategy: dict[str, int] = {}

    for strategy in STRATEGIES:
        results = grouped[strategy.key]
        elapsed = [float(result["elapsed_seconds"]) for result in results]
        row_count = int(results[0]["rows"])
        projected = median(elapsed) * total_rows / row_count
        normalized_times[strategy.key] = projected
        peak_by_strategy[strategy.key] = max(
            int(result["peak_rss_bytes"]) for result in results
        )
        verified = all(
            tuple(result["digest"]) == expected_by_count[int(result["rows"])]
            and result["quick_check"] == "ok"
            for result in results
        )
        projection_marker = "*" if strategy.sampled else ""
        rows.append(
            (
                strategy.label,
                f"{strategy.journal_mode}/{strategy.synchronous}",
                f"{row_count:,}",
                format_seconds_list(results),
                f"{projected:.3f}{projection_marker}",
                format_rss_list(results),
                "OK" if verified else "FAIL",
            )
        )

    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def render(row: Sequence[str]) -> str:
        return " | ".join(value.ljust(widths[i]) for i, value in enumerate(row))

    print(render(headers))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(render(row))

    speed_key = min(normalized_times, key=normalized_times.get)
    # The sampled baseline is not eligible for the memory title: its peak RSS
    # was measured honestly but it did not execute the full row count.
    full_keys = [strategy.key for strategy in STRATEGIES if not strategy.sampled]
    memory_key = min(full_keys, key=peak_by_strategy.get)
    return STRATEGY_BY_KEY[speed_key], STRATEGY_BY_KEY[memory_key]


def orchestrator(args: argparse.Namespace) -> int:
    if args.rows <= 0 or args.baseline_rows <= 0 or args.repeats <= 0:
        raise SystemExit("--rows, --baseline-rows, and --repeats must be positive")
    baseline_rows = min(args.baseline_rows, args.rows)

    print("SQLite bulk insert benchmark")
    print(f"Identity: {IDENTITY}")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"SQLite: {sqlite3.sqlite_version}")
    print(f"Platform: {platform.platform()}")
    print(f"Rows: {args.rows:,}")
    print(
        f"Autocommit sample: {baseline_rows:,} rows; its Time@1M is a linear projection"
    )
    print(f"Full-strategy trials: {args.repeats}")
    print(
        "Timed interval: first BEGIN/INSERT through COMMIT; WAL trials also include "
        "TRUNCATE checkpoint"
    )
    print("Peak RAM: per-worker process ru_maxrss; every trial uses a fresh process")
    print()

    print("Computing independent expected data digests...")
    expected_by_count = {
        baseline_rows: expected_digest(baseline_rows),
        args.rows: expected_digest(args.rows),
    }

    jobs: list[tuple[Strategy, int, int]] = []
    for strategy in STRATEGIES:
        trial_count = 1 if strategy.sampled else args.repeats
        row_count = baseline_rows if strategy.sampled else args.rows
        for trial in range(1, trial_count + 1):
            jobs.append((strategy, trial, row_count))
    random.Random(0x5A17E).shuffle(jobs)

    grouped: dict[str, list[dict[str, object]]] = {
        strategy.key: [] for strategy in STRATEGIES
    }
    script_path = Path(__file__).resolve()
    child_environment = os.environ.copy()
    child_environment["PYTHONHASHSEED"] = "0"

    with tempfile.TemporaryDirectory(prefix=f"sqlite-bench-{IDENTITY}-") as temp_name:
        temp_dir = Path(temp_name)
        for job_number, (strategy, trial, row_count) in enumerate(jobs, start=1):
            db_path = temp_dir / f"{IDENTITY}-{strategy.key}-trial-{trial}.sqlite3"
            print(
                f"[{job_number:02d}/{len(jobs):02d}] {strategy.label}, "
                f"trial {trial}, {row_count:,} rows...",
                flush=True,
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--worker",
                    strategy.key,
                    "--db",
                    str(db_path),
                    "--worker-rows",
                    str(row_count),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=child_environment,
                timeout=args.worker_timeout,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"worker failed for {strategy.key}:\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                )
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            grouped[strategy.key].append(result)

    for results in grouped.values():
        results.sort(key=lambda item: float(item["elapsed_seconds"]))

    print("\nResults")
    speed_winner, memory_winner = print_table(
        grouped, args.rows, expected_by_count
    )
    print(
        "\n* naive autocommit Time@1M is measured-time × "
        f"{args.rows:,}/{baseline_rows:,}; its RAM is measured, not projected."
    )
    print(
        "OFF/OFF rows are semantically identical but the database is rebuildable-only; "
        "a crash can corrupt it."
    )
    print(
        "INSERT-SELECT is applicable when rows can be generated in SQL or selected "
        "from an attached SQLite source."
    )
    print(f"\nSpeed Winner: {speed_winner.label}")
    print(f"Memory Winner: {memory_winner.label}")
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--baseline-rows", type=int, default=DEFAULT_BASELINE_ROWS)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--worker-timeout", type=float, default=180.0)
    parser.add_argument("--worker", choices=tuple(STRATEGY_BY_KEY))
    parser.add_argument("--db", type=Path)
    parser.add_argument("--worker-rows", type=int)
    args = parser.parse_args(argv)
    if args.worker and (args.db is None or args.worker_rows is None):
        parser.error("--worker requires --db and --worker-rows")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.worker:
        return worker(args.worker, args.db, args.worker_rows)
    return orchestrator(args)


if __name__ == "__main__":
    raise SystemExit(main())
