import math
import logging
from typing import Dict, List, Any, Callable
import concurrent.futures

# ==========================================
# 1. EVENT BUS & PUB-SUB CORE
# ==========================================
class EventBus:
    """Synchronous internal Pub-Sub dispatcher for high-frequency trading engine."""
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def subscribe(self, topic: str, callback: Callable):
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(callback)

    def publish(self, topic: str, payload: Any):
        if topic in self.subscribers:
            for callback in self.subscribers[topic]:
                callback(payload)

    def publish_async(self, topic: str, payload: Any):
        """Offload heavy tasks to a background thread so the hot path isn't blocked."""
        import sys
        if sys.platform == 'emscripten':
            # WASM/Pyodide typically lacks robust threading, so we execute synchronously or handle separately
            if topic in self.subscribers:
                for callback in self.subscribers[topic]:
                    try:
                        callback(payload)
                    except Exception as e:
                        print(f"Async Fallback Error: {e}")
        else:
            if topic in self.subscribers:
                for callback in self.subscribers[topic]:
                    self.thread_pool.submit(callback, payload)


# ==========================================
# 2. MATH UTILITIES & EWMA BIVARIATE BUFFER
# ==========================================
class KalmanFilterBivariate:
    """
    O(1) Recursive Kalman Filter for dynamic hedge ratio (beta) and intercept (alpha).
    Adapts faster to regime shifts than EWMA/Rolling OLS and prevents lagging drop-offs.
    """
    def __init__(self, delta=1e-5, r_var=1e-3):
        self.delta = delta
        self.r_var = r_var
        self.state = [0.0, 0.0] # [alpha, beta]
        self.P = [[1.0, 0.0], [0.0, 1.0]] # state covariance matrix
        self.initialized = False
        self.count = 0

    def append(self, x: float, y: float):
        if not self.initialized:
            self.state = [y, 0.0]
            self.initialized = True
            self.count = 1
            return
        self.count += 1
        self.P[0][0] += self.delta
        self.P[1][1] += self.delta
        h0 = 1.0
        h1 = x
        y_pred = self.state[0] * h0 + self.state[1] * h1
        e = y - y_pred
        S = (h0 * (self.P[0][0]*h0 + self.P[0][1]*h1) + 
             h1 * (self.P[1][0]*h0 + self.P[1][1]*h1)) + self.r_var
        k0 = (self.P[0][0]*h0 + self.P[0][1]*h1) / S
        k1 = (self.P[1][0]*h0 + self.P[1][1]*h1) / S
        self.state[0] += k0 * e
        self.state[1] += k1 * e
        p00 = self.P[0][0] - k0 * (h0*self.P[0][0] + h1*self.P[1][0])
        p01 = self.P[0][1] - k0 * (h0*self.P[0][1] + h1*self.P[1][1])
        p10 = self.P[1][0] - k1 * (h0*self.P[0][0] + h1*self.P[1][0])
        p11 = self.P[1][1] - k1 * (h0*self.P[0][1] + h1*self.P[1][1])
        self.P = [[p00, p01], [p10, p11]]

    def get_beta(self) -> float:
        return self.state[1]
        
    def get_alpha(self) -> float:
        return self.state[0]

    def reset(self):
        self.state = [0.0, 0.0]
        self.P = [[1.0, 0.0], [0.0, 1.0]]
        self.initialized = False
        self.count = 0


class EWMASingle:
    """O(1) EWMA for single variables (e.g. Z-Score Mean and Std)."""
    def __init__(self, window_size: float):
        self.alpha = 2.0 / (window_size + 1.0)
        self.initialized = False
        self.mean = 0.0
        self.var = 0.0
        self.count = 0

    def append(self, x: float):
        if not self.initialized:
            self.mean = x
            self.var = 0.0
            self.initialized = True
            self.count = 1
            return

        self.count += 1
        diff = x - self.mean
        self.mean += self.alpha * diff
        self.var = (1.0 - self.alpha) * (self.var + self.alpha * diff * diff)

    def std(self) -> float:
        return math.sqrt(max(0.0, self.var))

    def reset(self):
        self.initialized = False
        self.mean = 0.0
        self.var = 0.0
        self.count = 0


