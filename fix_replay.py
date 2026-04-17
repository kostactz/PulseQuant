import re

with open('tools/replay.py', 'r') as f:
    content = f.read()

# Add taker-fee arg
arg_old = """    parser.add_argument('--slippage-bps', type=float, default=10.0,
                        help="Market-order slippage in basis points (default 10 bps = 0.10%%)")"""

arg_new = """    parser.add_argument('--slippage-bps', type=float, default=10.0,
                        help="Market-order slippage in basis points (default 10 bps = 0.10%%)")
    parser.add_argument('--taker-fee', type=float, default=0.0005,
                        help="Taker fee (default 0.0005 = 5 bps)")"""

content = content.replace(arg_old, arg_new)

# Add taker_fee and slippage_bps to payload
payload_old = """        'data': {
            'sigma_threshold': args.sigma_threshold,
            'min_entry_spread_bps': args.min_entry_spread,
            'min_beta': args.min_beta,
            'max_beta': args.max_beta,
            'kalman_delta': args.kalman_delta,
            'kalman_r_var': args.kalman_r_var,
            'kelly_fraction_limit': args.kelly_fraction,
            'time_stop': args.time_stop
        }"""

payload_new = """        'data': {
            'sigma_threshold': args.sigma_threshold,
            'min_entry_spread_bps': args.min_entry_spread,
            'min_beta': args.min_beta,
            'max_beta': args.max_beta,
            'kalman_delta': args.kalman_delta,
            'kalman_r_var': args.kalman_r_var,
            'kelly_fraction_limit': args.kelly_fraction,
            'time_stop': args.time_stop,
            'taker_fee': args.taker_fee,
            'slippage_bps': args.slippage_bps
        }"""

content = content.replace(payload_old, payload_new)

with open('tools/replay.py', 'w') as f:
    f.write(content)

print("replay.py updated")
