# NEW_IMPLEMENTATION.md

## 1. Executive Summary
This document defines the architecture, quantitative logic, and engineering requirements for transforming the PulseQuant prototype into a production-grade Statistical Arbitrage (Stat Arb) trading engine. The objective is to pivot from a single-instrument directional strategy to a market-neutral, cointegration-based pair trading system (e.g., `BTCUSDT` / `ETHUSDT`), equipped with a deterministic backtesting harness, a robust asynchronous risk manager, and seamless UI integration.

## 2. Requirements Analysis

### 2.1 Retired Requirements
*   **Single-Leg Directional Trading:** The engine will no longer generate unhedged directional signals based on single-asset momentum or mean reversion. 
*   **Arbitrary Single-Asset Stop-Losses:** Stop-losses and take-profits are now evaluated at the *spread/portfolio* level rather than the individual asset level, unless guarding against catastrophic systemic risk.

### 2.2 Enhanced Requirements
*   **Backtesting & Determinism:** The `replay.py` harness is completely rewritten to process asynchronous *pair* ticks concurrently and simulate fills for both legs of the trade deterministically.
*   **UI Synchronization:** The UI delta payloads (`get_ui_delta()`) are expanded to include multi-asset portfolio states, spread values, dynamic hedge ratios, and z-scores. 
*   **Execution Logic:** Simulated execution must now route maker/taker orders for *two* assets asynchronously, rigorously managing the risk of "legging in" (where one leg fills but the other doesn't).

### 2.3 New Requirements
*   **Decoupled Pub-Sub Architecture:** The engine must handle trades, calculations, and ticks asynchronously via an in-memory event bus.
*   **Zero-Order Hold (ZOH) Alignment:** The engine must align timestamped ticks for a target and feature asset in real-time, bridging asynchronous data feeds safely.
*   **Multi-Frequency Analytics:** Real-time $O(1)$ computation of spread, hedge ratio (OLS), and z-score on every tick, with heavy stats (ADF, Half-life) offloaded to a background timer (e.g., per minute).
*   **Hedged Exposure Constraints:** Strict portfolio checks ensuring net delta remains within neutral bounds (e.g., Target Notional $\approx$ Feature Notional).
*   **Toxicity & Regime Gating:** Trading halts when regime changes occur, such as spread volatility expanding beyond historical norms or loss of cointegration.

---

## 3. Scientific & Quantitative Design

### 3.1 The Spread Model
The strategy relies on the relationship between two highly correlated assets.
*   **Target Asset ($Y$):** e.g., BTCUSDT
*   **Feature Asset ($X$):** e.g., ETHUSDT
*   **Hedge Ratio ($\beta_t$):** Estimated via a rolling Ordinary Least Squares (OLS) regression over a window $W$.
    $$ \beta_t = \frac{\text{Covariance}_W(X, Y)}{\text{Variance}_W(X)} $$
*   **Spread ($S_t$):** The residual of the relationship.
    $$ S_t = Y_t - \beta_t X_t $$

### 3.2 Signal Generation (Z-Score)
To normalize the spread and generate standardized signals:
*   **Rolling Mean ($\mu_t$) & Standard Deviation ($\sigma_t$):** Calculated over the trailing window $W$.
*   **Z-Score ($Z_t$):** 
    $$ Z_t = \frac{S_t - \mu_t}{\sigma_t} $$
*   **Entry Logic:**
    *   **Long Spread:** $Z_t < -\text{EntryThreshold}$ (Buy $Y$, Sell $X$)
    *   **Short Spread:** $Z_t > \text{EntryThreshold}$ (Sell $Y$, Buy $X$)
*   **Exit Logic:**
    *   **Mean Reversion:** Close positions when $Z_t$ reverts to $0$ (or a defined exit threshold).
    *   **Stop Loss / Time Stop:** Close if $Z_t$ exceeds a critical boundary (e.g., $|Z_t| > 4.0$) or if the trade age exceeds a multiple of the estimated half-life.

### 3.3 Multi-Frequency Calculation Matrix
To achieve $<100$ms tick-to-trade latency while maintaining deep statistical validity:
*   **Per-Tick (High-Frequency):**
    *   Update ZOH prices.
    *   $O(1)$ recursive updates to rolling Covariance and Variance.
    *   Calculate instantaneous Hedge Ratio ($\beta$), Spread ($S_t$), and Z-Score ($Z_t$).
    *   Threshold breach checks for entries/exits/stop-losses.
*   **Per-Second (Mid-Frequency):**
    *   Update portfolio risk metrics (Drawdown, Gross/Net Exposure).
    *   Check for stale Maker orders and cancel/replace them.
*   **Per-Minute (Low-Frequency):**
    *   Run ADF Cointegration test.
    *   Estimate Ornstein-Uhlenbeck (OU) Half-Life.
    *   Toxicity Gating: If ADF p-value $> 0.05$ (cointegration lost) or Half-Life $>$ threshold, emit `REGIME_CHANGE` to halt new entries and aggressively close open spreads.

---

## 4. Technical Architecture & Data Flow

### 4.1 Event-Driven Pub-Sub Core
The engine relies on an internal Event Bus (`engine.py::EventBus`) to decouple ingestion, analytics, and execution.
*   **`TICK_{SYMBOL}`:** Emitted when new market data arrives. Triggers ZOH updates and high-frequency math.
*   **`TIMER_{FREQ}`:** Clock-driven events (1s, 60s). Triggers risk checks and heavy math.
*   **`SIGNAL_GENERATED`:** Emitted when a Z-score crosses a threshold.
*   **`ORDER_UPDATE`:** Emitted asynchronously when an execution report arrives.

### 4.2 Asynchronous Execution & Legging Risk Management
To ensure utmost safety, we implement a "Maker-Taker" asynchronous execution state machine:
1.  **Signal Triggered:** (e.g., Long Spread -> Buy Target, Sell Feature).
2.  **Leg 1 (Maker):** Post a passive limit order for the leg with the wider spread/lower liquidity.
3.  **Wait State:** The system waits. If the Z-score reverts before the Maker is filled, the Maker order is canceled.
4.  **Leg 1 Filled:** Upon receiving the `FILLED` event for Leg 1, the engine *immediately* fires Leg 2.
5.  **Leg 2 (Taker):** Executed as a Market (or highly aggressive limit) order to instantly hedge the exposure and lock in the stat arb, eliminating directional risk.

### 4.3 Data Alignment (Zero-Order Hold)
Because real-world data and capture files are asynchronous, the system uses a Zero-Order Hold (ZOH) buffer. When `BTCUSDT` ticks, the engine evaluates the spread against the *last known* price of `ETHUSDT`, ensuring zero lookahead bias and stable backtests.

---

## 5. Implementation Phasing

*   **Phase 1: Foundation.** Implement `EventBus`, ZOH Data Ingestion, and the timer/clock sequence.
*   **Phase 2: Math Core.** Refactor `RingBuffer` for bivariate $O(1)$ covariance. Implement tick-level $\beta$, Spread, and Z-score calculations.
*   **Phase 3: Deep Stats & Signals.** Implement low-frequency ADF/Half-life timers. Build the Signal Generator listener.
*   **Phase 4: Execution & Risk.** Build the Maker-Taker asynchronous state machine and Portfolio limit guards.
*   **Phase 5: Backtesting.** Rewrite `replay.py` to ingest raw capture files, emit ticks to the Event Bus, and simulate asynchronous execution delays.
*   **Phase 6: UI & Polish.** Update `get_ui_delta()` to export pair metrics and integrate with Next.js frontend charts.

---

## 6. Detailed Component Breakdown & Enhancements

This section details the concrete changes required across all files, functions, and logic boundaries.

### 6.1 Core Engine (`public/python/engine.py`)

*   **Component: `EventBus` (New)**
    *   *Purpose:* Centralized Pub-Sub dispatcher for all internal components.
    *   *Functions:* `subscribe(topic, callback)`, `publish(topic, payload)`.
*   **Component: `BivariateRingBuffer` (Refactored/New)**
    *   *Purpose:* Replaces single-variable `RingBuffer` to support $O(1)$ pair statistics.
    *   *Logic:* Maintains arrays for $X$ and $Y$. Computes running sums for $\sum X$, $\sum Y$, $\sum X^2$, $\sum Y^2$, and $\sum XY$.
    *   *Methods:* `append(x, y)`, `covariance()`, `variance_x()`, `beta()`, `correlation()`.
*   **Component: `StatArbModel` (New)**
    *   *Purpose:* The "Analytics Layer" managing the ZOH alignment and continuous math.
    *   *Subscriptions:* `TICK_{TARGET}`, `TICK_{FEATURE}`.
    *   *Logic:* Caches latest ticks. When *either* updates, pushes the $(Target, Feature)$ tuple into `BivariateRingBuffer`. Computes $S_t$ and $Z_t$. Emits `MODEL_UPDATED`.
*   **Component: `SignalGenerator` (New)**
    *   *Purpose:* Listens to the model, applies strategy thresholds, and generates trade intents.
    *   *Subscriptions:* `MODEL_UPDATED`, `TIMER_1M` (for regime checks).
    *   *Logic:* Checks $Z_t$ against `EntryThreshold`. Emits `SIGNAL_GENERATED` (Long/Short) or `CLOSE_SPREAD`. Handles Toxicity flags.
*   **Component: `ExecutionManager` / `PortfolioManager` (Refactored)**
    *   *Purpose:* Replaces current directional routing. Manages the Async Legging State Machine.
    *   *Subscriptions:* `SIGNAL_GENERATED`, `ORDER_UPDATE`.
    *   *Logic:* 
        *   Maintains state enum (e.g., `IDLE`, `LEGGING_MAKER`, `HEDGED`). 
        *   On `SIGNAL_GENERATED`, routes Maker limit order for Leg 1.
        *   On `ORDER_UPDATE` (FILLED) for Leg 1, routes Market order for Leg 2.
    *   *Risk:* Checks net delta vs gross exposure limits.
*   **Component: `process_events(events)` (Refactored)**
    *   *Purpose:* The main ingest pipeline from outside callers (Replay or Pyodide).
    *   *Logic:* Deconstructs raw JSON events and publishes them directly to `EventBus`. Returns an aggregate of Intents generated during the tick cycle.
*   **Component: `get_ui_delta()` (Refactored)**
    *   *Purpose:* State serialization for the frontend.
    *   *Additions:* Must now serialize `spread`, `z_score`, `hedge_ratio`, `target_position`, `feature_position`, and `toxicity_state`.

### 6.2 Backtest & Replay Harness (`tools/replay.py`)

*   **Component: `load_rows()` & Data Alignment**
    *   *Fix/Enhancement:* Because we need *two* datasets (Target and Feature), the loader must ingest dual data feeds or a pre-aligned pair dataset. It must stream ticks strictly ordered by timestamp, simulating the asynchronous arrival of cross-asset market data.
*   **Component: `Simulation Loop`**
    *   *Enhancement:* Must handle a simulated clock to emit `TIMER_1S` and `TIMER_1M` events to the Engine's EventBus.
    *   *Enhancement:* Must support simulated execution delays. When Leg 1 fills, it must wait to receive the Leg 2 Intent, then simulate Leg 2 execution.
*   **Component: `Metrics Engine`**
    *   *Fix:* Adjust PnL calculations to aggregate both legs of the pair. Add "Hit Ratio" based on spread closures, not single-asset closures.

## 7. Quant Analyst Refinements & Rigor

Upon review of the initial plan, the following quantitative adjustments are necessary to ensure the engine behaves robustly under live, high-frequency conditions:

### 7.1 Log-Price Transformation
*   *Issue:* Using absolute prices ($Y_t - \beta X_t$) in crypto is dangerous due to massive price scale shifts. A beta calculated at BTC=\$50k will fail structurally at BTC=\$100k.
*   *Refinement:* All models (OLS, Covariance, Spread) must be computed on **Log-Prices**: $y_t = \ln(Y_t)$ and $x_t = \ln(X_t)$. 
    *   The spread becomes a log-spread: $S_t = y_t - \beta x_t$. 
    *   This naturally scales for percentage changes and maintains stationarity over much longer regimes.

### 7.2 Exponentially Weighted Moving Averages (EWMA) vs SMA
*   *Issue:* A standard `RingBuffer` (SMA) suffers from "drop-off" shocks. When a massive outlier exits the window $W$ steps later, $\beta$ and $\mu$ will violently jump, causing false signals.
*   *Refinement:* The `BivariateRingBuffer` must be replaced or augmented with an **EWMA** implementation for covariance, variance, and means. EWMA ensures smooth decay of old data, eliminating drop-off shocks and providing a more reactive $\beta_t$.

### 7.3 Explicit Window Definitions ($W_\beta$ vs $W_z$)
*   *Issue:* The plan implies a single window $W$.
*   *Refinement:* We must decouple the Structural Window from the Tactical Window.
    *   $W_\beta$: A longer halflife/window (e.g., hours/days) to establish the true cointegrating relationship.
    *   $W_z$: A shorter halflife/window (e.g., minutes/hours) for the z-score mean ($\mu_t$) and standard deviation ($\sigma_t$) to capture local tactical deviations.

### 7.4 Fee-Aware Signal Generation
*   *Issue:* Entering at $Z=2.0$ guarantees nothing if the spread edge doesn't cover transaction costs.
*   *Refinement:* The $Z$-score threshold must be dynamically adjusted, or the signal logic must explicitly check the expected spread capture against `TakerFee + MakerFee + BidAskSpread`.
    *   $ExpectedEdge = (Z_t \times \sigma_t) - Costs$. 
    *   Only emit `SIGNAL_GENERATED` if $ExpectedEdge > MinProfitBps$.

### 7.5 Leg Sizing and Rebalancing
*   *Issue:* Sizing Leg 2 as $Size_X = Size_Y \times \beta_t$ is correct at entry. However, as $\beta$ changes over the holding period, the hedge becomes imperfect.
*   *Refinement:* The engine must determine sizes *at entry* and hold them constant. We **do not** continuously rebalance the legs while the trade is open, as this would incur devastating fee drag.

### 7.6 Bid-Ask Execution Realism
*   *Issue:* Calculating $S_t$ on "last price" or mid-price during live execution leads to illusory PnL.
*   *Refinement:* 
    *   **Long Spread Signal:** Evaluate $Z_t$ using the executable prices: Buy Target at *Ask*, Sell Feature at *Bid*.
    *   **Short Spread Signal:** Sell Target at *Bid*, Buy Feature at *Ask*.
    *   This strictly prevents the engine from signaling on an illusory z-score spike that is purely a momentary widening of the bid-ask spread.

### 6.3 UI & Frontend Integration (`src/`)

*   **Component: `Trading Dashboard`**
    *   *Enhancement:* Add a new Chart for the **Spread ($S_t$)** with bands representing the Rolling Mean ($\mu_t$) and the $+/- Z$-score thresholds.
    *   *Enhancement:* Update position table to clearly display Hedged State (Target Pos vs Feature Pos, Delta).
*   **Component: `Strategy Controls`**
    *   *Enhancement:* Expose new pair-trading parameters:
        *   `Target Asset` & `Feature Asset` selectors.
        *   `Z-Score Entry/Exit Thresholds`.
        *   `Rolling Window Size` (in seconds/ticks).
        *   `Max Half-Life` limit.
*   **Component: `WebWorker / Pyodide Bridge`**
    *   *Fix:* Ensure the JSON payload bridge supports the expanded `get_ui_delta` schema without parsing performance hits.

## 8. Engineering & Implementation Specifications

To ensure clean code, maintainability, and clear developer handoff, the following engineering specifications bridge the gap between the quantitative model and the actual codebase.

### 8.1 Code Cleanup & Deprecation Strategy
The existing `engine.py` contains logic for directional, single-asset trading. To prevent tech debt and spaghetti code, we will perform a hard pruning:
*   **To be Deleted:**
    *   Old directional indicators (e.g., RSI, MACD, or single-asset momentum trackers if they exist).
    *   Single-asset stop-loss and trailing-stop logic inside the order manager.
    *   Any hardcoded symbol assumptions.
*   **To be Refactored/Kept:**
    *   `RingBuffer` will be kept as a base concept but rewritten to support EWMA and Bivariate ($X, Y$) operations.
    *   The core metrics accumulator (PnL, Drawdown, Profit Factor) will be adapted to calculate based on portfolio aggregate value rather than single-asset PnL.

### 8.2 Frontend WebSocket & Data Flow (React -> Pyodide)
The current UI likely streams a single asset's data to the Pyodide WebWorker. This pipeline must be completely overhauled:
*   **Dual WebSocket Subscriptions:** The Next.js frontend must subscribe to Binance WebSockets (e.g., `@bookTicker` or `@depth`) for *both* the Target and Feature assets concurrently.
*   **Message Normalization:** The React `onMessage` handler must normalize these ticks into a standard JSON payload with explicit symbol tags:
    `{ "type": "TICK", "symbol": "BTCUSDT", "timestamp": 1670000000, "bid": 50000, "ask": 50001 }`
*   **Pyodide Bridge Payload:** The frontend pushes these tagged ticks into the Pyodide WebWorker, which calls `engine.process_events([tick])`.

### 8.3 WebWorker / Engine API Contract
The interface between `worker.js` (or Pyodide equivalent) and `engine.py` must be strictly typed:
*   **Configuration API:** `engine.configure_strategy({"target": "BTCUSDT", "feature": "ETHUSDT", "z_entry": 2.0, "z_exit": 0.0})`
*   **Tick API:** `engine.process_events(events_array)`
*   **State API:** `engine.get_ui_delta()` must return a predictable dictionary mapped directly to React state updates:
    ```json
    {
      "portfolio_value": 10500,
      "positions": {"BTCUSDT": 0.5, "ETHUSDT": -8.0},
      "spread_metrics": {"current_spread": 150.5, "z_score": 2.1, "beta": 16.5},
      "toxicity_flag": false
    }
    ```

### 8.4 State Management (Next.js)
*   **Zustand/Redux Store:** The global state must be updated to track `positions` as a dictionary/map rather than a single number.
*   **UI Components:** The order book / depth charts must be duplicated or tabbed to show both Target and Feature assets.

### 8.5 Testing Methodology
Before integrating the full engine, we will adopt a bottom-up test-driven approach:
1.  **Unit Tests (Math):** Explicitly test `BivariateRingBuffer` (EWMA, Covariance, Beta) against `pandas` and `statsmodels` output using a static CSV fixture.
2.  **Unit Tests (EventBus):** Verify that asynchronous pub-sub events fire in the correct sequence without deadlocks.
3.  **Integration (Replay):** Run a 1-hour captured dual-tick `.jsonl` file through `replay.py` and assert that Leg 1 and Leg 2 orders are generated correctly.

## 9. Performance, Scalability & Maintainability (Engineering Deep Dive)

As a final technical validation before execution, we must address the specific performance bottlenecks introduced by running a high-frequency trading engine in a browser environment (Pyodide/WASM) and the associated asynchronous UI data flows.

### 9.1 The Pyodide/WASM Communication Bottleneck
*   **The Threat:** Crossing the JavaScript <-> Python (WASM) boundary is computationally expensive. Pushing 1,000 individual WebSocket ticks per second across this boundary will freeze the browser.
*   **The Solution (Tick Batching):** The JavaScript WebWorker must act as a buffer. It will aggregate incoming Binance WebSocket ticks into an array and flush them to `engine.process_events(batch)` at a controlled interval (e.g., every 50ms or 100ms). This reduces cross-boundary calls by 90%+ while preserving data sequence.

### 9.2 EventBus: Synchronous vs. Asynchronous
*   **The Threat:** Using Python's native `asyncio` for the internal `EventBus` can introduce unpredictable latency and complicate Pyodide compatibility.
*   **The Solution (Synchronous Dispatch):** The `EventBus` will use a purely synchronous, callback-based dispatcher for high-frequency events (`TICK`, `ORDER_UPDATE`). This guarantees deterministic execution order and $O(1)$ overhead. Only low-frequency timers (e.g., 60s ADF tests) will yield to background threads or scheduled tasks.

### 9.3 UI Thread & Render Throttling
*   **The Threat:** React re-rendering a chart 100 times a second will cause dropped frames and UI lockups.
*   **The Solution (Decoupled Rendering):** 
    1.  **WebWorker Offloading:** All WebSocket connections, JSON parsing, and Pyodide engine executions MUST live inside a dedicated WebWorker, completely detached from the main UI thread.
    2.  **Throttled UI Updates:** The WebWorker will emit a `get_ui_delta()` payload back to the main React thread at a maximum rate of 10Hz (100ms).
    3.  **Fixed-Length Arrays:** All charting data structures in React must use fixed-length arrays (e.g., max 1000 points) to prevent memory leaks and garbage collection stutters.

### 9.4 Code Maintainability & Type Safety
*   **The Threat:** Python dictionaries mapping to JS objects can easily break if schemas change, leading to silent failures in the UI.
*   **The Solution:** 
    *   Use explicit `TypedDict` or `dataclasses` in Python for the `get_ui_delta()` output.
    *   Create matching TypeScript interfaces (`engine.d.ts`) in the frontend to guarantee contract enforcement between the Python Engine and the React UI.

---

## 10. Current Progress & Next Steps

### 10.1 Completed Phases
All core engineering and quantitative phases (Phases 1-6) have been implemented:
*   **Math & Core Engine:** EventBus architecture is operational. Bivariate statistics (Covariance, Variance, Beta) update in $O(1)$ time. Signal generation successfully calculates the spread and z-score for trade intents.
*   **Execution & Risk:** The `ExecutionManager` handles asynchronous Maker-Taker state machine logic. The `PortfolioManager` actively tracks dual-asset positions and net delta constraints.
*   **Backtesting:** `tools/generate_mock_data.py` produces realistic paired market data. `tools/replay.py` accurately tests asynchronous delays and legging scenarios.
*   **Frontend UI:** Dual WebSocket streams (`BinanceAdapter.ts`) are working, Pyodide bridge correctly handles `get_ui_delta()`, and React components render the new Stat Arb metrics (Spread, Z-score, Net Delta, Toxicity flags).

### 10.2 Next Steps & Remaining Tasks
1.  **End-to-End Browser Testing:** Run the local dev server (`npm run dev`) and manually QA the UI to ensure the WebWorker tick batching runs smoothly without locking up the UI thread.
2.  **Testnet / Paper Trading Verification:** Connect the backend engine to Binance Testnet (or prolonged paper trading) to validate execution mechanics and ZOH alignments over live network latency.
3.  **Performance Profiling:** Validate that React fixed-length arrays and the Pyodide WebWorker don't leak memory over prolonged runtime sessions.
4.  **Code Cleanup:** Prune any lingering dead code related to the legacy directional (single-asset) system and apply final stylistic polishes to the dashboard components.
