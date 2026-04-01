# PulseQuant

In-browser medium-frequency trading tool (and simulator), with a React Next.js frontend and a Python trading engine (Pyodide).

- Web stack: Next.js + TypeScript + Tailwind
- In-browser trading engine: Python (`public/python/engine.py`), invoked through `workers/pythonEngine.worker.ts`
- Live/data test patterns: Binance adapter plus mock replay feed
- Paper trading with order book and trade history visualization
- Full test suite: Playwright integration + unit tests (Vitest, PyTest)

## What is in this repo

- `app/`: Next.js UI pages and routing
- `components/`: chart, orderbook, trades, setup modal
- `hooks/`: `useMarketData`, `usePythonWorker`, `useMobile`
- `lib/market-data`: `MarketDataService`, adapters (`BinanceAdapter`, `MockAdapter`)
- `lib/order/OrderManager.ts`: paper order logic and fills
- `lib/security`: credentials and cryptography helpers
- `public/python`: Pyodide engine and analysis scripts
- `workers/pythonEngine.worker.ts`: worker bridge between TS and Python
- `test/`: your unit tests and setup
- `e2e/`: Playwright end-to-end tests for browser experience (in development)

## Key behaviors

1. Market data enters via `MarketDataService` (live websocket or local mock replay).
2. Data is throttled/aggregated then sent into Python worker as tick snapshot packages.
3. `engine.py` maintains rolling indicators, OFI/OBI, VWAP, risk rules, paper orders, and portfolio statistics.
4. Worker emits compact arrays for charting and UI state updates.

## Run locally

1. `npm install`
2. `npm run dev`
3. Open `http://localhost:3000`

## Tests

- Unit (TS): `npm test` (Vitest)
- Unit (Python): `pytest` (in `public/python/tests` and `public/python/scripts`)
- E2E: `npm run test:e2e` (Playwright)
