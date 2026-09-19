# DuckDB 2.0 Fusion Harness Validation Prompts

All paid/live-agent validation prompts for the fusion-harness multi-model work come from this directory. Run them in numeric order, simple to complex. Do not invent inline agent prompts in the smoke or Herdr workflows; load the corresponding file verbatim.

Source announcement: https://duckdb.org/2026/08/17/duckdb-20-highlights

| Order | Prompt | Complexity | Intended command | Primary harness behavior |
|---:|---|---|---|---|
| 1 | `01-simple-opinion.md` | Simple | `/fh-opinion` | N-way read-only fan-out and responsive comparison |
| 2 | `02-simple-only-connect.md` | Simple | `/fh-only` armed mode | One-shot slot routing and auto-disarm |
| 3 | `03-medium-debate-server.md` | Medium | `/fh-debate --rounds 2` | Existing pairwise read-only debate regression |
| 4 | `04-medium-fusion-sql-lab.md` | Medium | `/fh-fusion` | N read-only workers; temporary FUSION is sole CWD writer |
| 5 | `05-medium-fusion-context-sync.md` | Medium | `/fh-fusion` | Full fused-result synchronization and exact ACK fan-out |
| 6 | `06-complex-collaborate-preview-lab.md` | Complex | `/fh-collaborate --rounds 1` | N-agent planning plus scheduler-enforced single writer |
| 7 | `07-complex-auto-validate-migration-kit.md` | Complex | `/fh-auto-validate` | Architect/Main gate-first regression |
| 8 | `08-complex-five-slot-product-blueprint.md` | Complex | Five-slot `/fh-fusion` | Maximum stack, N-source attribution, sole-writer delivery |

The suite spans the preview's Quack/`CONNECT` server mode, remote pushdown, `VARIANT`, triggers, DML in CTEs, `NEAREST` joins, asynchronous I/O, recursive CTE performance, storage v2.0, the PEG parser, native timezone/collation support, and stable C API extensions.
