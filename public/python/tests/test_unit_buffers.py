import pytest
import numpy as np
from public.python.engine import RingBuffer

def test_ringbuffer_basic():
    rb = RingBuffer(5)
    for i in range(3):
        rb.append(float(i))
    
    assert rb.count == 3
    assert rb.mean() == 1.0
    assert np.isclose(rb.std(), np.std([0, 1, 2]))

def test_ringbuffer_wrap_and_drift():
    rb = RingBuffer(5)
    
    # Push 10 elements to force wrapping and check rolling mean/std
    for i in range(10):
        rb.append(float(i))
        
    assert rb.count == 5
    # The last 5 elements are [5, 6, 7, 8, 9]
    assert rb.mean() == 7.0
    assert np.isclose(rb.std(), np.std([5, 6, 7, 8, 9]))
    
def test_ringbuffer_reanchor():
    rb = RingBuffer(10)
    
    # Push past the 1000 element threshold to test the re-anchor feature
    for i in range(2005):
        rb.append(100.0 + i)
        
    assert rb.count == 10
    # Expected mean is avg of [2095, 2096, ..., 2104] = 2099.5
    assert rb.mean() == 2099.5
    assert rb.std() > 0

def test_ringbuffer_constant_values():
    rb = RingBuffer(10)
    for i in range(20):
        rb.append(50.0)
        
    assert rb.mean() == 50.0
    assert rb.std() == 0.0
