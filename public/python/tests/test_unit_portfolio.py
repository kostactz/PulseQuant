import pytest
import time
from public.python.engine import Portfolio

def test_portfolio_init():
    p = Portfolio(initial_capital=100000.0)
    assert p.capital == 100000.0
    assert p.position == 0

def test_portfolio_execution_long():
    p = Portfolio()
    ts = time.time()
    
    # Buy 1 BTC at $50k (Taker fee: 0.04%)
    p.execute_trade('buy', 1.0, 50000.0, ts, 'taker')
    
    assert p.position == 1.0
    fee = 50000.0 * 1.0 * 0.0005
    assert p.capital == 100000.0 - 50000.0 - fee
    assert len(p.open_lots) == 1
    
def test_portfolio_fifo_matching():
    p = Portfolio()
    ts = time.time()
    
    # Buy 1 at 100, Maker (fee rebate 0.01%)
    p.execute_trade('buy', 1.0, 100.0, ts, 'maker')
    
    # Buy 2 at 110, Taker
    p.execute_trade('buy', 2.0, 110.0, ts + 1, 'taker')
    
    assert p.position == 3.0
    assert len(p.open_lots) == 2
    
    # Sell 1.5 at 120, Maker
    p.execute_trade('sell', 1.5, 120.0, ts + 2, 'maker')
    
    assert p.position == 1.5
    assert len(p.closed_trades) == 1 # 1.5 aggregated close event across FIFO matching
    
    # Verify profit
    analytics = p.get_trade_analytics()
    assert analytics['total_trades'] == 1
    assert analytics['hit_ratio'] == 1.0 # Closed trade was profitable
