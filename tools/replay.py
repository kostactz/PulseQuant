""" Standalone Backtesting Replay Tool for Phase 4 Stat Arb Trading Engine

Usage:
  python tools/replay.py --input test/resources/captures/mock_dual_asset.jsonl
  python tools/replay.py --input captures/ORDIUSDC_SUIUSDC_vision_2024-01-01_2024-01-01.jsonl \\
      --target ORDIUSDC --feature SUIUSDC --slippage-bps 10

Slippage model (conservative heuristic — REALISTIC_ENGINE.md §Phase 1):
  - MARKET orders: executed at mid ± slippage_bps (taker, is_maker=False).
  - LIMIT  orders: queued; filled only when a later tick *trades through* the
    limit price (ask < buy_limit OR bid > sell_limit, strict inequality).
    Filled at the limit price (maker, is_maker=True).

All EXECUTION_REPORTs include both transaction_time (ms) and transactionTime (ms)
so the engine can accept either field name.

Funding-rate events in the JSONL are forwarded directly to the engine so that
PortfolioManager._on_funding_rate_update can deduct/add funding payments.
"""

import argparse
import json
import gzip
import os
import sys
import time
import math
import importlib.util


def load_rows(path):
    print(f"Loading data from {path}...")
    opener = gzip.open if path.endswith('.gz') else open
    rows = []
    with opener(path, 'rt', encoding='utf8') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    print(f"Loaded {len(rows)} events.")
    return rows