# ==========================================
# 3. STAT ARB MODEL (Zero-Order Hold)
# ==========================================
class StatArbModel:
    """
    Manages the Zero-Order Hold alignment of asynchronous ticks and computes continuous pair analytics.
    """
    def __init__(self, bus: EventBus, target: str, feature: str):
        self.bus = bus
        self.target = target
        self.feature = feature
        
        # Configuration
        self.w_beta = 1200  # Longer structural window (ticks/events approx)
        self.w_z = 300      # Shorter tactical window
        
        # Statistical trackers
        self.bivariate = KalmanFilterBivariate(delta=1e-5, r_var=1e-3)
        self.spread_stats = EWMASingle(self.w_z)
        
        # ZOH State
        self.target_price = 0.0
        self.feature_price = 0.0
        
        self.target_bid = 0.0
        self.target_ask = 0.0
        self.feature_bid = 0.0
        self.feature_ask = 0.0
        
        # Current Metrics
        self.beta = 0.0
        self.spread = 0.0
        self.z_score = 0.0
        self.is_ready = False
        
        # Subscribe to ticks
        self.bus.subscribe(f'TICK_{self.target}', self._on_target_tick)
        self.bus.subscribe(f'TICK_{self.feature}', self._on_feature_tick)
        
    def _on_target_tick(self, tick: dict):
        self.target_bid = float(tick['bid'])
        self.target_ask = float(tick['ask'])
        self.target_price = (self.target_bid + self.target_ask) / 2.0
        self._evaluate(tick.get('timestamp', 0))

    def _on_feature_tick(self, tick: dict):
        self.feature_bid = float(tick['bid'])
        self.feature_ask = float(tick['ask'])
        self.feature_price = (self.feature_bid + self.feature_ask) / 2.0
        self._evaluate(tick.get('timestamp', 0))

    def _evaluate(self, timestamp: int):
        # Need both legs to have data
        if self.target_price == 0.0 or self.feature_price == 0.0:
            return

        # Use Log Prices for structural stability
        log_y = math.log(self.target_price)
        log_x = math.log(self.feature_price)

        # ── Look-ahead fix ──────────────────────────────────────────────────
        # Capture the *prior* beta BEFORE updating the Kalman state so that
        # the current tick's spread is computed with yesterday's estimate.
        # This prevents look-ahead bias in Z-score calculations.
        beta_prior = self.bivariate.get_beta()

        # 1. Update Bivariate Math (Kalman step)
        self.bivariate.append(log_x, log_y)

        # Minimum warmup period
        if self.bivariate.count < min(50, self.w_beta // 4):
            return

        self.is_ready = True
        self.beta = beta_prior  # expose the *prior* beta (causal)

        # 2. Compute current Log-Spread using the prior (lagged) beta
        self.spread = log_y - (beta_prior * log_x)

        # 3. Update Z-Score Math
        self.spread_stats.append(self.spread)

        if self.spread_stats.count > min(25, self.w_z // 4):
            std = self.spread_stats.std()
            if std > 1e-8:
                self.z_score = (self.spread - self.spread_stats.mean) / std
            else:
                self.z_score = 0.0

        # Emit updated model state
        self.bus.publish('MODEL_UPDATED', {
            'timestamp': timestamp,
            'target_price': self.target_price,
            'feature_price': self.feature_price,
            'target_ask': self.target_ask,
            'target_bid': self.target_bid,
            'feature_ask': self.feature_ask,
            'feature_bid': self.feature_bid,
            'beta': self.beta,
            'spread': self.spread,
            'spread_mean': self.spread_stats.mean,
            'spread_std': self.spread_stats.std(),
            'z_score': self.z_score,
            'is_ready': self.is_ready
        })

    def reset(self):
        self.bivariate.reset()
        self.spread_stats.reset()
        self.target_price = 0.0
        self.feature_price = 0.0
        self.is_ready = False
        self.beta = 0.0
        self.spread = 0.0
        self.z_score = 0.0


# ==========================================
# 4. SIGNAL GENERATOR (Regime & Thresholds)
# ==========================================
class SignalGenerator:
    """
    Listens to the model, applies strategy thresholds, and generates trade intents.
    Uses a dynamic cost hurdle that incorporates maker/taker fees, slippage, and
    expected funding drag so the engine only trades when edge exceeds total costs.
    """
    def __init__(self, bus: EventBus, target: str, feature: str, portfolio: 'PortfolioManager'):
        self.bus = bus
        self.target = target
        self.feature = feature
        self.portfolio = portfolio

        # Parameters
        self.entry_threshold = 2.0
        self.exit_threshold = 0.0
        self.max_half_life = 7200  # in periods
        self.max_net_delta = 50000.0  # max unhedged exposure

        self.maker_fee = 0.0002   # 2 bps — maker entry
        self.taker_fee = 0.0005   # 5 bps — taker exit
        self.slippage_bps = 10.0  # default conservative slippage

        # Dynamic hurdle state
        self.current_funding_rate: float = 0.0   # most recent funding rate (any symbol)
        self.half_life_seconds: float = 3600.0   # estimated hold time from regime data
        self.last_dynamic_hurdle_bps: float = 0.0

        self.is_toxic = False

        self.bus.subscribe('MODEL_UPDATED', self._on_model_updated)
        self.bus.subscribe('REGIME_CHANGE', self._on_regime_change)
        self.bus.subscribe('UPDATE_STRATEGY_PARAMS', self._on_update_params)
        self.bus.subscribe('FUNDING_RATE_UPDATE', self._on_funding_rate_update)

    def _on_update_params(self, payload: dict):
        if 'sigma_threshold' in payload:
            self.entry_threshold = float(payload['sigma_threshold'])
        if 'max_net_delta' in payload:
            self.max_net_delta = float(payload['max_net_delta'])
        if 'slippage_bps' in payload:
            self.slippage_bps = float(payload['slippage_bps'])

    def _on_funding_rate_update(self, payload: dict):
        """Track the latest funding rate for dynamic hurdle calculation."""
        rate = payload.get('fundingRate', payload.get('funding_rate', 0.0))
        self.current_funding_rate = float(rate)

    def _compute_dynamic_hurdle_bps(self) -> float:
        """Compute the minimum edge (in bps) required to justify a new position.

        dynamic_hurdle = maker_entry_fee + taker_exit_fee + slippage + funding_drag

        estimated hold time ≈ half_life_seconds (capped at one 8-hour funding period)
        funding_drag ≈ abs(funding_rate) × (hold / (8h)) × 10_000
        """
        maker_fee_bps = self.maker_fee * 10_000    # 2 bps
        taker_fee_bps = self.taker_fee * 10_000    # 5 bps
        hold_s = min(self.half_life_seconds, 8 * 3600)
        funding_bps = abs(self.current_funding_rate) * (hold_s / (8 * 3600)) * 10_000
        hurdle = maker_fee_bps + taker_fee_bps + self.slippage_bps + funding_bps
        self.last_dynamic_hurdle_bps = hurdle
        return hurdle

    def _on_model_updated(self, payload: dict):
        if not payload['is_ready']:
            return

        import math
        target_ask = payload.get('target_ask', payload.get('target_price', 0.0))
        target_bid = payload.get('target_bid', payload.get('target_price', 0.0))
        feature_ask = payload.get('feature_ask', payload.get('feature_price', 0.0))
        feature_bid = payload.get('feature_bid', payload.get('feature_price', 0.0))
        beta = payload.get('beta', 1.0)
        spread_mean = payload.get('spread_mean', 0.0)
        spread_std = payload.get('spread_std', 0.0)

        if spread_std > 1e-8 and target_ask > 0 and feature_bid > 0 and target_bid > 0 and feature_ask > 0:
            if beta >= 0:
                long_spread_val = math.log(target_ask) - beta * math.log(feature_bid)
                short_spread_val = math.log(target_bid) - beta * math.log(feature_ask)
            else:
                long_spread_val = math.log(target_ask) - beta * math.log(feature_ask)
                short_spread_val = math.log(target_bid) - beta * math.log(feature_bid)

            long_z_score = (long_spread_val - spread_mean) / spread_std
            short_z_score = (short_spread_val - spread_mean) / spread_std
        else:
            long_z_score = 0.0
            short_z_score = 0.0

        z_score = payload.get('z_score', 0.0)  # mid-price for tracking/exit

        # Dynamic cost hurdle replaces static min_profit_bps
        dynamic_hurdle_bps = self._compute_dynamic_hurdle_bps()

        expected_edge_long_bps = abs(long_z_score) * spread_std * 10_000 - (self.maker_fee + self.taker_fee) * 10_000
        expected_edge_short_bps = abs(short_z_score) * spread_std * 10_000 - (self.maker_fee + self.taker_fee) * 10_000

        # Entry signals (only when edge clears the dynamic hurdle)
        current_net_delta = self.portfolio.get_net_delta(target_ask, feature_bid)
        expected_target_notional = self.portfolio.cash * 0.1

        if not self.is_toxic:
            if long_z_score < -self.entry_threshold:
                if expected_edge_long_bps > dynamic_hurdle_bps:
                    if abs(current_net_delta + expected_target_notional) < self.max_net_delta:
                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'LONG_SPREAD signaled. Edge: {expected_edge_long_bps:.2f} bps > Hurdle: {dynamic_hurdle_bps:.2f} bps'})
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'LONG_SPREAD', 'z_score': long_z_score})
                elif expected_edge_long_bps > 0:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'LONG_SPREAD ignored. Edge {expected_edge_long_bps:.2f} bps < Hurdle {dynamic_hurdle_bps:.2f} bps'})
            elif short_z_score > self.entry_threshold:
                if expected_edge_short_bps > dynamic_hurdle_bps:
                    if abs(current_net_delta - expected_target_notional) < self.max_net_delta:
                        self.bus.publish('LOG', {'level': 'INFO', 'message': f'SHORT_SPREAD signaled. Edge: {expected_edge_short_bps:.2f} bps > Hurdle: {dynamic_hurdle_bps:.2f} bps'})
                        self.bus.publish('SIGNAL_GENERATED', {'direction': 'SHORT_SPREAD', 'z_score': short_z_score})
                elif expected_edge_short_bps > 0:
                    self.bus.publish('LOG', {'level': 'WARN', 'message': f'SHORT_SPREAD ignored. Edge {expected_edge_short_bps:.2f} bps < Hurdle {dynamic_hurdle_bps:.2f} bps'})

        # Exit logic
        if abs(z_score) > 4.0:
            self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD', 'z_score': z_score})
        elif abs(z_score) <= self.exit_threshold:
            self.bus.publish('SIGNAL_GENERATED', {'direction': 'CLOSE_SPREAD', 'z_score': z_score})

    def _on_regime_change(self, payload: dict):
        if payload.get('toxic', False):
            if not self.is_toxic:
                self.bus.publish('LOG', {'level': 'WARN', 'message': f'Regime changed to TOXIC (hurst: {payload.get("hurst", 1):.2f}, hl: {payload.get("half_life", 9999):.1f}). Scaling down.'})
            self.is_toxic = payload.get('toxic', False)
        else:
            if self.is_toxic:
                self.bus.publish('LOG', {'level': 'INFO', 'message': 'Regime recovered to SAFE. Restoring size.'})
            self.is_toxic = False
        # Update expected hold time from half-life estimate (convert from minutes to seconds)
        hl_mins = payload.get('half_life')
        if hl_mins is not None and hl_mins > 0:
            import math as _math
            hl_secs = float(hl_mins) * 60.0
            # Clamp to a sensible range [60s, 24h]
            self.half_life_seconds = max(60.0, min(hl_secs, 86400.0))


