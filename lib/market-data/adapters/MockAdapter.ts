import { MarketDataAdapter, NormalizedTick } from '../types';
import { generateMockTick } from '../../mockData';

export class MockAdapter implements MarketDataAdapter {
  private interval: NodeJS.Timeout | null = null;
  private tickCallback: ((tick: NormalizedTick) => void) | null = null;
  private lastBid = 150.00;
  private lastAsk = 150.05;

  async connect(): Promise<void> {
    if (this.interval) return;
      this.interval = setInterval(() => {
        const tick = generateMockTick(this.lastBid, this.lastAsk);
      this.lastBid = tick.bid;
      this.lastAsk = tick.ask;
        if (this.tickCallback) {
          this.tickCallback(tick);
        }
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
  }

  unsubscribe(symbol: string): void {
    console.log(`[MockAdapter] Unsubscribed from ${symbol}`);
  }

  onExecutionReport(callback: (report: any) => void): void {}

  onTick(callback: (tick: NormalizedTick) => void): void {
    this.tickCallback = callback;
  }
}
