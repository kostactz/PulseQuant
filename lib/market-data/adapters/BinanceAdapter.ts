import { logger } from "../../logger";
import { MarketDataAdapter, NormalizedTick } from '../types';
import { getRuntimeCredentials } from '../../security/credentials';

export class BinanceAdapter implements MarketDataAdapter {
  private publicWs: WebSocket | null = null;
  private userDataWs: WebSocket | null = null;
  
  private executionReportCallback: ((report: any) => void) | null = null;
  private syncStateCallback: ((state: any) => void) | null = null;
  private tickCallback: ((tick: NormalizedTick) => void) | null = null;

  private isTestnet: boolean;
  private enableUserData: boolean;
  private symbols: string[] = ['btcusdt', 'ethusdt'];
  
  constructor(isTestnet: boolean = true, enableUserData: boolean = true) {
    this.isTestnet = isTestnet;
    this.enableUserData = enableUserData;
    
    // Initialize maps
    this.symbols.forEach(sym => {
      this.obBids.set(sym, []);
      this.obAsks.set(sym, []);
      this.lastUpdateId.set(sym, 0);
      this.buffer.set(sym, []);
      this.isSnapshotLoaded.set(sym, false);
      this.accumulatedTradeVol.set(sym, 0);
    });
  }
  
  private get restBaseUrl(): string {
    return this.isTestnet ? 'https://testnet.binancefuture.com' : 'https://fapi.binance.com';
  }
  
  private get wsBaseUrl(): string {
    return this.isTestnet ? 'wss://stream.binancefuture.com' : 'wss://fstream.binance.com';
  }
  
  // Order Book State
  private obBids: Map<string, [number, number][]> = new Map();
  private obAsks: Map<string, [number, number][]> = new Map();
  private lastUpdateId: Map<string, number> = new Map();
  private buffer: Map<string, any[]> = new Map();
  private isSnapshotLoaded: Map<string, boolean> = new Map();
  private accumulatedTradeVol: Map<string, number> = new Map();
  
  // Real-time top of book
  private latestBookTicker: Map<string, { bid: number, ask: number, bidQty: number, askQty: number, ts: number }> = new Map();

  // Listen Key State
  private listenKey: string | null = null;
  private listenKeyInterval: NodeJS.Timeout | null = null;

  // Reconnection state
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private isIntentionalDisconnect = false;
  private hasAuthError = false;

  // HMAC Key Cache
  private cachedCryptoKey: CryptoKey | null = null;
  private lastPrivateKeyForCache: string | null = null;

  private get apiKey(): string {
    return getRuntimeCredentials()?.apiKey || process.env.NEXT_PUBLIC_BINANCE_API_KEY || '';
  }

  private get privateKey(): string {
    return getRuntimeCredentials()?.apiSecret || process.env.NEXT_PUBLIC_BINANCE_PRIVATE_KEY || '';
  }

  async connect(): Promise<void> {
    this.isIntentionalDisconnect = false;
    this.connectPublic();
    if (!this.hasAuthError) {
      await this.connectUserDataStream();
    }
  }

  private connectPublic() {
    if (this.publicWs) return;

    const streams = this.symbols.map(s => `${s}@bookTicker/${s}@depth@100ms/${s}@aggTrade`).join('/');
    const ws = new WebSocket(`${this.wsBaseUrl}/stream?streams=${streams}`);
    this.publicWs = ws;

    ws.onopen = () => {
      logger.binance('Public WS Connected for streams: ' + this.symbols.join(', '));
      this.symbols.forEach(sym => this.fetchSnapshot(sym));
    };

    ws.onmessage = (event) => {
      const raw = JSON.parse(event.data);
      const stream = raw.stream;
      const data = raw.data;
      
      if (!stream) return;
      
      const symbol = stream.split('@')[0];
      
      if (stream.includes('@aggTrade')) {
        const vol = this.accumulatedTradeVol.get(symbol) || 0;
        this.accumulatedTradeVol.set(symbol, vol + parseFloat(data.q));
        return;
      }
      
      if (stream.includes('@bookTicker')) {
        const ticker = {
          bid: parseFloat(data.b),
          bidQty: parseFloat(data.B),
          ask: parseFloat(data.a),
          askQty: parseFloat(data.A),
          ts: data.E || data.T || Date.now()
        };
        this.latestBookTicker.set(symbol, ticker);
        
        // Emit tick on bookTicker if we have depth loaded
        if (this.isSnapshotLoaded.get(symbol)) {
          this.emitTick(symbol, ticker.ts);
        }
        return;
      }

      if (stream.includes('@depth')) {
        if (!this.isSnapshotLoaded.get(symbol)) {
          const buf = this.buffer.get(symbol) || [];
          buf.push(data);
          this.buffer.set(symbol, buf);
          return;
        }
        this.processDepthUpdate(symbol, data);
      }
    };

    ws.onclose = () => {
      if (this.publicWs === ws) {
        logger.binance('Public WS Disconnected');
        this.publicWs = null;
        this.handleReconnect();
      }
    };
  }

