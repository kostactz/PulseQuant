""" Standalone Random Hyperparameter Search Tool for PulseQuant Engine.

This file is a standalone optimization script used to run randomized parameter search
against captured market data (JSONL format). It is not part of the production web
app; instead, it is a research utility that lets you find strong parameter sets
for the strategy engine.

Usage:
    python tools/optimize_random.py --input <capture.jsonl> [--trials 1000] [--workers 7] \
        [--output results.json] [--seed 42]

Arguments:
    --input     Path to a captured data file (JSON lines, each line is one event).
    --trials    Number of random trials to evaluate (default 100).
    --workers   Number of process workers to use (default cpu_count - 1).
    --output    Output JSON file path (default optimization_results.json).
    --seed      Random seed for reproducibility (default 42).

The tool loads events in each worker via initializer `init_worker`, then evaluates
each random parameter vector in `evaluate_params`, computes fitness, and writes
best results to the output file.
"""

import os
import sys
import json
import random
import time
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed

# Add the public/python directory to sys.path to import the engine
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../public/python')))
import engine

# Global dataset variable per worker
GLOBAL_DATA = []

def load_data(filepath):
    print(f"Loading data from {filepath}...")
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            if not line.strip(): continue
            try:
                data.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    print(f"Loaded {len(data)} events/rows.")
    return data

def init_worker(filepath):
    """
    Initializer for multiprocessing workers.
    Loads the dataset into the worker's memory once, avoiding IPC serialization costs.
    """
    global GLOBAL_DATA
    GLOBAL_DATA = load_data(filepath)

def generate_random_params():
    """Samples a random set of parameters from our defined search space."""
    return {
        # Base Engine Configuration (Static Best)
        'speed': 'fast', 
        'style': 'moderate', 
        
        # Risk & Stops (Static Best)
        'stop_min': 0.000696, 
        'stop_cap': 0.472905, 
        
        # Toxicity Control (Static Best)
        'flow_ofi_threshold': 3.499, 
        'obi_toxicity_threshold': 1.7118, 
        'toxicity_resting_multiplier': 0.9619, 
        'min_rest_ms': 450, 
        
        # Order Management & Indicators (Static Best)
        'inventory_skew_factor': 2.5, 
        'dobi_lambda': 0.02, 
        
        # --- 20 NEW OPTIMIZED PARAMETERS (TIGHTENED) ---
        # 1-4. Advanced Flow & Position Management
        'enable_flow_invalidation': True,
        'flow_obi_threshold': random.uniform(1.15, 1.45),  # around 1.299
        'max_inventory': random.uniform(9.0, 11.5),       # around 10.167
        'toxicity_resting_obi_multiplier': random.uniform(0.95, 1.3),
        
        # 5-6. Core Indicator State Setup
        'dobi_levels': random.randint(14, 20),
        'update_interval_ms': random.randint(25, 50),
        
        # 7-8. VPIN Sweep Parameters
        'vpin_alpha': random.uniform(0.35, 0.55),
        'vpin_sweep_threshold': random.uniform(0.15, 0.35),
        
        # 9-11. Statistical Indicator Bounds
        'alpha_vwap_decay': random.uniform(0.0003, 0.0012),
        'bb_std_multiplier': random.uniform(3.0, 4.5),
        'ofi_clip_bound': random.uniform(6.5, 10.5),
        
        # 12-15. Asymmetric Toxicity Shifting Dynamics
        'buy_deriv_shift_cap': random.uniform(0.2, 0.45),
        'sell_deriv_shift_cap': random.uniform(0.25, 0.5),
        'buy_deriv_pressure_multiplier': random.uniform(0.15, 0.4),
        'sell_deriv_pressure_multiplier': random.uniform(1.0, 1.6),
        
        # 16. Buffer Timings
        'whipsaw_time_buffer_ms': random.uniform(3500.0, 9000.0),
        
        # 17-20. Session Settings & Order Execution Types
        'tick_size': random.uniform(0.05, 0.12),
        'trade_size_bps': random.randint(150, 220),
        'post_only_mode': True,
        'chaser_distance_multiplier': random.uniform(0.8, 1.4)
    }

