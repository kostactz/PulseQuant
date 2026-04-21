import pytest
from public.python.engine import EventBus, SignalGenerator, PortfolioManager
import numpy as np

def test_signal_generator_basic():
    bus = EventBus()
    portfolio = PortfolioManager(bus, "BTC", "ETH")
    sg = SignalGenerator(bus, target="BTC", feature="ETH", portfolio=portfolio)
    
    signals = []
    regimes = []
    
    def on_signal(payload):
        signals.append(payload)
        
    def on_regime(payload):
        regimes.append(payload)
        
    bus.subscribe('SIGNAL_GENERATED', on_signal)
    bus.subscribe('REGIME_CHANGE', on_regime)
    
    # Send ready, but Z-score is low
    sg._on_model_updated({'is_ready': True, 'timestamp': 1000, 'target_price': 10.0, 'feature_price': 5.0, 'z_score': 1.0})
    assert len(signals) == 0
    
    # Trigger long spread signal
    import math
    sg.maker_fee = 0
    sg.taker_fee = 0
    sg._on_model_updated({
        'is_ready': True,
        'timestamp': 2000,
        'target_price': 10.0,
        'feature_price': 150.0,
        'beta': 1.0,
        'spread_mean': 0.0,
        'spread_std': 1.0,
        'z_score': -2.5
    })
    assert len(signals) == 1
    assert signals[-1]['direction'] == 'LONG_SPREAD'

def test_signal_generator_timers():
    bus = EventBus()
    from public.python.engine import BackgroundAnalyticsWorker
    bg = BackgroundAnalyticsWorker(bus)
    portfolio = PortfolioManager(bus, "BTC", "ETH")
    sg = SignalGenerator(bus, target="BTC", feature="ETH", portfolio=portfolio)
    
    regimes = []
    def on_regime(payload):
        regimes.append(payload)
    bus.subscribe('REGIME_CHANGE', on_regime)
    
    np.random.seed(42)
    # Generate non-cointegrated data
    feature_prices = np.cumsum(np.random.normal(0, 1, 100)) + 100
    target_prices = np.cumsum(np.random.normal(0, 1, 100)) + 100
    
    target_data = []
    feature_data = []
    for i in range(1, 101):
        ts = i * 1000
        target_data.append([ts, target_prices[i-1]])
        feature_data.append([ts, feature_prices[i-1]])
        
    bg._run_analytics({
        'targetData': target_data,
        'featureData': feature_data
    })
    
    bus.thread_pool.shutdown(wait=True)
    
    assert len(regimes) > 0
    assert regimes[-1]['toxic'] is True
