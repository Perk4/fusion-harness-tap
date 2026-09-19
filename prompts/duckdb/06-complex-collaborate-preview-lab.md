Collaboratively build `duckdb20_preview_lab/`, a reproducible playground for using and stress-testing the DuckDB v2.0 preview.

The configured agents must first propose independently, then use architect-directed rounds to agree on a task graph. The graph should cover:

- environment/version detection with an explicit v2-preview requirement;
- a `VARIANT` event-log workload with evolving record shapes;
- trigger-based auditing with OLD/NEW transition data;
- DML-in-CTE and `$variable` SQL examples;
- a bounded recursive-CTE microbenchmark that records timings without hard-coding the launch article's claimed 40× result; cap recursion at 10,000 rows, use one warmup plus one measured trial, and keep the entire benchmark under 30 seconds;
- parser diagnostics that capture precise error locations for intentionally invalid SQL;
- an async-I/O experiment plan for remote Parquet that is safe to skip when credentials/object storage are absent;
- a final `RESULTS.md` separating executed evidence, skipped experiments, and product ideas.

Deliverables should include a clear README, SQL fixtures, a runner, and machine-readable results. Never claim a preview feature passed unless it actually ran on a detected v2 preview. Every local validation command must be bounded to 60 seconds; do not run exhaustive filesystem searches, unbounded benchmarks, or network downloads.

Concurrency invariant: agents share one working directory and must never overwrite each other's work. Planning/review tasks may run in parallel with read-only tools. Any task that can mutate the project must run sequentially under the harness's single-writer scheduler, inspect the latest state, preserve previous changes, and leave a concrete handoff for the next agent. Do not create isolated git worktrees.

Source: https://duckdb.org/2026/08/17/duckdb-20-highlights
