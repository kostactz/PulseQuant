import React, { useState } from 'react';
import { Play, Activity } from 'lucide-react';

interface ManualTradePanelProps {
  onTrade: (side: 'buy' | 'sell', bps: number) => void;
  targetAsset: string;
  featureAsset: string;
  disabled: boolean;
}

export function ManualTradePanel({ onTrade, targetAsset, featureAsset, disabled }: ManualTradePanelProps) {
  const [bpsInput, setBpsInput] = useState<string>('100'); // Default 100 bps (1%)

  const handleTrade = (side: 'buy' | 'sell') => {
    const bps = parseFloat(bpsInput);
    if (!isNaN(bps) && bps > 0) {
      onTrade(side, bps);
    }
  };

  return (
    <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl mt-6">
      <h2 className="text-lg font-bold text-gray-900 mb-2">Manual Execution</h2>
      <p className="text-sm text-gray-500 mb-4">
        Manually enter or exit a spread position.
      </p>

      <div className="flex flex-col md:flex-row gap-4 items-center">
        <div className="flex flex-col gap-1 w-full md:w-auto">
          <label className="text-xs font-semibold text-gray-500 uppercase">Notional Target (BPS)</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={bpsInput}
              onChange={(e) => setBpsInput(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2 w-32 focus:ring-blue-500 focus:border-blue-500 outline-none"
              placeholder="e.g. 100"
              disabled={disabled}
            />
            <span className="text-sm text-gray-500 font-medium">(= {parseFloat(bpsInput || '0') / 100}%)</span>
          </div>
        </div>

        <div className="flex flex-wrap gap-3 w-full md:w-auto">
          <button
            onClick={() => handleTrade('buy')}
            disabled={disabled}
            className="flex-1 md:flex-none flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg font-medium transition-colors bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm shadow-emerald-500/30"
          >
            <Play className="w-4 h-4" />
            <span>Long {targetAsset}</span>
          </button>
          <button
            onClick={() => handleTrade('sell')}
            disabled={disabled}
            className="flex-1 md:flex-none flex items-center justify-center gap-2 px-5 py-2.5 rounded-lg font-medium transition-colors bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed shadow-sm shadow-red-500/30"
          >
            <Activity className="w-4 h-4" />
            <span>Short {targetAsset}</span>
          </button>
        </div>
      </div>
    </div>
  );
}