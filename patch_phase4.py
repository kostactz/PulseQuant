import re

with open('public/python/engine.py', 'r') as f:
    content = f.read()

# --- 1. SignalGenerator changes ---
sig_init_old = """        self.circuit_breaker_tripped = False
        self.initial_capital = self.portfolio.cash
        self.anchored_mean = None"""

sig_init_new = """        self.circuit_breaker_tripped = False
        self.initial_capital = self.portfolio.cash
        self.anchored_mean = None
        self.is_position_open = False"""

content = content.replace(sig_init_old, sig_init_new)

sig_sub_old = """        self.bus.subscribe('MODEL_UPDATED', self._on_model_updated)
        self.bus.subscribe('REGIME_CHANGE', self._on_regime_change)
        self.bus.subscribe('UPDATE_STRATEGY_PARAMS', self._on_update_params)
        self.bus.subscribe('FUNDING_RATE_UPDATE', self._on_funding_rate_update)"""

sig_sub_new = """        self.bus.subscribe('MODEL_UPDATED', self._on_model_updated)
        self.bus.subscribe('REGIME_CHANGE', self._on_regime_change)
        self.bus.subscribe('UPDATE_STRATEGY_PARAMS', self._on_update_params)
        self.bus.subscribe('FUNDING_RATE_UPDATE', self._on_funding_rate_update)
        self.bus.subscribe('ORDER_UPDATE', self._on_order_update)
        
    def _on_order_update(self, payload: dict):
        target_pos = self.portfolio.positions.get(self.target, 0.0)
        feature_pos = self.portfolio.positions.get(self.feature, 0.0)
        if abs(target_pos) < 1e-8 and abs(feature_pos) < 1e-8:
            self.is_position_open = False"""

content = content.replace(sig_sub_old, sig_sub_new)

entry_guard_old = """        is_beta_valid = (self.min_beta <= beta <= self.max_beta)

        if not self.is_toxic and variance > 1e-12 and is_beta_valid:"""

entry_guard_new = """        is_beta_valid = (self.min_beta <= beta <= self.max_beta)
        
        target_pos = self.portfolio.positions.get(self.target, 0.0)
        can_enter = (abs(target_pos) < 1e-8) and not self.is_position_open

        if not self.is_toxic and variance > 1e-12 and is_beta_valid and can_enter:"""

content = content.replace(entry_guard_old, entry_guard_new)

long_sig_old = """                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'LONG_SPREAD signaled. Edge: {expected_edge_long_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.anchored_mean = spread_mean
                        self.anchored_std = spread_std
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'LONG_SPREAD', 'z_score': long_z_score, 'target_notional': expected_target_notional})"""

long_sig_new = """                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'LONG_SPREAD signaled. Edge: {expected_edge_long_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.anchored_mean = spread_mean
                        self.anchored_std = spread_std
                        self.is_position_open = True
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'LONG_SPREAD', 'z_score': long_z_score, 'target_notional': expected_target_notional})"""

content = content.replace(long_sig_old, long_sig_new)

short_sig_old = """                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'SHORT_SPREAD signaled. Edge: {expected_edge_short_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.anchored_mean = spread_mean
                        self.anchored_std = spread_std
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'SHORT_SPREAD', 'z_score': short_z_score, 'target_notional': expected_target_notional})"""

short_sig_new = """                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'SHORT_SPREAD signaled. Edge: {expected_edge_short_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.anchored_mean = spread_mean
                        self.anchored_std = spread_std
                        self.is_position_open = True
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'SHORT_SPREAD', 'z_score': short_z_score, 'target_notional': expected_target_notional})"""

content = content.replace(short_sig_old, short_sig_new)


# --- 2. ExecutionManager changes ---
exec_init_old = """        self.maker_filled_qty = 0.0
        self.position_entry_ts = 0
        self.half_life_ms = 3600000.0  # default 1 hour
        
        self.maker_timeout_ms = 5000  # Dynamic based on regime"""

exec_init_new = """        self.maker_filled_qty = 0.0
        self.position_entry_ts = 0
        self.half_life_ms = 3600000.0  # default 1 hour
        
        self.maker_timeout_ms = 5000  # Dynamic based on regime
        self.current_position_id = None
        self.time_stop_mode = 'auto'
        self.time_stop_value = 2.0"""

content = content.replace(exec_init_old, exec_init_new)

exec_sub_old = """        self.bus.subscribe('ORDER_UPDATE', self._on_order_update)
        self.bus.subscribe('MODEL_UPDATED', self._on_model_update)
        self.bus.subscribe('TIMER_1S', self._on_timer)
        self.bus.subscribe('REGIME_CHANGE', self._on_regime_change)"""

