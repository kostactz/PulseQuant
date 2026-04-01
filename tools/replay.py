""" Standalone Backtesting Replay Tool for PulseQuant Engine

This script is a command-line tool to replay market capture data through the
PulseQuant Python engine (`public/python/engine.py`) for backtesting and performance
analysis.

Usage:
  python tools/replay.py --input path/to/capture.jsonl [--engine path/to/engine.py] \
      [--style moderate|conservative|aggressive] [--speed slow|normal|fast] \
      [--bps 100] [--warmup-ticks 500] [--chunk-size 1000] [--report-out report.json]

Example:
  python tools/replay.py -i test/resources/captures/capture_btcusdt_1774646116930.jsonl \
      --style aggressive --speed fast --bps 200 --warmup-ticks 1000 \
      --report-out /tmp/replay_report.json

This is intended to run offline from the repo root and print a final snapshot
summary as well as optionally writing a JSON report.
"""

import argparse
import json
import gzip
import importlib.util
import os
import sys
import time

def load_rows(path):
    print(f"Loading data from {path}...")
    opener = gzip.open if path.endswith('.gz') else open
    rows = []
    with opener(path, 'rt', encoding='utf8') as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    print(f"Loaded {len(rows)} ticks.")
    return rows

def import_engine(path='public/python/engine.py'):
    # Ensure numpy is available
    try:
        import numpy
    except ImportError:
        print("Error: numpy is required. Install via: pip install numpy")
        sys.exit(1)
        
    full_path = os.path.abspath(path)
    if not os.path.exists(full_path):
        print(f"Error: Engine not found at {full_path}")
        sys.exit(1)
        
    spec = importlib.util.spec_from_file_location('engine', full_path)
    mod = importlib.util.module_from_spec(spec)
    # Put module in sys.modules
    sys.modules['engine'] = mod
    spec.loader.exec_module(mod)
    return mod

def run_capture(engine, rows, style, speed, bps, warmup_ticks, chunk_size=1000):
    print(f"Initializing engine (Style: {style}, Speed: {speed}, BPS: {bps})")
    engine.clear_data()
    engine.update_strategy(style, speed)
    engine.set_trade_size(bps)
    
    total_rows = len(rows)
    print(f"Starting replay. Warmup ticks: {warmup_ticks}")
    
    start_time = time.time()
    
    engine.set_auto_trade(False)
    
    for i in range(0, total_rows, chunk_size):
        chunk = rows[i:i+chunk_size]
        
        # Determine if we cross the warmup boundary in this chunk
        if not engine.session.auto_trade:
            # Check if this chunk will surpass warmup
            if i + len(chunk) > warmup_ticks:
                # We need to process up to warmup_ticks with auto_trade=False
                # Then set it to True and process the rest
                split_idx = warmup_ticks - i
                if split_idx > 0:
                    engine.process_events([{'type': 'TICK', 'data': r} for r in chunk[:split_idx]])
                
                print(f"Warmup complete at tick {warmup_ticks}. Enabling auto-trade...")
                engine.set_auto_trade(True)
                
                if split_idx < len(chunk):
                    engine.process_events([{'type': 'TICK', 'data': r} for r in chunk[split_idx:]])
            else:
                engine.process_events([{'type': 'TICK', 'data': r} for r in chunk])
        else:
            engine.process_events([{'type': 'TICK', 'data': r} for r in chunk])
            
        # Progress indication
        if (i + chunk_size) % max(1, (total_rows // 10)) < chunk_size:
            progress = min(100, int((i + chunk_size) / total_rows * 100))
            print(f"Progress: {progress}% ({i + chunk_size}/{total_rows})")

    elapsed = time.time() - start_time
    print(f"Replay finished in {elapsed:.2f} seconds ({total_rows / elapsed:.0f} ticks/sec).")
    
    return engine.process_events([])  # Get final snapshot

def print_metrics(snapshot):
    print("\n" + "="*50)
    print("REPLAY RESULTS")
    print("="*50)
    
    print("\n--- Portfolio ---")
    print(f"Final Value:    ${snapshot['portfolio_value']:.2f}")
    print(f"Capital:        ${snapshot['capital']:.2f}")
    print(f"Position:       {snapshot['position']:.4f}")
    print(f"Max Drawdown:   -{snapshot['max_dd_pct']*100:.2f}% (Duration: {snapshot['max_dd_duration']/1000:.1f}s)")
    
    analytics = snapshot['analytics']
    print("\n--- Trading Analytics ---")
    print(f"Total Trades:   {analytics['total_trades']}")
    print(f"Hit Ratio:      {analytics['hit_ratio']*100:.2f}%")
    print(f"Profit Factor:  {analytics['profit_factor']:.2f}")
    print(f"Win/Loss Ratio: {analytics['win_loss_ratio']:.2f}")
    print(f"Avg Hold Time:  {analytics['avg_holding_time']/1000:.2f}s")
    print(f"Maker Fill Rate:{analytics['maker_fill_rate']*100:.2f}%")
    
    print("\n--- Microstructure ---")
    print(f"Pending Makers: {snapshot['pending_order_count']}")
    print(f"Canceled Fills: {snapshot['canceled_orders_total']}")
    print(f"Cancel Rate:    {snapshot['cancellation_rate']*100:.2f}%")
    print("="*50)

def save_report(snapshot, path):
    print(f"\nSaving detailed report to {path}")
    
    # We strip out large time series for the report to keep it manageable
    report = {
        'portfolio': {
            'value': snapshot['portfolio_value'],
            'capital': snapshot['capital'],
            'position': snapshot['position'],
            'max_dd_pct': snapshot['max_dd_pct'],
            'max_dd_duration': snapshot['max_dd_duration']
        },
        'analytics': snapshot['analytics'],
        'microstructure': {
            'pending_orders': snapshot['pending_order_count'],
            'canceled_orders': snapshot['canceled_orders_total'],
            'cancellation_rate': snapshot['cancellation_rate']
        },
        'trades': snapshot['recent_trades_full'],
        'cancellations': snapshot['recent_cancellations']
    }
    
    with open(path, 'w') as f:
        json.dump(report, f, indent=2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="PulseQuant Headless Engine Replay")
    parser.add_argument('--input', '-i', required=True, help="Path to the .jsonl or .jsonl.gz capture file")
    parser.add_argument('--engine', '-e', default='public/python/engine.py', help="Path to engine.py")
    parser.add_argument('--style', default='moderate', choices=['conservative', 'moderate', 'aggressive'], help="Trading style")
    parser.add_argument('--speed', default='normal', choices=['slow', 'normal', 'fast'], help="Signal speed")
    parser.add_argument('--bps', type=int, default=100, help="Trade size in basis points (bps)")
    parser.add_argument('--warmup-ticks', type=int, default=500, help="Number of ticks to process before enabling auto-trade")
    parser.add_argument('--chunk-size', type=int, default=1000, help="Number of ticks to process per engine call")
    parser.add_argument('--report-out', '-o', help="Path to save detailed JSON report")
    
    args = parser.parse_args()
    
    rows = load_rows(args.input)
    if not rows:
        print("Error: No data loaded.")
        sys.exit(1)
        
    engine = import_engine(args.engine)
    
    final_snapshot = run_capture(
        engine, 
        rows, 
        style=args.style, 
        speed=args.speed, 
        bps=args.bps, 
        warmup_ticks=args.warmup_ticks,
        chunk_size=args.chunk_size
    )
    
    print_metrics(final_snapshot)
    
    if args.report_out:
        save_report(final_snapshot, args.report_out)
