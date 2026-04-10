import pytest
import uuid
from public.python.engine import process_events, get_metrics, clear_data, set_auto_trade, set_immediate_execution, session, update_strategy


def _make_crossover_tick_data():
    """
    Builds a tick sequence designed to reliably trigger a Momentum Breakout signal:
    - Phase 1 (1100 ticks, price=99): populates the macro SMA buffer at ~99.
    - Phase 2 (100 ticks, price=97): micro_price drops below macro_sma.
    - Phase 3 (50 ticks, price=103, high +OFI): bullish crossover + strong OFI fires signal.
    Depth data is included so VPIN is computed correctly and passive signals are not blocked.
    """
    data = []
    ts = 1_700_000_000_000.0  # fixed epoch ms for reproducibility

    def make_tick(price, delta_bid, trade_vol):
        nonlocal ts
        bid = price - 0.05
        ask = price + 0.05
        row = {
            'timestamp': ts,
            'bid': bid, 'ask': ask, 'bid_vol': 10.0, 'ask_vol': 10.0,
            'delta_bid': delta_bid, 'delta_ask': -delta_bid,
            'trade_volume': trade_vol,
            'depth': {
                'bids': [[bid, 10.0], [bid - 0.1, 20.0], [bid - 0.2, 30.0]],
                'asks': [[ask, 10.0], [ask + 0.1, 20.0], [ask + 0.2, 30.0]]
            }
        }
        ts += 100.0
        return row

    for i in range(1100):
        data.append(make_tick(99.0, 0.1 if i % 2 == 0 else -0.1, 0.0))
    for _ in range(100):
        data.append(make_tick(97.0, -0.1, 0.0))
    for _ in range(50):
        data.append(make_tick(103.0, 5.0, 0.0))
    return data

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

def test_immediate_execution_mode():
    """Immediate execution mode should fill trades directly into the portfolio
    without routing through the order lifecycle (no PLACE_ORDER intents, no
    pending orders left behind)."""
    clear_data()
    set_auto_trade(True)
    set_immediate_execution(True)
    update_strategy('aggressive', 'fast')

    data = _make_crossover_tick_data()
    result = process_events(data)

    # No PLACE_ORDER intents should be generated in immediate mode
    intents = result.get('intents', [])
    place_order_intents = [i for i in intents if i.get('action') == 'PLACE_ORDER']
    assert place_order_intents == [], (
        f"Expected no PLACE_ORDER intents in immediate mode, got: {place_order_intents}"
    )

    # No orders should be sitting in the pending queue
    assert len(session.pending_orders) == 0, (
        f"Expected empty pending_orders in immediate mode, got {len(session.pending_orders)} orders"
    )

    # Trades should have been executed directly into the portfolio
    metrics = get_metrics()
    assert metrics['portfolio_value'] > 0
    trade_count = metrics.get('analytics', {}).get('total_trades', 0)
    assert trade_count > 0 or metrics.get('position', 0) != 0, (
        "Expected at least one trade to be executed immediately into the portfolio"
    )

    # Cleanup and ensure flag is reset so it doesn't pollute other tests
    set_immediate_execution(False)
    clear_data()
