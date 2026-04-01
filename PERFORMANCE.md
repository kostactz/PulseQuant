PulseQuant - Performance & Algorithmic Design
==========================================

This document describes the system’s live performance assumptions and basic algorithm design. 

High-level goals
-----------------
- Per-tick work is bounded and predictable; prefer O(1) per tick and O(log N) for book updates.
- Keep hot paths in native typed buffers and parameters so JS/Pyodide crossing is minimal.
- Maintain working state (best bid/ask + top-K order book) instead of full historical recomputation.
- Keep network and execution paths resilient to websocket disconnects and order-frequency limits.

Critical components and current complexity
-----------------------------------------

1) BinanceAdapter order book (lib/market-data/adapters/BinanceAdapter.ts)
   - Data structures: two sorted arrays, `obBids` (descending) and `obAsks` (ascending).
   - Snapshot handling: full depth fetch (`limit=1000`) on connect, then buffered updates are applied in sequence.
   - Live updates: binary search index (O(log N)), then splice insert/update/delete (O(N) worst-case). Top-level updates dominate; we keep book depth reasonable with 1000 entries.
   - Top of book: uses `@bookTicker` for best bid/ask to avoid level-1 drift; `@depth@100ms` for full depth maintenance.
   - Time-coherent delta OFI: store `prevBids` / `prevAsks` for top 5 levels and compute weighted level deltas every `emitTick`.
   - Depth rollup: group by price grain (`GROUP_SIZE=10`) over 20 levels in `groupLevels`; linear in `LIMIT`.

2) Latency controls and reliability
   - reconnect logic with back-off (`setTimeout` 3 sec), reset snapshot state, and replay buffered depth messages.
   - listenkey keepalive for user-order stream; robust auth-fatal detection (`-2015`, invalid key) to avoid tight reconnect loops.
   - OrderManager throttles trading API with token bucket, 50ms loop, cancel-first priority, and exponential retry backoff up to 3 attempts.

3) Indicator engine with ring buffers (public/python/engine.py)
   - `RingBuffer` uses fixed-size NumPy arrays for O(1) append and running sum/sum-sq maintenance.
   - periodic drift correction every 1000 appends prevents floating-point error blow-up.
   - `IndicatorState.update()` is mostly O(1) per tick, plus O(D) for deep-liquidity loops (`dobi_levels=18`).
   - time-based state update at `update_interval_ms = 25` ms, decoupling tick burst from indicator cadence.

4) Feature set in indicator pipeline (live behavior)
   - Micro-price = volume-weighted top-of-book mid with fallback to top-level volume.
   - VWAP with true volume accumulation + slow exponential fallback when trade volume is zero.
   - OFI by delta_bid/delta_ask, normalized by rolling stdev (burn-in of half-window), clipped to [-8.7,8.7], with long EMA smoothing.
   - Dynamic regime thresholds by abs(OFI EMA) ring buffer (p50/p80/p95 via mean+std mapping).
   - OBI and deep OBI: weighted 18-level imbalance, z-score normalized, clipped ±10, and EMA smoothing.
   - VPIN-style sweep detection from top-3 resting volume and trade flow.

5) Strategy & risk controls in the same pipeline
   - toxicity gate uses OFI EMA + OBI (raw and EMA) with resting multipliers.
   - configurable speed/style multipliers adjust all window sizes up to 2000 levels with a single parameter.
   - explicit cancel thresholds prevent execution in high-microstructure toxicity.

Message passing and serialization
---------------------------------
- JS side ships normalized `NormalizedTick` with typed numbers and pre-sliced top-20 depth arrays.
- Python received arrays are consumed without nested one-off dict reconstructions for most per-tick indicators.
- Export path supports incremental UI payloads; no full high-frequency history rebuild in engine.

Notes and TODOs
---------------
- `Array.splice` used in order book remains O(N); a tree/skiplist may be needed.
- Pyodide bridge uses normal JSON/structured clone for high-level objects; future work can add zero-copy shared memory.

Reference
---------
- `README.md` for architecture and system flow.
- `lib/market-data/adapters/BinanceAdapter.ts`, `public/python/engine.py` for actual implementation.

