import numpy as np
import math
import uuid
from collections import deque

# ==========================================
# 1. CORE UTILITIES & RING BUFFERS
# ==========================================
class RingBuffer:
    """Pre-allocated circular buffer for fast O(1) window operations. Includes running sum."""
    def __init__(self, size):
        self.size = size
        self.data = np.zeros(size, dtype=float)
        self.index = 0
        self.count = 0
        self.running_sum = 0.0
        self.running_sum_sq = 0.0
        self.total_appends = 0
        self.anchor = 0.0

    def append(self, value):
        if self.count == 0:
            self.anchor = value # Set anchor on first append
            
        centered_val = value - self.anchor
        
        old_val = self.data[self.index]
        centered_old = old_val - self.anchor if self.count == self.size else 0.0
        
        self.data[self.index] = value
        
        self.running_sum += (centered_val - centered_old)
        self.running_sum_sq += (centered_val**2 - centered_old**2)
        
        self.index = (self.index + 1) % self.size
        self.count = min(self.count + 1, self.size)
        self.total_appends += 1
        
        # Prevent float drift by recalculating sum periodically
        if self.total_appends % 1000 == 0:
            window = self.get_window()
            self.anchor = window[0] # Re-anchor periodically
            centered_window = window - self.anchor
            self.running_sum = np.sum(centered_window)
            self.running_sum_sq = np.sum(centered_window**2)

    def get_window(self):
        if self.count < self.size:
            return self.data[:self.count]
        return np.concatenate((self.data[self.index:], self.data[:self.index]))

    def reset(self):
        self.data.fill(0.0)
        self.index = 0
        self.count = 0
        self.running_sum = 0.0
        self.running_sum_sq = 0.0
        self.total_appends = 0
        self.anchor = 0.0

    def mean(self):
        return (self.running_sum / self.count) + self.anchor if self.count > 0 else 0.0

    def std(self):
        if self.count > 1:
            mean_centered = self.running_sum / self.count
            variance = (self.running_sum_sq / self.count) - (mean_centered**2)
            # max(0, variance) protects against float precision errors resulting in negatives
            return math.sqrt(max(0.0, variance))
        return 0.0

