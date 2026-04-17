# PulseQuant

In-browser high-performance Statistical Arbitrage (Stat Arb) trading tool and simulator. Features a React Next.js frontend and a Python trading engine running securely in Pyodide.

- Web stack: Next.js + TypeScript + Tailwind
- Core engine: Python (`public/python/engine.py`), sandboxed in WebAssembly via `workers/pythonEngine.worker.ts`
- Live data: Binance WebSocket adapter with dynamic pair selection (Target vs. Feature assets)
- Analysis: Real-time Z-Score, Beta, and spread calculation with interactive charting
- Execution: Paper trading with portfolio tracking and simulated order fills
- Full test suite: Playwright integration + unit tests (Vitest, PyTest)

## What is in this repo

- `app/`: Next.js UI pages and routing
- `components/`: Real-time charts, order books, trades, and strategy controls
- `hooks/`: `useMarketData`, `usePythonWorker`, `useMobile`
- `lib/market-data`: `MarketDataService`, adapters (`BinanceAdapter`, `MockAdapter`)
- `lib/order/OrderManager.ts`: Paper order logic and execution handling
- `lib/security`: API credentials and local cryptography helpers
- `public/python`: Pyodide Stat Arb engine (`engine.py`) and math libraries
- `workers/pythonEngine.worker.ts`: WebWorker bridge isolating heavy math from the UI thread
- `test/`: Vitest unit tests for UI and hooks
- `e2e/`: Playwright end-to-end tests for browser experience

## Key behaviors

1. User dynamically selects two assets (Target and Feature) from the UI.
2. Market data streams via `MarketDataService` using direct Binance WebSockets.
3. Ticks are packaged and dispatched to the WebWorker, avoiding main-thread blocking.
4. `engine.py` maintains an $O(1)$ `BivariateRingBuffer` to compute continuous rolling Beta and Z-Scores.
5. The Worker emits compact strategy signals back to the UI for charting and execution state updates.
6. When pairs are switched, the engine and WebSockets securely tear down and reset to prevent data corruption.

## Run locally

1. `npm install`
2. `npm run dev`
3. Open `http://localhost:3000`

## Backtesting & Analysis Tools

**1. Cointegration Analysis**
Test if two assets are cointegrated and find optimal parameters:
```bash
python public/python/scripts/cointegration_test.py --target-ticker ORDIUSDC --feature-ticker SUIUSDC
```

**2. Fetch Historical Data**
Download Binance Vision archive data (falls back to API if missing) for backtesting:
```bash
python tools/fetch_vision_data.py --symbols ORDIUSDC SUIUSDC --start-date 2026-03-01 --end-date 2026-03-31 --output capture.jsonl
```

**3. Run Replay Backtester**
Run the Python stat-arb engine against the captured historical data:
```bash
python tools/replay.py --input capture.jsonl --target ORDIUSDC --feature SUIUSDC
```

## Tests

- Unit (TS): `npm run test:unit` (Vitest)
- Unit (Python): `npm run test:py` (PyTest for engine logic)
- E2E: `npm run test:e2e` (Playwright)
- All: `npm run test`
