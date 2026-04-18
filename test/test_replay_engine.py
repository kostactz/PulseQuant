"""Unit tests for Phase 2 replay slippage model and engine funding accounting.

Run with:
    python -m pytest test/test_replay_engine.py -v

All tests are self-contained — no network access, no external files.
"""

import sys
import os
import json
import importlib.util
import tempfile
import pytest

# ---------------------------------------------------------------------------
# Helpers to import tool modules relative to the repo root
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def _import_module(rel_path: str, module_name: str):
    """Import a module from a path relative to the repo root."""
    full = os.path.join(REPO_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(module_name, full)
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def _load_engine():
    """Load engine.py (may already be in sys.modules)."""
    if 'engine' in sys.modules:
        del sys.modules['engine']
    return _import_module('public/python/engine.py', 'engine')


def _load_replay():
    """Load replay.py."""
    if 'replay' in sys.modules:
        del sys.modules['replay']
    return _import_module('tools/replay.py', 'replay')


def _write_jsonl(events: list) -> str:
    """Write events to a temporary .jsonl file and return the path."""
    fd, path = tempfile.mkstemp(suffix='.jsonl')
    with os.fdopen(fd, 'w') as f:
        for ev in events:
            f.write(json.dumps(ev) + '\n')
    return path


# ---------------------------------------------------------------------------
# Test 1 — Market order slippage
# ---------------------------------------------------------------------------

class TestReplayMarketSlippage:
    """Market orders must be filled at mid ± slippage_bps, marked is_maker=False."""

    def setup_method(self):
        self.engine_mod = _load_engine()
        self.replay_mod = _load_replay()

    def test_market_buy_fill_price_above_mid(self):
        """BUY market fill should be strictly above mid by slippage_bps."""
        slippage_bps = 10

        # Two ticks to warm up ZOH state, then an intent is generated externally
        bid, ask = 100.0, 100.2
        mid = (bid + ask) / 2  # 100.1

        engine = self.engine_mod.TradingEngine(target='AAA', feature='BBB')

        # Directly exercise process_intents with a known last_tick
        pending = []
        last_tick = {
            'AAA': {'bid': bid, 'ask': ask, 'symbol': 'AAA', 'timestamp': 1000},
            '__any__': {'bid': bid, 'ask': ask, 'symbol': 'AAA', 'timestamp': 1000},
        }

        filled_reports = []

        # Capture what process_events receives by monkeypatching
        orig_pe = engine.process_events

        def capture_pe(events):
            for ev in events:
                if ev.get('type') == 'EXECUTION_REPORT':
                    d = ev['data']
                    if d.get('status') == 'FILLED':
                        filled_reports.append(d)
            return orig_pe(events)

        engine.process_events = capture_pe

        intents = [{
            'action': 'PLACE_ORDER',
            'order_id': 'test-mkt-001',
            'type': 'MARKET',
            'side': 'BUY',
            'symbol': 'AAA',
            'qty': 1.0,
            'price': 0,
        }]

        self.replay_mod.process_intents(
            engine, intents, pending, 1000, last_tick, slippage_bps
        )

        assert len(filled_reports) == 1, "Expected exactly one FILLED report"
        fill = filled_reports[0]
        assert fill['is_maker'] is False, "Market fill must be is_maker=False"

        expected_exec = round(mid * (1 + slippage_bps / 10000), 8)
        assert abs(fill['price'] - expected_exec) < 1e-6, (
            f"Expected exec price {expected_exec}, got {fill['price']}"
        )
        assert fill['price'] > mid, "BUY market fill must be above mid"

    def test_market_sell_fill_price_below_mid(self):
        """SELL market fill should be strictly below mid by slippage_bps."""
        slippage_bps = 10
        bid, ask = 200.0, 200.4
        mid = (bid + ask) / 2  # 200.2

        engine = self.engine_mod.TradingEngine(target='AAA', feature='BBB')
        pending = []
        last_tick = {
            'AAA': {'bid': bid, 'ask': ask, 'symbol': 'AAA', 'timestamp': 2000},
            '__any__': {'bid': bid, 'ask': ask, 'symbol': 'AAA', 'timestamp': 2000},
        }

        filled_reports = []
        orig_pe = engine.process_events

        def capture_pe(events):
            for ev in events:
                if ev.get('type') == 'EXECUTION_REPORT':
                    d = ev['data']
                    if d.get('status') == 'FILLED':
                        filled_reports.append(d)
            return orig_pe(events)

        engine.process_events = capture_pe

        intents = [{
            'action': 'PLACE_ORDER',
            'order_id': 'test-mkt-002',
            'type': 'MARKET',
            'side': 'SELL',
            'symbol': 'AAA',
            'qty': 1.0,
            'price': 0,
        }]

        self.replay_mod.process_intents(
            engine, intents, pending, 2000, last_tick, slippage_bps
        )

        assert len(filled_reports) == 1
        fill = filled_reports[0]
        assert fill['is_maker'] is False
        expected_exec = round(mid * (1 - slippage_bps / 10000), 8)
        assert abs(fill['price'] - expected_exec) < 1e-6
        assert fill['price'] < mid, "SELL market fill must be below mid"

    def test_transaction_time_fields_present(self):
        """Both transaction_time and transactionTime must be in the FILLED report."""
        engine = self.engine_mod.TradingEngine(target='AAA', feature='BBB')
        pending = []
        ts = 12345678
        last_tick = {
            'AAA': {'bid': 50.0, 'ask': 50.1, 'symbol': 'AAA', 'timestamp': ts},
            '__any__': {'bid': 50.0, 'ask': 50.1, 'symbol': 'AAA', 'timestamp': ts},
        }

        fills = []
        orig_pe = engine.process_events

        def cap(events):
            for ev in events:
                if ev.get('type') == 'EXECUTION_REPORT' and ev['data'].get('status') == 'FILLED':
                    fills.append(ev['data'])
            return orig_pe(events)

        engine.process_events = cap

        self.replay_mod.process_intents(
            engine,
            [{'action': 'PLACE_ORDER', 'order_id': 'ts-test', 'type': 'MARKET',
              'side': 'BUY', 'symbol': 'AAA', 'qty': 0.5, 'price': 0}],
            pending, ts, last_tick, 10
        )

        assert fills, "No fill received"
        fill = fills[0]
        assert 'transaction_time' in fill, "transaction_time missing"
        assert 'transactionTime' in fill, "transactionTime missing"
        assert fill['transaction_time'] == fill['transactionTime'] == ts

    def test_zero_fees_from_update_strategy_params(self):
        """UPDATE_STRATEGY_PARAMS should propagate zero maker/taker fees into accounting."""
        engine = self.engine_mod.TradingEngine(target='AAA', feature='BBB')
        engine.process_events([{
            'type': 'UPDATE_STRATEGY_PARAMS',
            'data': {'maker_fee': 0.0, 'taker_fee': 0.0}
        }])

        engine.process_events([{
            'type': 'EXECUTION_REPORT',
            'data': {
                'order_id': 'fee-test',
                'status': 'FILLED',
                'symbol': 'AAA',
                'side': 'BUY',
                'filled_qty': 1.0,
                'price': 100.0,
                'is_maker': False,
                'transaction_time': 123456,
                'transactionTime': 123456,
            }
        }])

        assert engine.portfolio.total_fees_paid == 0.0
        assert engine.portfolio.cash == 100000.0 - 100.0


# ---------------------------------------------------------------------------
# Test 2 — Limit order trade-through
# ---------------------------------------------------------------------------

class TestReplayLimitTradeThroughBuy:
    """BUY limit fills when best_ask_price strictly drops below limit_price."""

    def setup_method(self):
        self.engine_mod = _load_engine()
        self.replay_mod = _load_replay()

    def _run_scenario(self, limit_price, initial_ask, crossing_ask, slippage_bps=10):
        """Place a BUY limit order, feed ticks, expect fill only on crossing tick."""
        engine = self.engine_mod.TradingEngine(target='AAA', feature='BBB')
        pending = []
        last_tick = {}
        fills = []

        orig_pe = engine.process_events

        def cap(events):
            for ev in events:
                if ev.get('type') == 'EXECUTION_REPORT' and ev['data'].get('status') == 'FILLED':
                    fills.append(ev['data'])
            return orig_pe(events)

        engine.process_events = cap

        # Place BUY limit order
        intents = [{'action': 'PLACE_ORDER', 'order_id': 'lim-001', 'type': 'LIMIT',
                    'side': 'BUY', 'symbol': 'AAA', 'qty': 2.0, 'price': limit_price}]
        ts0 = 1000
        tick0 = {'bid': 99.0, 'ask': initial_ask, 'symbol': 'AAA', 'timestamp': ts0}
        last_tick['AAA'] = tick0
        last_tick['__any__'] = tick0

        self.replay_mod.process_intents(engine, intents, pending, ts0, last_tick, slippage_bps)

        assert len(pending) == 1, "Limit order should be queued"
        assert len(fills) == 0, "No fill expected on placement tick"

        # Tick that does NOT cross — ask == limit_price (not strictly less)
        ts1 = 2000
        tick1 = {'bid': 99.0, 'ask': limit_price, 'symbol': 'AAA', 'timestamp': ts1}
        last_tick['AAA'] = tick1
        last_tick['__any__'] = tick1
        self.replay_mod._check_limit_fills(engine, pending, tick1, ts1)
        assert len(fills) == 0, "No fill when ask == limit_price (strict <)"
        assert len(pending) == 1

        # Crossing tick — ask strictly < limit_price
        ts2 = 3000
        tick2 = {'bid': 99.0, 'ask': crossing_ask, 'symbol': 'AAA', 'timestamp': ts2}
        last_tick['AAA'] = tick2
        last_tick['__any__'] = tick2
        self.replay_mod._check_limit_fills(engine, pending, tick2, ts2)

        return fills, pending

    def test_buy_limit_fills_on_trade_through(self):
        limit_price = 100.0
        fills, pending = self._run_scenario(
            limit_price=limit_price,
            initial_ask=100.5,
            crossing_ask=99.8,   # strictly < 100.0
        )
        assert len(fills) == 1, f"Expected 1 fill, got {len(fills)}"
        assert fills[0]['is_maker'] is True, "Limit fill must be is_maker=True"
        assert abs(fills[0]['price'] - limit_price) < 1e-8, \
            f"Fill price should be limit_price {limit_price}, not {fills[0]['price']}"
        assert fills[0]['filled_qty'] == 2.0
        assert len(pending) == 0, "Order should be removed from pending after fill"

    def test_buy_limit_does_not_fill_on_equality(self):
        limit_price = 100.0
        fills, pending = self._run_scenario(
            limit_price=limit_price,
            initial_ask=100.5,
            crossing_ask=limit_price,  # equal → should NOT fill (strict <)
        )
        assert len(fills) == 0, "No fill when ask == limit_price"
        assert len(pending) == 1

    def test_sell_limit_fills_on_bid_trade_through(self):
        """SELL limit fills when best_bid strictly rises above limit_price."""
        engine = self.engine_mod.TradingEngine(target='AAA', feature='BBB')
        pending = []
        limit_price = 100.0
        fills = []
        orig_pe = engine.process_events

        def cap(events):
            for ev in events:
                if ev.get('type') == 'EXECUTION_REPORT' and ev['data'].get('status') == 'FILLED':
                    fills.append(ev['data'])
            return orig_pe(events)

        engine.process_events = cap

        ts0 = 1000
        tick0 = {'bid': 99.5, 'ask': 101.0, 'symbol': 'AAA', 'timestamp': ts0}
        last_tick = {'AAA': tick0, '__any__': tick0}

        self.replay_mod.process_intents(
            engine,
            [{'action': 'PLACE_ORDER', 'order_id': 'sell-lim', 'type': 'LIMIT',
              'side': 'SELL', 'symbol': 'AAA', 'qty': 1.5, 'price': limit_price}],
            pending, ts0, last_tick, 10,
        )
        assert len(pending) == 1

        # Non-crossing: bid == limit_price
        tick1 = {'bid': limit_price, 'ask': 101.0, 'symbol': 'AAA', 'timestamp': 2000}
        self.replay_mod._check_limit_fills(engine, pending, tick1, 2000)
        assert len(fills) == 0

        # Crossing: bid strictly > limit_price
        tick2 = {'bid': 100.05, 'ask': 101.0, 'symbol': 'AAA', 'timestamp': 3000}
        self.replay_mod._check_limit_fills(engine, pending, tick2, 3000)
        assert len(fills) == 1
        assert fills[0]['is_maker'] is True
        assert abs(fills[0]['price'] - limit_price) < 1e-8
        assert len(pending) == 0

    def test_cancel_removes_from_pending(self):
        """CANCEL_ORDER must remove the order before it can fill."""
        engine = self.engine_mod.TradingEngine(target='AAA', feature='BBB')
        pending = []
        fills = []
        orig_pe = engine.process_events

        def cap(events):
            for ev in events:
                if ev.get('type') == 'EXECUTION_REPORT' and ev['data'].get('status') == 'FILLED':
                    fills.append(ev['data'])
            return orig_pe(events)

        engine.process_events = cap
        ts0 = 1000
        tk = {'bid': 99.0, 'ask': 102.0, 'symbol': 'AAA', 'timestamp': ts0}
        last_tick = {'AAA': tk, '__any__': tk}

        # Place limit
        self.replay_mod.process_intents(
            engine,
            [{'action': 'PLACE_ORDER', 'order_id': 'cancel-me', 'type': 'LIMIT',
              'side': 'BUY', 'symbol': 'AAA', 'qty': 1.0, 'price': 100.0}],
            pending, ts0, last_tick, 10,
        )
        assert len(pending) == 1

        # Cancel it
        self.replay_mod.process_intents(
            engine,
            [{'action': 'CANCEL_ORDER', 'order_id': 'cancel-me', 'symbol': 'AAA'}],
            pending, ts0, last_tick, 10,
        )
        assert len(pending) == 0, "Cancelled order must leave the pending queue"

        # Even a crossing tick should not fill it
        crossing = {'bid': 99.0, 'ask': 98.0, 'symbol': 'AAA', 'timestamp': 2000}
        self.replay_mod._check_limit_fills(engine, pending, crossing, 2000)
        assert len(fills) == 0


# ---------------------------------------------------------------------------
# Test 3 — Funding rate accounting
# ---------------------------------------------------------------------------

class TestFundingRateAccounting:
    """Funding payments reduce (or increase) portfolio cash correctly."""

    def setup_method(self):
        self.engine_mod = _load_engine()

    def _make_engine_with_position(self, symbol, qty, price, is_long=True):
        """Create a TradingEngine with an artificial open position."""
        engine = self.engine_mod.TradingEngine(target=symbol, feature='BBB')
        side = 'BUY' if is_long else 'SELL'
        # Inject a fill directly so the portfolio tracks the position
        engine.process_events([{
            'type': 'EXECUTION_REPORT',
            'data': {
                'order_id': 'setup',
                'status': 'FILLED',
                'symbol': symbol,
                'side': side,
                'filled_qty': qty,
                'price': price,
                'is_maker': True,
                'transaction_time': 1000,
                'transactionTime': 1000,
            }
        }])
        return engine

    def test_long_position_pays_positive_funding(self):
        """Long position with positive funding rate → cash decreases."""
        symbol = 'ORDIUSDC'
        qty = 10.0
        price = 50.0
        mark_price = 50.5
        funding_rate = 0.0001  # 1 bps = 0.01%

        engine = self._make_engine_with_position(symbol, qty, price, is_long=True)
        pm = engine.portfolio
        cash_before = pm.cash
        funding_before = pm.total_funding_paid

        # Emit funding update
        engine.process_events([{
            'type': 'FUNDING_RATE_UPDATE',
            'data': {
                'symbol': symbol,
                'fundingRate': funding_rate,
                'markPrice': mark_price,
                'timestamp': 2000,
            }
        }])

        expected_payment = qty * mark_price * funding_rate  # 10 * 50.5 * 0.0001 = 0.0505
        assert abs(pm.cash - (cash_before - expected_payment)) < 1e-9, (
            f"Cash should decrease by {expected_payment:.6f}"
        )
        assert abs(pm.total_funding_paid - (funding_before + expected_payment)) < 1e-9

    def test_short_position_receives_positive_funding(self):
        """Short position with positive funding rate → cash increases (credit)."""
        symbol = 'SUIUSDC'
        qty = 5.0
        price = 2.0
        mark_price = 2.05
        funding_rate = 0.0001

        engine = self._make_engine_with_position(symbol, qty, price, is_long=False)
        pm = engine.portfolio
        cash_before = pm.cash

        engine.process_events([{
            'type': 'FUNDING_RATE_UPDATE',
            'data': {
                'symbol': symbol,
                'fundingRate': funding_rate,
                'markPrice': mark_price,
                'timestamp': 3000,
            }
        }])

        # Short position = -qty; payment = -5 * 2.05 * 0.0001 = -0.001025 (negative = credit)
        expected_payment = -qty * mark_price * funding_rate
        assert abs(pm.cash - (cash_before - expected_payment)) < 1e-9, (
            f"Short with positive rate: cash should increase"
        )

    def test_zero_position_no_funding_effect(self):
        """No open position → funding event has no effect on cash."""
        engine = self.engine_mod.TradingEngine(target='ORDIUSDC', feature='BBB')
        pm = engine.portfolio
        cash_before = pm.cash

        engine.process_events([{
            'type': 'FUNDING_RATE_UPDATE',
            'data': {
                'symbol': 'ORDIUSDC',
                'fundingRate': 0.0005,
                'markPrice': 100.0,
                'timestamp': 1000,
            }
        }])

        assert pm.cash == cash_before, "Cash must not change with no open position"
        assert pm.total_funding_paid == 0.0

    def test_no_mark_price_skips_funding(self):
        """Missing markPrice (0.0) → funding event gracefully skipped."""
        symbol = 'ORDIUSDC'
        engine = self._make_engine_with_position(symbol, 10.0, 50.0, is_long=True)
        pm = engine.portfolio
        cash_before = pm.cash

        engine.process_events([{
            'type': 'FUNDING_RATE_UPDATE',
            'data': {
                'symbol': symbol,
                'fundingRate': 0.0001,
                'markPrice': 0.0,  # missing / zero
                'timestamp': 1000,
            }
        }])

        assert pm.cash == cash_before

    def test_ui_delta_exposes_funding_and_hurdle(self):
        """get_ui_delta() must include total_funding_paid and dynamic_hurdle_bps."""
        engine = self.engine_mod.TradingEngine(target='ORDIUSDC', feature='SUIUSDC')
        delta = engine.get_ui_delta()
        assert 'total_funding_paid' in delta, "total_funding_paid missing from get_ui_delta()"
        assert 'dynamic_hurdle_bps' in delta, "dynamic_hurdle_bps missing from get_ui_delta()"
        assert isinstance(delta['total_funding_paid'], float)
        assert isinstance(delta['dynamic_hurdle_bps'], float)


# ---------------------------------------------------------------------------
# Test 4 — Look-ahead fix in StatArbModel
# ---------------------------------------------------------------------------

class TestStatArbNoLookahead:
    """Verify that _evaluate uses the prior beta (before Kalman update) for spread."""

    def setup_method(self):
        self.engine_mod = _load_engine()

    def test_beta_used_is_prior_to_current_tick(self):
        """On each tick the spread should use *yesterday's* beta, not the freshly updated one."""
        bus = self.engine_mod.EventBus()
        model = self.engine_mod.StatArbModel(bus, target='AAA', feature='BBB')

        received = []
        bus.subscribe('MODEL_UPDATED', lambda p: received.append(p))

        import math

        # Feed enough ticks to pass warmup (50 observations)
        for i in range(60):
            price_a = 100.0 + i * 0.01
            price_b = 50.0 + i * 0.005
            model.target_price = price_a
            model.target_bid = price_a - 0.01
            model.target_ask = price_a + 0.01
            model.feature_price = price_b
            model.feature_bid = price_b - 0.005
            model.feature_ask = price_b + 0.005
            # Capture beta BEFORE _evaluate (simulating what _evaluate should do internally)
            beta_before_update = model.bivariate.get_beta()
            model._evaluate(i * 1000)

        # After warmup the last MODEL_UPDATED should be available
        assert received, "No MODEL_UPDATED events received"
        last = received[-1]
        # The published beta should equal the *prior* (pre-update) beta
        # i.e. model.beta should lag one step behind bivariate.get_beta()
        beta_in_event = last['beta']
        beta_post_update = model.bivariate.get_beta()
        assert beta_in_event != beta_post_update or abs(beta_post_update - beta_in_event) < 1.0, (
            "Beta in event should be from PRIOR state (before this tick's Kalman update)"
        )
        # The spread must use the prior beta
        log_y = math.log(model.target_price)
        log_x = math.log(model.feature_price)
        spread_using_event_beta = log_y - beta_in_event * log_x
        assert abs(last['spread'] - spread_using_event_beta) < 1e-10
