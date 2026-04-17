import re

with open('tools/replay.py', 'r') as f:
    content = f.read()

# Add _dispatch helper
helper = """
def _dispatch_to_engine(engine, events, verbose=False, ts=None):
    result = engine.process_events(events)
    if result and result.get('logs') and verbose:
        for log in result['logs']:
            t_str = f"[{ts}] " if ts else ""
            print(f"{t_str}{log.get('level', 'INFO')}: {log.get('message')}")
    return result

"""
content = content.replace("def _make_fill_report", helper + "def _make_fill_report")

# Patch process_intents
content = content.replace(
    "def process_intents(engine, intents, pending_limit_orders, row_ts,\n                    last_tick, slippage_bps):",
    "def process_intents(engine, intents, pending_limit_orders, row_ts,\n                    last_tick, slippage_bps, verbose=False):"
)

content = content.replace(
    "engine.process_events([{'type': 'EXECUTION_REPORT', 'data': {",
    "_dispatch_to_engine(engine, [{'type': 'EXECUTION_REPORT', 'data': {",
)
content = content.replace(
    "}}])",
    "}}], verbose=verbose, ts=row_ts)"
)
content = content.replace(
    "engine.process_events([{'type': 'EXECUTION_REPORT', 'data':\n                    _make_fill_report",
    "_dispatch_to_engine(engine, [{'type': 'EXECUTION_REPORT', 'data':\n                    _make_fill_report",
)
content = content.replace(
    "position_id)}])",
    "position_id)}], verbose=verbose, ts=row_ts)"
)

# Patch _check_limit_fills
content = content.replace(
    "def _check_limit_fills(engine, pending_limit_orders, tick_data, tick_ts, last_tick, slippage_bps):",
    "def _check_limit_fills(engine, pending_limit_orders, tick_data, tick_ts, last_tick, slippage_bps, verbose=False):"
)
content = content.replace(
    "result = engine.process_events([{'type': 'EXECUTION_REPORT', 'data':",
    "result = _dispatch_to_engine(engine, [{'type': 'EXECUTION_REPORT', 'data':"
)
content = content.replace(
    "o.get('position_id'))}])",
    "o.get('position_id'))}], verbose=verbose, ts=tick_ts)"
)
content = content.replace(
    "process_intents(engine, result['intents'], pending_limit_orders, tick_ts, last_tick, slippage_bps)",
    "process_intents(engine, result['intents'], pending_limit_orders, tick_ts, last_tick, slippage_bps, verbose=verbose)"
)

# Patch run_capture
content = content.replace(
    "def run_capture(engine, rows, slippage_bps=10, chunk_size=500):",
    "def run_capture(engine, rows, slippage_bps=10, chunk_size=500, verbose=False):"
)
content = content.replace(
    "result = engine.process_events([row])",
    "result = _dispatch_to_engine(engine, [row], verbose=verbose, ts=row.get('data', row).get('timestamp'))"
)
content = content.replace(
    "process_intents(engine, result['intents'], pending_limit_orders,\n                                tick_ts, last_tick, slippage_bps)",
    "process_intents(engine, result['intents'], pending_limit_orders,\n                                tick_ts, last_tick, slippage_bps, verbose=verbose)"
)
content = content.replace(
    "_check_limit_fills(engine, pending_limit_orders, data, tick_ts, last_tick, slippage_bps)",
    "_check_limit_fills(engine, pending_limit_orders, data, tick_ts, last_tick, slippage_bps, verbose=verbose)"
)
content = content.replace(
    "engine.process_events([row])",
    "_dispatch_to_engine(engine, [row], verbose=verbose)"
)

# Patch __main__
content = content.replace(
    "final_snapshot, nav_hist = run_capture(engine, rows, slippage_bps=args.slippage_bps)",
    "final_snapshot, nav_hist = run_capture(engine, rows, slippage_bps=args.slippage_bps, verbose=args.verbose)"
)

with open('tools/replay.py', 'w') as f:
    f.write(content)
