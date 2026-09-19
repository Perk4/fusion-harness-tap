# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Acceptance gate for: implement BENCH_PLAN.md as bench.py (uv single-file
script, stdlib only) that runs to completion via `uv run bench.py`, writes
RESULTS.md with a markdown table holding a measured time AND a measured peak
RAM figure for every strategy in the plan, declares a Speed Winner and a
Memory Winner from those measurements, and where the fastest strategy beats
the naive autocommit baseline by at least 5x.

Exit 0 iff every check passes. One PASS/FAIL line per check.
"""

import ast
import os
import re
import subprocess
import sys
import time

ROOT = "/private/tmp/ddc0f4d0/fusion-harness"
BENCH = os.path.join(ROOT, "bench.py")
RESULTS = os.path.join(ROOT, "RESULTS.md")
PLAN = os.path.join(ROOT, "BENCH_PLAN.md")

# The seven strategies defined by BENCH_PLAN.md ("Strategies (7)" table and
# the STRATEGIES dict in its appendix script).
STRATEGIES = [
    "naive_autocommit",
    "one_big_txn_loop",
    "executemany_list",
    "executemany_gen",
    "wal_tuned_gen",
    "max_tuned_gen",
    "set_based_ctes",
]
BASELINE = "naive_autocommit"
RUN_TIMEOUT = 240  # plan budget is ~3 minutes; measured fused run was ~7s

_results: list[bool] = []


def ok(msg: str) -> None:
    _results.append(True)
    print("PASS: " + msg)


def bad(msg: str) -> None:
    _results.append(False)
    print("FAIL: " + msg)


def one_line(s: str, limit: int = 500) -> str:
    s = " | ".join(part.strip() for part in s.strip().splitlines() if part.strip())
    return s[-limit:] if len(s) > limit else s


def clean_md(s: str) -> str:
    return re.sub(r"[`*_]", "", s)


def first_float(cell: str):
    m = re.search(r"-?\d+(?:\.\d+)?", cell.replace(",", ""))
    return float(m.group(0)) if m else None


def split_cells(line: str):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def parse_tables(text: str):
    """Return list of (header_cells, data_rows) for every markdown table."""
    lines = text.splitlines()
    tables = []
    i = 0
    sep_re = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
    while i < len(lines):
        if (
            "|" in lines[i]
            and i + 1 < len(lines)
            and "-" in lines[i + 1]
            and "|" in lines[i + 1]
            and sep_re.match(lines[i + 1])
        ):
            header = split_cells(lines[i])
            j = i + 2
            rows = []
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(split_cells(lines[j]))
                j += 1
            tables.append((header, rows))
            i = j
        else:
            i += 1
    return tables


def main() -> int:
    # ---- 0. plan still present (the thing bench.py must implement) --------
    if os.path.isfile(PLAN):
        plan_txt = open(PLAN, encoding="utf-8", errors="replace").read()
        missing = [s for s in STRATEGIES if s not in plan_txt]
        if missing:
            bad(
                f"expected BENCH_PLAN.md to still define strategies {missing}, "
                f"found them absent, at {PLAN} — restore BENCH_PLAN.md; the "
                f"plan is the spec and must not be edited"
            )
        else:
            ok("BENCH_PLAN.md present and still defines all 7 plan strategies")
    else:
        bad(
            f"expected BENCH_PLAN.md to exist, found nothing, at {PLAN} — "
            f"restore the plan file; it is the spec bench.py implements"
        )

    # ---- 1. bench.py exists ------------------------------------------------
    if not os.path.isfile(BENCH):
        bad(
            f"expected bench.py to exist, found nothing, at {BENCH} — "
            f"implement BENCH_PLAN.md as a single-file uv script named "
            f"bench.py in {ROOT} (stdlib only, runnable with `uv run bench.py`)"
        )
        print("\nRESULT: RED (gate cannot proceed without bench.py)")
        return 1
    ok(f"bench.py exists at {BENCH}")

    src = open(BENCH, encoding="utf-8", errors="replace").read()

    # ---- 2. PEP 723 header, empty dependencies (stdlib only) --------------
    if re.search(r"^#\s*///\s*script\s*$", src, re.MULTILINE):
        ok("bench.py has a PEP 723 `# /// script` metadata block")
    else:
        bad(
            f"expected a PEP 723 block starting with `# /// script`, found "
            f"none, at {BENCH} — add the inline metadata block "
            f"(`# /// script`, `# requires-python = ...`, "
            f"`# dependencies = []`, `# ///`) at the top of bench.py"
        )
    dep_lines = [l for l in src.splitlines() if re.search(r"^\#\s*dependencies\s*=", l)]
    if dep_lines and not re.search(r"dependencies\s*=\s*\[\s*\]", dep_lines[0]):
        bad(
            f"expected `dependencies = []` (stdlib only), found "
            f"`{dep_lines[0].strip()}`, at {BENCH} — remove all third-party "
            f"dependencies from the PEP 723 block; the plan requires Python "
            f"standard library only"
        )
    else:
        ok("PEP 723 dependencies are empty (stdlib only)")

    # ---- 3. all imports are stdlib -----------------------------------------
    try:
        tree = ast.parse(src)
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    roots.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        non_std = sorted(r for r in roots if r not in sys.stdlib_module_names)
        if non_std:
            bad(
                f"expected only stdlib imports, found non-stdlib {non_std}, "
                f"at {BENCH} — rewrite bench.py using only the Python "
                f"standard library"
            )
        else:
            ok("bench.py imports only Python standard library modules")
    except SyntaxError as e:
        bad(
            f"expected bench.py to be valid Python, found SyntaxError "
            f"`{one_line(str(e))}`, at {BENCH} — fix the syntax error"
        )

    # ---- 4. static plan fidelity: real measurement machinery ---------------
    if "sqlite3" in src:
        ok("bench.py uses sqlite3 (real inserts, not simulated)")
    else:
        bad(
            f"expected bench.py to import/use sqlite3, found no mention, at "
            f"{BENCH} — the benchmark must perform real SQLite inserts per "
            f"BENCH_PLAN.md"
        )
    if re.search(r"subprocess|multiprocessing", src):
        ok("bench.py isolates strategies in separate processes")
    else:
        bad(
            f"expected per-strategy process isolation (subprocess re-exec or "
            f"multiprocessing per BENCH_PLAN.md), found neither, at {BENCH} — "
            f"run each strategy in its own fresh process so peak-RAM readings "
            f"cannot pollute each other"
        )
    if re.search(r"ru_maxrss|getrusage", src):
        ok("bench.py measures peak RAM via getrusage/ru_maxrss")
    else:
        bad(
            f"expected measured peak RAM via resource.getrusage(...).ru_maxrss "
            f"per BENCH_PLAN.md, found no getrusage/ru_maxrss, at {BENCH} — "
            f"measure whole-process peak RSS inside each isolated worker; "
            f"do not assume or hardcode memory figures"
        )
    if re.search(r"1_000_000|1000000", src):
        ok("bench.py targets N=1,000,000 rows")
    else:
        bad(
            f"expected N=1,000,000 rows (literal 1_000_000 or 1000000), found "
            f"neither, at {BENCH} — the plan requires 1M rows for every "
            f"full-run strategy (baseline may be sampled and scaled)"
        )

    # ---- 5. `uv run bench.py` runs to completion ---------------------------
    pre_marker = time.time()
    proc = None
    ran_ok = False
    try:
        proc = subprocess.run(
            ["uv", "run", "bench.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT,
        )
        if proc.returncode == 0:
            ok("`uv run bench.py` ran to completion (exit 0)")
            ran_ok = True
        else:
            bad(
                f"expected `uv run bench.py` to exit 0, found exit "
                f"{proc.returncode}, at {BENCH} — fix the crash; stderr tail: "
                f"{one_line(proc.stderr or proc.stdout or '(empty)')}"
            )
    except FileNotFoundError:
        bad(
            f"expected `uv` on PATH so `uv run bench.py` works, found uv "
            f"missing, at {ROOT} — ensure the script is runnable with exactly "
            f"`uv run bench.py`; do not substitute another runner"
        )
        # best-effort fallback so content checks below still give feedback
        try:
            proc = subprocess.run(
                [sys.executable, "bench.py"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT,
            )
        except Exception:
            proc = None
    except subprocess.TimeoutExpired:
        bad(
            f"expected `uv run bench.py` to finish within {RUN_TIMEOUT}s "
            f"(plan budget ~3 minutes), found it still running, at {BENCH} — "
            f"sample the naive autocommit baseline (plan: 20,000 rows scaled "
            f"x50) instead of running it for the full 1M rows"
        )

    # ---- 6. RESULTS.md written by the run ----------------------------------
    if not os.path.isfile(RESULTS):
        bad(
            f"expected the run to write RESULTS.md, found no file, at "
            f"{RESULTS} — make bench.py write RESULTS.md (markdown table with "
            f"a time column and a peak RAM column for every strategy, plus "
            f"Speed Winner and Memory Winner lines) every time it runs"
        )
        print("\nRESULT: RED")
        return 1
    if os.path.getmtime(RESULTS) >= pre_marker - 2:
        ok("RESULTS.md was (re)written by this `uv run bench.py` invocation")
    else:
        bad(
            f"expected RESULTS.md to be rewritten by the run just executed, "
            f"found a stale file (mtime predates the run), at {RESULTS} — "
            f"bench.py itself must write RESULTS.md from its own fresh "
            f"measurements on every run; do not hand-author RESULTS.md"
        )

    text = open(RESULTS, encoding="utf-8", errors="replace").read()

    # ---- 7. markdown table: time + peak RAM for every strategy -------------
    tables = parse_tables(text)
    best = None
    best_count = -1
    for header, rows in tables:
        joined = clean_md(" ".join(" ".join(r) for r in rows))
        count = sum(1 for s in STRATEGIES if s in joined)
        if count > best_count:
            best_count = count
            best = (header, rows)

    times: dict[str, float] = {}
    rams: dict[str, float] = {}
    if best is None or best_count == 0:
        bad(
            f"expected a markdown table whose rows name the 7 plan strategies "
            f"{STRATEGIES}, found no such table, at {RESULTS} — write one "
            f"markdown table with one row per strategy using the plan's "
            f"strategy names"
        )
    else:
        header, rows = best
        time_col = next(
            (i for i, h in enumerate(header) if re.search(r"time|sec|duration", h, re.I)),
            None,
        )
        ram_candidates = [
            i for i, h in enumerate(header) if re.search(r"ram|rss|mem", h, re.I)
        ]
        ram_col = next(
            (i for i in ram_candidates if re.search(r"peak", header[i], re.I)),
            ram_candidates[0] if ram_candidates else None,
        )
        if time_col is None:
            bad(
                f"expected a time column (header matching time/sec/duration), "
                f"found headers {header}, at {RESULTS} — add a measured time "
                f"column to the results table"
            )
        else:
            ok(f"results table has a time column (`{header[time_col]}`)")
        if ram_col is None:
            bad(
                f"expected a peak RAM column (header matching RAM/RSS/mem), "
                f"found headers {header}, at {RESULTS} — add a measured peak "
                f"RAM column to the results table"
            )
        else:
            ok(f"results table has a peak RAM column (`{header[ram_col]}`)")

        if time_col is not None and ram_col is not None:
            for strat in STRATEGIES:
                row = next(
                    (r for r in rows if strat in clean_md(" ".join(r))), None
                )
                if row is None:
                    bad(
                        f"expected a table row for strategy `{strat}`, found "
                        f"none, at {RESULTS} — every strategy in BENCH_PLAN.md "
                        f"must have its own measured row"
                    )
                    continue
                t = first_float(row[time_col]) if time_col < len(row) else None
                m = first_float(row[ram_col]) if ram_col < len(row) else None
                if t is None or t <= 0:
                    bad(
                        f"expected a positive measured time for `{strat}`, "
                        f"found `{row[time_col] if time_col < len(row) else '(missing cell)'}`, "
                        f"at {RESULTS} — record the real measured wall time"
                    )
                else:
                    times[strat] = t
                if m is None or m <= 0:
                    bad(
                        f"expected a positive measured peak RAM for `{strat}`, "
                        f"found `{row[ram_col] if ram_col < len(row) else '(missing cell)'}`, "
                        f"at {RESULTS} — record the real measured peak RSS"
                    )
                else:
                    rams[strat] = m
            if len(times) == len(STRATEGIES):
                ok("every plan strategy has a positive measured time in the table")
            if len(rams) == len(STRATEGIES):
                ok("every plan strategy has a positive measured peak RAM in the table")

    # ---- 8. declared winners ------------------------------------------------
    def declared(kind: str):
        m = re.search(kind + r"\s*winner[^\n]*", text, re.I)
        if not m:
            return None, None
        line = clean_md(m.group(0))
        name = next((s for s in STRATEGIES if s in line), None)
        return line, name

    speed_line, speed_name = declared("speed")
    if speed_name:
        ok(f"RESULTS.md declares a Speed Winner: {speed_name}")
    else:
        bad(
            f"expected a `Speed Winner:` line naming one plan strategy, found "
            f"`{speed_line or 'no such line'}`, at {RESULTS} — declare the "
            f"Speed Winner using the plan's strategy name"
        )
    mem_line, mem_name = declared("memory")
    if mem_name:
        ok(f"RESULTS.md declares a Memory Winner: {mem_name}")
    else:
        bad(
            f"expected a `Memory Winner:` line naming one plan strategy, found "
            f"`{mem_line or 'no such line'}`, at {RESULTS} — declare the "
            f"Memory Winner using the plan's strategy name"
        )

    # ---- 9. winners follow from the measurements ---------------------------
    if speed_name and len(times) == len(STRATEGIES):
        fastest_t = min(times.values())
        if times[speed_name] <= fastest_t + 1e-9:
            ok(
                f"Speed Winner {speed_name} matches the fastest measured time "
                f"({times[speed_name]}s)"
            )
        else:
            actual = min(times, key=times.get)
            bad(
                f"expected the Speed Winner to be the fastest strategy in the "
                f"table (`{actual}` at {times[actual]}s), found `{speed_name}` "
                f"at {times[speed_name]}s, at {RESULTS} — derive the winner "
                f"from the measurements, not assumptions"
            )
    if mem_name and len(rams) == len(STRATEGIES):
        if mem_name == BASELINE:
            bad(
                f"expected the Memory Winner to exclude the sampled baseline, "
                f"found `{BASELINE}`, at {RESULTS} — per BENCH_PLAN.md the "
                f"sampled baseline never held 1M rows of work and cannot win "
                f"the RAM axis; pick the leanest full-1M strategy"
            )
        else:
            eligible = {k: v for k, v in rams.items() if k != BASELINE}
            lean = min(eligible.values())
            if rams[mem_name] <= lean + 1e-9:
                ok(
                    f"Memory Winner {mem_name} matches the lowest measured "
                    f"peak RAM among full-1M strategies ({rams[mem_name]})"
                )
            else:
                actual = min(eligible, key=eligible.get)
                bad(
                    f"expected the Memory Winner to have the lowest peak RAM "
                    f"among full-1M strategies (`{actual}` at {eligible[actual]}), "
                    f"found `{mem_name}` at {rams[mem_name]}, at {RESULTS} — "
                    f"derive the winner from the measurements"
                )

    # ---- 10. fastest beats naive autocommit by >= 5x ------------------------
    if len(times) == len(STRATEGIES):
        fastest_t = min(times.values())
        speedup = times[BASELINE] / fastest_t if fastest_t > 0 else 0.0
        if speedup >= 5.0:
            ok(
                f"fastest strategy beats naive autocommit by {speedup:.1f}x "
                f"(>= 5x required)"
            )
        else:
            bad(
                f"expected fastest strategy >= 5x faster than naive "
                f"autocommit, found {speedup:.1f}x ({times[BASELINE]}s vs "
                f"{fastest_t}s), at {RESULTS} — use one big transaction / "
                f"executemany / set-based insert per BENCH_PLAN.md so the "
                f"speedup is real"
            )
    else:
        bad(
            f"expected complete measured times for all 7 strategies to verify "
            f"the >=5x speedup, found only {sorted(times)} parseable, at "
            f"{RESULTS} — fix the results table first"
        )

    if not ran_ok:
        pass  # the uv-run FAIL above already carries the instruction

    failed = _results.count(False)
    print(
        f"\nRESULT: {'GREEN' if failed == 0 else 'RED'} "
        f"({_results.count(True)} passed, {failed} failed)"
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
