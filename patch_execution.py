import re

with open('public/python/engine.py', 'r') as f:
    content = f.read()

# Replace _on_signal handling of CLOSE and EMERGENCY
old_signal_exit = """        elif direction == 'CLOSE_SPREAD':
            self.bus.publish('LOG', {'level': 'INFO', 'message': f'CLOSE_SPREAD signaled. Exiting {self.target} & {self.feature}'})
            if self.state == 'LEGGING_MAKER_ENTRY':
                # Cancel maker order if it hasn't filled yet
                self.bus.publish('OUTBOUND_INTENT', {
                    'action': 'CANCEL_ORDER',
                    'order_id': self.active_maker_order_id,
                    'symbol': self.target
                })
                self.state = 'IDLE'
                self.active_maker_order_id = None
                self.pending_leg2 = None
                
            elif self.state == 'HEDGED':
                # Aggressive Limit exit both legs immediately
                self.state = 'CLOSING'
                
                target_pos = self.portfolio.positions[self.target]
                feature_pos = self.portfolio.positions[self.feature]
                slip_ratio = self.slippage_bps / 10000.0
                
                if abs(target_pos) > 1e-8:
                    side = 'SELL' if target_pos > 0 else 'BUY'
                    price = self.target_price * (1.0 - slip_ratio) if side == 'SELL' else self.target_price * (1.0 + slip_ratio)
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'PLACE_ORDER',
                        'order_id': str(uuid.uuid4()),
                        'symbol': self.target,
                        'side': side,
                        'type': 'LIMIT',
                        'price': price,
                        'qty': abs(target_pos)
                    })
                if abs(feature_pos) > 1e-8:
                    side = 'SELL' if feature_pos > 0 else 'BUY'
                    price = self.feature_price * (1.0 - slip_ratio) if side == 'SELL' else self.feature_price * (1.0 + slip_ratio)
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'PLACE_ORDER',
                        'order_id': str(uuid.uuid4()),
                        'symbol': self.feature,
                        'side': side,
                        'type': 'LIMIT',
                        'price': price,
                        'qty': abs(feature_pos)
                    })
                    
        elif direction == 'EMERGENCY_CLOSE_SPREAD':
            if self.state in ('LEGGING_MAKER_ENTRY', 'HEDGED'):
                self.bus.publish('LOG', {'level': 'WARN', 'message': f'EMERGENCY_CLOSE_SPREAD triggered. Exiting {self.target} & {self.feature}'})
                if self.state == 'LEGGING_MAKER_ENTRY':
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'CANCEL_ORDER',
                        'order_id': self.active_maker_order_id,
                        'symbol': self.target
                    })
                self.state = 'CLOSING'
                self.active_maker_order_id = None
                self.pending_leg2 = None
                
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
                        'price': 0
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
                        'price': 0
                    })"""

new_signal_exit = """        elif direction in ['CLOSE_SPREAD', 'EMERGENCY_CLOSE_SPREAD']:
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

content = content.replace(old_signal_exit, new_signal_exit)


# Replace _enter_spread
old_enter_spread = """    def _enter_spread(self, target_side: str, target_notional: float):
        if self.feature_price == 0 or self.target_price == 0 or target_notional <= 0:
            return
            
        self.state = 'LEGGING_MAKER_ENTRY'
        self.active_maker_order_id = str(uuid.uuid4())
        self.maker_order_ts = 0 
        self.maker_filled_qty = 0.0
        self.total_maker_orders += 1
        
        if self.latest_beta >= 0:
            feature_side = 'SELL' if target_side == 'BUY' else 'BUY'
        else:
            feature_side = target_side
            
        maker_price = self.target_bid if target_side == 'BUY' else self.target_ask
        target_qty = target_notional / maker_price if maker_price > 0 else 0.0
        
        slip_ratio = self.slippage_bps / 10000.0
        if feature_side == 'BUY':
            taker_price = self.feature_ask * (1.0 + slip_ratio)
        else:
            taker_price = self.feature_bid * (1.0 - slip_ratio)
            
        self.pending_leg2_template = {
            'symbol': self.feature,
            'side': feature_side,
            'type': 'MARKET',
            'price': taker_price
        }
        
        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': self.active_maker_order_id,
            'symbol': self.target,
            'side': target_side,
            'type': 'LIMIT',
            'qty': round(target_qty, 3),
            'price': round(maker_price, 2)
        })"""

new_enter_spread = """    def _enter_spread(self, target_side: str, target_notional: float):
        if self.feature_price == 0 or self.target_price == 0 or target_notional <= 0:
            return
            
        self.state = 'HEDGED'
        self.position_entry_ts = 0
        
        if self.latest_beta >= 0:
            feature_side = 'SELL' if target_side == 'BUY' else 'BUY'
        else:
            feature_side = target_side
            
        target_qty = target_notional / self.target_price if self.target_price > 0 else 0.0
        feature_qty = target_qty * (self.target_price / self.feature_price) * abs(self.latest_beta)
        
        target_qty = round(target_qty, 3)
        feature_qty = round(feature_qty, 3)
        
        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': str(uuid.uuid4()),
            'symbol': self.target,
            'side': target_side,
            'type': 'MARKET',
            'qty': target_qty,
            'price': 0.0
        })
        
        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': str(uuid.uuid4()),
            'symbol': self.feature,
            'side': feature_side,
            'type': 'MARKET',
            'qty': feature_qty,
            'price': 0.0
        })"""

content = content.replace(old_enter_spread, new_enter_spread)


# Replace _on_timer
old_on_timer = """    def _on_timer(self, payload: dict):
        ts = payload.get('timestamp', 0)
        
        # Initialize maker_order_ts on the first timer tick after order is placed
        if self.state == 'LEGGING_MAKER_ENTRY' and self.active_maker_order_id:
            if self.maker_order_ts == 0:
                self.maker_order_ts = ts
            
            if self.maker_order_ts > 0 and (ts - self.maker_order_ts) > self.maker_timeout_ms:
                # Maker timeout exceeded, cancel the order
                self.bus.publish('LOG', {'level': 'WARN', 'message': f'Maker order timed out ({self.maker_timeout_ms/1000:.1f}s), cancelling...'})
                self.bus.publish('OUTBOUND_INTENT', {
                    'action': 'CANCEL_ORDER',
                    'order_id': self.active_maker_order_id,
                    'symbol': self.target
                })
                self.maker_timeouts += 1
                self.state = 'IDLE'
                self.active_maker_order_id = None
                self.pending_leg2 = None
                self.maker_order_ts = 0

        # Time-Stop: Check if we've held the position drastically longer than the mean-reversion expected time
        if self.state == 'HEDGED' and self.position_entry_ts > 0:
            hold_time_ms = ts - self.position_entry_ts
            if hold_time_ms > 2.0 * self.half_life_ms:
                # We've held 2x the cointegration half-life without converging -> Emergency exit
                self.bus.publish('LOG', {'level': 'WARN', 'message': f'Time-stop triggered. Held for {hold_time_ms/1000:.1f}s (half-life: {self.half_life_ms/1000:.1f}s)'})
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD'})"""