exec_sub_new = """        self.bus.subscribe('ORDER_UPDATE', self._on_order_update)
        self.bus.subscribe('MODEL_UPDATED', self._on_model_update)
        self.bus.subscribe('TIMER_1S', self._on_timer)
        self.bus.subscribe('REGIME_CHANGE', self._on_regime_change)
        self.bus.subscribe('UPDATE_STRATEGY_PARAMS', self._on_update_params)
        
    def _on_update_params(self, payload: dict):
        if 'time_stop' in payload:
            ts_str = str(payload['time_stop']).strip().lower()
            if ts_str == 'auto':
                self.time_stop_mode = 'auto'
            elif ts_str.startswith('x'):
                self.time_stop_mode = 'multiplier'
                self.time_stop_value = float(ts_str[1:])
            elif ts_str.endswith('m'):
                self.time_stop_mode = 'static'
                self.time_stop_value = float(ts_str[:-1]) * 60 * 1000
            elif ts_str.endswith('h'):
                self.time_stop_mode = 'static'
                self.time_stop_value = float(ts_str[:-1]) * 3600 * 1000
            elif ts_str.endswith('s'):
                self.time_stop_mode = 'static'
                self.time_stop_value = float(ts_str[:-1]) * 1000
            else:
                try:
                    self.time_stop_mode = 'multiplier'
                    self.time_stop_value = float(ts_str)
                except ValueError:
                    pass"""

content = content.replace(exec_sub_old, exec_sub_new)

enter_spread_old = """        self.state = 'HEDGED'
        self.position_entry_ts = 0"""

enter_spread_new = """        self.state = 'HEDGED'
        self.position_entry_ts = 0
        import uuid
        self.current_position_id = str(uuid.uuid4())[:8]"""

content = content.replace(enter_spread_old, enter_spread_new)

intent_1_old = """        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': str(uuid.uuid4()),
            'symbol': self.target,
            'side': target_side,
            'type': 'MARKET',
            'qty': target_qty,
            'price': 0.0
        })"""

intent_1_new = """        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': str(uuid.uuid4()),
            'symbol': self.target,
            'side': target_side,
            'type': 'MARKET',
            'qty': target_qty,
            'price': 0.0,
            'position_id': self.current_position_id
        })"""

content = content.replace(intent_1_old, intent_1_new)

intent_2_old = """        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': str(uuid.uuid4()),
            'symbol': self.feature,
            'side': feature_side,
            'type': 'MARKET',
            'qty': feature_qty,
            'price': 0.0
        })"""

intent_2_new = """        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': str(uuid.uuid4()),
            'symbol': self.feature,
            'side': feature_side,
            'type': 'MARKET',
            'qty': feature_qty,
            'price': 0.0,
            'position_id': self.current_position_id
        })"""

content = content.replace(intent_2_old, intent_2_new)

exit_signal_old = """        elif direction in ['CLOSE_SPREAD', 'EMERGENCY_CLOSE_SPREAD']:
            if self.state != 'IDLE':
                self.bus.publish('LOG', {'level': 'INFO', 'message': f'{direction} signaled. Exiting {self.target} & {self.feature}'})
                self.state = 'CLOSING'
                
                target_pos = self.portfolio.positions[self.target]
                feature_pos = self.portfolio.positions[self.feature]
                
                if abs(target_pos) > 1e-8:
                    side = 'SELL' if target_pos > 0 else 'BUY'
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'PLACE_ORDER',
                        'order_id': str(uuid.uuid4()),
                        'symbol': self.target,
                        'side': side,
                        'type': 'MARKET',
                        'qty': abs(target_pos),
                        'price': 0.0
                    })
                if abs(feature_pos) > 1e-8:
                    side = 'SELL' if feature_pos > 0 else 'BUY'
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'PLACE_ORDER',
                        'order_id': str(uuid.uuid4()),
                        'symbol': self.feature,
                        'side': side,
                        'type': 'MARKET',
                        'qty': abs(feature_pos),
                        'price': 0.0
                    })"""

exit_signal_new = """        elif direction in ['CLOSE_SPREAD', 'EMERGENCY_CLOSE_SPREAD']:
            if self.state != 'IDLE':
                self.bus.publish('LOG', {'level': 'INFO', 'message': f'{direction} signaled. Exiting {self.target} & {self.feature} [PosID: {self.current_position_id}]'})
                self.state = 'CLOSING'
                
                target_pos = self.portfolio.positions[self.target]
                feature_pos = self.portfolio.positions[self.feature]
                
                if abs(target_pos) > 1e-8:
                    side = 'SELL' if target_pos > 0 else 'BUY'
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'PLACE_ORDER',
                        'order_id': str(uuid.uuid4()),
                        'symbol': self.target,
                        'side': side,
                        'type': 'MARKET',
                        'qty': abs(target_pos),
                        'price': 0.0,
                        'position_id': self.current_position_id
                    })
                if abs(feature_pos) > 1e-8:
                    side = 'SELL' if feature_pos > 0 else 'BUY'
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'PLACE_ORDER',
                        'order_id': str(uuid.uuid4()),
                        'symbol': self.feature,
                        'side': side,
                        'type': 'MARKET',
                        'qty': abs(feature_pos),
                        'price': 0.0,
                        'position_id': self.current_position_id
                    })"""

