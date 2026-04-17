import re

with open('tools/replay.py', 'r') as f:
    content = f.read()

old_args = """    parser.add_argument('--sigma-threshold', type=float, default=2.0,
                        help="Z-score threshold for entry")
    parser.add_argument('--min-entry-spread', type=float, default=0.0,
                        help="Minimum spread in bps to enter a trade")"""

new_args = """    parser.add_argument('--sigma-threshold', type=float, default=2.0,
                        help="Z-score threshold for entry")
    parser.add_argument('--min-entry-spread', type=float, default=0.0,
                        help="Minimum spread in bps to enter a trade")
    parser.add_argument('--min-beta', type=float, default=0.5,
                        help="Minimum allowed beta for entry")
    parser.add_argument('--max-beta', type=float, default=1.5,
                        help="Maximum allowed beta for entry")
    parser.add_argument('--kalman-delta', type=float, default=1e-5,
                        help="Kalman filter delta (state variance)")
    parser.add_argument('--kalman-r-var', type=float, default=1e-3,
                        help="Kalman filter r_var (observation noise)")
    parser.add_argument('--kelly-fraction', type=float, default=0.25,
                        help="Maximum kelly fraction limit")"""

content = content.replace(old_args, new_args)

old_update = """    # Apply user-specified strategy parameters
    engine.process_events([{
        'type': 'UPDATE_STRATEGY_PARAMS',
        'data': {
            'sigma_threshold': args.sigma_threshold,
            'min_entry_spread_bps': args.min_entry_spread
        }
    }])"""

new_update = """    # Apply user-specified strategy parameters
    engine.process_events([{
        'type': 'UPDATE_STRATEGY_PARAMS',
        'data': {
            'sigma_threshold': args.sigma_threshold,
            'min_entry_spread_bps': args.min_entry_spread,
            'min_beta': args.min_beta,
            'max_beta': args.max_beta,
            'kalman_delta': args.kalman_delta,
            'kalman_r_var': args.kalman_r_var,
            'kelly_fraction_limit': args.kelly_fraction
        }
    }])"""

content = content.replace(old_update, new_update)

with open('tools/replay.py', 'w') as f:
    f.write(content)
print("Replay tool updated.")
