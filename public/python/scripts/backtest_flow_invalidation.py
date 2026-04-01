"""Simple synthetic backtest to compare legacy vs patched risk logic.

Creates an initial taker long entry and then tests two exit triggers:
 - small price reversion (e.g., 10bps) which should close under legacy 5bps min stop
   but not under patched 15bps min stop
 - flow invalidation (OFI negative + OBI negative) which should close only when
   flow invalidation is enabled

This is a deterministic, minimal harness intended to demonstrate behavior differences.
"""
import time
import os
import sys

# Ensure the parent directory containing `engine.py` is on sys.path
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.abspath(os.path.join(THIS_DIR, '..'))
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

import engine


def timestamp_ms():
    return int(time.time() * 1000)


def run_case(name, stop_min, enable_flow, micro_drop_bps=0.001, flow_ofi=-0.6, flow_obi=-0.6):
    print(f"\n=== Case: {name} (stop_min={stop_min}, enable_flow={enable_flow}) ===")
    engine.clear_data()
    # Ensure strategy cooldown is reset between independent cases
    engine.session.strategy.cooldown_end_time = 0

    # Configure strategy
    s = engine.session.strategy
    s.stop_min = stop_min
    s.enable_flow_invalidation = enable_flow
    s.flow_ofi_threshold = 0.5
    s.flow_obi_threshold = 0.5

    ts = timestamp_ms()
    entry_price = 100.0
    qty = 1.0

    # Force a taker long entry (simulate getting filled)
    engine.session.portfolio.execute_trade('buy', qty, entry_price, ts, order_type='taker', indicators={})
    print(f"Opened long @ {entry_price} qty={qty}")

    # 1) Price reversion test
    ts += 100
    drop_price = entry_price * (1 - micro_drop_bps)
    ind_price_revert = {
        'micro_price': drop_price,
        'bb_std': 0.0,
        'ofi_ema': 0.0,
        'obi_norm': 0.0,
        'vwap': entry_price,
        'macro_sma': entry_price,
        'prev_macro_sma': entry_price
    }

    sig, bps, otype, tox = s.generate_signal(ind_price_revert, engine.session.portfolio, ts)
    closed_on_price = False
    if sig == -1:
        # close: execute market sell to exit
        engine.session.portfolio.execute_trade('sell', abs(engine.session.portfolio.position), drop_price, ts, order_type='taker', indicators=ind_price_revert)
        closed_on_price = True

    print(f"Price revert -> micro_price={drop_price:.6f}: signal={sig}, closed_on_price={closed_on_price}, close_reason={tox.get('close_reason')}")

    # Re-open for flow invalidation test
    ts += 100
    engine.session.portfolio.execute_trade('buy', qty, entry_price, ts, order_type='taker', indicators={})
    print(f"Reopened long @ {entry_price} qty={qty}")

    # 2) Flow invalidation test (OFI negative + OBI negative)
    ts += 100
    ind_flow = {
        'micro_price': entry_price,
        'bb_std': 0.0,
        'ofi_ema': flow_ofi,
        'obi_norm': flow_obi,
        'vwap': entry_price,
        'macro_sma': entry_price,
        'prev_macro_sma': entry_price
    }

    sig2, bps2, otype2, tox2 = s.generate_signal(ind_flow, engine.session.portfolio, ts)
    closed_on_flow = False
    if sig2 == -1:
        engine.session.portfolio.execute_trade('sell', abs(engine.session.portfolio.position), entry_price, ts, order_type='taker', indicators=ind_flow)
        closed_on_flow = True

    print(f"Flow revert -> ofi_ema={flow_ofi}, obi_norm={flow_obi}: signal={sig2}, closed_on_flow={closed_on_flow}, close_reason={tox2.get('close_reason')}")

    # Summarize portfolio closed trades and durations
    closed = engine.session.portfolio.closed_trades
    print(f"Closed trades count: {len(closed)}")
    for i, t in enumerate(closed):
        print(f"  {i}: entry={t['entry_price']} exit={t['exit_price']} qty={t['qty']} pnl={t['pnl']:.6f} duration_ms={t['duration']}")

    return {
        'name': name,
        'closed_trades': closed,
        'last_toxicity': engine.session.last_toxicity_state.copy()
    }


if __name__ == '__main__':
    # Run legacy (5 bps stop, no flow invalidation)
    legacy = run_case('legacy', stop_min=0.0005, enable_flow=False, micro_drop_bps=0.001)

    # Run patched (15 bps min stop + flow invalidation enabled)
    patched = run_case('patched', stop_min=0.0015, enable_flow=True, micro_drop_bps=0.001)

    print('\nDone.')
