import re

with open('public/python/engine.py', 'r') as f:
    content = f.read()

# Fix the elif condition that logs ignored spread
edge_old = """                elif expected_edge_long_bps > 0:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'LONG_SPREAD ignored. Edge {expected_edge_long_bps:.2f} bps < Hurdle {dynamic_hurdle_bps:.2f} bps'})
            elif short_z_score > self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_short_bps > 0:
                    expected_edge_short_dec = expected_edge_short_bps / 10000.0
                    kelly_short = expected_edge_short_dec / variance
                    half_kelly_short = kelly_short / 2.0
                    target_allocation_short = min(half_kelly_short * c_deg, self.kelly_fraction_limit)
                    expected_target_notional = self.portfolio.cash * target_allocation_short
                    
                    if abs(current_net_delta - expected_target_notional) < self.max_net_delta and expected_target_notional > 0:
                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'SHORT_SPREAD signaled. Edge: {expected_edge_short_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.anchored_mean = spread_mean
                        self.anchored_std = spread_std
                        self.is_position_open = True
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'SHORT_SPREAD', 'z_score': short_z_score, 'target_notional': expected_target_notional})
                elif expected_edge_short_bps > 0:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'SHORT_SPREAD ignored. Edge {expected_edge_short_bps:.2f} bps < Hurdle {dynamic_hurdle_bps:.2f} bps'})"""

edge_new = """                else:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'LONG_SPREAD ignored. Edge {expected_edge_long_bps:.2f} bps <= 0 (Hurdle {dynamic_hurdle_bps:.2f} bps)'})
            elif short_z_score > self.entry_threshold and current_spread_bps >= self.min_entry_spread_bps:
                if expected_edge_short_bps > 0:
                    expected_edge_short_dec = expected_edge_short_bps / 10000.0
                    kelly_short = expected_edge_short_dec / variance
                    half_kelly_short = kelly_short / 2.0
                    target_allocation_short = min(half_kelly_short * c_deg, self.kelly_fraction_limit)
                    expected_target_notional = self.portfolio.cash * target_allocation_short
                    
                    if abs(current_net_delta - expected_target_notional) < self.max_net_delta and expected_target_notional > 0:
                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'SHORT_SPREAD signaled. Edge: {expected_edge_short_bps:.2f} bps, Kelly Notional: {expected_target_notional:.2f}'})
                        self.anchored_mean = spread_mean
                        self.anchored_std = spread_std
                        self.is_position_open = True
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'SHORT_SPREAD', 'z_score': short_z_score, 'target_notional': expected_target_notional})
                else:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'SHORT_SPREAD ignored. Edge {expected_edge_short_bps:.2f} bps <= 0 (Hurdle {dynamic_hurdle_bps:.2f} bps)'})"""

content = content.replace(edge_old, edge_new)

with open('public/python/engine.py', 'w') as f:
    f.write(content)

print("engine.py updated 2")