# ==========================================
# 4A. BACKGROUND ANALYTICS WORKER
# ==========================================
class BackgroundAnalyticsWorker:
    """
    Subscribes to ANALYTICS_REQUEST and runs expensive math outside the event loop.
    Publishes REGIME_CHANGE back to the event bus.
    """
    def __init__(self, bus: EventBus, max_half_life=7200):
        self.bus = bus
        self.max_half_life = max_half_life
        self.bus.subscribe('ANALYTICS_REQUEST', self._run_analytics)
        
    def _run_analytics(self, payload: dict):
        try:
            import numpy as np
            import pandas as pd
            import statsmodels.api as sm
            from statsmodels.tsa.stattools import coint
            from public.python.analytics_core import get_hurst_exponent_dynamic, get_half_life
            
            target_data = payload.get('targetData', [])
            feature_data = payload.get('featureData', [])
            if len(target_data) < 100 or len(feature_data) < 100:
                return
                
            df_target = pd.DataFrame(target_data, columns=['timestamp', 'Target_Close'])
            df_target['timestamp'] = pd.to_datetime(df_target['timestamp'], unit='ms')
            df_target.set_index('timestamp', inplace=True)
            
            df_feature = pd.DataFrame(feature_data, columns=['timestamp', 'Feature_Close'])
            df_feature['timestamp'] = pd.to_datetime(df_feature['timestamp'], unit='ms')
            df_feature.set_index('timestamp', inplace=True)
            
            df_in = df_target.join(df_feature, how='inner').dropna()
            
            if len(df_in) < 100:
                return
                
            target_arr = np.log(df_in['Target_Close'].values)
            feature_arr = np.log(df_in['Feature_Close'].values)
            
            # 1. ADF Cointegration test
            score, p_value, _ = coint(target_arr, feature_arr)
            
            # 2. OU Half-life estimate & Hurst
            X = sm.add_constant(feature_arr)
            model = sm.OLS(target_arr, X).fit()
            spread = model.resid
            
            spread_series = pd.Series(spread, index=df_in.index)
            half_life_periods = get_half_life(spread_series, '1m')
            hurst = get_hurst_exponent_dynamic(spread, len(spread))
            
            # Toxicity Gating
            is_coint = p_value < 0.05
            is_hl_valid = half_life_periods * 60.0 < self.max_half_life
            
            is_toxic = not (is_coint and is_hl_valid and (hurst < 0.5))
            
            # Clean floating point infinites before sending to Pyodide
            if np.isinf(half_life_periods) or np.isnan(half_life_periods):
                half_life_periods = 99999.0
            if np.isinf(p_value) or np.isnan(p_value):
                p_value = 1.0
            if np.isinf(hurst) or np.isnan(hurst):
                hurst = 1.0
            
            # Publish back to the main event bus
            self.bus.publish('REGIME_CHANGE', {
                'toxic': bool(is_toxic),
                'adf_pvalue': float(p_value),
                'half_life': float(half_life_periods),
                'hurst': float(hurst)
            })
            
        except Exception as e:
            import traceback
            print(f"BackgroundAnalyticsWorker Error: {e}")
            traceback.print_exc()
            self.bus.publish('REGIME_CHANGE', {'toxic': True, 'error': str(e)})