def evaluate_params(params, trial_id):
    """
    Main evaluation function for a single trial.
    Runs the deterministic engine with a given set of params.
    """
    try:
        # Reset the engine state
        engine.clear_data()
        
        # 1. Update Base Mechanics (Speed scales all indicator ring buffers)
        engine.update_strategy(params['style'], params['speed'])
        
        # 2. Inject Static Strategy Parameters
        engine.session.strategy.stop_min = params['stop_min']
        engine.session.strategy.stop_cap = params['stop_cap']
        engine.session.strategy.flow_ofi_threshold = params['flow_ofi_threshold']
        engine.session.strategy.obi_toxicity_threshold = params['obi_toxicity_threshold']
        engine.session.strategy.toxicity_resting_multiplier = params['toxicity_resting_multiplier']
        engine.session.strategy.min_rest_ms = params['min_rest_ms']
        engine.session.strategy.inventory_skew_factor = params['inventory_skew_factor']
        
        # 3. Inject New Strategy Parameters
        engine.session.strategy.enable_flow_invalidation = params['enable_flow_invalidation']
        engine.session.strategy.flow_obi_threshold = params['flow_obi_threshold']
        engine.session.strategy.max_inventory = params['max_inventory']
        engine.session.strategy.toxicity_resting_obi_multiplier = params['toxicity_resting_obi_multiplier']
        
        engine.session.strategy.buy_deriv_shift_cap = params['buy_deriv_shift_cap']
        engine.session.strategy.sell_deriv_shift_cap = params['sell_deriv_shift_cap']
        engine.session.strategy.buy_deriv_pressure_multiplier = params['buy_deriv_pressure_multiplier']
        engine.session.strategy.sell_deriv_pressure_multiplier = params['sell_deriv_pressure_multiplier']
        engine.session.strategy.whipsaw_time_buffer_ms = params['whipsaw_time_buffer_ms']

        # 4. Inject Indicator Parameters
        engine.session.indicators.dobi_lambda = params['dobi_lambda']
        engine.session.indicators.dobi_levels = params['dobi_levels']
        engine.session.indicators.update_interval_ms = params['update_interval_ms']
        engine.session.indicators.vpin_alpha = params['vpin_alpha']
        engine.session.indicators.vpin_sweep_threshold = params['vpin_sweep_threshold']
        engine.session.indicators.alpha_vwap_decay = params['alpha_vwap_decay']
        engine.session.indicators.bb_std_multiplier = params['bb_std_multiplier']
        engine.session.indicators.ofi_clip_bound = params['ofi_clip_bound']
        
        # 5. Inject Session Constraints
        engine.session.tick_size = params['tick_size']
        engine.session.post_only_mode = params['post_only_mode']
        engine.session.min_chaser_distance = params['tick_size'] * params['chaser_distance_multiplier']
        
        # Enable auto-trading
        engine.set_auto_trade(True)
        engine.set_trade_size(params['trade_size_bps'])
        
        # Process data in chunks to simulate tick flow
        chunk_size = 2000
        for i in range(0, len(GLOBAL_DATA), chunk_size):
            engine.process_events([{'type': 'TICK', 'data': r} for r in GLOBAL_DATA[i:i+chunk_size]])
            
        # Flush the last tick and extract metrics
        stats = engine.process_events([])
        
        ending_val = stats['portfolio_value']
        start_val = engine.session.portfolio.initial_capital
        net_profit = ending_val - start_val
        
        total_trades = stats['analytics']['total_trades']
        win_rate = stats['analytics']['hit_ratio']
        max_dd = stats['max_dd_pct']
        
        # Fitness Score Formulation:
        # We want high returns, but penalize extreme drawdowns and lack of statistical significance (low trades)
        if total_trades < 10:
            fitness = -9999.0 # Disqualify parameters that don't trade enough
        else:
            # A simple utility metric: Net Profit penalizing maximum drawdown severity
            fitness = net_profit - (max_dd * start_val * 0.5) 
            
        return {
            'trial_id': trial_id,
            'params': params,
            'fitness': fitness,
            'metrics': {
                'net_profit': net_profit,
                'total_trades': total_trades,
                'win_rate': win_rate,
                'max_dd_pct': max_dd,
                'profit_factor': stats['analytics']['profit_factor'],
                'maker_fill_rate': stats['analytics']['maker_fill_rate']
            }
        }
    except Exception as e:
        # Catch unexpected engine crashes gracefully
        return {'trial_id': trial_id, 'fitness': -99999.0, 'error': str(e), 'params': params}

