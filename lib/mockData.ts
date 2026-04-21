export function generateMockTick(lastBid: number, lastAsk: number) {
  const change = (Math.random() - 0.5) * 0.5;
  const newBid = Math.max(1, lastBid + change);
  const newAsk = newBid + 0.05 + Math.random() * 0.05; 
  const midPrice = (newBid + newAsk) / 2;

  // Generate mock order book depth (100 levels to ensure we cover 10% range)
  const rawBids: [number, number][] = [];
  const rawAsks: [number, number][] = [];
  
  for (let i = 0; i < 100; i++) {
    rawBids.push([newBid - (i * 0.1), 100 + Math.random() * 500]);
    rawAsks.push([newAsk + (i * 0.1), 100 + Math.random() * 500]);
  }

  // Partition logic: 10% up (20 groups) and 10% down (20 groups)
  const partitionRange = 0.1; // 10%
  const partitionCount = 20;
  const binSize = (midPrice * partitionRange) / partitionCount;

  const groupLevels = (levels: [number, number][], isAsk: boolean) => {
    const bins: Record<number, number> = {};
    for (const [price, vol] of levels) {
      const priceDiff = isAsk ? price - midPrice : midPrice - price;
      if (priceDiff < 0 || priceDiff > midPrice * partitionRange) continue;
      
      const binIndex = Math.floor(priceDiff / binSize);
      if (binIndex >= partitionCount) continue;
      
      const binPrice = isAsk 
        ? midPrice + (binIndex + 1) * binSize 
        : midPrice - (binIndex + 1) * binSize;
      
      bins[binPrice] = (bins[binPrice] || 0) + vol;
    }
    
    return Object.entries(bins)
      .map(([p, v]) => [parseFloat(p), v] as [number, number])
      .sort((a, b) => isAsk ? a[0] - b[0] : b[0] - a[0]);
  };

  const bids = groupLevels(rawBids, false);
  const asks = groupLevels(rawAsks, true);
  
  return {
    timestamp: Date.now(),
    bid: newBid,
    ask: newAsk,
    bid_vol: rawBids[0][1],
    ask_vol: rawAsks[0][1],
    delta_bid: Math.random() > 0.5 ? Math.random() * 10 : 0,
    delta_ask: Math.random() > 0.5 ? Math.random() * 10 : 0,
    trade_volume: Math.random() > 0.3 ? Math.random() * 5 : 0,
    depth: { bids, asks },
    bids: rawBids.slice(0, 20),
    asks: rawAsks.slice(0, 20)
  };
}
