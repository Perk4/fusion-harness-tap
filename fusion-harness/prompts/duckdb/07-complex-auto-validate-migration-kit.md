Build a DuckDB v2.0 preview migration-readiness kit in `duckdb20_migration_kit/`.

The kit must contain:

- `README.md` with preview installation assumptions and a non-destructive workflow;
- `inventory.py`, an Astral `uv` single-file script that inspects a supplied directory of `.sql` files and reports constructs most likely to need v2.0 review: parser-sensitive syntax, lambda syntax, extension loading, storage-file assumptions, JSON-heavy columns that may benefit from `VARIANT`, and candidates for DML-in-CTE modernization;
- `fixtures/` with representative safe SQL inputs;
- `EXPECTED.md` explaining findings and distinguishing confirmed breaking changes from cautious review flags;
- automated tests runnable without network access or a DuckDB server.

If a DuckDB v2 preview is locally available, add an optional capability probe for the new parser, `VARIANT`, and triggers. If it is not available, the core inventory tests must still run and the probe must report `SKIP`, never a fabricated pass.

The acceptance gate must be designed before implementation and objectively verify every requested file, behavior, test, and honest preview-capability status.

Source: https://duckdb.org/2026/08/17/duckdb-20-highlights
