Create a decision-ready DuckDB v2.0 preview adoption memo at `DUCKDB20_ADOPTION_MEMO.md`.

The memo must synthesize:

1. the product opportunities from Quack/`CONNECT`, `VARIANT`, triggers, asynchronous object-store I/O, the PEG parser, storage v2.0, and stable C API extensions;
2. a migration-risk register covering parser compatibility, storage-format changes, preview instability, operational unknowns for server mode, and extension ABI assumptions;
3. three experiments ranked by learning value, each with a falsifiable success criterion;
4. a “preview fact vs. our inference” table so uncertain claims are not presented as release guarantees.

Fusion protocol requirement: all configured workers inspect and propose read-only; only the temporary FUSION agent writes the memo. After fusion, the complete fused memo/result must be sent back into every configured model's context using the no-action synchronization envelope. Each model must reply only `ACK FUSION <run-id>` and must not use tools, critique, revise, or continue the task during acknowledgement.

Source: https://duckdb.org/2026/08/17/duckdb-20-highlights
