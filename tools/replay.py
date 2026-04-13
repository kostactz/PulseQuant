""" Standalone Backtesting Replay Tool for Phase 4 Stat Arb Trading Engine

Usage:
  python tools/replay.py --input test/resources/captures/mock_dual_asset.jsonl
"""

import argparse
import json
import gzip
import os
import sys
import time
import importlib.util

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
    full_path = os.path.abspath(path)
    if not os.path.exists(full_path):
        print(f"Error: Engine not found at {full_path}")
        sys.exit(1)
        
    spec = importlib.util.spec_from_file_location('engine', full_path)
    if spec is None or spec.loader is None:
        print(f"Error: Could not load engine from {full_path}")
        sys.exit(1)
        
    mod = importlib.util.module_from_spec(spec) # type: ignore
    sys.modules['engine'] = mod
    spec.loader.exec_module(mod) # type: ignore
    return mod

def process_intents(engine, intents, pending_limit_orders, row_ts):
    # Process market orders immediately and queue limit orders
    for intent in intents:
        action = intent.get('action')
        order_id = intent.get('order_id')
        
        if action == 'PLACE_ORDER':
            order_type = intent.get('type')
            qty = float(intent.get('qty', 0))
            price = intent.get('price', 0)
            side = intent.get('side', '').upper()
            symbol = intent.get('symbol', '').upper()
            
            # Send NEW status
            engine.process_events([{'type': 'EXECUTION_REPORT', 'data': {
                'order_id': order_id,
                'status': 'NEW',
                'symbol': symbol,
                'side': side,
                'filled_qty': 0,
                'price': price,
                'transactionTime': row_ts
            }}])
            
            if order_type == 'MARKET':
                # Immediate fill
                engine.process_events([{'type': 'EXECUTION_REPORT', 'data': {
                    'order_id': order_id,
                    'status': 'FILLED',
                    'symbol': symbol,
                    'side': side,
                    'filled_qty': qty,
                    'price': price, 
                    'transactionTime': row_ts
                }}])
            else:
                # LIMIT order, wait some time in ms
                pending_limit_orders.append({
                    'order_id': order_id,
                    'symbol': symbol,
                    'side': side,
                    'qty': qty,
                    'price': price,
                    'wait_ms': 100, # 100ms simulated fill delay
                    'ts': row_ts
                })
                
        elif action == 'CANCEL_ORDER':
            # Remove from pending if exists
            pending_limit_orders[:] = [o for o in pending_limit_orders if o['order_id'] != order_id]
            engine.process_events([{'type': 'EXECUTION_REPORT', 'data': {
                'order_id': order_id,
                'status': 'CANCELED',
                'symbol': intent.get('symbol', ''),
                'filled_qty': 0,
                'price': 0,
                'transactionTime': row_ts
            }}])

def run_capture(engine, rows, chunk_size=1000):
    print("Starting replay...")
    start_time = time.time()
    
    pending_limit_orders = []
    
    def process_tick_batch(batch):
        if not batch:
            return

        result = engine.process_events(batch)
        if result and result.get('intents'):
            last_event = batch[-1]
            row = last_event.get('data', last_event)
            row_ts = row.get('timestamp', int(time.time() * 1000))
            process_intents(engine, result['intents'], pending_limit_orders, row_ts)
            
        # Check pending limit orders
        filled = []
        if pending_limit_orders and batch:
            last_event = batch[-1]
            current_ts = last_event.get('data', last_event).get('timestamp', int(time.time() * 1000))
            for o in pending_limit_orders:
                if current_ts - o['ts'] >= o['wait_ms']:
                    filled.append(o)
                
        for o in filled:
            engine.process_events([{'type': 'EXECUTION_REPORT', 'data': {
                'order_id': o['order_id'],
                'status': 'FILLED',
                'symbol': o['symbol'],
                'side': o['side'],
                'filled_qty': o['qty'],
                'price': o['price'],
                'transactionTime': int(time.time() * 1000)
            }}])
            pending_limit_orders.remove(o)

    total_rows = len(rows)
    for i in range(0, total_rows, chunk_size):
        chunk = rows[i:i+chunk_size]
        process_tick_batch([{'type': 'TICK', 'data': r} for r in chunk])
        
        if (i + chunk_size) % max(1, (total_rows // 10)) < chunk_size:
            progress = min(100, int((i + chunk_size) / total_rows * 100))
            print(f"Progress: {progress}% ({i + chunk_size}/{total_rows})")

    elapsed = time.time() - start_time
    print(f"Replay finished in {elapsed:.2f} seconds ({total_rows / elapsed:.0f} ticks/sec).")
    
    return engine.get_ui_delta()

def print_metrics(snapshot):
    print("\n" + "="*50)
    print("REPLAY RESULTS")
    print("="*50)
    
    print("\n--- Portfolio ---")
    print(f"Final Value (NAV):  ${snapshot['portfolio_value']:.2f}")
    print(f"Cash:               ${snapshot['capital']:.2f}")
    print(f"Positions:          {snapshot['positions']}")
    print(f"Net Delta:          ${snapshot['net_delta']:.2f}")
    
    print("\n--- Trading Analytics ---")
    print(f"Toxicity Flag:      {snapshot['toxicity_flag']}")
    print(f"Execution State:    {snapshot['execution_state']}")
    
    metrics = snapshot['spread_metrics']
    print("\n--- Spread Metrics ---")
    print(f"Z-Score:            {metrics['z_score']:.2f}")
    print(f"Beta:               {metrics['beta']:.4f}")
    print(f"Ready:              {metrics['is_ready']}")
    print("="*50)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Phase 4 Stat Arb Engine Replay")
    parser.add_argument('--input', '-i', required=True, help="Path to the .jsonl or .jsonl.gz capture file")
    parser.add_argument('--engine', '-e', default='public/python/engine.py', help="Path to engine.py")
    parser.add_argument('--target', type=str, default='BTCUSDT', help="Target asset symbol")
    parser.add_argument('--feature', type=str, default='ETHUSDT', help="Feature asset symbol")
    
    args = parser.parse_args()
    
    rows = load_rows(args.input)
    if not rows:
        print("Error: No data loaded.")
        sys.exit(1)
        
    engine_module = import_engine(args.engine)
    engine = engine_module.TradingEngine(target=args.target, feature=args.feature)
    
    final_snapshot = run_capture(engine, rows)
    
    print_metrics(final_snapshot)