# ==========================================
# 2. STATEFUL INDICATOR ENGINE (O(1) Updates)
# ==========================================
class IndicatorState:
    def __init__(self):
        self.reset(1.0)
        
    def reset(self, speed_multiplier):
        self.w_short = max(2, int(20 * speed_multiplier))
        self.w_med = max(5, int(170 * speed_multiplier))
        self.w_long = max(10, int(50 * speed_multiplier))
        self.w_macro = max(50, int(2000 * speed_multiplier))

        # Buffers for rolling window calculations
        self.bb_buffer = RingBuffer(self.w_med)
        self.macro_buffer = RingBuffer(self.w_macro)
        self.ofi_buffer = RingBuffer(self.w_long)
        self.obi_buffer = RingBuffer(self.w_long)
        
        # Absolute OFI history for dynamic regime calibration (5 mins approx, scaled by speed)
        self.w_abs_ofi = max(300, int(3000 * speed_multiplier))
        self.ofi_abs_buffer = RingBuffer(self.w_abs_ofi)
        
        # Rolling VWAP Buffers
        self.vwap_window = max(100, int(2000 * speed_multiplier))
        self.vwap_pv_buffer = RingBuffer(self.vwap_window)
        self.vwap_v_buffer = RingBuffer(self.vwap_window)

        # VPIN-like volume sweep tracking
        self.vpin_ema = 0.0
        self.vpin_ratio = 0.0
        self.vpin_sweep = False

        # Stateful variables
        self.prev_micro = None
        self.ofi_ema = 0.0
        self.ofi_derivative = 0.0
        self.obi_ema = 0.0
        # Deep OBI configuration
        self.dobi_lambda = 0.02  # exponential decay factor (lambda)
        self.dobi_levels = 10   # how many levels deep to consider
        self.vpin_alpha = 0.5056018116224201
        self.vpin_sweep_threshold = 0.15667675013266968
        self.alpha_vwap_decay = 0.0011576180112907173
        self.bb_std_multiplier = 4.4942490108554605
        self.ofi_clip_bound = 8.725766452653948
        
        # Time-based normalization (Bucket size)
        self.last_update_time = None
        self.update_interval_ms = 25 # Step indicators every 25ms (optimized)
        
        # Latest computed values
        self.latest = {
            'micro_price': 0.0, 'ofi': 0.0, 'ofi_ema': 0.0, 'ofi_deriv': 0.0, 'ofi_norm': 0.0,
            'bb_mid': 0.0, 'bb_upper': 0.0, 'bb_lower': 0.0, 'bb_std': 0.0,
            'vwap': 0.0, 'obi': 0.0, 'obi_raw': 0.0, 'obi_norm': 0.0, 'macro_sma': 0.0, 'prev_macro_sma': 0.0,
            'vpin_ratio': 0.0, 'vpin_ema': 0.0, 'vpin_sweep': False
        }

    def update(self, bid, ask, bid_vol, ask_vol, delta_bid, delta_ask, trade_volume, timestamp, bids=None, asks=None):
        # 1. Micro-Price Calculation (Always updated for UI accuracy)
        # We use a volume-weighted mid price (Micro-Price) rather than a simple average.
        # This gives a better estimate of fair value by reflecting the imbalance in top-of-book liquidity.
        # Compute exponentially-weighted deep volumes if depth is provided
        weighted_bid_vol = 0.0
        weighted_ask_vol = 0.0
        try:
            if bids is not None and asks is not None:
                n_levels = min(len(bids), len(asks), self.dobi_levels)
                for i in range(n_levels):
                    # weight top-of-book highest (i==0 -> weight=1.0)
                    weight = math.exp(-self.dobi_lambda * i)
                    try:
                        bq = float(bids[i][1])
                    except Exception:
                        bq = 0.0
                    try:
                        aq = float(asks[i][1])
                    except Exception:
                        aq = 0.0
                    weighted_bid_vol += bq * weight
                    weighted_ask_vol += aq * weight
        except Exception:
            # Defensive: if depth structure is unexpected, fall back
            weighted_bid_vol = 0.0
            weighted_ask_vol = 0.0

        # Fallback to top-of-book volumes if no depth available
        if (weighted_bid_vol + weighted_ask_vol) < 1e-9:
            weighted_bid_vol = bid_vol
            weighted_ask_vol = ask_vol

        total_vol = weighted_bid_vol + weighted_ask_vol + 1e-9
        # Deep Micro-Price: weighted by exponential depth volumes
        micro_price = (bid * weighted_ask_vol + ask * weighted_bid_vol) / total_vol
        self.latest['micro_price'] = micro_price
        # Expose weighted volumes for debugging/visibility
        self.latest['weighted_bid_vol'] = weighted_bid_vol
        self.latest['weighted_ask_vol'] = weighted_ask_vol

        # 1.b VPIN-style sweep detection
        top3_resting_vol = 0.0
        try:
            if bids is not None and asks is not None:
                top3_bid_vol = sum(float(bids[i][1]) for i in range(min(3, len(bids))))
                top3_ask_vol = sum(float(asks[i][1]) for i in range(min(3, len(asks))))
                top3_resting_vol = top3_bid_vol + top3_ask_vol
        except Exception:
            top3_resting_vol = bid_vol + ask_vol

        self.vpin_ratio = trade_volume / (top3_resting_vol + 1e-9)
        self.vpin_ema = (self.vpin_ratio * self.vpin_alpha) + (self.vpin_ema * (1.0 - self.vpin_alpha))
        self.vpin_sweep = self.vpin_ema > self.vpin_sweep_threshold

        self.latest['vpin_ratio'] = self.vpin_ratio
        self.latest['vpin_ema'] = self.vpin_ema
        self.latest['vpin_sweep'] = self.vpin_sweep

        # 2. Rolling VWAP Update & Time-Decay Fallback
        # VWAP acts as our local mean for mean-reversion signals.
        if trade_volume > 0:
            pv = micro_price * trade_volume
            self.vwap_pv_buffer.append(pv)
            self.vwap_v_buffer.append(trade_volume)
            
            sum_pv = self.vwap_pv_buffer.running_sum + (self.vwap_pv_buffer.anchor * self.vwap_pv_buffer.count)
            sum_v = self.vwap_v_buffer.running_sum + (self.vwap_v_buffer.anchor * self.vwap_v_buffer.count)
            self.latest['vwap'] = sum_pv / (sum_v + 1e-9)
        else:
            # Fallback for zero volume: slowly decay VWAP toward micro_price
            # Drastically reduce alpha. 1e-5 means it takes significant time to drift.
            alpha_vwap = self.alpha_vwap_decay
            if self.latest['vwap'] != 0.0:
                self.latest['vwap'] = (micro_price * alpha_vwap) + (self.latest['vwap'] * (1 - alpha_vwap))

        # Time-based normalization
        if self.last_update_time is None:
            self.last_update_time = timestamp
            
        time_elapsed = timestamp - self.last_update_time
        
        if time_elapsed >= self.update_interval_ms:
            self.last_update_time = timestamp
            
            # 3. Bollinger Bands & Macro Trend
            self.bb_buffer.append(micro_price)
            self.macro_buffer.append(micro_price)
            
            bb_mid = self.bb_buffer.mean()
            bb_std = self.bb_buffer.std()
            self.latest['bb_mid'] = bb_mid
            self.latest['bb_std'] = bb_std
            self.latest['bb_upper'] = bb_mid + (bb_std * self.bb_std_multiplier)
            self.latest['bb_lower'] = bb_mid - (bb_std * self.bb_std_multiplier)
            if self.latest['macro_sma'] != 0.0:
                self.latest['prev_macro_sma'] = self.latest['macro_sma']
            self.latest['macro_sma'] = self.macro_buffer.mean()
            if self.latest['prev_macro_sma'] == 0.0:
                self.latest['prev_macro_sma'] = self.latest['macro_sma']

            # 4. Normalized OFI with Burn-in and Clipping
            raw_ofi = delta_bid - delta_ask
            self.ofi_buffer.append(raw_ofi)
            
            # Minimum samples required before we trust the standard deviation (e.g., half the buffer)
            min_samples = self.w_long // 2 
            
            if self.ofi_buffer.count < min_samples:
                # Burn-in phase: Not enough data for a valid Z-score
                ofi_norm = 0.0
            else:
                ofi_std = self.ofi_buffer.std()
                
                # Prevent division by epsilon in a completely dead/static order book
                if ofi_std < 1e-5:
                    ofi_norm = 0.0
                else:
                    ofi_norm = raw_ofi / ofi_std
                    
                # Outlier Rejection: Clip extreme Z-scores to bounds of [-10, 10]
                ofi_norm = max(-self.ofi_clip_bound, min(self.ofi_clip_bound, ofi_norm))
            
            # Calculate EMA with a slightly higher alpha for the long OFI buffer (make it faster)
            # Dividing w_long by 2 effectively doubles the EMA responsiveness
            alpha_long = 2.0 / ((self.w_long / 2.0) + 1)
            prev_ofi_ema = self.ofi_ema
            self.ofi_ema = (ofi_norm * alpha_long) + (self.ofi_ema * (1 - alpha_long))
            
            self.latest['ofi'] = raw_ofi
            self.latest['ofi_norm'] = ofi_norm
            self.latest['ofi_ema'] = self.ofi_ema
            self.latest['ofi_deriv'] = self.ofi_ema - prev_ofi_ema
            
            # Dynamic Regime Calibration
            self.ofi_abs_buffer.append(abs(self.ofi_ema))
            if self.ofi_abs_buffer.count < (self.w_abs_ofi // 4):
                dynamic_p50 = 0.5
                dynamic_p80 = 0.84
                dynamic_p95 = 1.64
            else:
                abs_mean = self.ofi_abs_buffer.mean()
                abs_std = self.ofi_abs_buffer.std()
                dynamic_p50 = abs_mean
                dynamic_p80 = abs_mean + (0.84 * abs_std)
                dynamic_p95 = abs_mean + (1.64 * abs_std)
            self.latest['ofi_p50'] = dynamic_p50
            self.latest['ofi_p80'] = dynamic_p80
            self.latest['ofi_p95'] = dynamic_p95

            # 5. Order Book Imbalance (OBI) Z-Score Normalization
            # Replace top-of-book OBI with exponentially-weighted Deep OBI (D-OBI)
            total_resting_vol = weighted_bid_vol + weighted_ask_vol + 1e-9
            raw_obi = (weighted_bid_vol - weighted_ask_vol) / total_resting_vol

            self.obi_buffer.append(raw_obi)

            min_samples = self.w_long // 2
            if self.obi_buffer.count < min_samples:
                obi_norm = 0.0
            else:
                obi_mean = self.obi_buffer.mean()
                obi_std = self.obi_buffer.std()

                if obi_std < 1e-5:
                    obi_norm = 0.0
                else:
                    obi_norm = (raw_obi - obi_mean) / obi_std

                obi_norm = max(-10.0, min(10.0, obi_norm))

            # Deep OBI EMA smoothing to avoid brittle z-score drift and false positives
            alpha_obi = 2.0 / ((self.w_long / 2.0) + 1.0)
            self.obi_ema = (raw_obi * alpha_obi) + (self.obi_ema * (1.0 - alpha_obi))

            self.latest['obi_raw'] = raw_obi
            self.latest['obi_norm'] = obi_norm
            self.latest['obi'] = obi_norm
            self.latest['obi_ema'] = self.obi_ema
            
            self.latest['prev_micro'] = self.prev_micro if self.prev_micro is not None else micro_price
            self.prev_micro = micro_price
            
        return self.latest

# ==========================================
# 3. TRADING LOGIC & STRATEGY
# ==========================================
class TradingStrategy:
    def __init__(self):
        self.style = 'moderate'
        self.speed = 'fast'
        self.cooldown_end_time = 0
        # Risk configuration (tunable)
        # Minimum hard stop (default 15 bps) to survive spread/microstructure noise
        self.stop_min = 0.000696
        # Cap for dynamic stop distance (default 50 bps)
        self.stop_cap = 0.472905
        # Flow-invalidation thresholds (OFI / OBI)
        self.flow_ofi_threshold = 3.499
        self.flow_obi_threshold = 1.201642774178217
        # Enable/disable flow invalidation exits
        self.enable_flow_invalidation = True
        # Set asymmetric entry/exit thresholds to reduce immediate microstructure whipsaw
        self.flow_ofi_threshold = 3.499   # use optimized OFI reversal default
        self.flow_obi_threshold = 1.201642774178217   # tuned OBI reversal threshold for flow invalidation
        self.obi_toxicity_threshold = 1.7118  # absolute raw imbalance threshold vs normalized z-score
        self.min_rest_ms = 450.0           # require >=0.45s order resting before toxicity cancellation

        # Inventory-based market making (Avellaneda-Stoikov style)
        self.max_inventory = 11.211088539847164
        self.inventory_skew_factor = 2.5  # weight applied to spread adjustment

        # Toxicity gate relaxation for resting maker orders
        self.toxicity_resting_multiplier = 0.9619
        self.toxicity_resting_obi_multiplier = 1.269087505715421

        # VPIN-like sweep detection
        self.vpin_threshold = 0.35
        self.vpin_alpha = 0.5056018116224201
        self.vpin_sweep_threshold = 0.15667675013266968
        
        # Dynamic Shifts
        self.buy_deriv_shift_cap = 0.3310338385352486
        self.sell_deriv_shift_cap = 0.4944179766147796
        self.buy_deriv_pressure_multiplier = 0.23789185654197345
        self.sell_deriv_pressure_multiplier = 1.4029709022807553
        self.whipsaw_time_buffer_ms = 6271.55438884266

    def set_params(self, style, speed):
        self.style = style
        self.speed = speed

    def get_speed_multiplier(self):
        if self.speed == 'fast': return 0.5
        if self.speed == 'slow': return 2.0
        return 1.0

    def compute_toxicity_state(self, ind):
        ofi_ema = ind.get('ofi_ema', 0.0)
        ofi_deriv = ind.get('ofi_deriv', 0.0)
        # Explicitly obtain both raw and normalized OBI to avoid unit confusion.
        # 'obi_raw' is the imbalance percentage in [-1.0, 1.0].
        # 'obi_norm' is the Z-score normalized version. Keep 'obi' mapped
        # to the normalized value for backward compatibility.
        obi_raw = ind.get('obi_raw', ind.get('obi', 0.0))
        obi_norm = ind.get('obi_norm', ind.get('obi', 0.0))
        obi_ema = ind.get('obi_ema', obi_raw)
        obi = obi_norm
        dynamic_p80 = ind.get('ofi_p80', 0.84)
        dynamic_p95 = ind.get('ofi_p95', 0.95)

        base_buy_ofi_cancel = -dynamic_p80
        base_sell_ofi_cancel = dynamic_p80

        resting_buy_ofi_cancel = -dynamic_p80 * self.toxicity_resting_multiplier
        resting_sell_ofi_cancel = dynamic_p80 * self.toxicity_resting_multiplier
        resting_obi_toxicity = self.obi_toxicity_threshold * self.toxicity_resting_obi_multiplier

        buy_deriv_pressure = max(0.0, -ofi_deriv)
        sell_deriv_pressure = max(0.0, ofi_deriv)

        buy_deriv_shift = min(self.buy_deriv_shift_cap, buy_deriv_pressure * self.buy_deriv_pressure_multiplier)
        sell_deriv_shift = min(self.sell_deriv_shift_cap, sell_deriv_pressure * self.sell_deriv_pressure_multiplier)

        buy_ofi_cancel_level = base_buy_ofi_cancel + buy_deriv_shift
        sell_ofi_cancel_level = base_sell_ofi_cancel - sell_deriv_shift

        # Use raw OBI / EMA of raw OBI for toxicity gating rather than brittle Z-score.
        # Cancel a BUY if the imbalance is strongly ask-heavy, or if smoothed OBI backs it up.
        # Cancel a SELL if imbalance is strongly bid-heavy, or if smoothed OBI backs it up.
        cancel_buy = (
            (ofi_ema < buy_ofi_cancel_level) or
            (obi_raw < -self.obi_toxicity_threshold) or
            (obi_ema < -self.obi_toxicity_threshold)
        )
        cancel_sell = (
            (ofi_ema > sell_ofi_cancel_level) or
            (obi_raw > self.obi_toxicity_threshold) or
            (obi_ema > self.obi_toxicity_threshold)
        )

        vpin_sweep = bool(ind.get('vpin_sweep', False))

        return {
            'buy_ofi_cancel_level': float(buy_ofi_cancel_level),
            'sell_ofi_cancel_level': float(sell_ofi_cancel_level),
            'buy_ofi_cancel_level_resting': float(resting_buy_ofi_cancel),
            'sell_ofi_cancel_level_resting': float(resting_sell_ofi_cancel),
            'obi_toxicity_threshold_resting': float(resting_obi_toxicity),
            'cancel_buy_maker': bool(cancel_buy),
            'cancel_sell_maker': bool(cancel_sell),
            'ofi_ema': float(ofi_ema),
            'ofi_deriv': float(ofi_deriv),
            'obi_raw': float(obi_raw),
            'obi_ema': float(obi_ema),
            'obi_norm': float(obi_norm),
            'obi_toxicity_threshold': float(self.obi_toxicity_threshold),
            'vpin_ratio': float(ind.get('vpin_ratio', 0.0)),
            'vpin_ema': float(ind.get('vpin_ema', 0.0)),
            'vpin_sweep': vpin_sweep,
            # Keep legacy key 'obi' mapped to the normalized z-score
            'obi': float(obi)
        }

    def generate_signal(self, ind, portfolio, current_time):
        toxicity_state = self.compute_toxicity_state(ind)

        # Prevent any trading until the macro buffer is fully populated
        if ind['macro_sma'] == 0.0:
            return 0, 0, 'maker', toxicity_state, 'Macro buffer not populated'
            
        # Time-based Hysteresis: check cooldown end time
        if current_time < self.cooldown_end_time:
            return 0, 0, 'maker', toxicity_state, 'Cooldown active'

        if ind['micro_price'] == 0:
            return 0, 0, 'maker', toxicity_state, 'Micro price is zero'

        current_pos = portfolio.position
        avg_entry = portfolio.avg_entry_price

        # Using dynamic regime thresholds
        dynamic_p50 = ind.get('ofi_p50', 0.5)
        dynamic_p80 = ind.get('ofi_p80', 0.84)
        dynamic_p95 = ind.get('ofi_p95', 1.64)

        if self.style == 'aggressive':
            base_bps = 250
            cooldown_period_ms = 1000 # 1 second cooldown
            taker_thresh = dynamic_p80
        elif self.style == 'conservative':
            base_bps = 50
            cooldown_period_ms = 5000 # 5 seconds cooldown
            taker_thresh = dynamic_p95
        else: # moderate
            base_bps = 100
            cooldown_period_ms = 2500 # 2.5 seconds cooldown
            taker_thresh = dynamic_p80

        macro_bullish = ind['micro_price'] > ind['macro_sma']
        macro_bearish = ind['micro_price'] < ind['macro_sma']
        
        prev_micro = ind.get('prev_micro', ind['micro_price'])
        prev_macro_sma = ind.get('prev_macro_sma', ind['macro_sma'])
        
        just_crossed_bullish = (prev_micro <= prev_macro_sma) and (ind['micro_price'] > ind['macro_sma'])
        just_crossed_bearish = (prev_micro >= prev_macro_sma) and (ind['micro_price'] < ind['macro_sma'])
        
        # Calculate macro slope instead of static price threshold
        macro_slope_positive = ind['macro_sma'] >= ind.get('prev_macro_sma', ind['macro_sma'])
        macro_slope_negative = ind['macro_sma'] <= ind.get('prev_macro_sma', ind['macro_sma'])
        
        vwap_discount = ind['micro_price'] < ind['vwap'] if ind['vwap'] > 0 else False
        vwap_premium = ind['micro_price'] > ind['vwap'] if ind['vwap'] > 0 else False

        # Inventory-skew: positive means long, negative means short.
        inventory_frac = 0.0
        if self.max_inventory > 0:
            inventory_frac = max(-1.0, min(1.0, current_pos / self.max_inventory))
        inventory_skew = abs(inventory_frac) * self.inventory_skew_factor

        buy_signal, sell_signal = False, False
        order_type = 'maker'
        signal_reason = ''

        # Signal 1: Passive Absorption (Maker), but disable when strong VPIN sweep
        vpin_sweep = bool(ind.get('vpin_sweep', False))

        if not vpin_sweep:
            # Buy Condition: Mild negative OFI, strong positive resting liquidity, and price discount
            if (-dynamic_p50 < ind['ofi_ema'] < 0) and (ind['obi_norm'] > 0.84) and vwap_discount:
                buy_signal = True
                signal_reason = "Passive Absorption: Mild negative OFI, strong positive OBI, VWAP discount"
            # Trend Continuation (Buying minor dips in a strong macro trend)
            elif macro_slope_positive and vwap_discount and (0 < ind['ofi_ema'] < dynamic_p50):
                buy_signal = True
                signal_reason = "Trend Continuation: Buying minor dips in a strong macro trend"

            # Sell Condition: Mild positive OFI, strong negative resting liquidity, and price premium
            if (0 < ind['ofi_ema'] < dynamic_p50) and (ind['obi_norm'] < -0.84) and vwap_premium:
                sell_signal = True
                signal_reason = "Passive Absorption: Mild positive OFI, strong negative OBI, VWAP premium"
            # Trend Continuation (Selling minor rips in a strong downtrend)
            elif macro_slope_negative and vwap_premium and (-dynamic_p50 < ind['ofi_ema'] < 0):
                sell_signal = True
                signal_reason = "Trend Continuation: Selling minor rips in a strong downtrend"
        else:
            # When VPIN sweep is detected, do not attempt passive absorption.
            signal_reason = "VPIN sweep active; pausing passive signals"

        # Signal 2: Early Momentum Breakout (Taker)
        if ind['ofi_ema'] > taker_thresh and just_crossed_bullish:
            buy_signal = True
            order_type = 'taker'
            signal_reason = "Momentum Breakout: Strong OFI + macro bullish cross"
        elif ind['ofi_ema'] < -taker_thresh and just_crossed_bearish:
            sell_signal = True
            order_type = 'taker'
            signal_reason = "Momentum Breakout: Strong negative OFI + macro bearish cross"

        # Signal 3: Exhaustion Fade / Mean Reversion (Taker)
        elif macro_bullish and ind['micro_price'] > ind.get('bb_upper', float('inf')) and ind.get('ofi_deriv', 0.0) < 0:
            sell_signal = True
            order_type = 'taker'
            signal_reason = "Exhaustion Fade: Macro bullish but price above BB upper and OFI momentum fading"
        elif macro_bearish and ind['micro_price'] < ind.get('bb_lower', 0.0) and ind.get('ofi_deriv', 0.0) > 0:
            buy_signal = True
            order_type = 'maker'
            signal_reason = "Exhaustion Fade: Macro bearish but price below BB lower and OFI momentum recovering"

        # Risk Management (Dynamic Volatility-Adjusted Stops & Take Profit)
        close_long, close_short = False, False

        # Chaser stop targets based on micro_price and Bollinger volatility
        current_price_ref = ind['micro_price']
        soft_stop_dist = min(self.stop_cap * 0.8, (ind.get('bb_std', 0.0) / current_price_ref) * 1.0)
        hard_stop_dist = max(self.stop_min, (ind.get('bb_std', 0.0) / current_price_ref) * 1.5)

        # Inventory-skewed stop sensitivity: increase stop tightness with position size
        inventory_safety_margin = abs(inventory_frac) * self.inventory_skew_factor
        soft_stop_dist *= (1.0 + inventory_safety_margin)
        hard_stop_dist *= (1.0 + inventory_safety_margin)

        soft_stop_long = (avg_entry > 0) and (current_price_ref < avg_entry * (1 - soft_stop_dist))
        hard_stop_long = (avg_entry > 0) and (current_price_ref < avg_entry * (1 - hard_stop_dist))
        soft_stop_short = (avg_entry > 0) and (current_price_ref > avg_entry * (1 + soft_stop_dist))
        hard_stop_short = (avg_entry > 0) and (current_price_ref > avg_entry * (1 + hard_stop_dist))

        # Whipsaw buffer: force minimal time in the trade and require profit to allow flow invalidation
        time_in_trade = 0.0
        in_profit_long = False
        in_profit_short = False

        if current_pos != 0 and getattr(portfolio, 'open_lots', None):
            first_timestamp = float(portfolio.open_lots[0].get('timestamp', current_time))
            time_in_trade = max(0.0, current_time - first_timestamp)

        if current_pos > 0 and avg_entry > 0:
            in_profit_long = ind['micro_price'] > avg_entry
        if current_pos < 0 and avg_entry > 0:
            in_profit_short = ind['micro_price'] < avg_entry

        allow_flow_exit = (time_in_trade > self.whipsaw_time_buffer_ms) or in_profit_long or in_profit_short

        # Flow invalidation: exit on order-flow reversion (OFI) + resting liquidity shift (OBI)
        flow_ofi_threshold = ind.get('ofi_p95', self.flow_ofi_threshold)
        flow_invalidated_long = (self.enable_flow_invalidation and allow_flow_exit and
                                 ind.get('ofi_ema', 0.0) < -flow_ofi_threshold and
                                 ind.get('obi_norm', 0.0) < -self.flow_obi_threshold)
        flow_invalidated_short = (self.enable_flow_invalidation and allow_flow_exit and
                                  ind.get('ofi_ema', 0.0) > flow_ofi_threshold and
                                  ind.get('obi_norm', 0.0) > self.flow_obi_threshold)

        price_stop_long = hard_stop_long
        price_stop_short = hard_stop_short

        if current_pos > 0:
            if hard_stop_long:
                close_long, buy_signal, order_type = True, False, 'taker'
                signal_reason = "Hard Stop: Long exit"
            elif flow_invalidated_long or soft_stop_long:
                close_long, buy_signal, order_type = True, False, 'maker'
                signal_reason = "Maker exit: long soft stop / flow invalidation"
        elif current_pos < 0:
            if hard_stop_short:
                close_short, sell_signal, order_type = True, False, 'taker'
                signal_reason = "Hard Stop: Short exit"
            elif flow_invalidated_short or soft_stop_short:
                close_short, sell_signal, order_type = True, False, 'maker'
                signal_reason = "Maker exit: short soft stop / flow invalidation"
            
        # Execute Routing
        dynamic_bps = base_bps # Kept standard for reliable sizing
        
        signal, bps, o_type = 0, 0, 'maker'
        executed = False

        if close_long: 
            executed, signal, bps, o_type = True, -1, 0, order_type
        elif close_short: 
            executed, signal, bps, o_type = True, 1, 0, order_type
        elif sell_signal and current_pos >= 0: 
            executed, signal, bps, o_type = True, -1, dynamic_bps, order_type
        elif buy_signal and current_pos <= 0: 
            executed, signal, bps, o_type = True, 1, dynamic_bps, order_type

        # Lock out the engine if a trade was authorized
        if executed:
            self.cooldown_end_time = current_time + cooldown_period_ms

        # Surface risk diagnostics for observability
        try:
            toxicity_state['soft_stop_dist'] = float(soft_stop_dist)
            toxicity_state['hard_stop_dist'] = float(hard_stop_dist)
            toxicity_state['hard_stop'] = float(hard_stop_dist)  # backward compatibility
            toxicity_state['soft_stop_long'] = bool(soft_stop_long)
            toxicity_state['hard_stop_long'] = bool(hard_stop_long)
            toxicity_state['soft_stop_short'] = bool(soft_stop_short)
            toxicity_state['hard_stop_short'] = bool(hard_stop_short)
            toxicity_state['flow_invalidated_long'] = bool(flow_invalidated_long)
            toxicity_state['flow_invalidated_short'] = bool(flow_invalidated_short)
            toxicity_state['allow_flow_exit'] = bool(allow_flow_exit)
            toxicity_state['time_in_trade'] = float(time_in_trade)
            toxicity_state['in_profit_long'] = bool(in_profit_long)
            toxicity_state['in_profit_short'] = bool(in_profit_short)
            toxicity_state['flow_ofi_threshold'] = float(flow_ofi_threshold)
            toxicity_state['flow_obi_threshold'] = float(self.flow_obi_threshold)
            toxicity_state['inventory_fraction'] = float(inventory_frac)
            toxicity_state['inventory_skew'] = float(inventory_skew)
            toxicity_state['vpin_sweep'] = bool(vpin_sweep)

            close_reason = None
            if close_long or close_short:
                if flow_invalidated_long or flow_invalidated_short:
                    close_reason = 'flow_invalidation'
                elif hard_stop_long or hard_stop_short:
                    close_reason = 'hard_stop'
                elif soft_stop_long or soft_stop_short:
                    close_reason = 'soft_stop'

            toxicity_state['close_reason'] = close_reason
        except Exception:
            # Defensive: ensure we don't raise during signal generation
            pass

        return signal, bps, o_type, toxicity_state, signal_reason

# ==========================================
# 4. PORTFOLIO & EXECUTION
# ==========================================
class Portfolio:
    def __init__(self, initial_capital=100000.0):
        self.initial_capital = initial_capital
        self.reset()

    def execute_trade(self, side, qty, price, timestamp, order_type='taker', indicators=None, reason='', client_order_id=None):
        # Fees: taker pays 0.05%, maker pays 0.02% 
        fee_rate = 0.0004 if order_type == 'taker' else -0.0001
        fee = price * qty * fee_rate
        old_pos = self.position

        # Update O(1) executed qty
        self.total_executed_qty += qty
        if order_type == 'maker':
            self.maker_executed_qty += qty
            self.maker_trade_count += 1

        # Track realized PnL with FIFO matching
        remaining_qty = qty
        
        # Are we reducing/closing an existing position?
        if (side == 'sell' and old_pos > 0) or (side == 'buy' and old_pos < 0):
            total_chunk_pnl = 0.0
            total_matched_qty = 0.0
            weighted_duration = 0.0

            while remaining_qty > 0 and self.open_lots:
                lot = self.open_lots[0]
                matched_qty = min(remaining_qty, lot['qty'])
                
                # Calculate PnL for this chunk
                if side == 'sell': # Closing long
                    realized_pnl = matched_qty * (price - lot['price'])
                else: # Closing short
                    realized_pnl = matched_qty * (lot['price'] - price)
                    
                # Subtract proportional fee of the exit trade for this chunk
                chunk_exit_fee = price * matched_qty * fee_rate
                realized_pnl -= chunk_exit_fee
                
                entry_fee_chunk = lot['fee'] * (matched_qty / lot['qty'])
                realized_pnl -= entry_fee_chunk

                # Duration
                duration = timestamp - lot['timestamp']
                
                total_chunk_pnl += realized_pnl
                total_matched_qty += matched_qty
                weighted_duration += duration * matched_qty
                
                remaining_qty -= matched_qty
                lot['qty'] -= matched_qty
                lot['fee'] -= entry_fee_chunk # reduce remaining fee
                
                if lot['qty'] <= 1e-9: # avoid float issues
                    self.open_lots.popleft()

            if total_matched_qty > 0:
                avg_duration = weighted_duration / total_matched_qty
                
                self.closed_trades.append({
                    'timestamp': timestamp,
                    'qty': total_matched_qty,
                    'pnl': total_chunk_pnl,
                    'duration': avg_duration
                })
                
                # Update O(1) analytics
                if total_chunk_pnl > 0:
                    self.gross_profits += total_chunk_pnl
                    self.winning_trades_count += 1
                elif total_chunk_pnl < 0:
                    self.gross_losses += abs(total_chunk_pnl)
                    # Losses implicitly tracked by total_closed - winning - scratch (if we cared, but we'll infer it)
                
                self.total_holding_time += avg_duration

        # If there's still quantity left, it means we are opening a new position or adding to the opposite side
        if remaining_qty > 0:
            new_lot = {
                'side': side,
                'qty': remaining_qty,
                'price': price,
                'timestamp': timestamp,
                'fee': fee * (remaining_qty / qty)
            }
            self.open_lots.append(new_lot)

        if side == 'buy':
            self.capital -= (price * qty) + fee
            self.position += qty
        elif side == 'sell':
            self.capital += (price * qty) - fee
            self.position -= qty
            
        # Update avg_entry_price for legacy compatibility if needed by strategy
        if self.position == 0:
            self.avg_entry_price = 0.0
        elif len(self.open_lots) > 0:
            total_value = sum(l['qty'] * l['price'] for l in self.open_lots)
            total_qty = sum(l['qty'] for l in self.open_lots)
            self.avg_entry_price = total_value / total_qty
            
        self.last_trade_price = price
        
        found = False
        if client_order_id:
            for t in reversed(self.ui_recent_trades):
                if t.get('client_order_id') == client_order_id:
                    old_qty = t['qty']
                    old_price = t['price']
                    new_qty = old_qty + float(qty)
                    if new_qty > 0:
                        t['price'] = ((old_price * old_qty) + (price * float(qty))) / new_qty
                    t['qty'] = round(new_qty, 6)
                    t['timestamp'] = timestamp
                    found = True
                    break
                    
        if not found:
            trade_obj = {
                'timestamp': timestamp, 
                'side': side, 
                'price': price, 
                'qty': round(float(qty), 6), 
                'type': order_type,
                'indicators': indicators.copy() if indicators else {},
                'reason': reason,
                'client_order_id': client_order_id
            }
            self.trades.append(trade_obj)
            self.ui_recent_trades.append(trade_obj)
        
        # Calculate these on the fly for the log
        analytics = self.get_trade_analytics()
        current_port_value = self.capital + (self.position * price)
        current_eq = session.peak_equity if hasattr(session, 'peak_equity') else self.initial_capital
        current_dd_pct = (current_eq - current_port_value) / current_eq if current_port_value < current_eq else 0.0

        session.logs.append({
            'level': 'TRADE',
            'data': {
                'side': side,
                'price': price,
                'qty': round(float(qty), 6),
                'order_type': order_type,
                'reason': reason,
                'indicators': indicators.copy() if indicators else {},
                'metrics': {
                    'hit_ratio': analytics['hit_ratio'],
                    'profit_factor': analytics['profit_factor'],
                    'maker_fill_rate': analytics['maker_fill_rate'],
                    'avg_holding_time': analytics['avg_holding_time'],
                    'drawdown_pct': current_dd_pct
                }
            }
        })

    def get_metrics(self, current_price):
        return self.capital + (self.position * current_price)

    def get_trade_analytics(self):
        maker_fill_rate = (self.maker_executed_qty / self.total_executed_qty) if self.total_executed_qty > 0 else 0.0

        total_closed = len(self.closed_trades)
        if total_closed == 0:
            return {
                "hit_ratio": 0.0, 
                "win_loss_ratio": 0.0,
                "reward_risk_ratio": 0.0,
                "profit_factor": 0.0, 
                "total_trades": 0,
                "avg_holding_time": 0.0,
                "maker_fill_rate": maker_fill_rate
            }

        # Count actual losses where PNL < 0 (excluding exact zeroes/scratches)
        losers_count = sum(1 for t in self.closed_trades if t['pnl'] < 0)
        
        # Hit ratio considers all closed trades, but you could optionally exclude scratches
        hit_ratio = self.winning_trades_count / total_closed if total_closed > 0 else 0.0
        
        avg_win = (self.gross_profits / self.winning_trades_count) if self.winning_trades_count > 0 else 0.0
        avg_loss = (self.gross_losses / losers_count) if losers_count > 0 else 0.0

        # Win/Loss Ratio as count ratio
        win_loss_ratio = (self.winning_trades_count / losers_count) if losers_count > 0 else float(self.winning_trades_count)
        
        # Reward/Risk Ratio (Average Win / Average Loss)
        reward_risk_ratio = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else 0.0)
        
        profit_factor = (self.gross_profits / self.gross_losses) if self.gross_losses > 0 else (self.gross_profits if self.gross_profits > 0 else 0.0)

        avg_holding_time = self.total_holding_time / total_closed

        return {
            "hit_ratio": float(hit_ratio),
            "win_loss_ratio": float(win_loss_ratio),
            "reward_risk_ratio": float(reward_risk_ratio),
            "profit_factor": float(profit_factor),
            "total_trades": total_closed,
            "avg_holding_time": float(avg_holding_time),
            "maker_fill_rate": float(maker_fill_rate)
        }

    def reset(self):
        self.capital = self.initial_capital
        self.position = 0
        self.trades = []
        self.closed_trades = []
        self.open_lots = deque()
        self.avg_entry_price = 0.0
        self.last_trade_price = 0.0
        self.ui_recent_trades = deque()
        
        # O(1) analytics state
        self.total_executed_qty = 0.0
        self.maker_executed_qty = 0.0
        self.maker_trade_count = 0
        self.gross_profits = 0.0
        self.gross_losses = 0.0
        self.winning_trades_count = 0
        self.total_holding_time = 0.0

