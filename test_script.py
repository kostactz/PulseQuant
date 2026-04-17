import sys
sys.path.append('public/python')
from engine import StatArbModel, SignalGenerator, ExecutionManager, EventBus, PortfolioManager
import json

bus = EventBus()
portfolio = PortfolioManager(bus)
model = StatArbModel(bus, 'SUSHIUSDC', 'CAKEUSDC')
signal = SignalGenerator(bus, portfolio, 'SUSHIUSDC', 'CAKEUSDC')
exec_mgr = ExecutionManager(bus, portfolio, 'SUSHIUSDC', 'CAKEUSDC')

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
        else:
            model._on_feature_tick(evt['data'])
        i += 1

print("Total ticks:", i)
print("Logs:", len(logs))
for log in logs[:10]:
    print(log)
