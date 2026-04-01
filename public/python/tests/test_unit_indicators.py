import pytest
import numpy as np
import time
from public.python.engine import IndicatorState

def test_indicator_state_init():
    ind = IndicatorState()
    assert ind.latest['micro_price'] == 0.0
    assert ind.latest['vwap'] == 0.0

def test_deep_micro_price_fallback():
    ind = IndicatorState()
    ts = time.time()
    
    # Missing deep book info - fallback to top of book
    result = ind.update(100.0, 100.1, 10.0, 20.0, 0.0, 0.0, 0.0, ts)
    
    # Total volume = 30
    # Micro price = (Bid * AskVol + Ask * BidVol) / TotalVol
    # = (100.0 * 20.0 + 100.1 * 10.0) / 30.0 = (2000 + 1001) / 30 = 3001 / 30 = 100.0333...
    assert np.isclose(result['micro_price'], 100.033333333)

def test_deep_micro_price_exponential():
    ind = IndicatorState()
    ts = time.time()
    
    # Add deep book with lambda decay
    bids = [(100.0, 10.0), (99.9, 10.0)]
    asks = [(100.1, 20.0), (100.2, 20.0)]
    
    result = ind.update(100.0, 100.1, 10.0, 20.0, 0.0, 0.0, 0.0, ts, bids, asks)
    
    # Should calculate successfully and update micro-price
    assert result['micro_price'] > 100.0
    assert result['micro_price'] < 100.1

def test_time_decay_vwap():
    ind = IndicatorState()
    ts = time.time()
    
    # Trade volume > 0 sets initial VWAP
    res1 = ind.update(100.0, 100.2, 10.0, 10.0, 0.0, 0.0, 5.0, ts)
    assert res1['vwap'] > 0.0
    
    # Trade volume 0 causes VWAP to decay toward micro-price
    initial_vwap = res1['vwap']
    res2 = ind.update(105.0, 105.2, 10.0, 10.0, 0.0, 0.0, 0.0, ts + 0.2)
    
    assert res2['vwap'] > initial_vwap # Pulled slightly towards 105