# ==========================================
# 5. PORTFOLIO & EXECUTION MANAGERS
# ==========================================
import uuid

class PortfolioManager:
    """
    Tracks dual-asset positions, cash, and calculates net delta.
    Accounts for funding payments and exact maker/taker fees.
    """
    def __init__(self, bus: EventBus, target: str, feature: str):
        self.bus = bus
        self.target = target
        self.feature = feature
        self.positions = {target: 0.0, feature: 0.0}
        self.cash = 100000.0
        self.total_fees_paid = 0.0
        self.total_funding_paid = 0.0  # net funding debited (positive = paid out)
        self.realized_pnl = 0.0
        self.avg_entry_prices = {target: 0.0, feature: 0.0}
        self.recent_trades = []

        self.bus.subscribe('ORDER_UPDATE', self._on_order_update)
        self.bus.subscribe('FUNDING_RATE_UPDATE', self._on_funding_rate_update)
        
    def _on_funding_rate_update(self, payload: dict):
        """Deduct (or credit) funding payments for any open position.

        Convention (Binance perpetuals):
          payment = position_size × mark_price × funding_rate
          positive funding_rate → longs pay shorts  → payment > 0 for long positions
          negative funding_rate → shorts pay longs   → payment < 0 for long positions
        Cash is reduced by *payment* (a negative payment = credit).
        """
        symbol = payload.get('symbol', '').upper()
        rate = float(payload.get('fundingRate', payload.get('funding_rate', 0.0)))
        mark = float(payload.get('markPrice', payload.get('mark_price', 0.0)))
        pos = self.positions.get(symbol, 0.0)

        if pos == 0.0 or mark <= 0.0:
            return  # no open position or no mark price — skip

        payment = pos * mark * rate  # +ve = longs pay, -ve = longs receive
        self.cash -= payment
        self.realized_pnl -= payment
        self.total_funding_paid += payment

    def _on_order_update(self, payload: dict):
        status = payload.get('status')
        if status == 'FILLED':
            symbol = payload.get('symbol', '').upper()
            if not symbol:
                return
            qty = float(payload.get('filled_qty', 0.0))
            price = float(payload.get('price', 0.0))
            side = payload.get('side', '').upper()
            # Accept is_maker from replay EXECUTION_REPORT
            is_maker = bool(payload.get('is_maker', False))

            fee_rate = 0.0002 if is_maker else 0.0005
            notional = qty * price
            fee = notional * fee_rate

            sign = 1.0 if side == 'BUY' else -1.0

            if symbol in self.positions:
                prev_pos = self.positions[symbol]
                new_pos = prev_pos + (qty * sign)
                pnl = 0.0

                # Realized PnL Calculation
                if (prev_pos > 0 and side == 'SELL') or (prev_pos < 0 and side == 'BUY'):
                    # Reducing position
                    closed_qty = min(abs(prev_pos), qty)
                    entry_price = self.avg_entry_prices[symbol]
                    pnl = (price - entry_price) * closed_qty * (1.0 if prev_pos > 0 else -1.0)
                    self.realized_pnl += pnl

                    # If position flipped, update avg entry for the remaining qty
                    if (prev_pos > 0 and new_pos < 0) or (prev_pos < 0 and new_pos > 0):
                        self.avg_entry_prices[symbol] = price
                else:
                    # Increasing position
                    total_cost = (abs(prev_pos) * self.avg_entry_prices[symbol]) + (qty * price)
                    self.avg_entry_prices[symbol] = total_cost / abs(new_pos) if new_pos != 0 else 0.0

                if abs(new_pos) < 1e-8:
                    new_pos = 0.0
                    self.avg_entry_prices[symbol] = 0.0

                self.positions[symbol] = new_pos
                # Fees are applied exactly once here (replay marks is_maker; engine applies rate)
                self.cash -= (qty * price * sign) + fee
                self.total_fees_paid += fee
                
                self.bus.publish('LOG', {'level': 'INFO', 'message': f"Order FILLED: {side} {qty} {symbol} @ {price}. Fee: {fee:.4f} (Maker: {is_maker})"})

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
                }
                self.recent_trades.append(trade_record)
                if len(self.recent_trades) > 100:
                    self.recent_trades.pop(0)

    def get_unrealized_pnl(self, target_bid: float, target_ask: float, feature_bid: float, feature_ask: float) -> float:
        upnl = 0.0
        # Target Leg Liquidation Value
        t_pos = self.positions.get(self.target, 0.0)
        if t_pos > 0: upnl += (target_bid - self.avg_entry_prices.get(self.target, 0.0)) * t_pos
        elif t_pos < 0: upnl += (target_ask - self.avg_entry_prices.get(self.target, 0.0)) * t_pos
        
        # Feature Leg Liquidation Value
        f_pos = self.positions.get(self.feature, 0.0)
        if f_pos > 0: upnl += (feature_bid - self.avg_entry_prices.get(self.feature, 0.0)) * f_pos
        elif f_pos < 0: upnl += (feature_ask - self.avg_entry_prices.get(self.feature, 0.0)) * f_pos
        
        return upnl

    def get_nav(self, target_price: float, feature_price: float) -> float:
        nav = self.cash
        nav += self.positions[self.target] * target_price
        nav += self.positions[self.feature] * feature_price
        return nav
        
    def get_net_delta(self, target_price: float, feature_price: float) -> float:
        notional_target = self.positions[self.target] * target_price
        notional_feature = self.positions[self.feature] * feature_price
        return notional_target + notional_feature

