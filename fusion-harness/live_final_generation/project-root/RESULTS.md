# SQLite Bulk Insert Benchmark Results

Fresh measurements: **1,000,000 target rows**, Python 3.12.13, SQLite 3.50.4, macOS-26.5.2-arm64-arm-64bit.

The timer includes row generation, binding, insertion, and commit. WAL timing also includes `wal_checkpoint(TRUNCATE)`. Each strategy ran in a fresh process against a fresh database.

| Strategy | Measured rows | Time 1M rows (s) | Speedup vs naive | Peak RAM (MB) | RSS over base (MB) |
|---|---:|---:|---:|---:|---:|
| `set_based_ctes` | 1,000,000 | 0.1700 | 1147.98x | 26.051 | 4.014 |
| `executemany_gen` | 1,000,000 | 0.3480 | 560.77x | 25.625 | 3.588 |
| `max_tuned_gen` | 1,000,000 | 0.3484 | 560.15x | 25.641 | 3.604 |
| `executemany_list` | 1,000,000 | 0.3761 | 518.88x | 228.737 | 206.701 |
| `wal_tuned_gen` | 1,000,000 | 0.3918 | 498.07x | 25.903 | 3.867 |
| `one_big_txn_loop` | 1,000,000 | 0.6071 | 321.41x | 25.854 | 3.817 |
| `naive_autocommit` | 20,000 (sampled) | 195.1362* | 1.00x | 24.183 | 2.146 |

\* `naive_autocommit` ran 20,000 real rows; its measured time was scaled by 50. Its RAM reading is measured, not scaled, and it is excluded from the memory-winner decision.

`max_tuned_gen` and `set_based_ctes` use `journal_mode=OFF`/`synchronous=OFF`; they are for rebuildable staging loads only.

Bare-worker peak RSS calibration: **22.036 MB**.
Total benchmark wall time: **6.857 s**.

**Speed Winner: `set_based_ctes`** — 0.1700 s, 1147.98x faster than naive.
**Memory Winner: `executemany_gen`** — 25.625 MB peak RSS, +3.588 MB over the calibration worker.
