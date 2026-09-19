DuckDB v2.0 introduces DuckDB-as-a-server through Quack and the `CONNECT` statement. A client can `ATTACH 'quack:server.example.com' AS qk (TOKEN '...')`, `CONNECT qk`, run queries remotely, and `DISCONNECT`. `CONNECT` can also route SQL to PostgreSQL or MySQL with remote pushdown.

Explain to a developer, in under 350 words, how session routing changes between `ATTACH` and `CONNECT`, then provide one minimal server/client walkthrough and three checks for proving the query ran remotely rather than pulling the full table locally.

This is a direct one-agent explanation. Do not create files, run tools, or perform setup. Use only the supplied launch context and clearly label anything the preview article does not specify.

Source: https://duckdb.org/2026/08/17/duckdb-20-highlights
