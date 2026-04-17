import re

with open('public/python/engine.py', 'r') as f:
    content = f.read()

# --- 1. Phase 1: Correct Cointegration Spread Mathematics ---

# StatArbModel._evaluate
old_eval = """        # ── Look-ahead fix ──────────────────────────────────────────────────
        # Capture the *prior* beta BEFORE updating the Kalman state so that
        # the current tick's spread is computed with yesterday's estimate.
        # This prevents look-ahead bias in Z-score calculations.
        beta_prior = self.bivariate.get_beta()

        dt_ms = timestamp - self.last_ts if self.last_ts > 0 else 1000.0
        if dt_ms <= 0: dt_ms = 1000.0
        self.last_ts = timestamp

        # 1. Update Bivariate Math (Kalman step)
        self.bivariate.append(log_x, log_y, dt_ms)

        # Minimum warmup period
        if self.bivariate.count < min(50, self.w_beta // 4):
            return

        self.is_ready = True
        self.beta = beta_prior  # expose the *prior* beta (causal)

        # 2. Compute current Log-Spread using the prior (lagged) beta
        self.spread = log_y - (beta_prior * log_x)"""

new_eval = """        # ── Look-ahead fix ──────────────────────────────────────────────────
        # Capture the *prior* beta BEFORE updating the Kalman state so that
        # the current tick's spread is computed with yesterday's estimate.
        # This prevents look-ahead bias in Z-score calculations.
        beta_prior = self.bivariate.get_beta()
        alpha_prior = self.bivariate.get_alpha()

        dt_ms = timestamp - self.last_ts if self.last_ts > 0 else 1000.0
        if dt_ms <= 0: dt_ms = 1000.0
        self.last_ts = timestamp

        # 1. Update Bivariate Math (Kalman step)
        self.bivariate.append(log_x, log_y, dt_ms)

        # Minimum warmup period
        if self.bivariate.count < min(50, self.w_beta // 4):
            return

        self.is_ready = True
        self.beta = beta_prior  # expose the *prior* beta (causal)
        self.alpha_val = alpha_prior

        # 2. Compute current Log-Spread using the prior (lagged) beta and alpha
        self.spread = log_y - (beta_prior * log_x) - alpha_prior"""

content = content.replace(old_eval, new_eval)

# StatArbModel bus.publish
old_model_pub = """            'beta': self.beta,
            'spread': self.spread,"""
new_model_pub = """            'beta': self.beta,
            'alpha': self.alpha_val,
            'spread': self.spread,"""
content = content.replace(old_model_pub, new_model_pub)

# StatArbModel reset
old_reset = """        self.is_ready = False
        self.beta = 0.0
        self.spread = 0.0"""
new_reset = """        self.is_ready = False
        self.beta = 0.0
        self.alpha_val = 0.0
        self.spread = 0.0"""
content = content.replace(old_reset, new_reset)

# SignalGenerator._on_model_updated spread val calculation
old_sig_spread = """        beta = payload.get('beta', 1.0)
        spread_mean = payload.get('spread_mean', 0.0)
        spread_std = payload.get('spread_std', 0.0)

        if spread_std > 1e-8 and target_ask > 0 and feature_bid > 0 and target_bid > 0 and feature_ask > 0:
            if beta >= 0:
                long_spread_val = math.log(target_ask) - beta * math.log(feature_bid)
                short_spread_val = math.log(target_bid) - beta * math.log(feature_ask)
            else:
                long_spread_val = math.log(target_ask) - beta * math.log(feature_ask)
                short_spread_val = math.log(target_bid) - beta * math.log(feature_bid)"""

new_sig_spread = """        beta = payload.get('beta', 1.0)
        alpha = payload.get('alpha', 0.0)
        spread_mean = payload.get('spread_mean', 0.0)
        spread_std = payload.get('spread_std', 0.0)

        if spread_std > 1e-8 and target_ask > 0 and feature_bid > 0 and target_bid > 0 and feature_ask > 0:
            if beta >= 0:
                long_spread_val = math.log(target_ask) - beta * math.log(feature_bid) - alpha
                short_spread_val = math.log(target_bid) - beta * math.log(feature_ask) - alpha
            else:
                long_spread_val = math.log(target_ask) - beta * math.log(feature_ask) - alpha
                short_spread_val = math.log(target_bid) - beta * math.log(feature_bid) - alpha"""

content = content.replace(old_sig_spread, new_sig_spread)


# --- 2. Phase 2: Eliminate Z-Score Whipsaw Trap ---

# SignalGenerator init
old_sig_init2 = """        self.min_beta = 0.5
        self.max_beta = 1.5"""
new_sig_init2 = """        self.min_beta = 0.5
        self.max_beta = 1.5
        self.stop_loss_multiplier = 2.0"""
content = content.replace(old_sig_init2, new_sig_init2)

# SignalGenerator exit logic
old_exit = """        if self.anchored_mean is not None and self.anchored_std is not None and self.anchored_std > 1e-12:
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

new_exit = """        if self.anchored_mean is not None and self.anchored_std is not None and self.anchored_std > 1e-12:
            # We are currently in a position. Use the anchored parameters to measure reversion.
            eval_z_score = (payload.get('spread', 0.0) - self.anchored_mean) / self.anchored_std
            
            # Determine direction of our position
            target_pos = self.portfolio.positions.get(self.target, 0.0)
            is_long = target_pos > 0.0
            
            # Reversion conditions:
            # If LONG, we want the spread (and z-score) to increase towards 0.
            # If SHORT, we want the spread (and z-score) to decrease towards 0.
            reverted = False
            if is_long and eval_z_score >= -self.exit_threshold:
                reverted = True
            elif not is_long and eval_z_score <= self.exit_threshold:
                reverted = True
                
            # Emergency Stop Loss
            emergency_threshold = self.entry_threshold * self.stop_loss_multiplier
            stopped_out = False
            if is_long and eval_z_score <= -emergency_threshold:
                stopped_out = True
            elif not is_long and eval_z_score >= emergency_threshold:
                stopped_out = True
                
            if stopped_out:
                self.anchored_mean = None
                self.anchored_std = None
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD', 'z_score': eval_z_score})
            elif reverted:
                self.anchored_mean = None
                self.anchored_std = None
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'CLOSE_SPREAD', 'z_score': eval_z_score})
        else:
            # Not in a position, just tracking
            eval_z_score = z_score"""

content = content.replace(old_exit, new_exit)


# --- 3. Phase 3: Enhance UI / Metrics ---
old_ui = """                'z_score': self.model.z_score,
                'beta': self.model.beta,
                'hedge_ratio': self.model.beta,"""
new_ui = """                'z_score': self.model.z_score,
                'beta': self.model.beta,
                'alpha': getattr(self.model, 'alpha_val', 0.0),
                'hedge_ratio': self.model.beta,"""
content = content.replace(old_ui, new_ui)

with open('public/python/engine.py', 'w') as f:
    f.write(content)

print("Successfully applied Phase 3 enhancements.")
