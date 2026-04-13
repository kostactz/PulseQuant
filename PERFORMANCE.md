PulseQuant - Performance & Algorithmic Design
==========================================

This document outlines the performance constraints and quantitative algorithms powering the Statistical Arbitrage engine.

High-level goals
-----------------
- Per-tick computations must be bounded and predictable, specifically achieving $O(1)$ constant time execution in the core math engine.
- Complete thread isolation: The main UI thread must not handle floating-point math, linear regression, or strategy logic. All heavy lifting happens in the WebWorker.
- Memory isolation: Changing market pairs must immediately tear down and reclaim associated buffers to avoid state bleed.

Critical Components & Complexity
-----------------------------------------

1) BinanceAdapter Order Book (`lib/market-data/adapters/BinanceAdapter.ts`)
   - Data structures: Two arrays (`obBids`, `obAsks`) managing the order book up to 1000 levels.
   - Live updates: Deltas arrive via `@depth@100ms`, inserted using a fast binary search index ($O(\log N)$) followed by array splices (worst case $O(N)$). 
   - Time-coherent delta OFI (Order Flow Imbalance): Stored `prevBids`/`prevAsks` compared to current top 5 levels via simple differences ($O(1)$) to inject microstructure context.
   - Reconnections: Designed to handle socket closures (or deliberate pair-switching tear-downs) gracefully by dumping buffers and repopulating a fresh snapshot.

2) Statistical Arbitrage Engine (`public/python/engine.py` & `math.py`)
   - Core mechanism: The algorithm revolves around cointegration between a Target asset and Feature asset, computed in real-time.
   - `BivariateRingBuffer`: A fixed-size NumPy structure avoiding DataFrame slicing overhead. Features single $O(1)$ appends.
   - Rolling moments: Instead of naive `.mean()` or `.cov()` recomputation over a window of length D, the buffer tracks running $Sum_{X}$, $Sum_{Y}$, $Sum_{X^2}$, $Sum_{XY}$. This yields variance, covariance, and rolling Beta in $O(1)$ time per tick.
   - Periodic Drift Correction: Every 1,000 ticks, full array sums are re-run to eliminate accumulated IEEE-754 floating-point errors from continuous add/subtract operations.
   - Signal Generator: Transforms raw prices into a spread utilizing the dynamic Beta coefficient, applying Z-Score normalization for mean-reversion trading limits.

3) Execution & Re-Initialization
   - Dynamic pair instantiation: A `configure_strategy(target, feature)` method securely halts execution, destroys old RingBuffers, and resets the PM (Portfolio Manager) memory, preventing "ghost ticks".
   - The WebWorker bridge deserializes compact `NormalizedTick` payloads and pushes them directly into the Python engine instance.

Serialization
-------------
- The TypeScript to Pyodide/Python bridge uses standard JSON structured clones over WebWorker `postMessage`.
- We exclusively slice and ship the top 20 depth levels across the boundary, guaranteeing serialization overhead is well under 1 millisecond.

Future Optimizations
--------------------
- Switch from array splicing (`Array.splice`) to a Red-Black Tree or Skip List for deeper, high-liquidity order book handling to eliminate $O(N)$ depth insertions.
- Explore zero-copy `SharedArrayBuffer` when the Pyodide bridge API matures to further cut messaging latency.

Reference
---------
- `README.md` for architecture and system flow.
- `lib/market-data/adapters/BinanceAdapter.ts`, `public/python/engine.py` for actual implementation.

