export function generateMockTick(lastBid: number, lastAsk: number) {
  const change = (Math.random() - 0.5) * 0.5;
  const newBid = Math.max(1, lastBid + change);
  const newAsk = newBid + 0.05 + Math.random() * 0.05; 
  
  // Generate mock order book depth (10 levels)
  const bids: [number, number][] = [];
  const asks: [number, number][] = [];
  let currentBidVol = 100 + Math.random() * 500;
  let currentAskVol = 100 + Math.random() * 500;
  
  for (let i = 0; i < 10; i++) {
    bids.push([newBid - (i * 0.05), currentBidVol]);
    asks.push([newAsk + (i * 0.05), currentAskVol]);
    currentBidVol += 50 + Math.random() * 200;
    currentAskVol += 50 + Math.random() * 200;
  }
  
  return {
    timestamp: Date.now(),
    bid: newBid,
    ask: newAsk,
    bid_vol: bids[0][1],
    ask_vol: asks[0][1],
    delta_bid: Math.random() > 0.5 ? Math.random() * 10 : 0,
    delta_ask: Math.random() > 0.5 ? Math.random() * 10 : 0,
    trade_volume: Math.random() > 0.3 ? Math.random() * 5 : 0,
    depth: { bids, asks },
    // Provide raw top-N levels to match BinanceAdapter shape
    bids,
    asks
  };
}
