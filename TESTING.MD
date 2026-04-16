**Testing Guide**

- Main test locations: `public/python/tests/` (Python engine logic) and `test/` + `e2e/` (JS/Vitest/Playwright).
- Python tests live in `public/python/tests/*.py` and share fixtures via `public/python/tests/conftest.py`.

Quick start (Python engine)
---------------------------
1) Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install pytest pytest-benchmark numpy
```

2) Run all Python tests (from repo root):

```bash
npm run test:py
```

3) Run specific Stat Arb math tests:

```bash
python3 -m pytest public/python/tests/test_math.py -q
python3 -m pytest public/python/tests/test_model.py -q
python3 -m pytest public/python/tests/test_signal.py -q
```

Writing tests
-------------
- Add files under `public/python/tests/` with the prefix `test_`.
- Use fixtures as arguments (e.g., `mock_tick_data` from `conftest.py`).
- Keep tests small, deterministic, and self-contained, specifically when validating $O(1)$ ring buffer computations or Beta resets.

JS tests
--------
- Unit (React/Hooks): `npm run test:unit` (Vitest).
- E2E (UI): `npm run test:e2e` (Playwright).
- Full suite: `npm run test` (Python + Vitest + Playwright).

Setup
-----
- Node 20.19+ required.
- Install dependencies:

```bash
npm ci
npx playwright install --with-deps
```

Debugging
---------
- Verbose PyTest:

```bash
python3 -m pytest public/python/tests/test_execution.py -s -v
```

- Filter tests:

```bash
pytest -k "bivariate" -q
```

Replay helper & Mock Data
-------------
- `tools/replay.py` utilizes JSONL captures to pump mock data through `public/python/engine.py` for backtesting.
- `tools/generate_mock_data.py` builds correlated synthetic Target and Feature tick pairs. You can customize the spread volatility using the CLI.
- Input file format adheres to the `NormalizedTick` shape found in `lib/market-data/types.ts`.

Realistic Backtester Integration
--------------------------------
- Phase 2 introduced a high-fidelity continuous integration pipeline covering exact cost accounting and event routing.
- **`test_pipeline.sh`**: The master CI bash script for the orchestration layer. By default, it runs offline Python unit tests enforcing 10bps slippage bounds and Limit queue trade-through conditions.
  - Quick run (fast unit tests): `./test_pipeline.sh`
  - Integration mode: `RUN_INTEGRATION=1 ./test_pipeline.sh` (Downloads >1.5M ticks natively from Binance Vision for a target date, interleaves funding streams into a `.jsonl`, and validates realistic simulated hedging).
- **`test/test_replay_engine.py`**: A suite of `pytest` functions executing purely over the Python sub-process layer. These validate exchange-style event bus mechanisms (e.g., Maker Limits strict inequality fills, slippage precision, portfolio cash deductions on funding, and `is_maker` flags).

