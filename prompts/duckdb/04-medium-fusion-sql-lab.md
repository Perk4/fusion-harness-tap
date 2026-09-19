Design and build a compact DuckDB v2.0 preview SQL lab in `duckdb20_fusion_lab/` that teaches four announced capabilities:

- first-class `VARIANT` storage, extraction, and containment;
- `BEFORE`/`AFTER` triggers with an audit-table example;
- DML inside a materialized CTE using `RETURNING`;
- one new SQL surface such as variables (`$x`) or JSON mutation.

Required canonical deliverables:

- `duckdb20_fusion_lab/README.md` — prerequisites, preview warning, run instructions, expected observations, and cleanup;
- `duckdb20_fusion_lab/lab.sql` — deterministic setup, examples, assertions/verification queries, and cleanup;
- `duckdb20_fusion_lab/run.sh` — detects the installed DuckDB version, refuses to claim success on a non-v2 preview, runs the lab when compatible, and reports unsupported preview syntax honestly.

Fusion protocol requirement: parallel model workers are researchers/planners only and must not modify the project. The temporary FUSION agent is the sole writer and must synthesize their results, create the canonical files, inspect them, and run safe local validation if a compatible preview binary is available. Never fabricate a pass when the preview is unavailable.

Source: https://duckdb.org/2026/08/17/duckdb-20-highlights
