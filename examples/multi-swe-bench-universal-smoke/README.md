# Multi-SWE-bench Universal Smoke

Example dataset for `benchrail` built from five instances across `SWE-bench_Multilingual` and `SWE-bench_Lite`:

- `vuejs__core-11915` - TypeScript
- `caddyserver__caddy-6411` - Go
- `tokio-rs__tokio-7139` - Rust
- `fmtlib__fmt-3901` - C++
- `pydicom__pydicom-1694` - Python

The dataset is aimed at smoke-testing the `benchrail-universal:latest` image across different language ecosystems, including one Python task sourced from `SWE-bench_Lite`.
Each instance uses `docker.image` with runtime selection through `docker.env`.

## Included layout

Each instance contains:
- `config.json` with the original `problem_statement` as the prompt
- `patches/test.patch` from the source benchmark parquet
- `environment/setup.sh` for minimal dependency/bootstrap work
- `environment/run-selected-tests.sh` for targeted checks

## Notes

- The selected instances are relatively recent, but the exact repository version is fixed by `base_commit` from the source parquet dataset.
- The dataset is hybrid: four instances come from `SWE-bench_Multilingual`, and `pydicom__pydicom-1694` comes from `SWE-bench_Lite`.
- The JavaScript instance intentionally runs only the Mocha regression added by the patch. The same upstream patch also touches a Karma browser spec, but the Mocha regression is the essential SSRF check and keeps this smoke dataset lightweight.
- This dataset is intended primarily for Docker runs with the universal image. Local runs also work if the host already has matching toolchains installed.
- This directory contains dataset-derived benchmark material.
- `SWE-bench/SWE-bench` upstream repository is MIT-licensed.
- `SWE-bench/SWE-bench_Lite` is available under the MIT License.
- `SWE-bench/SWE-bench_Multilingual` publishes `License: mit` on Hugging Face.
- Verify upstream terms before redistributing dataset-derived artifacts.

## Validate

```bash
uv run benchrail validate --dataset examples/multi-swe-bench-universal-smoke
```


## Run in Docker

```bash
uv run benchrail run --dataset examples/multi-swe-bench-universal-smoke --mode docker
```

If you want to use the local Codex login instead of `CODEX_API_KEY`, add `--auth-session`.
The runner will copy `~/.codex/auth.json` into each task container after it starts.