# ==========================================
# 5. MAIN SESSION & COMPATIBILITY API
# ==========================================
class TradingSession:
    def __init__(self):
        self.portfolio = Portfolio()
        self.strategy = TradingStrategy()
        self.indicators = IndicatorState()
        
        self.auto_trade = False
        self.trade_size_bps = 185
        self.logs = []
        
        # Keep up to 12 hours of UI/RingBuffer history (supports ~10Hz tick rate = 432,000 samples)
        self.ui_history_window = 12 * 60 * 60 * 10  # 12 hours
        self.ui_timestamps = RingBuffer(self.ui_history_window)
        self.ui_mid_prices = RingBuffer(self.ui_history_window)
        self.ui_ofi = RingBuffer(self.ui_history_window)
        self.ui_ofi_ema = RingBuffer(self.ui_history_window)
        self.ui_macro_sma = RingBuffer(self.ui_history_window)
        self.ui_vwap = RingBuffer(self.ui_history_window)
        self.ui_bb_mid = RingBuffer(self.ui_history_window)
        self.ui_bb_upper = RingBuffer(self.ui_history_window)
        self.ui_bb_lower = RingBuffer(self.ui_history_window)
        self.ui_obi = RingBuffer(self.ui_history_window)
        self.ui_obi_raw = RingBuffer(self.ui_history_window)
        self.ui_obi_norm = RingBuffer(self.ui_history_window)
        
        self.last_ui_timestamp = 0.0
        self.last_ui_ask = 0.0
        self.last_ui_bid = 0.0
        
        self.value_hist = deque(maxlen=75000)
        
        self.tick_counter = 0
        self.pending_orders = {}
        self.outbound_queue = []
        self.canceled_orders = deque(maxlen=5000)
        self.canceled_orders_total = 0
        self.last_toxicity_state = {
            'buy_ofi_cancel_level': -0.5,
            'sell_ofi_cancel_level': 0.5,
            'cancel_buy_maker': False,
            'cancel_sell_maker': False,
            'ofi_ema': 0.0,
            'ofi_deriv': 0.0,
            'obi': 0.0,
            'obi_raw': 0.0,
            'obi_norm': 0.0
        }

        self.peak_equity = self.portfolio.initial_capital
        self.current_drawdown_start: float | None = None
        self.max_dd_pct = 0.0
        self.max_dd_duration = 0.0
        self.last_ui_sync_count = 0

        # Post-only quoting and tick size for chaser orders
        self.tick_size = 0.05327427600863069
        self.post_only_mode = True
        self.min_chaser_distance = self.tick_size * 1.3332895115365753

