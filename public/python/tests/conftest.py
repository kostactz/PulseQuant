import pytest
import time

@pytest.fixture
def mock_tick_data():
    def _generate(n=1000, trend='up', volatility=0.01, start_ts=None):
        data = []
        base_price = 100.0
        ts = start_ts if start_ts is not None else (time.time() * 1000)
        for i in range(n):
            if trend == 'up':
                base_price += volatility
            elif trend == 'down':
                base_price -= volatility
            else:
                base_price += (volatility if i % 2 == 0 else -volatility)
                
            bid = base_price - 0.05
            ask = base_price + 0.05
            
            data.append({
                'timestamp': ts,
                'bid': bid,
                'ask': ask,
                'bid_vol': 10.0 + (i % 5),
                'ask_vol': 10.0 + (i % 3),
                'delta_bid': 1.0 if i % 2 == 0 else -0.5,
                'delta_ask': -1.0 if i % 2 == 0 else 0.5,
                'trade_volume': 5.0 if i % 10 == 0 else 0.0,
                'bids': [[bid, 10.0], [bid - 0.1, 20.0]],
                'asks': [[ask, 10.0], [ask + 0.1, 20.0]]
            })
            ts += 100.0
        return data
        return data
    return _generate
