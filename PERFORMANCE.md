# Algorithmic Analysis - Perfmance

Content: algorithmic underpinnings, time complexities, and data flow architecture of the PulseQuant trading engine and the cointegration/backtesting tool.

---

## 1. Data Architecture and Dataflow

The PulseQuant system employs a "Serverless" pattern to run high-frequency quantitative models entirely in the browser without locking the main UI thread.

### 1.1 Ingestion and Websockets
Market data originates from live WebSockets (e.g., `BinanceAdapter`) and is managed centrally by the `MarketDataService.ts` in Next.js. 
- The adapter normalizes incoming ticks and emits them to subscribers.
- The `useMarketData` hook in the React frontend listens to these ticks and immediately dispatches them to the Pyodide WebWorker via `postMessage`.

### 1.2 The Pyodide WebWorker Bridge (`pythonEngine.worker.ts`)
To prevent the Python WASM environment from freezing due to overwhelming tick volume, the WebWorker implements a **batched queuing system**:
- **Buffering:** Ticks are pushed into an in-memory `tickBuffer`.
- **Batching:** A timeout flushes the buffer to the Python engine (`process_events`) every 50ms.
- **Backpressure / Overflow Protection:** The queue has a hard limit (`MAX_WORKER_QUEUE_SIZE = 400`). If the Python engine execution falls behind, older events are truncated, dropping stale ticks rather than crashing the system with out-of-memory errors or infinite latency buildup.
- **Latency Tracking:** The worker records `netLat` (network to execution) and `sysLat` (queue time to execution) to monitor engine health.

---

## 2. Core Trading Engine (`engine.py`)

The trading engine is engineered strictly for **$O(1)$ constant-time execution** in the hot path. Rolling window operations using standard arrays/dataframes would cause $O(N)$ degradation per tick, which is fatal in high-frequency trading.

### 2.1 Recursive Kalman Filter (`KalmanFilterBivariate`)
Instead of using Rolling Ordinary Least Squares (OLS) to estimate the hedge ratio ($\beta$), the engine uses a dynamic state estimation Kalman Filter.
- **Algorithm:** Treats $\alpha$ (intercept) and $\beta$ (slope) as hidden states in a constant-velocity model, perturbed by process noise ($\delta$).
- **Update Step:** 
  1. Predict: $\theta_{t|t-1} = \theta_{t-1}$
  2. Innovation: $e_t = y_t - (\alpha + \beta x_t)$
  3. Kalman Gain: $K_t = P_{t|t-1} H_t^T (H_t P_{t|t-1} H_t^T + R)^{-1}$
  4. Update: $\theta_t = \theta_{t|t-1} + K_t e_t$
- **Performance:** Since the state space is exactly 2 dimensions ($[\alpha, \beta]$), the covariance matrix $P$ is $2 \times 2$. All matrix operations are expanded into raw algebraic scalars.
- **Time Complexity:** **$O(1)$** per tick. Memory footprint is minimal.

### 2.2 Exponentially Weighted Moving Average (`EWMASingle`)
The spread mean and variance (necessary for the Z-score) are calculated using an exponentially weighted recursive formula.
- **Algorithm:** 
  - $\alpha = 1 - \exp(-\Delta t / \tau)$
  - $\mu_t = \mu_{t-1} + \alpha(x_t - \mu_{t-1})$
  - $\sigma^2_t = (1-\alpha)(\sigma^2_{t-1} + \alpha(x_t - \mu_{t-1})^2)$
- **Performance:** Accounts for asynchronous arrival times via $\Delta t$ in milliseconds, preventing distortion during periods of low liquidity.
- **Time Complexity:** **$O(1)$** per tick.

### 2.3 Zero-Order Hold (ZOH) & Causal Math
The `StatArbModel` aligns asynchronous ticks from two different exchanges/assets.
- **Algorithm:** The last known price of a leg is held constant until a new tick arrives.
- **Crucial Causal Trick:** To prevent look-ahead bias, the spread $S_t$ is calculated using the *prior* state estimates $\beta_{t-1}$ and $\alpha_{t-1}$ before the Kalman filter digests the new price $P_t$. 

### 2.4 Dynamic Hurdle Execution
The `SignalGenerator` evaluates whether an entry edge exceeds the aggregate friction of the market.
- **Dynamic Hurdle:** `maker_fee + taker_fee + slippage + (funding_rate * expected_hold_time)`
- Edge is calculated in basis points based on the $Z$-score variance. Only trades that clear the hurdle are executed.

---

## 3. Cointegration Analysis Script (`cointegration_test.py`)

The research script is built for vectorized batch processing of high-resolution klines to find cointegration bounds.

### 3.1 Lead-Lag Cross Correlation
- **Algorithm:** Computes Pearson correlation $\rho(\tau)$ on smoothed logarithmic returns offset by lag $\tau \in [-30, 30]$.
- **Time Complexity:** **$O(L \cdot N)$** where $L$ is the maximum lag tested and $N$ is the dataset length.
- **Outcome:** Determines which asset acts as the "Feature" (leader) and which is the "Target" (follower).

### 3.2 Cointegration Verification (Engle-Granger)
- **Algorithm:** Performs OLS regression $y_t = \beta x_t + \alpha + \epsilon_t$, then applies the Augmented Dickey-Fuller (ADF) test to the residuals $\epsilon_t$ to confirm stationarity ($I(0)$).
- **Performance Trick:** If $N > 10,000$ points, the data is downsampled to 15-minute intervals. Cointegration is a macro-structural property, so micro-noise is irrelevant to the ADF test. Downsampling drops the ADF time complexity from minutes to milliseconds.

### 3.3 Stochastic Mean-Reversion Modeling
- **Hurst Exponent ($H$):** Uses the variance-of-lags method. If $H < 0.5$, the spread is mean-reverting.
- **Half-Life (Ornstein-Uhlenbeck):** Regresses the change in spread against the lagged spread ($\Delta S_t = \lambda S_{t-1} + \epsilon$). Half-life is $HL = -\ln(2)/\lambda$.

### 3.4 Vectorized Backtester
Unlike the event-driven Pyodide engine, the script's backtester uses vectorized arrays for pure speed.
- **Algorithm:** Calculates signals over the entire $N$-length array, tracks positions using state transitions (1, -1, 0), and calculates gross/net returns applying exact Maker/Taker logic on turnover.
- **Time Complexity:** **$O(N)$**. Enables instantaneous evaluation of years of 1-minute data during parameter sweeps.