session = TradingSession()

def set_trade_size(bps):
    session.trade_size_bps = bps
    return True

def execute_trade(side, bps=None, order_type='taker', reason='Manual user trade'):
    if session.ui_timestamps.count == 0: return False
    
    actual_bps = bps if bps is not None else session.trade_size_bps
    
    price_ref = session.last_ui_ask if side == 'buy' else session.last_ui_bid
    portfolio_value = session.portfolio.get_metrics(price_ref)
    
    if actual_bps == 0:
        qty = abs(session.portfolio.position)
    else:
        qty = (portfolio_value * (actual_bps / 10000.0)) / price_ref
        
    if qty <= 0: return False
    
    ind_snapshot = session.indicators.latest.copy() if hasattr(session.indicators, 'latest') else {}
    
    # Route the order through the outbound queue instead of immediately faking a portfolio update
    row_mock = {'ask': session.last_ui_ask, 'bid': session.last_ui_bid}
    route_order(side, qty, order_type, row_mock, ind_snapshot, session.last_ui_timestamp, signal_reason=reason)
    
    session.strategy.cooldown_end_time = session.last_ui_timestamp + 2500 
    return True

def set_auto_trade(enabled):
    session.auto_trade = enabled
    return session.auto_trade

def update_strategy(style, speed):
    session.strategy.set_params(style, speed)
    session.indicators.reset(session.strategy.get_speed_multiplier())
    return True

