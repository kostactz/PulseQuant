import pytest
from public.python.engine import StatArbModel, EventBus
import math

def test_statarb_model():
    bus = EventBus()
    
    events = []
    def on_model_update(payload):
        events.append(payload)
        
    bus.subscribe('MODEL_UPDATED', on_model_update)
    
    model = StatArbModel(bus, target="BTC", feature="ETH")
    
    # Warm up period
    for i in range(1, 100):
        bus.publish("TICK_BTC", {"bid": 10.0 + i*0.1, "ask": 10.2 + i*0.1, "timestamp": i*1000})
        bus.publish("TICK_ETH", {"bid": 5.0 + i*0.05, "ask": 5.1 + i*0.05, "timestamp": i*1000})
        
    assert len(events) > 0
    last_event = events[-1]
    
    assert 'beta' in last_event
    assert 'spread' in last_event
    assert 'z_score' in last_event
    
    assert model.is_ready
    
    # Check log math
    expected_target_price = (10.0 + 99*0.1 + 10.2 + 99*0.1) / 2.0
    expected_feature_price = (5.0 + 99*0.05 + 5.1 + 99*0.05) / 2.0
    
    assert math.isclose(model.target_price, expected_target_price)
    assert math.isclose(model.feature_price, expected_feature_price)
