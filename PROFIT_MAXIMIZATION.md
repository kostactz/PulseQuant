# PROFIT MAXIMIZATION & DYNAMIC SIZING PLAN
## 1. Executive Summary
The current statistical arbitrage engine relies on hardcoded static position sizing (`base_size = 0.1` in `ExecutionManager`) and binary regime filters ("Safe" vs "Toxic"). To truly maximize risk-adjusted profit (Sharpe/Sortino ratios) and prevent catastrophic drawdowns during structural regime shifts, the engine must transition to dynamic position sizing. 

This document outlines the step-by-step implementation of the **Continuous Half-Kelly Criterion**, overlaid with **Cointegration Degradation Scaling** and **Volatility Risk Parity**, ensuring optimal capital compounding across both backtest (1s) and live (100ms) data frequencies.

---

## 2. Mathematical Foundations

### 2.1. The Continuous Kelly Fraction
For a continuous-time finance model, the optimal Kelly fraction ($f^*$) representing the percentage of capital to allocate is:
$$f^* = \frac{\mu}{\sigma^2}$$

In our Statistical Arbitrage context:
*   **Expected Return ($\mu$)**: The expected convergence of the spread minus trading costs. We approximate this using the calculated edge: $\mu = \text{Expected Edge (decimal)}$.
*   **Variance ($\sigma^2$)**: The variance of the spread, which we track via our EWMA filter (`spread_std ** 2`).

### 2.2. Half-Kelly
To buffer against non-normal fat tails, parameter estimation errors, and jump-diffusion risk common in crypto, we apply the Half-Kelly heuristic:
$$f_{HK} = \frac{f^*}{2}$$

### 2.3. Cointegration Degradation Scaling (Gradient vs. Binary)
Currently, if the ADF p-value > 0.05, the regime is "Toxic" and sizing is slashed. This binary switch causes sudden portfolio shocks. Instead, we apply a continuous scalar $C_{deg}$:
$$C_{deg} = \max\left(0, 1 - \frac{p\text{-value}}{\text{threshold}}\right)$$
If the threshold is 0.05:
*   At p-value = 0.01: $C_{deg} = 0.8$ (80% allocation)
*   At p-value = 0.04: $C_{deg} = 0.2$ (20% allocation)
*   At p-value >= 0.05: $C_{deg} = 0.0$ (No new allocations)

### 2.4. Volatility Targeting & Gross Exposure Constraints
Regardless of what Half-Kelly suggests, we cap exposure based on the underlying asset's volatility to maintain tail-risk parity:
*   **Max Capital Allocation:** $\min(f_{HK} \times C_{deg}, \text{Max Leverage Limit})$

---

## 3. Step-by-Step Implementation Plan

### Phase 1: Remove Hardcoded Sizes & Plumb Configuration
1.  **Update `engine.py` global stubs**: Implement `set_trade_size(bps)` and `set_strategy_params` to accept max leverage, risk limits, and Kelly multipliers from the UI.
2.  **Refactor `ExecutionManager`**: Remove `self.base_size = 0.1`. Update the state machine to accept dynamically calculated `target_qty` directly from the `SIGNAL_GENERATED` payload.

### Phase 2: Dynamic Signal Generation (Half-Kelly)
1.  **Modify `SignalGenerator._on_model_updated`**:
    *   Convert `expected_edge_long_bps` from basis points back to a decimal expected return ($\mu$).
    *   Calculate variance $\sigma^2$ = `spread_std ** 2`. Ensure $\sigma^2 > 0$ to avoid division by zero.
    *   Calculate $f^* = \mu / \sigma^2$.
    *   Apply Half-Kelly: $f_{HK} = f^* / 2.0$.
2.  **Calculate Target Notional**:
    *   `target_notional = self.portfolio.cash * f_{HK}`
3.  **Pass Target to Execution**:
    *   Inject the calculated `target_notional` into the `SIGNAL_GENERATED` event: `{'direction': 'LONG_SPREAD', 'target_notional': target_notional}`.

### Phase 3: Cointegration & Regime Scaling
1.  **Update `BackgroundAnalyticsWorker`**:
    *   Ensure the precise `adf_pvalue` is always published in the `REGIME_CHANGE` payload, even if it exceeds the toxicity threshold.
2.  **Update `SignalGenerator._on_regime_change`**:
    *   Track the latest `adf_pvalue`.
    *   Calculate $C_{deg} = \max(0.0, 1.0 - (p / 0.05))$.
    *   Apply $C_{deg}$ to the `target_notional` before emitting the signal.

### Phase 4: Tick Frequency Normalization (1s vs 100ms)
**The Data Frequency Problem:**
Our `KalmanFilterBivariate` and `EWMASingle` advance their state *per tick*. In live trading (100ms), 10 ticks occur for every 1 tick in backtesting (1s). This means a window size of `300` ticks represents 5 minutes in backtesting, but only 30 seconds in live trading, drastically altering $\sigma^2$ and $\mu$ estimations.

**The Fix:**
1.  **Time-Based Alpha Decay**: Refactor `EWMASingle` to use a time-based decay factor. Instead of `self.alpha = 2 / (window_size + 1)`, dynamically compute alpha based on the millisecond timestamp delta (`dt`) between the current tick and the last tick.
    *   $\alpha = 1 - \exp(-\frac{dt}{\tau})$, where $\tau$ is the target time constant (e.g., 5 minutes in milliseconds).
2.  **Kalman Filter Covariance Injection**: Scale the state covariance injection (`self.delta`) in `KalmanFilterBivariate` proportionally to `dt`.

---

## 4. Impacted Files & Components

*   **`public/python/engine.py`**
    *   `EWMASingle`: Refactor `append()` to accept `timestamp` for time-based alpha.
    *   `KalmanFilterBivariate`: Refactor `append()` to accept `timestamp` for time-scaled `delta`.
    *   `StatArbModel`: Pass tick timestamps into the math utilities.
    *   `SignalGenerator`: Implement Kelly math, $C_{deg}$ scaling, and volatility caps in `_on_model_updated`.
    *   `ExecutionManager`: Remove `base_size`, parse `target_qty` from intents, and ensure maker leg accurately sizes to the requested dynamic notional.
*   **`tools/replay.py`**
    *   Ensure CLI arguments can configure the Kelly multiplier (e.g., `--kelly-fraction 0.5`).

---

## 5. Acceptance Criteria

1.  **Dynamic Sizing Removal**: No hardcoded `0.1` asset base sizes exist anywhere in `engine.py`.
2.  **Half-Kelly Execution**: The `target_qty` of a `PLACE_ORDER` intent mathematically matches $0.5 \times (\text{Edge} / \text{Variance}) \times \text{Available Cash}$ (scaled by regime).
3.  **Degradation Curve**: When the ADF p-value shifts from 0.01 to 0.04 in `BackgroundAnalyticsWorker`, the resulting trade sizes proportionally shrink without triggering a hard "Toxic" binary stop.
4.  **Time Invariance**: Running the strategy over a 1s downsampled dataset produces ~95% identical trade signals and Z-scores as running it over the raw 100ms dataset, proving time-based EWMA/Kalman normalization works.
5.  **Capital Preservation**: A backtest over a known structural break (where pairs permanently diverge) results in an asymptotic reduction of trade size to $0$, avoiding the characteristic "Kelly Blowup" drawdown.