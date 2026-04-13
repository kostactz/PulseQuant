import math
import numpy as np
import logging
from typing import Dict, List, Any, Callable

# ==========================================
# 1. EVENT BUS & PUB-SUB CORE
# ==========================================
class EventBus:
    """Synchronous internal Pub-Sub dispatcher for high-frequency trading engine."""
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}

    def subscribe(self, topic: str, callback: Callable):
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(callback)

    def publish(self, topic: str, payload: Any):
        if topic in self.subscribers:
            for callback in self.subscribers[topic]:
                callback(payload)

# ==========================================
# 2. MATH UTILITIES & EWMA BIVARIATE BUFFER
# ==========================================
class EWMABivariate:
    """
    O(1) Exponentially Weighted Moving Average (EWMA) for covariance, variance, and means.
    Prevents drop-off shocks typical in SMA RingBuffers.
    """
    def __init__(self, window_size: float):
        self.alpha = 2.0 / (window_size + 1.0)
        self.initialized = False
        
        self.mean_x = 0.0
        self.mean_y = 0.0
        self.var_x = 0.0
        self.var_y = 0.0
        self.cov_xy = 0.0
        self.count = 0

    def append(self, x: float, y: float):
        if not self.initialized:
            self.mean_x = x
            self.mean_y = y
            self.var_x = 0.0
            self.var_y = 0.0
            self.cov_xy = 0.0
            self.initialized = True
            self.count = 1
            return

        self.count += 1
        
        diff_x = x - self.mean_x
        diff_y = y - self.mean_y
        
        self.mean_x += self.alpha * diff_x
        self.mean_y += self.alpha * diff_y
        
        # Update variance and covariance using new means
        new_diff_x = x - self.mean_x
        new_diff_y = y - self.mean_y
        
        self.var_x = (1.0 - self.alpha) * (self.var_x + self.alpha * diff_x * diff_x)
        self.var_y = (1.0 - self.alpha) * (self.var_y + self.alpha * diff_y * diff_y)
        self.cov_xy = (1.0 - self.alpha) * (self.cov_xy + self.alpha * diff_x * diff_y)

    def get_beta(self) -> float:
        if self.var_x < 1e-12:
            return 0.0
        return self.cov_xy / self.var_x

    def reset(self):
        self.initialized = False
        self.mean_x = 0.0
        self.mean_y = 0.0
        self.var_x = 0.0
        self.var_y = 0.0
        self.cov_xy = 0.0
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
        self.bivariate = EWMABivariate(self.w_beta)
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

        # 1. Update Bivariate Math
        self.bivariate.append(log_x, log_y)
        
        # Minimum warmup period
        if self.bivariate.count < min(50, self.w_beta // 4):
            return
            
        self.is_ready = True
        self.beta = self.bivariate.get_beta()
        
        # 2. Compute current Log-Spread
        self.spread = log_y - (self.beta * log_x)
        
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
    Computes low-frequency ADF cointegration and Half-life estimators on 1M timers.
    """
    def __init__(self, bus: EventBus, target: str, feature: str):
        self.bus = bus
        self.target = target
        self.feature = feature
        
        # Parameters
        self.entry_threshold = 2.0
        self.exit_threshold = 0.0
        self.max_half_life = 7200  # in periods
        
        self.is_toxic = False
        
        # Downsampled history buffers for low-freq math
        self.history_target = []
        self.history_feature = []
        self.last_hist_ts = 0
        
        self.bus.subscribe('MODEL_UPDATED', self._on_model_updated)
        self.bus.subscribe('TIMER_1M', self._on_timer_1m)
        
    def _on_model_updated(self, payload: dict):
        if not payload['is_ready']:
            return
            
        ts = payload['timestamp']
        # Keep 1 data point per second roughly for history
        if ts - self.last_hist_ts >= 1000:
            self.history_target.append(payload['target_price'])
            self.history_feature.append(payload['feature_price'])
            self.last_hist_ts = ts
            
            # Maintain max history buffer length (e.g. 5000)
            if len(self.history_target) > 5000:
                self.history_target.pop(0)
                self.history_feature.pop(0)
                
        z_score = payload['z_score']
        
        # Entry signals
        if not self.is_toxic:
            if z_score < -self.entry_threshold:
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'LONG_SPREAD', 'z_score': z_score})
            elif z_score > self.entry_threshold:
                self.bus.publish('SIGNAL_GENERATED', {'direction': 'SHORT_SPREAD', 'z_score': z_score})
                
        # Exit logic
        if abs(z_score) <= self.exit_threshold:
            self.bus.publish('SIGNAL_GENERATED', {'direction': 'CLOSE_SPREAD', 'z_score': z_score})

    def _on_timer_1m(self, payload: dict):
        if len(self.history_target) < 50:
            return
            
        try:
            import numpy as np
            import statsmodels.api as sm
            from statsmodels.tsa.stattools import coint
            
            target_arr = np.array(self.history_target)
            feature_arr = np.array(self.history_feature)
            
            # 1. ADF Cointegration test
            score, p_value, _ = coint(target_arr, feature_arr)
            
            # 2. OU Half-life estimate
            X = sm.add_constant(feature_arr)
            model = sm.OLS(target_arr, X).fit()
            spread = model.resid
            
            spread_lag = spread[:-1]
            spread_diff = np.diff(spread)
            
            X_hl = sm.add_constant(spread_lag)
            hl_model = sm.OLS(spread_diff, X_hl).fit()
            lam = hl_model.params[1] if len(hl_model.params) > 1 else 0.0
            
            if lam < 0:
                half_life_periods = -np.log(2) / lam
            else:
                half_life_periods = np.inf
                
            # Toxicity Gating
            is_coint = p_value < 0.05
            is_hl_valid = half_life_periods < self.max_half_life
            
            was_toxic = self.is_toxic
            self.is_toxic = not (is_coint and is_hl_valid)
            
            if self.is_toxic and not was_toxic:
                self.bus.publish('REGIME_CHANGE', {'toxic': True, 'p_value': p_value, 'half_life': half_life_periods})
            elif not self.is_toxic and was_toxic:
                self.bus.publish('REGIME_CHANGE', {'toxic': False, 'p_value': p_value, 'half_life': half_life_periods})
                
        except Exception as e:
            # Fallback to toxic if math fails
            if not self.is_toxic:
                self.is_toxic = True
                self.bus.publish('REGIME_CHANGE', {'toxic': True, 'error': str(e)})

# ==========================================
# 5. PORTFOLIO & EXECUTION MANAGERS
# ==========================================
import uuid

class PortfolioManager:
    """
    Tracks dual-asset positions, cash, and calculates net delta.
    """
    def __init__(self, bus: EventBus, target: str, feature: str):
        self.bus = bus
        self.target = target
        self.feature = feature
        self.positions = {target: 0.0, feature: 0.0}
        self.cash = 100000.0
        
        self.bus.subscribe('ORDER_UPDATE', self._on_order_update)
        
    def _on_order_update(self, payload: dict):
        status = payload.get('status')
        if status == 'FILLED':
            symbol = payload['symbol']
            qty = float(payload.get('filled_qty', 0.0))
            price = float(payload.get('price', 0.0))
            side = payload.get('side', '')
            
            sign = 1.0 if side == 'BUY' else -1.0
            
            if symbol in self.positions:
                self.positions[symbol] += qty * sign
                self.cash -= qty * price * sign

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
    def __init__(self, bus: EventBus, target: str, feature: str, portfolio: PortfolioManager):
        self.bus = bus
        self.target = target
        self.feature = feature
        self.portfolio = portfolio
        
        self.state = "IDLE"
        self.active_maker_order_id = None
        self.pending_leg2 = None
        
        self.latest_beta = 1.0
        self.target_price = 0.0
        self.feature_price = 0.0
        
        self.base_size = 0.1 # Trade size for the target asset
        
        self.bus.subscribe('SIGNAL_GENERATED', self._on_signal)
        self.bus.subscribe('ORDER_UPDATE', self._on_order_update)
        self.bus.subscribe('MODEL_UPDATED', self._on_model_update)
        
    def _on_model_update(self, payload: dict):
        if payload.get('is_ready'):
            self.latest_beta = float(payload.get('beta', 1.0))
            self.target_price = float(payload.get('target_price', 0.0))
            self.feature_price = float(payload.get('feature_price', 0.0))

    def _on_signal(self, payload: dict):
        direction = payload.get('direction')
        
        if direction == 'LONG_SPREAD' and self.state == 'IDLE':
            # Buy Target (Maker), Sell Feature (Taker)
            self._enter_spread('BUY', 'SELL')
            
        elif direction == 'SHORT_SPREAD' and self.state == 'IDLE':
            # Sell Target (Maker), Buy Feature (Taker)
            self._enter_spread('SELL', 'BUY')
            
        elif direction == 'CLOSE_SPREAD':
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
                # Market exit both legs immediately
                self.state = 'IDLE'
                
                target_pos = self.portfolio.positions[self.target]
                feature_pos = self.portfolio.positions[self.feature]
                
                if abs(target_pos) > 1e-8:
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'PLACE_ORDER',
                        'order_id': str(uuid.uuid4()),
                        'symbol': self.target,
                        'side': 'SELL' if target_pos > 0 else 'BUY',
                        'type': 'MARKET',
                        'qty': abs(target_pos)
                    })
                if abs(feature_pos) > 1e-8:
                    self.bus.publish('OUTBOUND_INTENT', {
                        'action': 'PLACE_ORDER',
                        'order_id': str(uuid.uuid4()),
                        'symbol': self.feature,
                        'side': 'SELL' if feature_pos > 0 else 'BUY',
                        'type': 'MARKET',
                        'qty': abs(feature_pos)
                    })

    def _enter_spread(self, target_side: str, feature_side: str):
        if self.feature_price == 0 or self.target_price == 0:
            return
            
        self.state = 'LEGGING_MAKER_ENTRY'
        self.active_maker_order_id = str(uuid.uuid4())
        
        # Calculate feature qty based on Beta and Notional ratio
        # Feature Notional = Target Notional * Beta
        feature_qty = self.base_size * (self.target_price / self.feature_price) * abs(self.latest_beta)
        
        self.pending_leg2 = {
            'order_id': str(uuid.uuid4()),
            'symbol': self.feature,
            'side': feature_side,
            'type': 'MARKET',
            'qty': feature_qty
        }
        
        self.bus.publish('OUTBOUND_INTENT', {
            'action': 'PLACE_ORDER',
            'order_id': self.active_maker_order_id,
            'symbol': self.target,
            'side': target_side,
            'type': 'LIMIT',
            'qty': self.base_size,
            'price': self.target_price
        })

    def _on_order_update(self, payload: dict):
        status = payload.get('status')
        order_id = payload.get('order_id')
        
        if self.state == 'LEGGING_MAKER_ENTRY' and order_id == self.active_maker_order_id:
            if status == 'FILLED' and self.pending_leg2 is not None:
                # Leg 1 Filled! Immediately send Market order for Leg 2
                self.bus.publish('OUTBOUND_INTENT', {
                    'action': 'PLACE_ORDER',
                    'order_id': self.pending_leg2['order_id'],
                    'symbol': self.pending_leg2['symbol'],
                    'side': self.pending_leg2['side'],
                    'type': self.pending_leg2['type'],
                    'qty': self.pending_leg2['qty']
                })
                self.state = 'HEDGED'
                self.active_maker_order_id = None
                self.pending_leg2 = None
                
            elif status in ['CANCELED', 'REJECTED', 'EXPIRED']:
                # Legging failed
                self.state = 'IDLE'
                self.active_maker_order_id = None
                self.pending_leg2 = None

# ==========================================
# 6. ENGINE ENTRY POINT
# ==========================================
class TradingEngine:
    def __init__(self, target='BTCUSDT', feature='ETHUSDT'):
        self.bus = EventBus()
        self.model = StatArbModel(self.bus, target=target, feature=feature)
        self.signal_generator = SignalGenerator(self.bus, target=target, feature=feature)
        self.portfolio = PortfolioManager(self.bus, target=target, feature=feature)
        self.execution = ExecutionManager(self.bus, target=target, feature=feature, portfolio=self.portfolio)
        self.target = target
        self.feature = feature
        self.last_ts = 0
        self.last_1s_timer = 0
        self.last_1m_timer = 0

    def configure_strategy(self, target: str, feature: str):
        self.target = target.upper()
        self.feature = feature.upper()
        
        self.bus = EventBus()
        self.model = StatArbModel(self.bus, target=self.target, feature=self.feature)
        self.signal_generator = SignalGenerator(self.bus, target=self.target, feature=self.feature)
        self.portfolio = PortfolioManager(self.bus, target=self.target, feature=self.feature)
        self.execution = ExecutionManager(self.bus, target=self.target, feature=self.feature, portfolio=self.portfolio)
        
        self.last_ts = 0
        self.last_1s_timer = 0
        self.last_1m_timer = 0

    def process_events(self, events: List[dict]):
        intents = []
        # Temporarily intercept intents from the bus
        def on_intent(intent):
            intents.append(intent)
        self.bus.subscribe('OUTBOUND_INTENT', on_intent)

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

        return {'intents': intents}

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
            'positions': self.portfolio.positions,
            'net_delta': self.portfolio.get_net_delta(self.model.target_price, self.model.feature_price),
            'spread_metrics': {
                'current_spread': self.model.spread,
                'z_score': self.model.z_score,
                'beta': self.model.beta,
                'is_ready': self.model.is_ready,
                'target_price': self.model.target_price,
                'feature_price': self.model.feature_price
            },
            'toxicity_flag': self.signal_generator.is_toxic,
            'execution_state': self.execution.state,
            'recent_trades': [],
            'pending_orders': []
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

def update_strategy(style, speed):
    # Stub for UI compliance
    pass

def set_trade_size(bps):
    # Stub for UI compliance
    pass

def set_auto_trade(enabled):
    # Stub for UI compliance
    pass
