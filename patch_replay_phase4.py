import re

with open('tools/replay.py', 'r') as f:
    content = f.read()

make_fill_old = """def _make_fill_report(order_id, symbol, side, qty, price, is_maker, ts):
    \"\"\"Build an EXECUTION_REPORT data dict.  Both timestamp aliases are present.\"\"\"
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
    }"""

make_fill_new = """def _make_fill_report(order_id, symbol, side, qty, price, is_maker, ts, position_id=None):
    \"\"\"Build an EXECUTION_REPORT data dict.  Both timestamp aliases are present.\"\"\"
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
        'position_id': position_id,
    }"""

content = content.replace(make_fill_old, make_fill_new)

process_intent_old = """            side = intent.get('side', '').upper()
            symbol = intent.get('symbol', '').upper()"""

process_intent_new = """            side = intent.get('side', '').upper()
            symbol = intent.get('symbol', '').upper()
            position_id = intent.get('position_id')"""

content = content.replace(process_intent_old, process_intent_new)

process_fill_old = """                engine.process_events([{'type': 'EXECUTION_REPORT', 'data':
                    _make_fill_report(order_id, symbol, side, qty,
                                      exec_price, False, row_ts)}])"""

process_fill_new = """                engine.process_events([{'type': 'EXECUTION_REPORT', 'data':
                    _make_fill_report(order_id, symbol, side, qty,
                                      exec_price, False, row_ts, position_id)}])"""

content = content.replace(process_fill_old, process_fill_new)

limit_queue_old = """                pending_limit_orders.append({
                    'order_id': order_id,
                    'symbol': symbol,
                    'side': side,
                    'qty': qty,
                    'price': price,
                    'ts': row_ts,
                })"""

limit_queue_new = """                pending_limit_orders.append({
                    'order_id': order_id,
                    'symbol': symbol,
                    'side': side,
                    'qty': qty,
                    'price': price,
                    'ts': row_ts,
                    'position_id': position_id,
                })"""

content = content.replace(limit_queue_old, limit_queue_new)

limit_fill_old = """    for o in filled:
        result = engine.process_events([{'type': 'EXECUTION_REPORT', 'data':
            _make_fill_report(o['order_id'], o['symbol'], o['side'],
                              o['qty'], o['price'], True, tick_ts)}])"""

limit_fill_new = """    for o in filled:
        result = engine.process_events([{'type': 'EXECUTION_REPORT', 'data':
            _make_fill_report(o['order_id'], o['symbol'], o['side'],
                              o['qty'], o['price'], True, tick_ts, o.get('position_id'))}])"""

content = content.replace(limit_fill_old, limit_fill_new)


args_old = """    parser.add_argument('--kelly-fraction', type=float, default=0.25,
                        help="Maximum kelly fraction limit")"""

args_new = """    parser.add_argument('--kelly-fraction', type=float, default=0.25,
                        help="Maximum kelly fraction limit")
    parser.add_argument('--time-stop', type=str, default='auto',
                        help="Time stop configuration (auto, x2, 45m, 2.5h, 120s)")"""

content = content.replace(args_old, args_new)

update_old = """            'kalman_delta': args.kalman_delta,
            'kalman_r_var': args.kalman_r_var,
            'kelly_fraction_limit': args.kelly_fraction"""

update_new = """            'kalman_delta': args.kalman_delta,
            'kalman_r_var': args.kalman_r_var,
            'kelly_fraction_limit': args.kelly_fraction,
            'time_stop': args.time_stop"""

content = content.replace(update_old, update_new)

with open('tools/replay.py', 'w') as f:
    f.write(content)
print("replay.py patched.")
