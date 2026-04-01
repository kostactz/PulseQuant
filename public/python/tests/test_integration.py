import pytest
import uuid
from public.python.engine import process_events, get_metrics, clear_data, set_auto_trade, session, update_strategy

def test_integration_workflow(mock_tick_data):
    clear_data()
    set_auto_trade(True)
    update_strategy('aggressive', 'fast')
    
    # Get 1500 ticks of trending up data
    data = mock_tick_data(1500, trend='up')
    
    # Process
    process_events(data)
    metrics = get_metrics()
    
    assert metrics['portfolio_value'] > 0
    assert session.tick_counter == 1500
    
    # Clean up
    clear_data()
    assert session.portfolio.position == 0
    assert len(session.pending_orders) == 0

def test_cancellation_logic(mock_tick_data):
    clear_data()
    
    data = mock_tick_data(1)
    
    # Mocking a maker order
    order_id = str(uuid.uuid4())
    session.pending_orders[order_id] = {
        'side': 'buy',
        'qty': 1.0,
        'type': 'maker',
        'price': 90.0,
        'status': 'NEW',
        'submitted_at': data[0]['timestamp'] if data else 0,
    }
    
    # Process extreme down move to trigger toxicity cancellation
    # First 100 rows normal to build a balanced mean
    data_normal = mock_tick_data(100, trend='chop')
    process_events(data_normal)
    
    last_ts = data_normal[-1]['timestamp']
    
    # Next 100 rows skewed to spike the OFI Z-score downwards
    data_skew = mock_tick_data(100, trend='down', start_ts=last_ts + 100.0)
    for row in data_skew:
        row['delta_bid'] = -10.0
        row['delta_ask'] = 10.0
    
    res = process_events(data_skew)
    
    print(f"Cancel total: {session.canceled_orders_total}, toxicity state: {session.last_toxicity_state}")
    
    # The order should have been queued for cancel
    assert session.pending_orders[order_id]['status'] == 'PENDING_CANCEL'
    assert any(intent['action'] == 'CANCEL_ORDER' and intent['clientOrderId'] == order_id for intent in res['intents'])
