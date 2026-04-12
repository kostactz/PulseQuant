import pytest
import numpy as np
import pandas as pd
from public.python.engine import EWMABivariate, EWMASingle

def test_ewma_single():
    ewma = EWMASingle(window_size=10)
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    
    for x in data:
        ewma.append(x)
        
    assert ewma.count == 5
    # The mean is an EMA, so it will be weighted towards the recent values.
    assert ewma.mean > 2.0 and ewma.mean < 5.0
    assert ewma.std() > 0.0

def test_ewma_bivariate():
    window_size = 100
    ewma = EWMABivariate(window_size=window_size)
    
    # Create some linear data where y = 2x + 1
    np.random.seed(42)
    x_data = np.linspace(0, 10, 1000)
    y_data = 2.0 * x_data + 1.0 + np.random.normal(0, 0.1, 1000)
    
    for x, y in zip(x_data, y_data):
        ewma.append(x, y)
        
    assert ewma.count == 1000
    
    # Beta should be close to 2.0
    beta = ewma.get_beta()
    assert np.isclose(beta, 2.0, atol=0.1)

    ewma.reset()
    assert ewma.count == 0
    assert ewma.get_beta() == 0.0

def test_ewma_pandas_comparison():
    window_size = 50
    ewma_bi = EWMABivariate(window_size=window_size)
    
    np.random.seed(1)
    x_data = np.random.randn(200).cumsum()
    y_data = 1.5 * x_data + np.random.randn(200)
    
    betas = []
    for x, y in zip(x_data, y_data):
        ewma_bi.append(x, y)
        betas.append(ewma_bi.get_beta())
        
    df = pd.DataFrame({'x': x_data, 'y': y_data})
    
    # Use pandas to calculate EWMA covariance and variance
    cov = df['x'].ewm(span=window_size, adjust=False).cov(df['y'])
    var = df['x'].ewm(span=window_size, adjust=False).var()
    pd_betas = cov / var
    
    # Compare our O(1) implementation to pandas
    # Pandas EWM covariance might have a slightly different initialization or bias correction, 
    # but after warmup it should be very close.
    assert np.isclose(betas[-1], pd_betas.iloc[-1], rtol=0.05)
