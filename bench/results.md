# Benchmark: imsg (Rust core) vs pure-Python

Synthetic chat.db: **50,000 messages** (70% stored as attributedBody blobs). Best-of-5 wall time, Apple Silicon. SQLite is the same C library on both sides, so the delta is native + multicore decode/match.

### Full-history search over 50,000 messages (decodes every blob)

| engine | time (ms) | speedup |
|---|---:|---:|
| python | 115.2 | 1.0× (baseline) |
| rust | 34.3 | 3.4× |

### Batched decode of 50,000 attributedBody blobs

| engine | time (ms) | speedup |
|---|---:|---:|
| python | 18.1 | 1.0× (baseline) |
| rust | 19.1 | 0.9× |
