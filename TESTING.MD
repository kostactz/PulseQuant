**Testing Guide**

- Main test locations: `public/python/tests/` (Python engine) and `test/` + `e2e/` (JS/Vitest/Playwright).
- Python tests live in `public/python/tests/*.py` and share fixtures in `public/python/tests/conftest.py`.
- Engine tests avoid external IO; call `clear_data()` when depending on global `session` state.

Quick start (Python engine)
---------------------------
1) Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install pytest pytest-benchmark numpy
```

2) Run all Python tests:

```bash
python3 -m pytest public/python/tests/
# or from repo root
npm run test:py
```

3) Run a specific test:

```bash
python3 -m pytest public/python/tests/test_unit_buffers.py::test_ringbuffer_basic -q
python3 -m pytest public/python/tests/test_unit_buffers.py -q
```

4) Benchmark test (local only):

```bash
python3 -m pytest public/python/tests/test_performance.py -q
```

Writing tests
-------------
- Add files under `public/python/tests/` with prefix `test_`.
- Use fixtures as args (`mock_tick_data` from `conftest.py`).
- Keep tests small, deterministic, and self-contained.

JS tests
--------
- Unit: `npm run test:unit` (Vitest).
- E2E: `npm run test:e2e` (Playwright).
- Full run: `npm run test` (py + unit + e2e).

Setup
-----
- Node 20.19+.
- Install:

```bash
npm ci
npx playwright install --with-deps
```

- Python: use `.venv` in repo root.

Debugging
---------
- Verbose pytest:

```bash
python3 -m pytest public/python/tests/test_integration.py::test_cancellation_logic -s -q
```

- Filter tests:

```bash
pytest -k ringbuffer -q
```

- CI skip benchmarks:

```bash
pytest -k "not performance" -q
```

Useful pytest options
---------------------
- `-k`, `-q`, `-s`, `-x`, `--maxfail=1`.

Replay helper
-------------
- `tools/replay.py` uses JSONL captures and `public/python/engine.py`.
- Input file format follows `NormalizedTick` shape from `lib/market-data/types.ts`.
- Use `--report-out` for JSON output of portfolio/trades.

