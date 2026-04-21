export interface NormalizedDepth {
  bids: [number, number][]; // [price, size]
  asks: [number, number][];
}

export interface NormalizedTick {
  symbol?: string;
  timestamp: number;
  bid: number;
  ask: number;
  bid_vol: number;
  ask_vol: number;
  delta_bid: number;
  delta_ask: number;
  trade_volume: number;
  depth: NormalizedDepth;
  // Raw top-N levels (un-grouped) for deeper microstructure analysis
  bids?: [number, number][]; // [price, size]
  asks?: [number, number][];
}

export interface FundingRateData {
  symbol: string;
  fundingRate: number;
  markPrice: number;
  timestamp: number;
}

export interface MarketDataAdapter {
  connect(): Promise<void>;
  disconnect(): Promise<void>;
  subscribe(symbol: string): void;
  unsubscribe(symbol: string): void;
  setSymbols?(target: string, feature: string): Promise<void>;
  onTick(callback: (tick: NormalizedTick) => void): void;
  onExecutionReport?(callback: (report: any) => void): void;
  onSyncState?(callback: (state: any) => void): void;
  onMarkPriceUpdate?(callback: (data: FundingRateData) => void): void;
}