class ExecutionManager:
    """
    Manages the Asynchronous Legging State Machine (Maker-Taker).
    Ensures safe entry into dual-leg pairs.
    """
    def __init__(self, bus: EventBus, target: str, feature: str, portfolio: 'PortfolioManager'):
        self.bus = bus
        self.target = target
        self.feature = feature
        self.portfolio = portfolio
        
        self.state = "IDLE"
        self.active_maker_order_id = None
        self.pending_leg2_template = None
        
        self.latest_beta = 1.0
        self.target_price = 0.0
        self.feature_price = 0.0
        self.target_bid = 0.0
        self.target_ask = 0.0
        self.feature_bid = 0.0
        self.feature_ask = 0.0
        self.maker_filled_qty = 0.0
        self.position_entry_ts = 0
        self.half_life_ms = 3600000.0  # default 1 hour
        
        self.base_size = 0.1 # Trade size for the target asset
        self.maker_timeout_ms = 5000  # Dynamic based on regime
        self.maker_order_ts = 0
        self.slippage_bps = 5.0       # Dynamic based on volatility
        
        self.bus.subscribe('SIGNAL_GENERATED', self._on_signal)
        self.bus.subscribe('ORDER_UPDATE', self._on_order_update)
        self.bus.subscribe('MODEL_UPDATED', self._on_model_update)
        self.bus.subscribe('TIMER_1S', self._on_timer)
        self.bus.subscribe('REGIME_CHANGE', self._on_regime_change)
        
    def _on_regime_change(self, payload: dict):
        if payload.get('toxic', False):
            # Scale down size during toxic regimes
            self.base_size = max(0.01, self.base_size * 0.5)
        else:
            # Restore/scale up slightly if safe, capped at 0.5
            self.base_size = min(0.5, self.base_size * 1.1)
            
        hl_mins = payload.get('half_life', 50.0)
        if hl_mins <= 0:
            hl_mins = 50.0
        hl_ticks = float(hl_mins) * 60.0
        self.half_life_ms = hl_ticks * 1000.0
        # Faster mean reversion (lower half_life) -> tighter timeout
        # e.g., if hl_ticks=10 ticks, timeout=2000ms. If hl_ticks=100, timeout=10000ms
        self.maker_timeout_ms = max(1000, min(15000, int(hl_ticks * 200)))
        
        vol = payload.get('volatility', 0.001)
        # Higher volatility -> higher slippage tolerance to ensure fills
        self.slippage_bps = max(1.0, min(25.0, vol * 10000))
        


    def _on_model_update(self, payload: dict):
        if payload.get('is_ready'):
            self.latest_beta = float(payload.get('beta', 1.0))
            self.target_price = float(payload.get('target_price', 0.0))
            self.feature_price = float(payload.get('feature_price', 0.0))
            self.target_bid = float(payload.get('target_bid', self.target_price))
            self.target_ask = float(payload.get('target_ask', self.target_price))
            self.feature_bid = float(payload.get('feature_bid', self.feature_price))
            self.feature_ask = float(payload.get('feature_ask', self.feature_price))

    def _on_signal(self, payload: dict):
        direction = payload.get('direction')
        
        if direction == 'LONG_SPREAD' and self.state == 'IDLE':
            self.bus.publish('LOG', {'level': 'INFO', 'message': f'Entering LONG_SPREAD for {self.target} & {self.feature}'})
            self._enter_spread('BUY')
            
        elif direction == 'SHORT_SPREAD' and self.state == 'IDLE':
            self.bus.publish('LOG', {'level': 'INFO', 'message': f'Entering SHORT_SPREAD for {self.target} & {self.feature}'})
            self._enter_spread('SELL')
            
        elif direction == 'CLOSE_SPREAD':
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
                    })

    def _enter_spread(self, target_side: str):
        if self.feature_price == 0 or self.target_price == 0:
            return
            
        self.state = 'LEGGING_MAKER_ENTRY'
        self.active_maker_order_id = str(uuid.uuid4())
        self.maker_order_ts = 0 
        self.maker_filled_qty = 0.0
        
        if self.latest_beta >= 0:
            feature_side = 'SELL' if target_side == 'BUY' else 'BUY'
        else:
            feature_side = target_side
            
        maker_price = self.target_bid if target_side == 'BUY' else self.target_ask
        
        slip_ratio = self.slippage_bps / 10000.0
        if feature_side == 'BUY':
            taker_price = self.feature_ask * (1.0 + slip_ratio)
        else:
            taker_price = self.feature_bid * (1.0 - slip_ratio)
            
        self.pending_leg2_template = {
            'symbol': self.feature,
            'side': feature_side,
            'type': 'LIMIT',
            'price': taker_price
        }
        
        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': self.active_maker_order_id,
            'symbol': self.target,
            'side': target_side,
            'type': 'LIMIT',
            'qty': round(self.base_size, 3),
            'price': round(maker_price, 2)
        })

    def _on_timer(self, payload: dict):
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
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'EMERGENCY_CLOSE_SPREAD'})

    def _on_order_update(self, payload: dict):
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
                self.state = 'IDLE'