content = content.replace(exit_signal_old, exit_signal_new)

timer_old = """    def _on_timer(self, payload: dict):
        ts = payload.get('timestamp', 0)
        
        # Time-Stop: Check if we've held the position drastically longer than the mean-reversion expected time
        if self.state == 'HEDGED' and self.position_entry_ts > 0:
            hold_time_ms = ts - self.position_entry_ts
            if hold_time_ms > 2.0 * self.half_life_ms:
                self.bus.publish('LOG', {'level': 'WARN', 'message': f'Time-stop triggered. Held for {hold_time_ms/1000:.1f}s (half-life: {self.half_life_ms/1000:.1f}s)'})
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD'})"""

timer_new = """    def _on_timer(self, payload: dict):
        ts = payload.get('timestamp', 0)
        
        # Time-Stop: Check if we've held the position drastically longer than the mean-reversion expected time
        if self.state == 'HEDGED' and self.position_entry_ts > 0:
            hold_time_ms = ts - self.position_entry_ts
            
            if self.time_stop_mode == 'multiplier':
                max_hold_ms = self.half_life_ms * self.time_stop_value
            elif self.time_stop_mode == 'static':
                max_hold_ms = self.time_stop_value
            else: # auto
                max_hold_ms = max(self.half_life_ms * 2.0, 3600000.0) # min 1 hour
                
            if hold_time_ms > max_hold_ms:
                self.bus.publish('LOG', {'level': 'WARN', 'message': f'Time-stop triggered. Held for {hold_time_ms/1000:.1f}s (max: {max_hold_ms/1000:.1f}s) [PosID: {self.current_position_id}]'})
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD'})"""

content = content.replace(timer_old, timer_new)

order_update_old = """        if self.state == 'CLOSING':
            target_pos = self.portfolio.positions.get(self.target, 0.0)
            feature_pos = self.portfolio.positions.get(self.feature, 0.0)
            if abs(target_pos) < 1e-8 and abs(feature_pos) < 1e-8:
                self.state = 'IDLE'
                self.position_entry_ts = 0"""

order_update_new = """        if self.state == 'CLOSING':
            target_pos = self.portfolio.positions.get(self.target, 0.0)
            feature_pos = self.portfolio.positions.get(self.feature, 0.0)
            if abs(target_pos) < 1e-8 and abs(feature_pos) < 1e-8:
                self.state = 'IDLE'
                self.position_entry_ts = 0
                self.current_position_id = None"""

content = content.replace(order_update_old, order_update_new)


# --- 3. PortfolioManager changes ---
pm_log_old = """                self.bus.publish('LOG', {'level': 'INFO', 'message': f"Order FILLED: {side} {qty} {symbol} @ {price}. Fee: {fee:.4f} (Maker: {is_maker})"})

                # Accept both timestamp alias forms
                ts = payload.get('transaction_time',
                                 payload.get('transactionTime',
                                             payload.get('timestamp', 0)))
                trade_record = {
                    'timestamp': ts,
                    'symbol': symbol,
                    'side': side.lower(),
                    'qty': qty,
                    'price': price,
                    'fee': fee,
                    'is_maker': is_maker,
                    'realized_pnl': pnl,
                }"""

pm_log_new = """                position_id = payload.get('position_id', '')
                pos_str = f" [PosID: {position_id}]" if position_id else ""
                self.bus.publish('LOG', {'level': 'INFO', 'message': f"Order FILLED: {side} {qty} {symbol} @ {price}. Fee: {fee:.4f} (Maker: {is_maker}){pos_str}"})

                # Accept both timestamp alias forms
                ts = payload.get('transaction_time',
                                 payload.get('transactionTime',
                                             payload.get('timestamp', 0)))
                trade_record = {
                    'timestamp': ts,
                    'symbol': symbol,
                    'side': side.lower(),
                    'qty': qty,
                    'price': price,
                    'fee': fee,
                    'is_maker': is_maker,
                    'realized_pnl': pnl,
                    'position_id': position_id,
                }"""

content = content.replace(pm_log_old, pm_log_new)


with open('public/python/engine.py', 'w') as f:
    f.write(content)

print("engine.py patched.")
