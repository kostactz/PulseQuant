import { MarketDataAdapter, NormalizedTick } from './types';
import { MockAdapter } from './adapters/MockAdapter';

export class MarketDataService {
  private adapter: MarketDataAdapter;
  private tickListeners: Set<(tick: NormalizedTick) => void> = new Set();
  private isConnected: boolean = false;

  constructor(adapter?: MarketDataAdapter) {
    // Default to MockAdapter, but can be injected with BinanceAdapter, CoinbaseAdapter, etc.
    this.adapter = adapter || new MockAdapter();
    this.adapter.onTick(this.handleTick.bind(this));
  }

  private handleTick(tick: NormalizedTick) {
    this.tickListeners.forEach(listener => listener(tick));
  }

  async start() {
    if (this.isConnected) return;
    await this.adapter.connect();
    this.isConnected = true;
  }

  async stop() {
    if (!this.isConnected) return;
    await this.adapter.disconnect();
    this.isConnected = false;
  }

  subscribeToTicks(callback: (tick: NormalizedTick) => void) {
    this.tickListeners.add(callback);
    return () => {
      this.tickListeners.delete(callback);
    };
  }

  subscribe(symbol: string) {
    this.adapter.subscribe(symbol);
  }

  unsubscribe(symbol: string) {
    this.adapter.unsubscribe(symbol);
  }

  // Allows swapping the underlying data source at runtime
  async changeAdapter(newAdapter: MarketDataAdapter) {
    await this.stop();
    this.adapter = newAdapter;
    this.adapter.onTick(this.handleTick.bind(this));
    await this.start();
  }
}

// Export a singleton instance for the app to use
export const marketDataService = new MarketDataService();
