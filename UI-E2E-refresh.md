# PulseQuant UI & E2E Refresh Implementation Plan

This document outlines the step-by-step technical implementation plan to resolve the engine bottleneck issues, restore manual trading, harden API connectivity, and introduce a robust End-to-End (E2E) testing strategy for the PulseQuant platform.

## Phase 1: Engine Tuning & Bug Fixes

**Goal:** Modify the trading engine to prevent overly aggressive gating and double-counting of execution costs, allowing valid trades to execute.

### Step 1.1: Refactor Hurdle Logic
- **File:** `public/python/engine.py`
- **Action:** Update the `_compute_dynamic_hurdle_bps` method.
- **Details:** 
  - Since the signal generator uses crossed-book pricing (`target_ask`, `feature_bid`, etc.) which already accounts for the Bid-Ask spread, the hurdle should not penalize the strategy with 4x slippage. 
  - Reduce the `round_trip_slippage_bps` multiplier from `4` to `2` (or a configurable lower bound) to represent market impact beyond the top-of-book, rather than the full spread itself.
  - Review the use of mid-price `z_score` vs crossed-book `long_z_score` / `short_z_score` to ensure gross edge isn't artificially penalized.

### Step 1.2: Soften Toxicity Gating
- **File:** `public/python/engine.py` (Specifically inside the `BackgroundAnalyticsWorker` or `SignalGenerator`).
- **Action:** Adjust the `is_toxic` evaluation criteria.
- **Details:** 
  - Relax the Hurst exponent threshold slightly (e.g., from `< 0.5` to `< 0.55` or parameterize it) to tolerate brief periods of random walk without completely shutting down trading.
  - Consider implementing a smoothing factor or a cooling-off period (e.g., requires 3 consecutive minutes of `p_value > 0.05` to trigger toxicity) rather than a binary switch based on the immediate last tick.

### Step 1.3: Expose Debug Telemetry to UI
- **File:** `public/python/engine.py`, `workers/pythonEngine.worker.ts`, and `app/page.tsx`.
- **Action:** Plumb `dynamic_hurdle_bps` and toxicity reasons through the worker boundary.
- **Details:**
  - In `engine.py`, ensure that state dumps (e.g., `_on_heartbeat` or metrics payloads) include the calculated `last_dynamic_hurdle_bps` and the specific reason for toxicity (e.g., `toxic_reason: 'High Hurst'`).
  - Update `types.ts` and `pythonEngine.worker.ts` to forward these fields.
  - Update `app/page.tsx` to conditionally display these metrics in the UI, explaining to the user why trades are being skipped.

---

## Phase 2: UI Restoration (Manual Trading)

**Goal:** Allow users to manually enter/exit positions from the UI by wiring up the existing engine functionality.

### Step 2.1: Implement Manual Trade UI Components
- **File:** `app/page.tsx` or create a new component `components/ManualTradePanel.tsx`.
- **Action:** Add "Buy" and "Sell" buttons.
- **Details:**
  - Create a clean interface with two primary buttons: `Long Target (Short Feature)` and `Short Target (Long Feature)`.
  - Add an input to specify the target notional or edge required (or default to market order parameters if `bps` is omitted).

### Step 2.2: Wire UI to the Worker Hook
- **File:** `app/page.tsx`
- **Action:** Connect the newly created buttons to the `executeTrade` function exported by `usePythonWorker`.
- **Details:**
  - `onClick` handlers should call `executeTrade('buy')` or `executeTrade('sell')`.
  - Ensure the UI correctly reflects pending manual trade execution (e.g., loading spinners) until the engine confirms the position change via state updates.

---

## Phase 3: API & Connectivity Hardening

**Goal:** Prevent Binance API rate limits and ensure proper credential handling across different network modes.

### Step 3.1: Optimize Open Orders Fetching
- **File:** `lib/market-data/adapters/BinanceAdapter.ts`
- **Action:** Modify the `connectUserDataStream` initialization.
- **Details:**
  - Replace the global fetch `this.fetchOpenOrders('')` with targeted requests.
  - Iterate over the currently subscribed `this.symbols` and fetch open orders individually, or rely solely on WebSocket events for open order state construction if possible, to drastically reduce the API weight.

### Step 3.2: Isolate Environment Credentials
- **File:** `lib/market-data/adapters/BinanceAdapter.ts` and `app/page.tsx`.
- **Action:** Ensure keys are invalidated or isolated when switching modes.
- **Details:**
  - When switching between `TESTNET` and `MAINNET`, enforce that the `BinanceAdapter` instance is destroyed and recreated with the correct corresponding base URLs.
  - Validate that `getRuntimeCredentials()` fetches the correct key pair for the specific environment, prompting the user if Testnet keys are missing while switching to Testnet.

---

## Phase 4: E2E Testing Strategy

**Goal:** Implement automated tests to verify the full flow: Data Ingestion -> Engine Worker -> Signal Generation -> UI Update.

### Step 4.1: Setup E2E Trading Spec
- **File:** `e2e/trading.spec.ts` (New file)
- **Action:** Create a Playwright test suite for trading flows.
- **Details:**
  - Configure the test to boot the app in `PAPER` mode by default.

### Step 4.2: Mock Data Injection
- **File:** `lib/market-data/adapters/MockAdapter.ts` (Enhance if needed) and `e2e/trading.spec.ts`.
- **Action:** Inject a deterministic, highly cointegrated data stream.
- **Details:**
  - The `MockAdapter` should be capable of emitting a predefined sequence of `NormalizedTick` events that guarantee a massive Z-Score deviation, overcoming any hurdle.
  - In the E2E test, use Playwright to trigger this mock sequence (e.g., by clicking a hidden "Test Mode" trigger or via URL parameters).

### Step 4.3: Assert Trade Execution
- **File:** `e2e/trading.spec.ts`
- **Action:** Verify the engine reacts and trades.
- **Details:**
  - Assert that after the mock sequence is injected, the engine correctly generates a signal.
  - Assert that a paper trade is executed and appears in the `TradesList` component.
  - Validate that portfolio metrics (Positions, PnL) update accordingly in the UI.

### Step 4.4: Integrate E2E into Pipeline
- **File:** `test_pipeline.sh`
- **Action:** Add the Playwright test suite to the CI pipeline.
- **Details:**
  - Add `npm run test:e2e` to the bash script to ensure these integrated tests are run alongside Python unit tests and backtests.