def import_engine(path='public/python/engine.py'):
    full_path = os.path.abspath(path)
    if not os.path.exists(full_path):
        print(f"Error: Engine not found at {full_path}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location('engine', full_path)
    if spec is None or spec.loader is None:
        print(f"Error: Could not load engine from {full_path}")
        sys.exit(1)

    mod = importlib.util.module_from_spec(spec)  # type: ignore
    sys.modules['engine'] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _make_fill_report(order_id, symbol, side, qty, price, is_maker, ts):
    """Build an EXECUTION_REPORT data dict.  Both timestamp aliases are present."""
    return {
        'order_id': order_id,
        'status': 'FILLED',
        'symbol': symbol,
        'side': side,
        'filled_qty': qty,
        'price': price,
        'is_maker': is_maker,
        'transaction_time': ts,
        'transactionTime': ts,
    }


def process_intents(engine, intents, pending_limit_orders, row_ts,
                    last_tick, slippage_bps):
    """Process outbound intents from the engine.

    - MARKET orders → immediate fill with slippage applied to mid.
    - LIMIT  orders → queued for trade-through detection on later ticks.
    - CANCEL  orders → remove from pending queue + send CANCELED report.
    """
    for intent in intents:
        action = intent.get('action')
        order_id = intent.get('order_id')

        if action == 'PLACE_ORDER':
            order_type = intent.get('type', 'LIMIT').upper()
            qty = float(intent.get('qty', 0))
            price = float(intent.get('price', 0))
            side = intent.get('side', '').upper()
            symbol = intent.get('symbol', '').upper()

            # Acknowledge order creation
            engine.process_events([{'type': 'EXECUTION_REPORT', 'data': {
                'order_id': order_id,
                'status': 'NEW',
                'symbol': symbol,
                'side': side,
                'filled_qty': 0,
                'price': price,
                'transaction_time': row_ts,
                'transactionTime': row_ts,
            }}])

            if order_type == 'MARKET':
                # Compute mid from the most recent tick for this symbol (or
                # the global last tick if no symbol-specific data is available).
                tick_data = last_tick.get(symbol) or last_tick.get('__any__')
                if tick_data:
                    mid = (float(tick_data['bid']) + float(tick_data['ask'])) / 2.0
                else:
                    # Fall back to the intent price if we have no tick context
                    mid = price if price > 0 else 0.0

                slip = slippage_bps / 10000.0
                if side == 'BUY':
                    exec_price = round(mid * (1.0 + slip), 8)
                else:
                    exec_price = round(mid * (1.0 - slip), 8)

                engine.process_events([{'type': 'EXECUTION_REPORT', 'data':
                    _make_fill_report(order_id, symbol, side, qty,
                                      exec_price, False, row_ts)}])

            else:  # LIMIT order → queue for trade-through
                pending_limit_orders.append({
                    'order_id': order_id,
                    'symbol': symbol,
                    'side': side,
                    'qty': qty,
                    'price': price,
                    'ts': row_ts,
                })

        elif action == 'CANCEL_ORDER':
            # Remove from pending queue (determinate, no partial cancels)
            pending_limit_orders[:] = [
                o for o in pending_limit_orders if o['order_id'] != order_id
            ]
            engine.process_events([{'type': 'EXECUTION_REPORT', 'data': {
                'order_id': order_id,
                'status': 'CANCELED',
                'symbol': intent.get('symbol', ''),
                'side': intent.get('side', ''),
                'filled_qty': 0,
                'price': 0,
                'transaction_time': row_ts,
                'transactionTime': row_ts,
            }}])


def _check_limit_fills(engine, pending_limit_orders, tick_data, tick_ts):
    """Check all pending limit orders against the latest tick for trade-through.

    Trade-through rules (conservative, no look-ahead, full-fill only):
      BUY  limit fills when best_ask_price STRICTLY < limit_price
      SELL limit fills when best_bid_price STRICTLY > limit_price
    Fills use the limit price (maker fill) and is_maker=True.
    """
    if not tick_data:
        return

    best_bid = float(tick_data.get('bid', 0.0))
    best_ask = float(tick_data.get('ask', float('inf')))
    symbol = tick_data.get('symbol', '').upper()

    filled = []
    for o in pending_limit_orders:
        if o['symbol'] != symbol:
            continue
        if o['side'] == 'BUY' and best_ask < o['price']:
            filled.append(o)
        elif o['side'] == 'SELL' and best_bid > o['price']:
            filled.append(o)

    for o in filled:
        engine.process_events([{'type': 'EXECUTION_REPORT', 'data':
            _make_fill_report(o['order_id'], o['symbol'], o['side'],
                              o['qty'], o['price'], True, tick_ts)}])
        pending_limit_orders.remove(o)


def run_capture(engine, rows, slippage_bps=10, chunk_size=500):
    print(f"Starting replay (slippage={slippage_bps} bps)...")
    start_time = time.time()

    pending_limit_orders = []
    # last_tick[symbol] = most recent tick data dict for that symbol
    last_tick: dict = {}

    total_rows = len(rows)
    
    nav_history = []
    first_ts = None
    last_sample_ts = 0
    sample_interval_ms = 3600 * 1000  # 1 hour

    for i, row in enumerate(rows):
        ev_type = row.get('type')
        data = row.get('data', row)

        if ev_type == 'TICK':
            symbol = data.get('symbol', '').upper()
            tick_ts = data.get('timestamp', int(time.time() * 1000))

            # Update zero-order hold for this symbol
            last_tick[symbol] = data
            last_tick['__any__'] = data  # fallback for symbol-agnostic lookups
            
            if first_ts is None:
                first_ts = tick_ts
                nav_history.append(engine.get_ui_delta()['portfolio_value'])
                last_sample_ts = tick_ts
            elif tick_ts - last_sample_ts >= sample_interval_ms:
                nav_history.append(engine.get_ui_delta()['portfolio_value'])
                last_sample_ts = tick_ts

            # Feed tick to engine, collect any new intents
            result = engine.process_events([row])
            if result and result.get('intents'):
                process_intents(engine, result['intents'], pending_limit_orders,
                                tick_ts, last_tick, slippage_bps)

            # Check limit order trade-through on every new tick
            _check_limit_fills(engine, pending_limit_orders, data, tick_ts)

        elif ev_type == 'FUNDING_RATE_UPDATE':
            # Route funding events directly — engine handles accounting
            engine.process_events([row])

        else:
            # Forward any other event type (REGIME_DATA etc.) as-is
            engine.process_events([row])

        # Progress reporting
        if total_rows > 0 and (i + 1) % max(1, total_rows // 10) == 0:
            progress = int((i + 1) / total_rows * 100)
            print(f"Progress: {progress}% ({i + 1}/{total_rows})")

    elapsed = time.time() - start_time
    tps = total_rows / elapsed if elapsed > 0 else 0
    print(f"Replay finished in {elapsed:.2f}s ({tps:.0f} events/sec).")

    return engine.get_ui_delta(), nav_history


def print_metrics(snapshot, nav_history=None, verbose=False):
    print("\n" + "="*55)
    print("REPLAY RESULTS")
    print("="*55)

    print("\n--- Portfolio ---")
    print(f"Final NAV:           ${snapshot['portfolio_value']:.4f}")
    print(f"Cash:                ${snapshot['capital']:.4f}")
    print(f"Realized PnL:        ${snapshot.get('realized_pnl', 0.0):.4f}")
    print(f"Unrealized PnL:      ${snapshot.get('unrealized_pnl', 0.0):.4f}")
    print(f"Total Fees Paid:     ${snapshot.get('total_fees_paid', 0.0):.4f}")
    print(f"Total Funding Paid:  ${snapshot.get('total_funding_paid', 0.0):.6f}")
    print(f"Positions:           {snapshot['positions']}")
    print(f"Net Delta:           ${snapshot['net_delta']:.4f}")

    print("\n--- Strategy ---")
    print(f"Toxicity Flag:       {snapshot['toxicity_flag']}")
    print(f"Execution State:     {snapshot['execution_state']}")
    print(f"Dynamic Hurdle:      {snapshot.get('dynamic_hurdle_bps', 'n/a')} bps")

    metrics = snapshot.get('spread_metrics', {})
    print("\n--- Spread Metrics ---")
    print(f"Z-Score:             {metrics.get('z_score', 0.0):.4f}")
    print(f"Beta:                {metrics.get('beta', 0.0):.6f}")
    print(f"Ready:               {metrics.get('is_ready', False)}")
    
    trades_volume = snapshot.get('trades_volume', 0)
    timed_out = snapshot.get('maker_timeouts', 0)
    total_maker_orders = snapshot.get('total_maker_orders', 0)
    hit_ratio = 1.0 - (timed_out / total_maker_orders) if total_maker_orders > 0 else 0.0
    
    win_trades = snapshot.get('win_trades', 0)
    loss_trades = snapshot.get('loss_trades', 0)
    wl_ratio = (win_trades / loss_trades) if loss_trades > 0 else (float('inf') if win_trades > 0 else 0.0)

    sharpe = 0.0
    if nav_history and len(nav_history) > 1:
        returns = [(nav_history[i] - nav_history[i-1]) / nav_history[i-1] for i in range(1, len(nav_history))]
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = math.sqrt(variance) if variance > 0 else 1e-8
        # Annualized Sharpe assuming hourly sampling
        sharpe = (mean_r / std_r) * math.sqrt(24 * 365)
        
    print("\n--- Trading Details ---")
    print(f"Trades Volume:       {trades_volume} completed legs")
    print(f"Timed-out Volume:    {timed_out} maker timeouts")
    print(f"Hit Ratio:           {hit_ratio:.2%}")
    print(f"Win/Loss Ratio:      {wl_ratio:.2f} ({win_trades} W / {loss_trades} L)")
    print(f"Annualized Sharpe:   {sharpe:.2f}")
    
    if verbose:
        all_trades = snapshot.get('all_historical_trades', [])
        print("\n--- Verbose Trade History ---")
        if not all_trades:
            print("No trades executed.")
        else:
            print(f"{'Time':<15} | {'Symbol':<10} | {'Side':<5} | {'Qty':<6} | {'Price':<10} | {'Fee':<8} | {'Maker':<5} | {'PnL'}")
            print("-" * 82)
            import datetime
            for t in all_trades:
                ts_str = datetime.datetime.fromtimestamp(t['timestamp']/1000).strftime('%m-%d %H:%M:%S')
                print(f"{ts_str:<15} | {t['symbol']:<10} | {t['side']:<5} | {t['qty']:<6} | {t['price']:<10.4f} | {t['fee']:<8.4f} | {str(t['is_maker']):<5} | {t['realized_pnl']:<8.4f}")
    
    print("="*55)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Phase 4 Stat Arb Engine Replay — conservative slippage model",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--input', '-i', required=True,
                        help="Path to the .jsonl or .jsonl.gz capture file")
    parser.add_argument('--engine', '-e', default='public/python/engine.py',
                        help="Path to engine.py")
    parser.add_argument('--target', type=str, default='BTCUSDT',
                        help="Target asset symbol")
    parser.add_argument('--feature', type=str, default='ETHUSDT',
                        help="Feature asset symbol")
    parser.add_argument('--slippage-bps', type=float, default=10.0,
                        help="Market-order slippage in basis points (default 10 bps = 0.10%%)")
    parser.add_argument('--sigma-threshold', type=float, default=2.0,
                        help="Z-score threshold for entry")
    parser.add_argument('--min-entry-spread', type=float, default=0.0,
                        help="Minimum spread in bps to enter a trade")
    parser.add_argument('--verbose', action='store_true',
                        help="Print verbose trade history")

    args = parser.parse_args()

    rows = load_rows(args.input)
    if not rows:
        print("Error: No data loaded.")
        sys.exit(1)

    engine_module = import_engine(args.engine)
    engine = engine_module.TradingEngine(
        target=args.target.upper(),
        feature=args.feature.upper(),
    )

    # Apply user-specified strategy parameters
    engine.process_events([{
        'type': 'UPDATE_STRATEGY_PARAMS',
        'data': {
            'sigma_threshold': args.sigma_threshold,
            'min_entry_spread_bps': args.min_entry_spread
        }
    }])

    final_snapshot, nav_hist = run_capture(engine, rows, slippage_bps=args.slippage_bps)
    print_metrics(final_snapshot, nav_history=nav_hist, verbose=args.verbose)