def handle_tick(row, ts):
    ind = session.indicators.update(
        row['bid'], row['ask'], row['bid_vol'], row['ask_vol'],
        row['delta_bid'], row['delta_ask'], row.get('trade_volume', 0.0),
        ts,
        row.get('depth', {}).get('bids')[:10] if row.get('depth') else None,
        row.get('depth', {}).get('asks')[:10] if row.get('depth') else None 
    )

    toxicity_state = session.strategy.compute_toxicity_state(ind)
    session.last_toxicity_state = toxicity_state.copy()

    # 1. Cancel stale maker orders due to toxicity
    # We iterate over pending_orders dictionary
    for order_id, order in list(session.pending_orders.items()):
        if order.get('status') != 'NEW' and order.get('status') != 'PARTIALLY_FILLED':
            continue # Skip if not active on exchange
            
        should_cancel = False
        cancel_reason = None
        trigger_detail = {}

        submitted_at = float(order.get('submitted_at', ts))
        resting_ms = ts - submitted_at
        is_violent_sweep = abs(toxicity_state.get('ofi_deriv', 0.0)) > 2.0

        can_apply_toxicity = (resting_ms >= session.strategy.min_rest_ms) or is_violent_sweep

        if can_apply_toxicity:
            obi_norm_val = toxicity_state.get('obi_norm', toxicity_state.get('obi', 0.0))
            if order['side'] == 'buy':
                if resting_ms >= session.strategy.min_rest_ms:
                    ofi_gate = toxicity_state['ofi_ema'] < toxicity_state.get('buy_ofi_cancel_level_resting', toxicity_state['buy_ofi_cancel_level'])
                    obi_gate = obi_norm_val < -toxicity_state.get('obi_toxicity_threshold_resting', toxicity_state['obi_toxicity_threshold'])
                else:
                    ofi_gate = toxicity_state['cancel_buy_maker']
                    obi_gate = False

                if ofi_gate or obi_gate:
                    should_cancel = True
                    cancel_reason = 'buy_toxicity_gate'
            elif order['side'] == 'sell':
                if resting_ms >= session.strategy.min_rest_ms:
                    ofi_gate = toxicity_state['ofi_ema'] > toxicity_state.get('sell_ofi_cancel_level_resting', toxicity_state['sell_ofi_cancel_level'])
                    obi_gate = obi_norm_val > toxicity_state.get('obi_toxicity_threshold_resting', toxicity_state['obi_toxicity_threshold'])
                else:
                    ofi_gate = toxicity_state['cancel_sell_maker']
                    obi_gate = False

                if ofi_gate or obi_gate:
                    should_cancel = True
                    cancel_reason = 'sell_toxicity_gate'
        
        if should_cancel:
            order['status'] = 'PENDING_CANCEL'
            session.outbound_queue.append({
                'action': 'CANCEL_ORDER',
                'clientOrderId': order_id,
                'symbol': 'btcusdt',
                'reason': cancel_reason
            })
            continue

    # Chaser update: reprice pending maker exit orders if price moved significantly
    for order_id, order in list(session.pending_orders.items()):
        if order.get('status') not in ('NEW', 'PARTIALLY_FILLED'):
            continue
        if order.get('type', 'maker') == 'maker' and order.get('chaser'):
            tick = session.tick_size
            # Increased reprice threshold for high latency live trading
            reprice_threshold = tick * 10 
            if order['side'] == 'buy':
                target_price = min(row['bid'] + tick, row['ask'] - tick)
            else:
                target_price = max(row['ask'] - tick, row['bid'] + tick)

            if abs(order['price'] - target_price) > reprice_threshold:
                # Cancel and replace
                order['status'] = 'PENDING_CANCEL'
                session.outbound_queue.append({
                    'action': 'CANCEL_ORDER',
                    'clientOrderId': order_id,
                    'symbol': 'btcusdt',
                    'reason': 'chaser_reprice'
                })
                # Note: We don't immediately PLACE. A new order will be routed if needed by signal gen.
                # Or we could emit a MODIFY_ORDER. For simplicity, let the strategy re-emit the signal on next tick.

    session.ui_timestamps.append(ts)
    session.ui_mid_prices.append(ind['micro_price'])
    session.ui_ofi.append(ind['ofi_norm'])
    session.ui_ofi_ema.append(ind['ofi_ema'])
    session.ui_macro_sma.append(ind['macro_sma'])
    session.ui_vwap.append(ind['vwap'])
    session.ui_bb_mid.append(ind.get('bb_mid', ind['micro_price']))
    session.ui_bb_upper.append(ind.get('bb_upper', ind['micro_price']))
    session.ui_bb_lower.append(ind.get('bb_lower', ind['micro_price']))
    session.ui_obi.append(ind['obi'])
    session.ui_obi_raw.append(ind['obi_raw'])
    session.ui_obi_norm.append(ind['obi_norm'])
    
    session.last_ui_timestamp = ts
    session.last_ui_ask = row['ask']
    session.last_ui_bid = row['bid']
    session.tick_counter += 1
    
    if session.tick_counter % 50 == 0:
        port_val = session.portfolio.get_metrics(ind['micro_price'])
        session.value_hist.append(port_val)
        
        if port_val > session.peak_equity:
            session.peak_equity = port_val
            session.current_drawdown_start = None
        else:
            if session.current_drawdown_start is None:
                session.current_drawdown_start = ts
            dd_pct = (session.peak_equity - port_val) / session.peak_equity
            session.max_dd_pct = max(session.max_dd_pct, dd_pct)
            dd_duration = ts - session.current_drawdown_start
            session.max_dd_duration = max(session.max_dd_duration, dd_duration)

    # Signal generation
    if session.auto_trade:
        sig, auto_bps, order_type, toxicity_state, reason_text = session.strategy.generate_signal(ind, session.portfolio, ts)
        session.last_toxicity_state = toxicity_state.copy()
        
        if sig != 0:
            side = 'buy' if sig == 1 else 'sell'
            
            # Check if we're closing
            closing = False
            if sig == 1 and session.portfolio.position < 0: closing = True
            elif sig == -1 and session.portfolio.position > 0: closing = True
            
            qty_to_trade = 0
            if closing:
                has_pending_close = any(o['side'] == side and o.get('status') in ('NEW', 'PENDING_SUBMIT') for o in session.pending_orders.values())
                if order_type == 'taker':
                    # Cancel existing makers to take
                    for oid, o in session.pending_orders.items():
                        if o['side'] == side:
                            o['status'] = 'PENDING_CANCEL'
                            session.outbound_queue.append({'action': 'CANCEL_ORDER', 'clientOrderId': oid, 'symbol': 'btcusdt'})
                    qty_to_trade = abs(session.portfolio.position)
                elif not has_pending_close:
                    qty_to_trade = abs(session.portfolio.position)
            elif auto_bps > 0:
                price_ref = row['ask'] if side == 'buy' else row['bid']
                qty_to_trade = (session.portfolio.get_metrics(price_ref) * (auto_bps / 10000.0)) / price_ref

            if qty_to_trade > 0:
                route_order(side, qty_to_trade, order_type, row, ind.copy(), ts, reason_text)

