import re

with open('public/python/engine.py', 'r') as f:
    content = f.read()

# 1. Fix dynamic hurdle math
hurdle_old = """    def _compute_dynamic_hurdle_bps(self) -> float:
        \"\"\"Compute the minimum edge (in bps) required to justify a new position.

        dynamic_hurdle = taker_entry_fee + taker_exit_fee + slippage + funding_drag

        estimated hold time ≈ half_life_seconds (capped at one 8-hour funding period)
        funding_drag ≈ abs(funding_rate) × (hold / (8h)) × 10_000
        \"\"\"
        taker_entry_fee_bps = self.taker_fee * 10_000  # 5 bps
        taker_exit_fee_bps = self.taker_fee * 10_000   # 5 bps"""

hurdle_new = """    def _compute_dynamic_hurdle_bps(self) -> float:
        \"\"\"Compute the minimum edge (in bps) required to justify a new position.

        dynamic_hurdle = taker_entry_fee + taker_exit_fee + slippage + funding_drag

        estimated hold time ≈ half_life_seconds (capped at one 8-hour funding period)
        funding_drag ≈ abs(funding_rate) × (hold / (8h)) × 10_000
        \"\"\"
        # 2 legs per entry (target + feature) and 2 legs per exit
        taker_entry_fee_bps = (self.taker_fee * 2) * 10_000
        taker_exit_fee_bps = (self.taker_fee * 2) * 10_000"""

content = content.replace(hurdle_old, hurdle_new)

# 2. Fix expected edge and kelly fraction input
edge_old = """        dynamic_hurdle_bps = self._compute_dynamic_hurdle_bps()

        expected_edge_long_bps = abs(long_z_score) * spread_std * 10_000 - (self.taker_fee * 2) * 10_000
        expected_edge_short_bps = abs(short_z_score) * spread_std * 10_000 - (self.taker_fee * 2) * 10_000

        # Entry signals (only when edge clears the dynamic hurdle)
        current_net_delta = self.portfolio.get_net_delta(target_ask, feature_bid)
        current_spread_bps = abs(payload.get('spread', 0.0)) * 10000.0
        
        variance = spread_std ** 2
        c_deg = max(0.0, 1.0 - (self.latest_pvalue / self.toxicity_threshold))

        is_beta_valid = (self.min_beta <= beta <= self.max_beta)
        
        target_pos = self.portfolio.positions.get(self.target, 0.0)
        can_enter = (abs(target_pos) < 1e-8) and not self.is_position_open

        if not self.is_toxic and variance > 1e-12 and is_beta_valid and can_enter:
            if long_z_score < -self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_long_bps > dynamic_hurdle_bps:"""

edge_new = """        dynamic_hurdle_bps = self._compute_dynamic_hurdle_bps()

        # Net edge = Gross edge (in bps) - total cost hurdle (in bps)
        expected_edge_long_bps = abs(long_z_score) * spread_std * 10_000 - dynamic_hurdle_bps
        expected_edge_short_bps = abs(short_z_score) * spread_std * 10_000 - dynamic_hurdle_bps

        # Entry signals (only when edge clears the dynamic hurdle)
        current_net_delta = self.portfolio.get_net_delta(target_ask, feature_bid)
        current_spread_bps = abs(payload.get('spread', 0.0)) * 10000.0
        
        variance = spread_std ** 2
        c_deg = max(0.0, 1.0 - (self.latest_pvalue / self.toxicity_threshold))

        is_beta_valid = (self.min_beta <= beta <= self.max_beta)
        
        target_pos = self.portfolio.positions.get(self.target, 0.0)
        can_enter = (abs(target_pos) < 1e-8) and not self.is_position_open

        if not self.is_toxic and variance > 1e-12 and is_beta_valid and can_enter:
            if long_z_score < -self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_long_bps > 0:"""

content = content.replace(edge_old, edge_new)

edge_short_old = """            elif short_z_score > self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_short_bps > dynamic_hurdle_bps:"""

edge_short_new = """            elif short_z_score > self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_short_bps > 0:"""

content = content.replace(edge_short_old, edge_short_new)

# 3. Add taker_fee to _on_update_params
params_old = """    def _on_update_params(self, payload: dict):
        if 'sigma_threshold' in payload:"""

params_new = """    def _on_update_params(self, payload: dict):
        if 'taker_fee' in payload:
            self.taker_fee = float(payload['taker_fee'])
        if 'sigma_threshold' in payload:"""

content = content.replace(params_old, params_new)

with open('public/python/engine.py', 'w') as f:
    f.write(content)

print("engine.py updated")