  // --- Listen Key & User Data Stream ---

  private async fetchListenKey(): Promise<string> {
    const res = await fetch(`${this.restBaseUrl}/fapi/v1/listenKey`, {
      method: 'POST',
      headers: {
        'X-MBX-APIKEY': this.apiKey
      }
    });
    const data = await res.json();
    if (!data.listenKey) throw new Error('Failed to get listenKey: ' + JSON.stringify(data));
    return data.listenKey;
  }

  private async keepAliveListenKey(): Promise<void> {
    if (!this.listenKey) return;
    try {
      await fetch(`${this.restBaseUrl}/fapi/v1/listenKey`, {
        method: 'PUT',
        headers: { 'X-MBX-APIKEY': this.apiKey }
      });
      logger.binance('ListenKey kept alive');
    } catch (err) {
      logger.error('Failed to keep alive ListenKey:', err);
    }
  }

  private async connectUserDataStream() {
    if (!this.enableUserData) return;
    if (this.userDataWs) return;
    if (!this.apiKey) {
      logger.warn('No API Key provided, skipping User Data Stream');
      return;
    }

    try {
      this.listenKey = await this.fetchListenKey();
      
      if (this.listenKeyInterval) clearInterval(this.listenKeyInterval);
      this.listenKeyInterval = setInterval(() => this.keepAliveListenKey(), 30 * 60 * 1000);

      const ws = new WebSocket(`${this.wsBaseUrl}/ws/${this.listenKey}`);
      this.userDataWs = ws;

      ws.onopen = async () => {
        logger.binance('User Data Stream Connected');
        if (this.syncStateCallback) {
          try {
            const [openOrders, accountInfo] = await Promise.all([
              // We could fetch open orders for all symbols here, but this might be costly, or we can just fetch all open orders without symbol
              this.fetchOpenOrders(''),
              this.fetchAccountInformation()
            ]);
            
            let capital = null;
            let positions: Record<string, number> = {};
            
            if (accountInfo && accountInfo.assets && accountInfo.positions) {
              const usdtAsset = accountInfo.assets.find((a: any) => a.asset === 'USDT');
              if (usdtAsset) {
                capital = parseFloat(usdtAsset.marginBalance);
              }
              
              accountInfo.positions.forEach((p: any) => {
                if (parseFloat(p.positionAmt) !== 0) {
                  positions[p.symbol.toLowerCase()] = parseFloat(p.positionAmt);
                }
              });
            }

            this.syncStateCallback({ 
              open_orders: openOrders,
              capital: capital !== null ? capital : undefined,
              positions: Object.keys(positions).length > 0 ? positions : undefined
            });
          } catch (err) {
            logger.error('Error fetching data for sync:', err);
          }
        }
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.e === 'ORDER_TRADE_UPDATE') {
          const order = data.o;
          if (this.executionReportCallback) {
            this.executionReportCallback({
              clientOrderId: order.c,
              status: order.X,
              lastFilledQuantity: order.l,
              lastFilledPrice: order.L,
              transactionTime: data.E,
              cancelReason: order.r
            });
          }
        }
      };

      ws.onclose = () => {
        if (this.userDataWs === ws) {
          logger.binance('User Data Stream Disconnected');
          this.userDataWs = null;
          if (this.listenKeyInterval) clearInterval(this.listenKeyInterval);
          this.handleReconnect();
        }
      };
    } catch (err: any) {
      logger.error('User Data Stream connection failed:', err);
      if (err.message && (err.message.includes('-2015') || err.message.includes('Invalid API-key'))) {
        logger.error('Fatal auth error, stopping user data stream reconnects. Please check your API keys or IS_TESTNET configuration.');
        this.hasAuthError = true;
        return;
      }
      this.handleReconnect();
    }
  }

  private handleReconnect() {
    if (this.isIntentionalDisconnect) return;
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
    
    this.reconnectTimeout = setTimeout(() => {
      logger.binance('Attempting to reconnect...');
      this.symbols.forEach(sym => {
        this.isSnapshotLoaded.set(sym, false);
        this.buffer.set(sym, []);
      });
      this.connect();
    }, 3000);
  }

  // Helper: Binary search
  private findInsertIndex(arr: [number, number][], price: number, descending: boolean): number {
    let low = 0;
    let high = arr.length - 1;
    
    while (low <= high) {
      const mid = (low + high) >>> 1;
      const midPrice = arr[mid][0];
      if (midPrice === price) return mid;
      if (descending) {
        if (midPrice < price) high = mid - 1;
        else low = mid + 1;
      } else {
        if (midPrice > price) high = mid - 1;
        else low = mid + 1;
      }
    }
    return low;
  }

  private updateBook(book: [number, number][], price: number, qty: number, descending: boolean) {
    const idx = this.findInsertIndex(book, price, descending);
    if (idx < book.length && book[idx][0] === price) {
      if (qty === 0) book.splice(idx, 1);
      else book[idx][1] = qty;
    } else if (qty > 0) {
      book.splice(idx, 0, [price, qty]);
    }
  }

  private async fetchSnapshot(symbol: string) {
    try {
      const res = await fetch(`${this.restBaseUrl}/fapi/v1/depth?symbol=${symbol.toUpperCase()}&limit=1000`);
      const snap = await res.json();
      
      this.lastUpdateId.set(symbol, snap.lastUpdateId);
      const bids: [number, number][] = [];
      const asks: [number, number][] = [];
      
      snap.bids.forEach((b: string[]) => bids.push([parseFloat(b[0]), parseFloat(b[1])]));
      snap.asks.forEach((a: string[]) => asks.push([parseFloat(a[0]), parseFloat(a[1])]));
      
      bids.sort((a, b) => b[0] - a[0]); 
      asks.sort((a, b) => a[0] - b[0]); 
      
      this.obBids.set(symbol, bids);
      this.obAsks.set(symbol, asks);
      
      this.isSnapshotLoaded.set(symbol, true);

      const buf = this.buffer.get(symbol) || [];
      const lastId = snap.lastUpdateId;
      const validEvents = buf.filter(e => e.u > lastId);
      validEvents.forEach(e => this.processDepthUpdate(symbol, e));
      this.buffer.set(symbol, []);
    } catch (error) {
      logger.error(`Failed to fetch snapshot for ${symbol}:`, error);
      this.handleReconnect();
    }
  }

  private processDepthUpdate(symbol: string, event: any) {
    const lastId = this.lastUpdateId.get(symbol) || 0;
    if (event.u <= lastId) return;

    const bids = this.obBids.get(symbol) || [];
    const asks = this.obAsks.get(symbol) || [];

    event.b.forEach((b: string[]) => {
      this.updateBook(bids, parseFloat(b[0]), parseFloat(b[1]), true); 
    });

    event.a.forEach((a: string[]) => {
      this.updateBook(asks, parseFloat(a[0]), parseFloat(a[1]), false); 
    });

    this.obBids.set(symbol, bids);
    this.obAsks.set(symbol, asks);
    this.lastUpdateId.set(symbol, event.u);
    this.emitTick(symbol, event.E || Date.now());
  }

  private emitTick(symbol: string, timestamp: number) {
    if (!this.tickCallback) return;

    const sortedBids = this.obBids.get(symbol) || [];
    const sortedAsks = this.obAsks.get(symbol) || [];

    if (sortedBids.length === 0 || sortedAsks.length === 0) return;

    let topBidPrice = sortedBids[0][0];
    let topBidQty = sortedBids[0][1];
    let topAskPrice = sortedAsks[0][0];
    let topAskQty = sortedAsks[0][1];

    const ticker = this.latestBookTicker.get(symbol);
    if (ticker) {
      topBidPrice = ticker.bid;
      topBidQty = ticker.bidQty;
      topAskPrice = ticker.ask;
      topAskQty = ticker.askQty;
    }

    const GROUP_SIZE = symbol === 'ethusdt' ? 1 : 10;
    const LIMIT = 20;

    const groupLevels = (levels: [number, number][], isAsk: boolean, groupSize: number, limit: number) => {
      const result: [number, number][] = [];
      let currentGroupPrice = -1;
      let currentGroupVol = 0;
      
      for (const [price, vol] of levels) {
        const groupedPrice = isAsk 
          ? Math.ceil(price / groupSize) * groupSize 
          : Math.floor(price / groupSize) * groupSize;
          
        if (currentGroupPrice === -1) {
          currentGroupPrice = groupedPrice;
          currentGroupVol = vol;
        } else if (groupedPrice === currentGroupPrice) {
          currentGroupVol += vol;
        } else {
          result.push([currentGroupPrice, currentGroupVol]);
          if (result.length >= limit) break;
          currentGroupPrice = groupedPrice;
          currentGroupVol = vol;
        }
      }
      if (result.length < limit && currentGroupPrice !== -1) {
        result.push([currentGroupPrice, currentGroupVol]);
      }
      return result;
    };

    const groupedBids = groupLevels(sortedBids, false, GROUP_SIZE, LIMIT);
    const groupedAsks = groupLevels(sortedAsks, true, GROUP_SIZE, LIMIT);

    const exportedBids = sortedBids.slice(0, 20).map(x => [...x] as [number, number]);
    const exportedAsks = sortedAsks.slice(0, 20).map(x => [...x] as [number, number]);

    if (ticker) {
      if (exportedBids.length > 0 && exportedBids[0][0] === topBidPrice) {
        exportedBids[0][1] = topBidQty;
      }
      if (exportedAsks.length > 0 && exportedAsks[0][0] === topAskPrice) {
        exportedAsks[0][1] = topAskQty;
      }
    }

    const accumulatedTradeVol = this.accumulatedTradeVol.get(symbol) || 0;

    const tick: NormalizedTick = {
      symbol,
      timestamp,
      bid: topBidPrice,
      ask: topAskPrice,
      bid_vol: topBidQty,
      ask_vol: topAskQty,
      delta_bid: 0,
      delta_ask: 0,
      trade_volume: accumulatedTradeVol,
      depth: { bids: groupedBids, asks: groupedAsks },
      bids: exportedBids,
      asks: exportedAsks
    };

    this.accumulatedTradeVol.set(symbol, 0);
    this.tickCallback(tick);
  }

  // --- REST Order Execution ---

  private async signHMAC(queryString: string): Promise<string> {
    const encoder = new TextEncoder();
    const currentPrivateKey = this.privateKey;
    const msgData = encoder.encode(queryString);

    if (!this.cachedCryptoKey || this.lastPrivateKeyForCache !== currentPrivateKey) {
      const keyData = encoder.encode(currentPrivateKey);
      this.cachedCryptoKey = await globalThis.crypto.subtle.importKey(
        'raw',
        keyData,
        { name: 'HMAC', hash: 'SHA-256' },
        false,
        ['sign']
      );
      this.lastPrivateKeyForCache = currentPrivateKey;
    }

    const signature = await globalThis.crypto.subtle.sign('HMAC', this.cachedCryptoKey, msgData);
    
    return Array.from(new Uint8Array(signature))
      .map(b => b.toString(16).padStart(2, '0'))
      .join('');
  }

  public async placeOrder(symbol: string, side: 'BUY' | 'SELL', quantity: number, price?: number, newClientOrderId?: string, type?: string, timeInForce?: string) {
    if (!this.apiKey || !this.privateKey) {
      throw new Error('API credentials not set');
    }

    const params = new URLSearchParams();
    params.append('symbol', symbol.toUpperCase());
    params.append('side', side);
    params.append('type', type || (price ? 'LIMIT' : 'MARKET'));
    params.append('quantity', quantity.toString());
    params.append('timestamp', Date.now().toString());

    if (newClientOrderId) params.append('newClientOrderId', newClientOrderId);
    if (price) params.append('price', price.toString());
    if (type === 'LIMIT') params.append('timeInForce', timeInForce || 'GTC');

    const queryString = params.toString();
    const signature = await this.signHMAC(queryString);
    params.append('signature', signature);

    const res = await fetch(`${this.restBaseUrl}/fapi/v1/order`, {
      method: 'POST',
      headers: {
        'X-MBX-APIKEY': this.apiKey,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: params.toString()
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(`Place order failed: ${JSON.stringify(data)}`);
    }
    return data;
  }

  public async cancelOrder(symbol: string, origClientOrderId: string) {
    if (!this.apiKey || !this.privateKey) {
      throw new Error('API credentials not set');
    }

    const params = new URLSearchParams();
    params.append('symbol', symbol.toUpperCase());
    params.append('origClientOrderId', origClientOrderId);
    params.append('timestamp', Date.now().toString());

    const queryString = params.toString();
    const signature = await this.signHMAC(queryString);
    params.append('signature', signature);

    const res = await fetch(`${this.restBaseUrl}/fapi/v1/order`, {
      method: 'DELETE',
      headers: {
        'X-MBX-APIKEY': this.apiKey,
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      body: params.toString()
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(`Cancel order failed: ${JSON.stringify(data)}`);
    }
    return data;
  }

  public async fetchAccountInformation() {
    if (!this.apiKey || !this.privateKey) return null;
    
    const params = new URLSearchParams();
    params.append('timestamp', Date.now().toString());

    const queryString = params.toString();
    const signature = await this.signHMAC(queryString);
    params.append('signature', signature);

    try {
      const res = await fetch(`${this.restBaseUrl}/fapi/v2/account?${params.toString()}`, {
        method: 'GET',
        headers: {
          'X-MBX-APIKEY': this.apiKey,
        },
      });

      if (!res.ok) throw new Error('Failed to fetch account info');
      const data = await res.json();
      return data;
    } catch (err) {
      logger.error('fetchAccountInformation error:', err);
      return null;
    }
  }

  public async fetchOpenOrders(symbol: string) {
    if (!this.apiKey || !this.privateKey) return [];
    
    const params = new URLSearchParams();
    if (symbol) {
      params.append('symbol', symbol.toUpperCase());
    }
    params.append('timestamp', Date.now().toString());

    const queryString = params.toString();
    const signature = await this.signHMAC(queryString);
    params.append('signature', signature);

    try {
      const res = await fetch(`${this.restBaseUrl}/fapi/v1/openOrders?${params.toString()}`, {
        method: 'GET',
        headers: {
          'X-MBX-APIKEY': this.apiKey,
        },
      });

      if (!res.ok) throw new Error('Failed to fetch open orders');
      const data = await res.json();
      return data;
    } catch (err) {
      logger.error('fetchOpenOrders error:', err);
      return [];
    }
  }

  async disconnect(): Promise<void> {
    this.isIntentionalDisconnect = true;
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
    if (this.listenKeyInterval) clearInterval(this.listenKeyInterval);
    
    if (this.publicWs) {
      this.publicWs.onclose = null;
      this.publicWs.onmessage = null;
      this.publicWs.close();
      this.publicWs = null;
    }
    if (this.userDataWs) {
      this.userDataWs.onclose = null;
      this.userDataWs.onmessage = null;
      this.userDataWs.close();
      this.userDataWs = null;
    }
  }

  async setSymbols(target: string, feature: string): Promise<void> {
    const newSymbols = [target.toLowerCase(), feature.toLowerCase()];
    
    if (this.publicWs) {
      this.isIntentionalDisconnect = true;
      this.publicWs.onclose = null;
      this.publicWs.onmessage = null;
      this.publicWs.close();
      this.publicWs = null;
    }
    
    this.symbols.forEach(sym => {
      this.obBids.delete(sym);
      this.obAsks.delete(sym);
      this.buffer.delete(sym);
      this.latestBookTicker.delete(sym);
      this.accumulatedTradeVol.delete(sym);
      this.lastUpdateId.delete(sym);
      this.isSnapshotLoaded.delete(sym);
    });

    this.symbols = newSymbols;
    this.symbols.forEach(sym => {
      this.obBids.set(sym, []);
      this.obAsks.set(sym, []);
      this.lastUpdateId.set(sym, 0);
      this.buffer.set(sym, []);
      this.isSnapshotLoaded.set(sym, false);
      this.accumulatedTradeVol.set(sym, 0);
    });

    this.isIntentionalDisconnect = false;
    this.connectPublic();
  }

  subscribe(symbol: string): void {
    console.log(`[BinanceAdapter] Subscribed to ${symbol}`);
    if (!this.symbols.includes(symbol.toLowerCase())) {
      this.symbols.push(symbol.toLowerCase());
      // Re-init state for new symbol
      const sym = symbol.toLowerCase();
      this.obBids.set(sym, []);
      this.obAsks.set(sym, []);
      this.lastUpdateId.set(sym, 0);
      this.buffer.set(sym, []);
      this.isSnapshotLoaded.set(sym, false);
      this.accumulatedTradeVol.set(sym, 0);
      
      // We would need to reconnect or send a sub message, but since Binance WS uses query string streams upon connect,
      // it's easier to drop and reconnect public.
      if (this.publicWs) {
        this.publicWs.onclose = null;
        this.publicWs.onmessage = null;
        this.publicWs.close(); // Will trigger reconnect
        this.publicWs = null;
      }
    }
  }

  unsubscribe(symbol: string): void {
    console.log(`[BinanceAdapter] Unsubscribed from ${symbol}`);
    const sym = symbol.toLowerCase();
    this.symbols = this.symbols.filter(s => s !== sym);
    if (this.publicWs) {
      this.publicWs.onclose = null;
      this.publicWs.onmessage = null;
      this.publicWs.close(); // Will trigger reconnect
      this.publicWs = null;
    }
  }

  onExecutionReport(callback: (report: any) => void): void {
    this.executionReportCallback = callback;
  }

  onSyncState(callback: (state: any) => void): void {
    this.syncStateCallback = callback;
  }

  onTick(callback: (tick: NormalizedTick) => void): void {
    this.tickCallback = callback;
  }
}
