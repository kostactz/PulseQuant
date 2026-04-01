import time
from public.python import engine


def make_indicator(micro_price=100.0, bb_std=0.0, ofi_ema=0.0, obi_norm=0.0, vwap=100.0, macro_sma=100.0):
    ind = {
        'micro_price': micro_price,
        'bb_std': bb_std,
        'ofi_ema': ofi_ema,
        'obi_norm': obi_norm,
        'vwap': vwap,
        'macro_sma': macro_sma,
        'prev_macro_sma': macro_sma
    }
    return ind


def test_hard_stop_minimum():
    strat = engine.TradingStrategy()
    strat.stop_min = 0.0015
    ind = make_indicator(micro_price=100.0, bb_std=0.0001)
    # Simulate a filled long position in portfolio
    pf = engine.Portfolio()
    pf.position = 1.0
    pf.avg_entry_price = 100.0

    # Price moves slightly within 10 bps, but a soft stop is now expected (maker exit)
    ind['micro_price'] = 100.0 * (1 - 0.001)  # 10 bps drop
    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, int(time.time() * 1000))
    assert tox['hard_stop'] >= 0.0015
    assert tox.get('soft_stop_long', False) is True
    assert sig == -1
    assert otype == 'maker'

def test_flow_invalidation_closes_long_with_time_buffer():
    strat = engine.TradingStrategy()
    strat.enable_flow_invalidation = True
    strat.flow_ofi_threshold = 0.5
    strat.flow_obi_threshold = 0.5
    strat.whipsaw_time_buffer_ms = 5000

    ind = make_indicator(micro_price=100.0, bb_std=0.0, ofi_ema=-0.6, obi_norm=-0.6)
    pf = engine.Portfolio()
    pf.position = 1.0
    pf.avg_entry_price = 100.0
    pf.open_lots.append({'timestamp': 0.0, 'qty': 1.0, 'price': 100.0})

    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, 6000)
    # Expect close signal (-1) because time in trade > adjusted whipsaw buffer
    assert sig == -1
    assert tox.get('flow_invalidated_long', False) is True
    assert tox.get('allow_flow_exit', False) is True
    assert otype == 'maker'


def test_flow_invalidation_closes_short_with_time_buffer():
    strat = engine.TradingStrategy()
    strat.enable_flow_invalidation = True
    strat.flow_ofi_threshold = 0.5
    strat.flow_obi_threshold = 0.5
    strat.whipsaw_time_buffer_ms = 5000

    ind = make_indicator(micro_price=100.0, bb_std=0.0, ofi_ema=0.6, obi_norm=0.6)
    pf = engine.Portfolio()
    pf.position = -1.0
    pf.avg_entry_price = 100.0
    pf.open_lots.append({'timestamp': 0.0, 'qty': 1.0, 'price': 100.0})

    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, 6000)
    # Expect close signal (1) because time in trade > adjusted whipsaw buffer
    assert sig == 1
    assert tox.get('flow_invalidated_short', False) is True
    assert tox.get('allow_flow_exit', False) is True
    assert otype == 'maker'


def test_flow_invalidation_not_allowed_in_first_5s():
    strat = engine.TradingStrategy()
    strat.enable_flow_invalidation = True
    strat.flow_ofi_threshold = 0.5
    strat.flow_obi_threshold = 0.5

    ind = make_indicator(micro_price=100.0, bb_std=0.0, ofi_ema=-0.6, obi_norm=-0.6)
    pf = engine.Portfolio()
    pf.position = 1.0
    pf.avg_entry_price = 100.0
    pf.open_lots.append({'timestamp': 5000.0, 'qty': 1.0, 'price': 100.0})

    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, 8000)
    # Expect no close because time_in_trade < 5s and no profit
    assert sig == 0
    assert tox.get('flow_invalidated_long', False) is False
    assert tox.get('allow_flow_exit', False) is False
    assert otype == 'maker'


