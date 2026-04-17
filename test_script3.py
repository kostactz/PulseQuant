import sys
sys.path.append('public/python')
from engine import StatArbModel, SignalGenerator, ExecutionManager, EventBus, PortfolioManager
import json

bus = EventBus()
portfolio = PortfolioManager(bus, 'SUSHIUSDC', 'CAKEUSDC')
model = StatArbModel(bus, 'SUSHIUSDC', 'CAKEUSDC')
signal = SignalGenerator(bus, 'SUSHIUSDC', 'CAKEUSDC', portfolio)
exec_mgr = ExecutionManager(bus, 'SUSHIUSDC', 'CAKEUSDC', portfolio)

signal._on_update_params({
    'sigma_threshold': 0.1,
    'min_entry_spread_bps': 0.0,
    'min_beta': 0.0,
    'max_beta': 2.0,
    'taker_fee': 0.0,
    'slippage_bps': 0.0
})

logs = []
def print_log(payload):
    logs.append(payload)

bus.subscribe('LOG', print_log)
bus.subscribe('SIGNAL_GENERATED', print_log)

i = 0
for line in open('capture_small.jsonl'):
    evt = json.loads(line)
    if 'timestamp' in evt['data']:
        if evt['data']['symbol'] == 'SUSHIUSDC':
            model._on_target_tick(evt['data'])
            # simulate a full update trigger
            if model.is_ready:
                signal._on_model_updated({
                    'is_ready': True,
                    'target_price': model.target_price,
                    'feature_price': model.feature_price,
                    'target_ask': model.target_ask,
                    'feature_bid': model.feature_bid,
                    'target_bid': model.target_bid,
                    'feature_ask': model.feature_ask,
                    'spread': model.spread,
                    'z_score': model.z_score,
                    'beta': model.beta,
                    'spread_mean': model.spread_stats.mean,
                    'spread_std': model.spread_stats.std()
                })
        else:
            model._on_feature_tick(evt['data'])
        i += 1

print("Total ticks:", i)
print("Logs:", len(logs))
for log in logs[:10]:
    print(log)