new_on_timer = """    def _on_timer(self, payload: dict):
        ts = payload.get('timestamp', 0)
        
        # Time-Stop: Check if we've held the position drastically longer than the mean-reversion expected time
        if self.state == 'HEDGED' and self.position_entry_ts > 0:
            hold_time_ms = ts - self.position_entry_ts
            if hold_time_ms > 2.0 * self.half_life_ms:
                self.bus.publish('LOG', {'level': 'WARN', 'message': f'Time-stop triggered. Held for {hold_time_ms/1000:.1f}s (half-life: {self.half_life_ms/1000:.1f}s)'})
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD'})"""

content = content.replace(old_on_timer, new_on_timer)


# Replace _on_order_update
old_on_order_update = """    def _on_order_update(self, payload: dict):
        status = payload.get('status')
        order_id = payload.get('order_id')
        
        if self.state == 'LEGGING_MAKER_ENTRY' and order_id == self.active_maker_order_id:
            qty_filled = float(payload.get('filled_qty', 0.0))
            
            if qty_filled > self.maker_filled_qty and self.pending_leg2_template is not None:
                newly_filled = qty_filled - self.maker_filled_qty
                self.maker_filled_qty = qty_filled
                
                taker_qty = newly_filled * (self.target_price / self.feature_price) * abs(self.latest_beta)
                # Production enforcement: Round to exchange lot size (e.g. 3 decimal places)
                taker_qty = round(taker_qty, 3)
                
                self.bus.publish('OUTBOUND_INTENT', {
                    'action': 'PLACE_ORDER',
                    'order_id': str(uuid.uuid4()),
                    'symbol': self.pending_leg2_template['symbol'],
                    'side': self.pending_leg2_template['side'],
                    'type': self.pending_leg2_template['type'],
                    'price': self.pending_leg2_template.get('price'),
                    'qty': taker_qty,
                    'price': round(self.pending_leg2_template.get('price', 0.0), 2)
                })
                
            if status == 'FILLED':
                # Leg2 filled completely, we are fully hedged now
                self.state = 'HEDGED'
                self.position_entry_ts = float(payload.get('transaction_time', payload.get('transactionTime', payload.get('timestamp', 0))))
                self.active_maker_order_id = None
                self.pending_leg2_template = None
                self.maker_order_ts = 0
                self.maker_filled_qty = 0.0
                
            elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                self.state = 'IDLE'
                self.active_maker_order_id = None
                self.pending_leg2_template = None
                self.maker_order_ts = 0
                self.maker_filled_qty = 0.0

        # If CLOSING, stay in CLOSING until positions reach zero (monitored by PortfolioManager)
        # We can loosely reset the state to IDLE if both positions hit zero.
        if self.state == 'CLOSING':
            target_pos = self.portfolio.positions.get(self.target, 0.0)
            feature_pos = self.portfolio.positions.get(self.feature, 0.0)
            if abs(target_pos) < 1e-8 and abs(feature_pos) < 1e-8:
                self.state = 'IDLE'"""

new_on_order_update = """    def _on_order_update(self, payload: dict):
        status = payload.get('status')
        if status == 'FILLED':
            if self.state == 'HEDGED' and self.position_entry_ts == 0:
                self.position_entry_ts = float(payload.get('transaction_time', payload.get('transactionTime', payload.get('timestamp', 0))))

        if self.state == 'CLOSING':
            target_pos = self.portfolio.positions.get(self.target, 0.0)
            feature_pos = self.portfolio.positions.get(self.feature, 0.0)
            if abs(target_pos) < 1e-8 and abs(feature_pos) < 1e-8:
                self.state = 'IDLE'
                self.position_entry_ts = 0"""

content = content.replace(old_on_order_update, new_on_order_update)

with open('public/python/engine.py', 'w') as f:
    f.write(content)
print("Execution manager patched successfully!")
