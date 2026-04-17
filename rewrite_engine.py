import re

with open('public/python/engine.py', 'r') as f:
    content = f.read()

# --- 1. SignalGenerator Init Update ---
old_init = """        self.toxicity_threshold = 0.05
        self.kelly_fraction_limit = 0.25
        self.max_drawdown_pct = 0.05
        self.circuit_breaker_tripped = False
        self.initial_capital = self.portfolio.cash"""

new_init = """        self.toxicity_threshold = 0.05
        self.kelly_fraction_limit = 0.25
        self.max_drawdown_pct = 0.05
        self.circuit_breaker_tripped = False
        self.initial_capital = self.portfolio.cash
        self.anchored_mean = None
        self.anchored_std = None
        self.min_beta = 0.5
        self.max_beta = 1.5"""

content = content.replace(old_init, new_init)

# --- 2. Dynamic Hurdle Fee Update ---
old_hurdle = """    def _compute_dynamic_hurdle_bps(self) -> float:
        \"\"\"Compute the minimum edge (in bps) required to justify a new position.

        dynamic_hurdle = maker_entry_fee + taker_exit_fee + slippage + funding_drag

        estimated hold time ≈ half_life_seconds (capped at one 8-hour funding period)
        funding_drag ≈ abs(funding_rate) × (hold / (8h)) × 10_000
        \"\"\"
        maker_fee_bps = self.maker_fee * 10_000    # 2 bps
        taker_fee_bps = self.taker_fee * 10_000    # 5 bps
        hold_s = min(self.half_life_seconds, 8 * 3600)
        funding_bps = abs(self.current_funding_rate) * (hold_s / (8 * 3600)) * 10_000
        hurdle = maker_fee_bps + taker_fee_bps + self.slippage_bps + funding_bps"""

new_hurdle = """    def _compute_dynamic_hurdle_bps(self) -> float:
        \"\"\"Compute the minimum edge (in bps) required to justify a new position.

        dynamic_hurdle = taker_entry_fee + taker_exit_fee + slippage + funding_drag

        estimated hold time ≈ half_life_seconds (capped at one 8-hour funding period)
        funding_drag ≈ abs(funding_rate) × (hold / (8h)) × 10_000
        \"\"\"
        taker_entry_fee_bps = self.taker_fee * 10_000  # 5 bps
        taker_exit_fee_bps = self.taker_fee * 10_000   # 5 bps
        hold_s = min(self.half_life_seconds, 8 * 3600)
        funding_bps = abs(self.current_funding_rate) * (hold_s / (8 * 3600)) * 10_000
        hurdle = taker_entry_fee_bps + taker_exit_fee_bps + self.slippage_bps + funding_bps"""

content = content.replace(old_hurdle, new_hurdle)

# --- 3. Expected Edge Calculation ---
old_expected = """        expected_edge_long_bps = abs(long_z_score) * spread_std * 10_000 - (self.maker_fee + self.taker_fee) * 10_000
        expected_edge_short_bps = abs(short_z_score) * spread_std * 10_000 - (self.maker_fee + self.taker_fee) * 10_000"""

new_expected = """        expected_edge_long_bps = abs(long_z_score) * spread_std * 10_000 - (self.taker_fee * 2) * 10_000
        expected_edge_short_bps = abs(short_z_score) * spread_std * 10_000 - (self.taker_fee * 2) * 10_000"""

content = content.replace(old_expected, new_expected)