def route_order(side, qty, order_type, price_reference_row, ind_copy, ts, signal_reason=''):
    client_order_id = str(uuid.uuid4())
    
    # Binance BTCUSDT futures require stepSize of 0.001
    qty = max(0.001, round(float(qty), 3))
    
    if order_type == 'taker':
        exec_price = price_reference_row['ask'] if side == 'buy' else price_reference_row['bid']
        
        session.pending_orders[client_order_id] = {
            'side': side, 'qty': qty, 'type': 'taker',
            'price': exec_price, 'ind': ind_copy,
            'submitted_at': ts, 'status': 'PENDING_SUBMIT',
            'reason': signal_reason, 'chaser': False
        }
        
        session.outbound_queue.append({
            'action': 'PLACE_ORDER',
            'clientOrderId': client_order_id,
            'symbol': 'btcusdt',
            'side': side.upper(),
            'type': 'MARKET',
            'quantity': qty
        })
    else:
        tick = session.tick_size
        if side == 'buy':
            limit_price = min(price_reference_row['bid'] + tick, price_reference_row['ask'] - tick)
        else:
            limit_price = max(price_reference_row['ask'] - tick, price_reference_row['bid'] + tick)

        if limit_price <= 0:
            limit_price = price_reference_row['bid'] if side == 'buy' else price_reference_row['ask']

        # BTCUSDT price precision is 1 decimal place
        limit_price = round(float(limit_price), 1)

        session.pending_orders[client_order_id] = {
            'side': side, 'qty': qty, 'type': 'maker',
            'price': limit_price, 'ind': ind_copy,
            'submitted_at': ts, 'status': 'PENDING_SUBMIT',
            'toxicity_at_submit': session.last_toxicity_state.copy(),
            'reason': signal_reason, 'chaser': True
        }
        
        session.outbound_queue.append({
            'action': 'PLACE_ORDER',
            'clientOrderId': client_order_id,
            'symbol': 'btcusdt',
            'side': side.upper(),
            'type': 'LIMIT',
            'price': limit_price,
            'quantity': qty,
            'timeInForce': 'GTX' # Post-Only
        })

