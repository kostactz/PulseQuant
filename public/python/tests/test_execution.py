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
    exec_mgr.slippage_bps = 500.0 # 5% slippage so it survives 2 decimal rounding
    bus.publish('SIGNAL_GENERATED', {'direction': 'LONG_SPREAD', 'target_notional': 1000.0})
    
    # Check Maker Intent
    assert exec_mgr.state == 'HEDGED'
    assert len(intents) == 2
    maker_intent = intents[0]
    assert maker_intent['action'] == 'PLACE_ORDER'
    assert maker_intent['symbol'] == 'BTC'
    assert maker_intent['side'] == 'BUY'
    assert maker_intent['type'] == 'MARKET'
    
    taker_intent = intents[1]
    assert taker_intent['action'] == 'PLACE_ORDER'
    assert taker_intent['symbol'] == 'ETH'
    assert taker_intent['side'] == 'SELL'
    assert taker_intent['type'] == 'MARKET'
    
    # 3. Simulate Fills
    bus.publish('ORDER_UPDATE', {
        'order_id': maker_intent.get('order_id', 'unknown'),
        'symbol': 'BTC',
        'status': 'FILLED',
        'side': 'BUY',
        'filled_qty': maker_intent['qty'],
        'price': maker_intent['price']
    })
    
    bus.publish('ORDER_UPDATE', {
        'order_id': taker_intent.get('order_id', 'taker_1'),
        'symbol': 'ETH',
        'status': 'FILLED',
        'side': 'SELL',
        'filled_qty': taker_intent['qty'],
        'price': 10.0
    })
    
    # 5. Trigger Close
    portfolio.positions['BTC'] = maker_intent['qty']
    portfolio.positions['ETH'] = -taker_intent['qty']
    
    bus.publish('SIGNAL_GENERATED', {'direction': 'CLOSE_SPREAD'})
    assert exec_mgr.state == 'CLOSING'
    assert len(intents) == 4
    
    close_intent_1 = intents[2]
    close_intent_2 = intents[3]
    
    symbols = [close_intent_1['symbol'], close_intent_2['symbol']]
    assert 'BTC' in symbols
    assert 'ETH' in symbols
    
    assert close_intent_1['type'] == 'MARKET'
    assert close_intent_2['type'] == 'MARKET'
