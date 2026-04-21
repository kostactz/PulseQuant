import { FundingRateData, MarketDataAdapter, NormalizedTick } from '../types';
import { generateMockTick } from '../../mockData';

export class MockAdapter implements MarketDataAdapter {
  private interval: NodeJS.Timeout | null = null;
  private tickCallback: ((tick: NormalizedTick) => void) | null = null;
  private lastBids: Record<string, number> = {};
  private lastAsks: Record<string, number> = {};
  private subscribedSymbols: Set<string> = new Set();
  private targetSymbol: string = '';
  private featureSymbol: string = '';

  async connect(): Promise<void> {
    if (this.interval) return;
    this.interval = setInterval(() => {
      let triggerDeviation = false;
      if (typeof window !== 'undefined' && (window as any).__TRIGGER_MASSIVE_DEVIATION__) {
        triggerDeviation = true;
        (window as any).__TRIGGER_MASSIVE_DEVIATION__ = false;
      }

      this.subscribedSymbols.forEach((symbol) => {
        let bid = this.lastBids[symbol] || 100.00;
        let ask = this.lastAsks[symbol] || 100.05;

        if (triggerDeviation && symbol === this.targetSymbol) {
          bid *= 1.10; // 10% jump on target
          ask *= 1.10;
        } else if (triggerDeviation && symbol === this.featureSymbol) {
          bid *= 0.90; // 10% drop on feature
          ask *= 0.90;
        }

        const tick = generateMockTick(bid, ask);
        tick.symbol = symbol;
        this.lastBids[symbol] = tick.bid;
        this.lastAsks[symbol] = tick.ask;

        if (this.tickCallback) {
          this.tickCallback(tick);
        }
      });
    }, 100);
  }

  async disconnect(): Promise<void> {
    if (this.interval) {
      clearInterval(this.interval);
      this.interval = null;
    }
  }

  subscribe(symbol: string): void {
    console.log(`[MockAdapter] Subscribed to ${symbol}`);
    this.subscribedSymbols.add(symbol);
    if (!this.lastBids[symbol]) this.lastBids[symbol] = 100.00;
    if (!this.lastAsks[symbol]) this.lastAsks[symbol] = 100.05;
  }

  unsubscribe(symbol: string): void {
    console.log(`[MockAdapter] Unsubscribed from ${symbol}`);
    this.subscribedSymbols.delete(symbol);
  }

  async setSymbols(target: string, feature: string): Promise<void> {
    this.targetSymbol = target;
    this.featureSymbol = feature;
  }

  onExecutionReport(callback: (report: any) => void): void {}

  onMarkPriceUpdate(_callback: (data: FundingRateData) => void): void {}

  onTick(callback: (tick: NormalizedTick) => void): void {
    this.tickCallback = callback;
  }
}