def handle_execution_report(report):
    client_order_id = report.get('clientOrderId')
    status = report.get('status')
    
    if client_order_id in session.pending_orders:
        order = session.pending_orders[client_order_id]
        
        if status in ['NEW', 'PARTIALLY_FILLED']:
            order['status'] = status
            if status == 'PARTIALLY_FILLED':
                # Register fill
                filled_qty = float(report.get('lastFilledQuantity', 0))
                filled_price = float(report.get('lastFilledPrice', order['price']))
                ts = float(report.get('transactionTime', session.last_ui_timestamp))
                session.portfolio.execute_trade(order['side'], filled_qty, filled_price, ts, order['type'], order.get('ind', {}), reason=order.get('reason', ''), client_order_id=client_order_id)
        elif status == 'FILLED':
            filled_qty = float(report.get('lastFilledQuantity', 0))
            filled_price = float(report.get('lastFilledPrice', order['price']))
            ts = float(report.get('transactionTime', session.last_ui_timestamp))
            session.portfolio.execute_trade(order['side'], filled_qty, filled_price, ts, order['type'], order.get('ind', {}), reason=order.get('reason', ''), client_order_id=client_order_id)
            del session.pending_orders[client_order_id]
        elif status in ['CANCELED', 'EXPIRED', 'REJECTED']:
            session.canceled_orders_total += 1
            ts = float(report.get('transactionTime', session.last_ui_timestamp))
            submitted_at = order.get('submitted_at', ts)
            
            reason = report.get('cancelReason', status)
            
            # Add detailed log for visibility in UI
            if status == 'REJECTED' or status == 'EXPIRED':
                session.logs.append({
                    'level': 'ERROR',
                    'message': f"Order {status}: {client_order_id}",
                    'data': {
                        'side': order['side'],
                        'price': order['price'],
                        'qty': order['qty'],
                        'reason': reason
                    }
                })
            elif status == 'CANCELED':
                session.logs.append({
                    'level': 'WARN',
                    'message': f"Order CANCELED: {client_order_id}",
                    'data': {
                        'side': order['side'],
                        'reason': reason
                    }
                })
            
            session.canceled_orders.append({
                'timestamp': ts,
                'submitted_at': submitted_at,
                'resting_ms': ts - submitted_at,
                'side': order['side'],
                'price': order['price'],
                'qty': order['qty'],
                'reason': reason,
                'toxicity': session.last_toxicity_state.copy()
            })
            del session.pending_orders[client_order_id]

