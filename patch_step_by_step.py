import sys

# Patch replay.py
with open('tools/replay.py', 'r') as f:
    replay_content = f.read()

replay_content = replay_content.replace(
    "def _check_limit_fills(engine, pending_limit_orders, tick_data, tick_ts):",
    "def _check_limit_fills(engine, pending_limit_orders, tick_data, tick_ts, last_tick, slippage_bps):"
)

old_fills = """    for o in filled:
        engine.process_events([{'type': 'EXECUTION_REPORT', 'data':
            _make_fill_report(o['order_id'], o['symbol'], o['side'],
                              o['qty'], o['price'], True, tick_ts)}])
        pending_limit_orders.remove(o)"""

new_fills = """    for o in filled:
        result = engine.process_events([{'type': 'EXECUTION_REPORT', 'data':
            _make_fill_report(o['order_id'], o['symbol'], o['side'],
                              o['qty'], o['price'], True, tick_ts)}])
        if result and result.get('intents'):
            process_intents(engine, result['intents'], pending_limit_orders, tick_ts, last_tick, slippage_bps)
        pending_limit_orders.remove(o)"""
replay_content = replay_content.replace(old_fills, new_fills)

old_call = """            # Check limit order trade-through on every new tick
            _check_limit_fills(engine, pending_limit_orders, data, tick_ts)"""
new_call = """            # Check limit order trade-through on every new tick
            _check_limit_fills(engine, pending_limit_orders, data, tick_ts, last_tick, slippage_bps)"""
replay_content = replay_content.replace(old_call, new_call)

with open('tools/replay.py', 'w') as f:
    f.write(replay_content)

# Patch engine.py
with open('public/python/engine.py', 'r') as f:
    engine_content = f.read()

engine_content = engine_content.replace("self.state = [0.0, 0.0] # [alpha, beta]", "self.state = [0.0, 1.0] # [alpha, beta]")
engine_content = engine_content.replace("self.state = [y, 0.0]", "self.state = [y - x, 1.0]")

old_kalman_reset = """    def reset(self):
        self.state = [0.0, 0.0]
        self.P = [[1.0, 0.0], [0.0, 1.0]]"""
new_kalman_reset = """    def reset(self):
        self.state = [0.0, 1.0]
        self.P = [[1.0, 0.0], [0.0, 1.0]]"""
engine_content = engine_content.replace(old_kalman_reset, new_kalman_reset)

old_sig_init = """        self.toxicity_threshold = 0.05
        self.kelly_fraction_limit = 0.25"""
new_sig_init = """        self.toxicity_threshold = 0.05
        self.kelly_fraction_limit = 0.25
        self.max_drawdown_pct = 0.05
        self.circuit_breaker_tripped = False
        self.initial_capital = self.portfolio.cash"""
engine_content = engine_content.replace(old_sig_init, new_sig_init)

old_sig_params = """        if 'toxicity_threshold' in payload:
            self.toxicity_threshold = float(payload['toxicity_threshold'])"""
new_sig_params = """        if 'toxicity_threshold' in payload:
            self.toxicity_threshold = float(payload['toxicity_threshold'])
        if 'max_drawdown_pct' in payload:
            self.max_drawdown_pct = float(payload['max_drawdown_pct'])"""
engine_content = engine_content.replace(old_sig_params, new_sig_params)

old_sig_update = """    def _on_model_updated(self, payload: dict):
        if not payload['is_ready']:
            return

        import math"""
new_sig_update = """    def _on_model_updated(self, payload: dict):
        if not payload['is_ready']:
            return

        target_price = payload.get('target_price', 0.0)
        feature_price = payload.get('feature_price', 0.0)
        
        if target_price > 0 and feature_price > 0:
            current_nav = self.portfolio.get_nav(target_price, feature_price)
            drawdown_pct = (current_nav - self.initial_capital) / self.initial_capital
            if drawdown_pct <= -self.max_drawdown_pct:
                if not self.circuit_breaker_tripped:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'CIRCUIT BREAKER TRIPPED! Drawdown: {drawdown_pct*100:.2f}%'})
                    self.circuit_breaker_tripped = True
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD'})
                return
            if self.circuit_breaker_tripped:
                return

        import math"""
engine_content = engine_content.replace(old_sig_update, new_sig_update)

old_leg2 = """        self.pending_leg2_template = {
            'symbol': self.feature,
            'side': feature_side,
            'type': 'LIMIT',
            'price': taker_price
        }"""
new_leg2 = """        self.pending_leg2_template = {
            'symbol': self.feature,
            'side': feature_side,
            'type': 'MARKET',
            'price': taker_price
        }"""
engine_content = engine_content.replace(old_leg2, new_leg2)

with open('public/python/engine.py', 'w') as f:
    f.write(engine_content)

print("Successfully applied all 4 enhancements.")
