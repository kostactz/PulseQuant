import json
import random
import time
import argparse

def generate():
    parser = argparse.ArgumentParser(description='Generate mock dual-asset data')
    parser.add_argument('--target', type=str, default='BTCUSDT', help='Target asset symbol')
    parser.add_argument('--feature', type=str, default='ETHUSDT', help='Feature asset symbol')
    args = parser.parse_args()

    out = f"test/resources/captures/mock_dual_asset_{args.target}_{args.feature}.jsonl"
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
                
            # Emit Target
            f.write(json.dumps({
                "symbol": args.target,
                "timestamp": ts,
                "bid": btc_price - 0.5,
                "ask": btc_price + 0.5
            }) + "\n")
            
            # Emit Feature
            f.write(json.dumps({
                "symbol": args.feature,
                "timestamp": ts + 10, # Slightly offset
                "bid": eth_price - 0.5,
                "ask": eth_price + 0.5
            }) + "\n")
            
if __name__ == '__main__':
    generate()