def test_vpin_sweep_blocks_passive_absorption():
    strat = engine.TradingStrategy()
    ind = make_indicator(micro_price=100.0, bb_std=0.0, ofi_ema=-0.2, obi_norm=0.9, vwap=100.0, macro_sma=100.0)
    ind['vpin_sweep'] = True
    pf = engine.Portfolio()
    pf.position = 0.0
    pf.avg_entry_price = 0.0

    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, int(time.time() * 1000))
    assert sig == 0
    assert otype == 'maker'
    assert tox.get('vpin_sweep', False) is True


def test_toxicity_obi_raw_threshold():
    strat = engine.TradingStrategy()
    # raw OBI should be used (and EMA if available) for toxicity gating.
    ind = make_indicator(micro_price=100.0, bb_std=0.0, ofi_ema=0.0)
    ind['obi_raw'] = 0.82
    ind['obi_ema'] = 0.82
    pf = engine.Portfolio()
    pf.position = 0.0
    pf.avg_entry_price = 0.0

    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, int(time.time() * 1000))
    assert tox['cancel_sell_maker'] is False

    ind['obi_raw'] = -0.82
    ind['obi_ema'] = -0.82
    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, int(time.time() * 1000))
    assert tox['cancel_buy_maker'] is False


def test_soft_stop_closes_long_as_maker():
    strat = engine.TradingStrategy()
    ind = make_indicator(micro_price=99.30, bb_std=0.5, ofi_ema=0.0, obi_norm=0.0)
    pf = engine.Portfolio()
    pf.position = 1.0
    pf.avg_entry_price = 100.0

    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, int(time.time() * 1000))
    assert sig == -1
    assert otype == 'maker'
    assert tox.get('soft_stop_long', False) is True
    assert tox.get('hard_stop_long', False) is False
    assert tox.get('close_reason') == 'soft_stop'


def test_hard_stop_closes_long_as_taker():
    strat = engine.TradingStrategy()
    ind = make_indicator(micro_price=98.0, bb_std=0.5, ofi_ema=0.0, obi_norm=0.0)
    pf = engine.Portfolio()
    pf.position = 1.0
    pf.avg_entry_price = 100.0

    sig, bps, otype, tox, reason = strat.generate_signal(ind, pf, int(time.time() * 1000))
    assert sig == -1
    assert otype == 'taker'
    assert tox.get('hard_stop_long', False) is True
    assert tox.get('close_reason') == 'hard_stop'


def test_toxicity_min_rest_time_not_cancelled_before_threshold():
    engine.clear_data()
    session = engine.session
    session.strategy.enable_flow_invalidation = True
    session.strategy.obi_toxicity_threshold = 0.80

    # Create an open maker order that should be cancelled when toxicity gate triggers
    order = {
        'side': 'buy', 'qty': 1.0, 'type': 'maker', 'price': 100.0,
        'submitted_at': 0.0, 'ind': {}, 'reason': 'test', 'status': 'NEW'
    }
    session.pending_orders["test_id"] = order

    # Step 1: under resting period -> no cancellation
    row1 = {'timestamp': 1400.0, 'bid': 99.8, 'ask': 100.2,
            'bid_vol': 0.1, 'ask_vol': 1.0,'delta_bid': 0.0,'delta_ask': 0.0,'trade_volume':0.0,
            'bids': [[99.8, 0.1]], 'asks': [[100.2, 1.0]]}
    # supply OBI values via indicator from prior updates to qualify cancel conditions
    session.indicators.latest['obi_raw'] = -0.82
    session.indicators.latest['obi_ema'] = -0.82
    session.indicators.latest['ofi_ema'] = 0.0

    engine.process_events([row1])
    assert len(session.canceled_orders) == 0

    # Step 2: cross min rest threshold -> OBI under relaxed resting gate should not cancel
    row2 = row1.copy(); row2['timestamp'] = 1500.0
    # OBI is slightly beyond strict-but-not-beyond-resting threshold given multiplier=1.5
    session.indicators.latest['obi_raw'] = -0.82
    session.indicators.latest['obi_ema'] = -0.82
    engine.process_events([row2])
    assert len(session.canceled_orders) == 0
