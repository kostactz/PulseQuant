import pytest
import math
from public.python.engine import EventBus, PortfolioManager, ExecutionManager

def test_async_legging_state_machine():
    bus = EventBus()
    portfolio = PortfolioManager(bus, "BTC", "ETH")
    exec_mgr = ExecutionManager(bus, "BTC", "ETH", portfolio)
    
    intents = []
    def on_intent(payload):
        intents.append(payload)
    bus.subscribe('OUTBOUND_INTENT', on_intent)
    
    # 1. Provide Model Prices
    bus.publish('MODEL_UPDATED', {
        'is_ready': True,
        'beta': 0.5, 
        'target_price': 100.0, 
        'feature_price': 10.0,
        'timestamp': 1000
    })
    
    # 2. Trigger LONG_SPREAD
    bus.publish('SIGNAL_GENERATED', {'direction': 'LONG_SPREAD'})
    
    # Check Maker Intent
    assert exec_mgr.state == 'LEGGING_MAKER_ENTRY'
    assert len(intents) == 1
    maker_intent = intents[0]
    assert maker_intent['action'] == 'PLACE_ORDER'
    assert maker_intent['symbol'] == 'BTC'
    assert maker_intent['side'] == 'BUY'
    assert maker_intent['type'] == 'LIMIT'
    
    # 3. Simulate Maker Fill
    bus.publish('ORDER_UPDATE', {
        'order_id': maker_intent.get('order_id', 'unknown'),
        'symbol': 'BTC',
        'status': 'FILLED',
        'side': 'BUY',
        'filled_qty': maker_intent['qty'],
        'price': maker_intent['price']
    })
    
    # Check Portfolio updated and Taker Intent fired
    assert math.isclose(portfolio.positions['BTC'], maker_intent['qty'])
    assert exec_mgr.state == 'HEDGED'
    assert len(intents) == 2
    taker_intent = intents[1]
    assert taker_intent['action'] == 'PLACE_ORDER'
    assert taker_intent['symbol'] == 'ETH'
    assert taker_intent['side'] == 'SELL'
    assert taker_intent['type'] == 'LIMIT'
    
    # Expected Qty of Feature = Qty_Y * (Price_Y / Price_X) * Beta
    # = exec_mgr.base_size * (100 / 10) * 0.5 = base_size * 5
    expected_qty = exec_mgr.base_size * 5.0
    assert math.isclose(taker_intent['qty'], expected_qty)
    
    # Check slippage (5 bps = 0.0005. Price = 10.0, Sell order price = 10 * (1 - 0.0005) = 9.995)
    assert taker_intent['price'] < 10.0
    
    # 4. Simulate Taker Fill
    bus.publish('ORDER_UPDATE', {
        'order_id': taker_intent.get('order_id', 'taker_1'),
        'symbol': 'ETH',
        'status': 'FILLED',
        'side': 'SELL',
        'filled_qty': taker_intent['qty'],
        'price': 10.0
    })
    
    assert math.isclose(portfolio.positions['ETH'], -expected_qty)
    
    # 5. Trigger Close
    bus.publish('SIGNAL_GENERATED', {'direction': 'CLOSE_SPREAD'})
    assert exec_mgr.state == 'IDLE'
    assert len(intents) == 4
    
    close_intent_1 = intents[2]
    close_intent_2 = intents[3]
    
    symbols = [close_intent_1['symbol'], close_intent_2['symbol']]
    assert 'BTC' in symbols
    assert 'ETH' in symbols
    
    # Both should be LIMIT orders with slippage protection
    assert close_intent_1['type'] == 'LIMIT'
    assert close_intent_2['type'] == 'LIMIT'
    assert 'price' in close_intent_1
    assert 'price' in close_intent_2