# --- 4. Entry Logic (Beta Bounding + Anchoring Mean) ---
old_entry_logic = """        if not self.is_toxic and variance > 1e-12:
            if long_z_score < -self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_long_bps > dynamic_hurdle_bps:
                    expected_edge_long_dec = expected_edge_long_bps / 10000.0
                    kelly_long = expected_edge_long_dec / variance
                    half_kelly_long = kelly_long / 2.0
                    target_allocation_long = min(half_kelly_long * c_deg, self.kelly_fraction_limit)
                    expected_target_notional = self.portfolio.cash * target_allocation_long
                    
                    if abs(current_net_delta + expected_target_notional) < self.max_net_delta and expected_target_notional > 0:
                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'LONG_SPREAD signaled. Edge: {expected_edge_long_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'LONG_SPREAD', 'z_score': long_z_score, 'target_notional': expected_target_notional})
                elif expected_edge_long_bps > 0:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'LONG_SPREAD ignored. Edge {expected_edge_long_bps:.2f} bps < Hurdle {dynamic_hurdle_bps:.2f} bps'})
            elif short_z_score > self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_short_bps > dynamic_hurdle_bps:
                    expected_edge_short_dec = expected_edge_short_bps / 10000.0
                    kelly_short = expected_edge_short_dec / variance
                    half_kelly_short = kelly_short / 2.0
                    target_allocation_short = min(half_kelly_short * c_deg, self.kelly_fraction_limit)
                    expected_target_notional = self.portfolio.cash * target_allocation_short
                    
                    if abs(current_net_delta - expected_target_notional) < self.max_net_delta and expected_target_notional > 0:
                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'SHORT_SPREAD signaled. Edge: {expected_edge_short_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'SHORT_SPREAD', 'z_score': short_z_score, 'target_notional': expected_target_notional})
                elif expected_edge_short_bps > 0:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'SHORT_SPREAD ignored. Edge {expected_edge_short_bps:.2f} bps < Hurdle {dynamic_hurdle_bps:.2f} bps'})

        # Exit logic
        if abs(z_score) > 4.0:
            self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD', 'z_score': z_score})
        elif abs(z_score) <= self.exit_threshold:
            self.bus.publish('SIGNAL_GENERATED', {'direction': 'CLOSE_SPREAD', 'z_score': z_score})"""

new_entry_logic = """        is_beta_valid = (self.min_beta <= beta <= self.max_beta)

        if not self.is_toxic and variance > 1e-12 and is_beta_valid:
            if long_z_score < -self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_long_bps > dynamic_hurdle_bps:
                    expected_edge_long_dec = expected_edge_long_bps / 10000.0
                    kelly_long = expected_edge_long_dec / variance
                    half_kelly_long = kelly_long / 2.0
                    target_allocation_long = min(half_kelly_long * c_deg, self.kelly_fraction_limit)
                    expected_target_notional = self.portfolio.cash * target_allocation_long
                    
                    if abs(current_net_delta + expected_target_notional) < self.max_net_delta and expected_target_notional > 0:
                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'LONG_SPREAD signaled. Edge: {expected_edge_long_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.anchored_mean = spread_mean
                        self.anchored_std = spread_std
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'LONG_SPREAD', 'z_score': long_z_score, 'target_notional': expected_target_notional})
                elif expected_edge_long_bps > 0:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'LONG_SPREAD ignored. Edge {expected_edge_long_bps:.2f} bps < Hurdle {dynamic_hurdle_bps:.2f} bps'})
            elif short_z_score > self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_short_bps > dynamic_hurdle_bps:
                    expected_edge_short_dec = expected_edge_short_bps / 10000.0
                    kelly_short = expected_edge_short_dec / variance
                    half_kelly_short = kelly_short / 2.0
                    target_allocation_short = min(half_kelly_short * c_deg, self.kelly_fraction_limit)
                    expected_target_notional = self.portfolio.cash * target_allocation_short
                    
                    if abs(current_net_delta - expected_target_notional) < self.max_net_delta and expected_target_notional > 0:
                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'SHORT_SPREAD signaled. Edge: {expected_edge_short_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.anchored_mean = spread_mean
                        self.anchored_std = spread_std
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'SHORT_SPREAD', 'z_score': short_z_score, 'target_notional': expected_target_notional})
                elif expected_edge_short_bps > 0:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'SHORT_SPREAD ignored. Edge {expected_edge_short_bps:.2f} bps < Hurdle {dynamic_hurdle_bps:.2f} bps'})

        # Exit logic
        if self.anchored_mean is not None and self.anchored_std is not None and self.anchored_std > 1e-12:
            eval_z_score = (payload.get('spread', 0.0) - self.anchored_mean) / self.anchored_std
        else:
            eval_z_score = z_score

        if abs(eval_z_score) > 4.0:
            self.anchored_mean = None
            self.anchored_std = None
            self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD', 'z_score': eval_z_score})
        elif abs(eval_z_score) <= self.exit_threshold and self.portfolio.positions.get(self.target, 0.0) != 0.0:
            self.anchored_mean = None
            self.anchored_std = None
            self.bus.publish('SIGNAL_GENERATED', {'direction': 'CLOSE_SPREAD', 'z_score': eval_z_score})"""

content = content.replace(old_entry_logic, new_entry_logic)

with open('public/python/engine.py', 'w') as f:
    f.write(content)