def main():
    parser = argparse.ArgumentParser(description="Random Search Optimizer for PulseQuant Engine")
    parser.add_argument('--input', type=str, required=True, help="Path to capture .jsonl file")
    parser.add_argument('--trials', type=int, default=100, help="Number of random search trials (default 100)")
    parser.add_argument('--workers', type=int, default=os.cpu_count() - 1, help="Number of parallel workers")
    parser.add_argument('--output', type=str, default="optimization_results.json", help="Output results file")
    parser.add_argument('--seed', type=int, default=42, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    # Set the random seed
    random.seed(args.seed)
    
    if not os.path.exists(args.input):
        print(f"Error: Input file {args.input} not found.")
        sys.exit(1)
        
    print(f"Starting Random Search Optimization:")
    print(f"- Dataset: {args.input}")
    print(f"- Trials: {args.trials}")
    print(f"- Workers: {args.workers}")
    print(f"- Seed: {args.seed}")
    print("-" * 50)
    
    start_time = time.time()
    results = []
    
    # Execute trials in parallel utilizing all CPU cores
    with ProcessPoolExecutor(max_workers=max(1, args.workers), initializer=init_worker, initargs=(args.input,)) as executor:
        futures = {}
        for trial_id in range(args.trials):
            params = generate_random_params()
            futures[executor.submit(evaluate_params, params, trial_id)] = trial_id
            
        completed = 0
        for future in as_completed(futures):
            completed += 1
            res = future.result()
            results.append(res)
            
            # Simple progress tracking
            if 'error' in res:
                print(f"Trial {res['trial_id']} Failed: {res['error']}")
            else:
                fitness = res['fitness']
                pnl = res['metrics']['net_profit']
                trades = res['metrics']['total_trades']
                print(f"[{completed}/{args.trials}] Trial {res['trial_id']} finished | Fitness: {fitness:.2f} | PnL: ${pnl:.2f} | Trades: {trades}")
                
    elapsed = time.time() - start_time
    print("-" * 50)
    print(f"Optimization completed in {elapsed:.2f} seconds.")
    
    # Sort results exclusively by standard fitness descending
    valid_results = [r for r in results if 'error' not in r and r['fitness'] > -9000]
    valid_results.sort(key=lambda x: x['fitness'], reverse=True)
    
    leaderboard = valid_results[:20] # Keep top 20
    
    if leaderboard:
        print("\n🏆 Top 3 Parameter Sets:")
        for idx, res in enumerate(leaderboard[:3]):
            print(f"Rank {idx+1} [Trial {res['trial_id']}]:")
            print(f"  Fitness: {res['fitness']:.2f}")
            print(f"  Metrics: Net=${res['metrics']['net_profit']:.2f}, WinRate={res['metrics']['win_rate']:.2%}, "
                  f"MaxDD={res['metrics']['max_dd_pct']:.2%}, Trades={res['metrics']['total_trades']}")
            print(f"  Params : {json.dumps(res['params'], indent=2)}")
    else:
        print("No profitable or valid parameter sets found (check minimum trade requirements).")
        
    # Save complete sorted results to disk
    with open(args.output, 'w') as f:
        json.dump(leaderboard, f, indent=4)
        
    print(f"\nTop results saved to {args.output}")

if __name__ == '__main__':
    main()



##########
## Last Run:
#
# Optimization completed in 1052.48 seconds.
#
# 🏆 Top 3 Parameter Sets:
# Rank 1 [Trial 2081]:
#   Fitness: 13.82
#   Metrics: Net=$14.61, WinRate=80.69%, MaxDD=0.00%, Trades=145
#   Params : {
#   "speed": "fast",
#   "style": "moderate",
#   "stop_min": 0.000696,
#   "stop_cap": 0.472905,
#   "flow_ofi_threshold": 3.499,
#   "obi_toxicity_threshold": 1.7118,
#   "toxicity_resting_multiplier": 0.9619,
#   "min_rest_ms": 450,
#   "inventory_skew_factor": 2.5,
#   "dobi_lambda": 0.02,
#   "enable_flow_invalidation": true,
#   "flow_obi_threshold": 1.201642774178217,
#   "max_inventory": 11.211088539847164,
#   "toxicity_resting_obi_multiplier": 1.269087505715421,
#   "dobi_levels": 18,
#   "update_interval_ms": 25,
#   "vpin_alpha": 0.5056018116224201,
#   "vpin_sweep_threshold": 0.15667675013266968,
#   "alpha_vwap_decay": 0.0011576180112907173,
#   "bb_std_multiplier": 4.4942490108554605,
#   "ofi_clip_bound": 8.725766452653948,
#   "buy_deriv_shift_cap": 0.3310338385352486,
#   "sell_deriv_shift_cap": 0.4944179766147796,
#   "buy_deriv_pressure_multiplier": 0.23789185654197345,
#   "sell_deriv_pressure_multiplier": 1.4029709022807553,
#   "whipsaw_time_buffer_ms": 6271.55438884266,
#   "tick_size": 0.05327427600863069,
#   "trade_size_bps": 194,
#   "post_only_mode": true,
#   "chaser_distance_multiplier": 1.3332895115365753
# }
# Rank 2 [Trial 138]:
#   Fitness: 13.59
#   Metrics: Net=$14.39, WinRate=80.27%, MaxDD=0.00%, Trades=147
#   Params : {
#   "speed": "fast",
#   "style": "moderate",
#   "stop_min": 0.000696,
#   "stop_cap": 0.472905,
#   "flow_ofi_threshold": 3.499,
#   "obi_toxicity_threshold": 1.7118,
#   "toxicity_resting_multiplier": 0.9619,
#   "min_rest_ms": 450,
#   "inventory_skew_factor": 2.5,
#   "dobi_lambda": 0.02,
#   "enable_flow_invalidation": true,
#   "flow_obi_threshold": 1.1580520407948556,
#   "max_inventory": 11.353839480579131,
#   "toxicity_resting_obi_multiplier": 1.1125350362010613,
#   "dobi_levels": 18,
#   "update_interval_ms": 31,
#   "vpin_alpha": 0.4879621682675077,
#   "vpin_sweep_threshold": 0.24904827442258873,
#   "alpha_vwap_decay": 0.00032876062318085364,
#   "bb_std_multiplier": 4.302784610384509,
#   "ofi_clip_bound": 8.28257557095058,
#   "buy_deriv_shift_cap": 0.20258307095966602,
#   "sell_deriv_shift_cap": 0.4729667012675361,
#   "buy_deriv_pressure_multiplier": 0.23054091582185032,
#   "sell_deriv_pressure_multiplier": 1.2769731303483813,
#   "whipsaw_time_buffer_ms": 3787.6617764657653,
#   "tick_size": 0.05025084021939254,
#   "trade_size_bps": 157,
#   "post_only_mode": true,
#   "chaser_distance_multiplier": 1.065464261270084
# }
# Rank 3 [Trial 1368]:
#   Fitness: 13.51
#   Metrics: Net=$14.30, WinRate=80.82%, MaxDD=0.00%, Trades=146
#   Params : {
#   "speed": "fast",
#   "style": "moderate",
#   "stop_min": 0.000696,
#   "stop_cap": 0.472905,
#   "flow_ofi_threshold": 3.499,
#   "obi_toxicity_threshold": 1.7118,
#   "toxicity_resting_multiplier": 0.9619,
#   "min_rest_ms": 450,
#   "inventory_skew_factor": 2.5,
#   "dobi_lambda": 0.02,
#   "enable_flow_invalidation": true,
#   "flow_obi_threshold": 1.3255203868532541,
#   "max_inventory": 9.714697564975094,
#   "toxicity_resting_obi_multiplier": 1.022822367538351,
#   "dobi_levels": 15,
#   "update_interval_ms": 29,
#   "vpin_alpha": 0.4251095076595119,
#   "vpin_sweep_threshold": 0.26073840428204975,
#   "alpha_vwap_decay": 0.0010092151613960883,
#   "bb_std_multiplier": 4.469953225411203,
#   "ofi_clip_bound": 9.693503651063882,
#   "buy_deriv_shift_cap": 0.35971318397207624,
#   "sell_deriv_shift_cap": 0.33859685543946927,
#   "buy_deriv_pressure_multiplier": 0.15514317074639494,
#   "sell_deriv_pressure_multiplier": 1.1412839707430353,
#   "whipsaw_time_buffer_ms": 7844.032049639165,
#   "tick_size": 0.051851605369487686,
#   "trade_size_bps": 214,
#   "post_only_mode": true,
#   "chaser_distance_multiplier": 1.194322535697765
# }
################################