def handle_sync_state(data):
    open_orders = data.get('open_orders', [])
    exchange_cids = {str(o.get('clientOrderId')) for o in open_orders if o.get('clientOrderId')}
    
    cids_to_cancel = []
    for client_order_id, order in session.pending_orders.items():
        if order.get('status') in ['NEW', 'PARTIALLY_FILLED']:
            if str(client_order_id) not in exchange_cids:
                cids_to_cancel.append(client_order_id)
                
    for cid in cids_to_cancel:
        order = session.pending_orders[cid]
        session.canceled_orders_total += 1
        ts = session.last_ui_timestamp
        submitted_at = order.get('submitted_at', ts)
        
        session.canceled_orders.append({
            'timestamp': ts,
            'submitted_at': submitted_at,
            'resting_ms': ts - submitted_at,
            'side': order['side'],
            'price': order['price'],
            'qty': order['qty'],
            'reason': 'sync_reconciliation_missing',
            'toxicity': session.last_toxicity_state.copy()
        })
        del session.pending_orders[cid]
        
    if 'capital' in data and data['capital'] is not None:
        session.portfolio.capital = float(data['capital'])
    
    if 'position' in data and data['position'] is not None:
        session.portfolio.position = float(data['position'])
        
    if 'capital' in data or 'position' in data:
        # Reset peak equity since portfolio value jumped due to sync
        # Determine port val based on last ui price if available
        price_ref = session.ui_mid_prices.get_window()[-1] if session.ui_mid_prices.count > 0 else 0.0
        if price_ref > 0:
            session.peak_equity = session.portfolio.get_metrics(price_ref)
            session.current_drawdown_start = None

def get_metrics():
    min_time = session.ui_timestamps.data[session.ui_timestamps.index] if session.ui_timestamps.count == session.ui_timestamps.size else (session.ui_timestamps.data[0] if session.ui_timestamps.count > 0 else 0.0)
    
    while session.portfolio.ui_recent_trades and session.portfolio.ui_recent_trades[0]['timestamp'] < min_time:
        session.portfolio.ui_recent_trades.popleft()
    while session.canceled_orders and session.canceled_orders[0]['timestamp'] < min_time:
        session.canceled_orders.popleft()

    recent_trades = list(session.portfolio.ui_recent_trades)[-100:]
    recent_cancellations = list(session.canceled_orders)[-100:]
    
    port_val = session.value_hist[-1] if session.value_hist else session.portfolio.capital
    current_dd_pct = (session.peak_equity - port_val) / session.peak_equity if port_val < session.peak_equity else 0.0

    return {
        "last_micro_price": session.ui_mid_prices.get_window()[-1] if session.ui_mid_prices.count > 0 else 0.0,
        "portfolio_value": port_val,
        "capital": float(session.portfolio.capital),
        "position": float(session.portfolio.position),
        "tick_count": session.tick_counter,
        "pending_order_count": len(session.pending_orders),
        "canceled_orders_total": int(session.canceled_orders_total),
        "cancellation_rate": float(
            session.canceled_orders_total /
            (session.canceled_orders_total + session.portfolio.maker_trade_count)
        ) if (session.canceled_orders_total + session.portfolio.maker_trade_count) > 0 else 0.0,
        "last_toxicity_state": session.last_toxicity_state.copy(),
        "trades": {
            "timestamp": [t['timestamp'] for t in recent_trades],
            "side": [t['side'] for t in recent_trades],
            "price": [t['price'] for t in recent_trades],
            "qty": [t['qty'] for t in recent_trades]
        },
        "auto_trade": bool(session.auto_trade),
        "strategy_style": session.strategy.style,
        "strategy_speed": session.strategy.speed,
        "recent_trades_full": recent_trades,
        "recent_cancellations": recent_cancellations,
        "pending_orders": list(session.pending_orders.values()),
        "analytics": session.portfolio.get_trade_analytics(),
        "current_dd_pct": float(current_dd_pct),
        "max_dd_pct": float(session.max_dd_pct),
        "max_dd_duration": float(session.max_dd_duration)
    }

def process_events(events):
    for event in events:
        event_type = event.get('type', 'TICK') if isinstance(event, dict) else 'TICK'
        
        if event_type == 'TICK':
            row = event.get('data', event) if isinstance(event, dict) else event
            ts = float(row['timestamp'])
            handle_tick(row, ts)
        elif event_type == 'EXECUTION_REPORT':
            handle_execution_report(event.get('data', {}))
        elif event_type == 'SYNC_STATE':
            handle_sync_state(event.get('data', {}))

    current_logs = session.logs.copy()
    session.logs.clear()
    
    intents = list(session.outbound_queue)
    session.outbound_queue.clear()

    return {
        "logs": current_logs,
        "intents": intents
    }


def get_ui_delta():
    count = session.ui_timestamps.total_appends - session.last_ui_sync_count
    if count <= 0:
        return {
            "timestamps": [], "mid_prices": [], "ofi": [], "ofi_ema": [],
            "macro_sma": [], "vwap": [], "bb_mid": [], "bb_upper": [], 
            "bb_lower": [], "obi": [], "obi_raw": [], "obi_norm": []
        }
    
    # Cap count to avoid asking for more than the buffer holds if sync is delayed
    count = min(count, session.ui_timestamps.count)
    
    res = {
        "timestamps": session.ui_timestamps.get_window()[-count:].tolist(),
        "mid_prices": session.ui_mid_prices.get_window()[-count:].tolist(),
        "ofi": session.ui_ofi.get_window()[-count:].tolist(),
        "ofi_ema": session.ui_ofi_ema.get_window()[-count:].tolist(),
        "macro_sma": session.ui_macro_sma.get_window()[-count:].tolist(),
        "vwap": session.ui_vwap.get_window()[-count:].tolist(),
        "bb_mid": session.ui_bb_mid.get_window()[-count:].tolist(),
        "bb_upper": session.ui_bb_upper.get_window()[-count:].tolist(),
        "bb_lower": session.ui_bb_lower.get_window()[-count:].tolist(),
        "obi": session.ui_obi.get_window()[-count:].tolist(),
        "obi_raw": session.ui_obi_raw.get_window()[-count:].tolist(),
        "obi_norm": session.ui_obi_norm.get_window()[-count:].tolist()
    }
    
    session.last_ui_sync_count = session.ui_timestamps.total_appends
    return res

def clear_data():
    session.portfolio.reset()
    session.indicators.reset(session.strategy.get_speed_multiplier())
    session.strategy.cooldown_end_time = 0

    session.ui_timestamps.reset()
    session.ui_mid_prices.reset()
    session.ui_ofi.reset()
    session.ui_ofi_ema.reset()
    session.ui_macro_sma.reset()
    session.ui_vwap.reset()
    session.ui_bb_mid.reset()
    session.ui_bb_upper.reset()
    session.ui_bb_lower.reset()
    session.ui_obi.reset()
    session.ui_obi_raw.reset()
    session.ui_obi_norm.reset()

    session.last_ui_timestamp = 0.0
    session.last_ui_ask = 0.0
    session.last_ui_bid = 0.0

    session.value_hist.clear()
    session.tick_counter = 0
    session.pending_orders.clear()
    session.outbound_queue.clear()
    session.canceled_orders.clear()
    session.canceled_orders_total = 0
    session.last_toxicity_state = {
        'buy_ofi_cancel_level': -0.5,
        'sell_ofi_cancel_level': 0.5,
        'cancel_buy_maker': False,
        'cancel_sell_maker': False,
        'ofi_ema': 0.0,
        'ofi_deriv': 0.0,
        'obi': 0.0,
        'obi_raw': 0.0,
        'obi_norm': 0.0
    }

    session.peak_equity = session.portfolio.initial_capital
    session.current_drawdown_start = None
    session.max_dd_pct = 0.0
    session.last_ui_sync_count = 0
    session.max_dd_duration = 0.0
    return True