# ==========================================
# 6. ENGINE ENTRY POINT
# ==========================================
class TradingEngine:
    def __init__(self, target='BTCUSDT', feature='ETHUSDT'):
        self.bus = EventBus()
        self.model = StatArbModel(self.bus, target=target, feature=feature)
        self.portfolio = PortfolioManager(self.bus, target=target, feature=feature)
        self.signal_generator = SignalGenerator(self.bus, target=target, feature=feature, portfolio=self.portfolio)
        self.background_worker = BackgroundAnalyticsWorker(self.bus)
        self.execution = ExecutionManager(self.bus, target=target, feature=feature, portfolio=self.portfolio)
        self.target = target
        self.feature = feature
        self.last_ts = 0
        self.last_1s_timer = 0
        self.last_1m_timer = 0
        self.latest_regime = {
            'hurst': None,
            'half_life': None,
            'adf_pvalue': None,
            'volatility': 0.0,
            'toxic': False
        }
        self.bus.subscribe('REGIME_CHANGE', self._on_regime_change)

    def _on_regime_change(self, payload: dict):
        self.latest_regime.update(payload)

    def configure_strategy(self, target: str, feature: str):
        self.target = target.upper()
        self.feature = feature.upper()
        
        self.bus = EventBus()
        self.model = StatArbModel(self.bus, target=self.target, feature=self.feature)
        self.portfolio = PortfolioManager(self.bus, target=self.target, feature=self.feature)
        self.signal_generator = SignalGenerator(self.bus, target=self.target, feature=self.feature, portfolio=self.portfolio)
        self.background_worker = BackgroundAnalyticsWorker(self.bus)
        self.execution = ExecutionManager(self.bus, target=self.target, feature=self.feature, portfolio=self.portfolio)
        
        self.last_ts = 0
        self.last_1s_timer = 0
        self.last_1m_timer = 0
        self.latest_regime = {
            'hurst': None,
            'half_life': None,
            'adf_pvalue': None,
            'volatility': 0.0,
            'toxic': False
        }
        self.bus.subscribe('REGIME_CHANGE', self._on_regime_change)

    def process_events(self, events: List[dict]):
        intents = []
        logs = []
        # Temporarily intercept intents from the bus
        def on_intent(intent):
            intents.append(intent)
        def on_log(log):
            logs.append(log)
        self.bus.subscribe('OUTBOUND_INTENT', on_intent)
        self.bus.subscribe('LOG', on_log)

        for event in events:
            ev_type = event.get('type')
            data = event.get('data', event)
            
            # Handle tick routing
            if ev_type == 'TICK':
                symbol = data.get('symbol', '').upper()
                if not symbol:
                    # Fallback for old single-asset data
                    symbol = self.target
                
                ts = data.get('timestamp', 0)
                self.last_ts = ts
                
                # Check timers
                self._check_timers(ts)
                
                self.bus.publish(f'TICK_{symbol}', data)
                
            elif ev_type == 'EXECUTION_REPORT':
                self.bus.publish('ORDER_UPDATE', data)

            elif ev_type == 'FUNDING_RATE_UPDATE':
                # Route funding events to all subscribers (PortfolioManager, SignalGenerator)
                self.bus.publish('FUNDING_RATE_UPDATE', data)

            elif ev_type == 'REGIME_DATA':
                self.bus.publish_async('ANALYTICS_REQUEST', data)

        if 'OUTBOUND_INTENT' in self.bus.subscribers:
            if on_intent in self.bus.subscribers['OUTBOUND_INTENT']:
                self.bus.subscribers['OUTBOUND_INTENT'].remove(on_intent)
        if 'LOG' in self.bus.subscribers:
            if on_log in self.bus.subscribers['LOG']:
                self.bus.subscribers['LOG'].remove(on_log)

        return {'intents': intents, 'logs': logs}

    def _check_timers(self, current_ts: int):
        # 1-second timer
        if current_ts - self.last_1s_timer >= 1000:
            self.bus.publish('TIMER_1S', {'timestamp': current_ts})
            self.last_1s_timer = current_ts

        # 1-minute timer
        if current_ts - self.last_1m_timer >= 60000:
            self.bus.publish('TIMER_1M', {'timestamp': current_ts})
            self.last_1m_timer = current_ts

    def get_ui_delta(self):
        return {
            'portfolio_value': self.portfolio.get_nav(self.model.target_price, self.model.feature_price),
            'capital': self.portfolio.cash,
            'realized_pnl': getattr(self.portfolio, 'realized_pnl', 0.0),
            'unrealized_pnl': self.portfolio.get_unrealized_pnl(
                self.model.target_bid, self.model.target_ask,
                self.model.feature_bid, self.model.feature_ask
            ) if hasattr(self.portfolio, 'get_unrealized_pnl') else 0.0,
            'total_fees_paid': getattr(self.portfolio, 'total_fees_paid', 0.0),
            'total_funding_paid': getattr(self.portfolio, 'total_funding_paid', 0.0),
            'dynamic_hurdle_bps': getattr(self.signal_generator, 'last_dynamic_hurdle_bps', 0.0),
            'positions': self.portfolio.positions,
            'target_position': self.portfolio.positions.get(self.target, 0.0),
            'feature_position': self.portfolio.positions.get(self.feature, 0.0),
            'avg_entry_prices': getattr(self.portfolio, 'avg_entry_prices', {}),
            'net_delta': self.portfolio.get_net_delta(self.model.target_price, self.model.feature_price),
            'spread_metrics': {
                'current_spread': self.model.spread,
                'z_score': self.model.z_score,
                'beta': self.model.beta,
                'hedge_ratio': self.model.beta,
                'is_ready': self.model.is_ready,
                'target_price': self.model.target_price,
                'feature_price': self.model.feature_price,
                'target_bid': self.model.target_bid,
                'target_ask': self.model.target_ask,
                'feature_bid': self.model.feature_bid,
                'feature_ask': self.model.feature_ask,
                'hurst': self.latest_regime.get('hurst'),
                'half_life': self.latest_regime.get('half_life'),
                'adf_pvalue': self.latest_regime.get('adf_pvalue')
            },
            'toxicity_flag': self.signal_generator.is_toxic,
            'execution_state': self.execution.state,
            'recent_trades': getattr(self.portfolio, 'recent_trades', [])[-50:],
            'pending_orders': [self.execution.pending_leg2_template] if getattr(self.execution, 'pending_leg2_template', None) else []
        }
        
    def clear_data(self):
        self.model.reset()

