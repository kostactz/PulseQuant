import re

with open('public/python/engine.py', 'r') as f:
    content = f.read()

old_sig_update = """        if 'max_drawdown_pct' in payload:
            self.max_drawdown_pct = float(payload['max_drawdown_pct'])"""

new_sig_update = """        if 'max_drawdown_pct' in payload:
            self.max_drawdown_pct = float(payload['max_drawdown_pct'])
        if 'min_beta' in payload:
            self.min_beta = float(payload['min_beta'])
        if 'max_beta' in payload:
            self.max_beta = float(payload['max_beta'])"""

content = content.replace(old_sig_update, new_sig_update)

old_stat_init = """        self.bus.subscribe(f'TICK_{self.target}', self._on_target_tick)
        self.bus.subscribe(f'TICK_{self.feature}', self._on_feature_tick)"""

new_stat_init = """        self.bus.subscribe(f'TICK_{self.target}', self._on_target_tick)
        self.bus.subscribe(f'TICK_{self.feature}', self._on_feature_tick)
        self.bus.subscribe('UPDATE_STRATEGY_PARAMS', self._on_update_params)
        
    def _on_update_params(self, payload: dict):
        if 'kalman_delta' in payload:
            self.bivariate.delta = float(payload['kalman_delta'])
        if 'kalman_r_var' in payload:
            self.bivariate.r_var = float(payload['kalman_r_var'])"""

content = content.replace(old_stat_init, new_stat_init)

with open('public/python/engine.py', 'w') as f:
    f.write(content)
print("Updated parameters.")
