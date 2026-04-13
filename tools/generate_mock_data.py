import json
import random
import time

def generate():
    out = "test/resources/captures/mock_dual_asset.jsonl"
    print(f"Generating mock data to {out}")
    
    start_ts = int(time.time() * 1000)
    
    btc_price = 50000.0
    eth_price = 3000.0
    
    with open(out, 'w') as f:
        for i in range(10000):
            ts = start_ts + (i * 1000)
            
            # Random walk
            if i > 5000 and i < 6000:
                # Force a divergence
                btc_price += random.normalvariate(5.0, 10.0)
                eth_price += random.normalvariate(-1.0, 2.0)
            else:
                # Cointegrated move
                move = random.normalvariate(0, 10.0)
                btc_price += move
                eth_price += move * 0.06 + random.normalvariate(0, 1.0)
                
            # Emit BTC
            f.write(json.dumps({
                "symbol": "BTCUSDT",
                "timestamp": ts,
                "bid": btc_price - 0.5,
                "ask": btc_price + 0.5
            }) + "\n")
            
            # Emit ETH
            f.write(json.dumps({
                "symbol": "ETHUSDT",
                "timestamp": ts + 10, # Slightly offset
                "bid": eth_price - 0.5,
                "ask": eth_price + 0.5
            }) + "\n")
            
if __name__ == '__main__':
    generate()