# Default singleton instance for Pyodide UI compatibility
engine_instance = TradingEngine()

def process_events(events):
    return engine_instance.process_events(events)

def get_ui_delta():
    return engine_instance.get_ui_delta()

def configure_strategy(target: str, feature: str):
    engine_instance.configure_strategy(target, feature)

def clear_data():
    engine_instance.clear_data()

def run_adhoc_analysis(payload: dict):
    from public.python.analytics_core import calculate_rolling_metrics
    import pandas as pd
    import numpy as np
    
    target_data = payload.get('targetData', [])
    feature_data = payload.get('featureData', [])
    window_size = int(payload.get('windowSize', 800))
    
    if not target_data or not feature_data:
        return {'error': 'No data provided'}
        
    df_target = pd.DataFrame(target_data, columns=['timestamp', 'Close'])
    df_target['timestamp'] = pd.to_datetime(df_target['timestamp'], unit='ms')
    df_target.set_index('timestamp', inplace=True)
    
    df_feature = pd.DataFrame(feature_data, columns=['timestamp', 'Feature_Price'])
    df_feature['timestamp'] = pd.to_datetime(df_feature['timestamp'], unit='ms')
    df_feature.set_index('timestamp', inplace=True)
    
    df_in = df_target.join(df_feature, how='outer').ffill().dropna()
    
    if len(df_in) < window_size:
        return {'error': f'Not enough overlapping data points ({len(df_in)}) for the given window size ({window_size})'}
        
    df_calc = calculate_rolling_metrics(df_in, window_size)
    z_scores = df_calc['Z_Score'].replace([np.inf, -np.inf], np.nan).dropna().values
    
    if len(z_scores) == 0:
        return {'error': 'Failed to calculate Z-scores'}
        
    hist, bin_edges = np.histogram(z_scores, bins=50, density=False)
    
    mean_z = np.mean(z_scores)
    std_z = np.std(z_scores)
    recommended_sigma = std_z * 2.0
    
    bins_data = []
    for i in range(len(hist)):
        bin_center = (bin_edges[i] + bin_edges[i+1]) / 2.0
        bins_data.append({
            'bin': float(bin_center),
            'count': int(hist[i])
        })
        
    return {
        'bins': bins_data,
        'recommended_sigma': float(recommended_sigma),
        'mean': float(mean_z),
        'std': float(std_z),
        'total_points': len(z_scores)
    }

def update_strategy(style, speed):
    # Stub for UI compliance
    pass

def set_trade_size(bps):
    # Stub for UI compliance
    pass

def set_auto_trade(enabled):
    # Stub for UI compliance
    pass

def set_strategy_params(payload: dict):
    engine_instance.bus.publish('UPDATE_STRATEGY_PARAMS', payload)
