# PulseQuant

[Live preview](https://pulsequant.kostas-chatzis.me/)

**PulseQuant** is a high-performance, in-browser Statistical Arbitrage (Stat Arb) trading tool and simulator, for crypto Perpetual Futures on Binance. It combines a modern React/Next.js frontend with a robust Python trading engine running in WebAssembly (Pyodide), enabling execution directly in the browser.

## Mission

It implements a UI and trading engine, designed for medium-frequency trading of cointegrated crypto pairs, featuring real-time state estimation and automated execution logic.

### Technical Highlights
- **Python Engine (`engine.py`):** A custom event-driven engine featuring:
    - **Recursive Kalman Filters:** $O(1)$ dynamic estimation of Beta (hedge ratio) and Alpha.
    - **Causal Analytics:** Z-Score and spread calculations using Beta priors to eliminate look-ahead bias.
    - **Zero-Order Hold (ZOH):** Precise alignment of asynchronous market data ticks.
    - **Maker-Taker State Machine:** Sophisticated execution management with dynamic cost hurdles (fees, slippage, funding).
- **WASM Integration:** Heavy quantitative logic is offloaded to WebWorkers via **Pyodide**, ensuring a responsive 60fps UI.
- **Backtesting Suite:** A high-fidelity replay tool (`tools/replay.py`) that simulates market-order slippage and limit-order trade-throughs.

A details analysis of the algorithmic implementation can be found in [PERFORMANCE.md](./PERFORMANCE.md)

---

## Latest Analysis & Reports

We recently conducted an exhaustive cointegration and backtesting study on the **ORDI/SUI** pair:
**[View the Technical Report: ORDI/SUI Cointegration Analysis](reports/publish.md)**

---

## Development & Quick Start

### 1. Local Development
```bash
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) to access the live trading dashboard.

### 2. Backtesting Workflow
Download historical data from Binance Vision and run the engine replay:
```bash
# Fetch data
python tools/fetch_vision_data.py --symbols ORDIUSDC SUIUSDC --start-date 2026-03-01 --end-date 2026-03-31 --output capture.jsonl

# Run replay
python tools/replay.py --input capture.jsonl --target ORDIUSDC --feature SUIUSDC --verbose
```

### 3. Cointegration Analysis
Discover new pairs and find optimal entry parameters:
```bash
python public/python/scripts/cointegration_test.py --target-ticker ORDIUSDC --feature-ticker SUIUSDC --backtest 40
```

---

## Testing Suite

PulseQuant maintains a rigorous testing environment across both TypeScript and Python:

- **Full Suite:** `npm run test`
- **Engine Logic:** `npm run test:py` (PyTest)
- **UI & Hooks:** `npm run test:unit` (Vitest)
- **E2E Integration:** `npm run test:e2e` (Playwright)

## Repository Structure

- `app/`: Next.js pages and global styles.
- `public/python/`: The heart of the engine (`engine.py`) and analytics core.
- `workers/`: Pyodide orchestrator for WebWorker execution.
- `lib/market-data/`: Multi-adapter service for live (Binance) and mock data.
- `tools/`: CLI utilities for data ingestion and optimization.

---