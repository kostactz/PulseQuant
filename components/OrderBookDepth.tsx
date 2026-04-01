import React from 'react';

interface OrderBookDepthProps {
  bids: [number, number][];
  asks: [number, number][];
  currentBid?: number;
  currentAsk?: number;
}

export const OrderBookDepth: React.FC<OrderBookDepthProps> = ({ bids, asks, currentBid, currentAsk }) => {
  if (!bids || !asks || bids.length === 0 || asks.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500 text-sm">
        Waiting for order book data...
      </div>
    );
  }

  // Calculate max volume for scaling the depth bars
  const maxBidVol = Math.max(...bids.map((b) => b[1]));
  const maxAskVol = Math.max(...asks.map((a) => a[1]));
  const maxVol = Math.max(maxBidVol, maxAskVol);

  return (
    <div className="flex flex-col h-full text-sm font-mono">
      {/* Header */}
      <div className="grid grid-cols-3 text-gray-500 font-medium pb-2 border-b border-gray-200 mb-2 text-xs uppercase tracking-wider shrink-0">
        <div className="text-left">Size</div>
        <div className="text-center">Price</div>
        <div className="text-right">Size</div>
      </div>

      <div className="flex-1 flex flex-col justify-center">
        {/* Asks (Sell Orders) - Reversed to show lowest ask at the bottom */}
        <div className="flex flex-col-reverse gap-[2px]">
          {asks.map((ask, i) => {
            const [price, vol] = ask;
            const width = Math.max(1, (vol / maxVol) * 100);
            return (
              <div key={`ask-${i}`} className="relative grid grid-cols-3 items-center py-0.5 group text-xs">
                <div 
                  className="absolute right-0 top-0 bottom-0 bg-red-100 transition-all duration-100" 
                  style={{ width: `${width}%` }} 
                />
                <div className="text-left text-gray-600 z-10 pl-2">-</div>
                <div className="text-center text-red-600 z-10 font-medium">{price.toFixed(2)}</div>
                <div className="text-right text-gray-600 z-10 pr-2">{Math.round(vol)}</div>
              </div>
            );
          })}
        </div>

        {/* Spread Indicator */}
        <div className="flex items-center justify-center py-2 my-1 border-y border-gray-200 bg-gray-50 z-20">
          <span className="text-xs text-gray-500">
            Spread: {currentAsk && currentBid ? Math.abs(currentAsk - currentBid).toFixed(2) : Math.abs(asks[0][0] - bids[0][0]).toFixed(2)}
          </span>
        </div>

        {/* Bids (Buy Orders) */}
        <div className="flex flex-col gap-[2px]">
          {bids.map((bid, i) => {
            const [price, vol] = bid;
            const width = Math.max(1, (vol / maxVol) * 100);
            return (
              <div key={`bid-${i}`} className="relative grid grid-cols-3 items-center py-0.5 group text-xs">
                <div 
                  className="absolute left-0 top-0 bottom-0 bg-emerald-100 transition-all duration-100" 
                  style={{ width: `${width}%` }} 
                />
                <div className="text-left text-gray-600 z-10 pl-2">{Math.round(vol)}</div>
                <div className="text-center text-emerald-600 z-10 font-medium">{price.toFixed(2)}</div>
                <div className="text-right text-gray-600 z-10 pr-2">-</div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
