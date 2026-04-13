import pytest
from public.python.engine import EventBus, SignalGenerator
import numpy as np

def test_signal_generator_basic():
    bus = EventBus()
    sg = SignalGenerator(bus, target="BTC", feature="ETH")
    
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
    sg._on_model_updated({'is_ready': True, 'timestamp': 2000, 'target_price': 10.0, 'feature_price': 5.0, 'z_score': -2.5})
    assert len(signals) == 1
    assert signals[-1]['direction'] == 'LONG_SPREAD'

def test_signal_generator_timers():
    bus = EventBus()
    from public.python.engine import BackgroundAnalyticsWorker
    bg = BackgroundAnalyticsWorker(bus)
    sg = SignalGenerator(bus, target="BTC", feature="ETH")
    
    regimes = []
    def on_regime(payload):
        regimes.append(payload)
    bus.subscribe('REGIME_CHANGE', on_regime)
    
    np.random.seed(42)
    # Generate non-cointegrated data
    feature_prices = np.cumsum(np.random.normal(0, 1, 100)) + 100
    target_prices = np.cumsum(np.random.normal(0, 1, 100)) + 100
    
    for i in range(1, 101):
        sg._on_model_updated({
            'is_ready': True, 
            'timestamp': i * 1000, 
            'target_price': target_prices[i-1], 
            'feature_price': feature_prices[i-1], 
            'z_score': 0.5
        })
        
    sg._on_timer_1m({'timestamp': 100000})
    
    import time
    time.sleep(0.5) # Wait for thread pool to finish
    
    assert len(regimes) > 0
    assert regimes[-1]['toxic'] is True
