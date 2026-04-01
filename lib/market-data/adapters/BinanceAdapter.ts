import { logger } from "../../logger";
import { MarketDataAdapter, NormalizedTick } from '../types';
import { getRuntimeCredentials } from '../../security/credentials';

const symbol = 'btcusdt';

export class BinanceAdapter implements MarketDataAdapter {
  private publicWs: WebSocket | null = null;
  private userDataWs: WebSocket | null = null;
  
  private executionReportCallback: ((report: any) => void) | null = null;
  private syncStateCallback: ((state: any) => void) | null = null;
  private tickCallback: ((tick: NormalizedTick) => void) | null = null;

  private isTestnet: boolean;
  private enableUserData: boolean;
  
  constructor(isTestnet: boolean = true, enableUserData: boolean = true) {
    this.isTestnet = isTestnet;
    this.enableUserData = enableUserData;
  }
  
  private get restBaseUrl(): string {
    // Determine if we are running in the browser
    const isBrowser = typeof window !== 'undefined';
    
    if (isBrowser) {
      // Use Next.js rewrites to avoid CORS issues
      return this.isTestnet ? '/binance-api/testnet' : '/binance-api/mainnet';
    } else {
      return this.isTestnet ? 'https://testnet.binancefuture.com' : 'https://fapi.binance.com';
    }
  }
  
  private get wsBaseUrl(): string {
    return this.isTestnet ? 'wss://stream.binancefuture.com' : 'wss://fstream.binance.com';
  }
  
  // Order Book State
  private obBids: [number, number][] = [];
  private obAsks: [number, number][] = [];
  private lastUpdateId = 0;
  private buffer: any[] = [];
  private isSnapshotLoaded = false;
  private accumulatedTradeVol = 0;
  
  // Real-time top of book
  private latestBookTicker: { bid: number, ask: number, bidQty: number, askQty: number, ts: number } | null = null;
  
  // Previous top of book for OFI
  private prevBids: [number, number][] = [];
  private prevAsks: [number, number][] = [];

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

    this.publicWs = new WebSocket(`${this.wsBaseUrl}/stream?streams=${symbol}@bookTicker/${symbol}@depth@100ms/${symbol}@aggTrade`);

    this.publicWs.onopen = () => {
      logger.binance('Public WS Connected');
      this.fetchSnapshot(symbol);
    };

    this.publicWs.onmessage = (event) => {
      const raw = JSON.parse(event.data);
      const stream = raw.stream;
      const data = raw.data;
      
      if (stream.includes('@aggTrade')) {
        this.accumulatedTradeVol += parseFloat(data.q);
        return;
      }
      
      if (stream.includes('@bookTicker')) {
        this.latestBookTicker = {
          bid: parseFloat(data.b),
          bidQty: parseFloat(data.B),
          ask: parseFloat(data.a),
          askQty: parseFloat(data.A),
          ts: data.E || data.T || Date.now()
        };
        // Emit tick on bookTicker if we have depth loaded
        if (this.isSnapshotLoaded) {
          this.emitTick(this.latestBookTicker.ts);
        }
        return;
      }

      if (stream.includes('@depth')) {
        if (!this.isSnapshotLoaded) {
          this.buffer.push(data);
          return;
        }
        this.processDepthUpdate(data);
      }
    };

    this.publicWs.onclose = () => {
      logger.binance('Public WS Disconnected');
      this.publicWs = null;
      this.handleReconnect();
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
      
      // Keep alive every 30 minutes
      if (this.listenKeyInterval) clearInterval(this.listenKeyInterval);
      this.listenKeyInterval = setInterval(() => this.keepAliveListenKey(), 30 * 60 * 1000);

      this.userDataWs = new WebSocket(`${this.wsBaseUrl}/ws/${this.listenKey}`);

      this.userDataWs.onopen = async () => {
        logger.binance('User Data Stream Connected');
        if (this.syncStateCallback) {
          try {
            const [openOrders, accountInfo] = await Promise.all([
              this.fetchOpenOrders(symbol),
              this.fetchAccountInformation()
            ]);
            
            let capital = null;
            let position = null;
            
            if (accountInfo && accountInfo.assets && accountInfo.positions) {
              const usdtAsset = accountInfo.assets.find((a: any) => a.asset === 'USDT');
              if (usdtAsset) {
                capital = parseFloat(usdtAsset.marginBalance);
              }
              
              const btcPosition = accountInfo.positions.find((p: any) => p.symbol === symbol.toUpperCase());
              if (btcPosition) {
                position = parseFloat(btcPosition.positionAmt);
              }
            }

            this.syncStateCallback({ 
              open_orders: openOrders,
              capital: capital !== null ? capital : undefined,
              position: position !== null ? position : undefined
            });
          } catch (err) {
            logger.error('Error fetching data for sync:', err);
          }
        }
      };

      this.userDataWs.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.e === 'ORDER_TRADE_UPDATE') {
          const order = data.o;
          if (this.executionReportCallback) {
            // Normalize report for engine
            this.executionReportCallback({
              clientOrderId: order.c,
              status: order.X, // NEW, PARTIALLY_FILLED, FILLED, CANCELED, EXPIRED, REJECTED
              lastFilledQuantity: order.l,
              lastFilledPrice: order.L,
              transactionTime: data.E,
              cancelReason: order.r
            });
          }
        }
      };

      this.userDataWs.onclose = () => {
        logger.binance('User Data Stream Disconnected');
        this.userDataWs = null;
        if (this.listenKeyInterval) clearInterval(this.listenKeyInterval);
        this.handleReconnect();
      };
    } catch (err: any) {
      logger.error('User Data Stream connection failed:', err);
      if (err.message && (err.message.includes('-2015') || err.message.includes('Invalid API-key'))) {
        logger.error('Fatal auth error, stopping user data stream reconnects. Please check your API keys or IS_TESTNET configuration.');
        this.hasAuthError = true;
        return; // Do not attempt to reconnect
      }
      this.handleReconnect();
    }
  }

  private handleReconnect() {
    if (this.isIntentionalDisconnect) return;
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
    
    this.reconnectTimeout = setTimeout(() => {
      logger.binance('Attempting to reconnect...');
      this.isSnapshotLoaded = false;
      this.buffer = [];
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
      const res = await fetch(`${this.restBaseUrl}/fapi/v1/depth?symbol=${symbol}&limit=1000`);
      const snap = await res.json();
      
      this.lastUpdateId = snap.lastUpdateId;
      this.obBids = [];
      this.obAsks = [];
      
      snap.bids.forEach((b: string[]) => this.obBids.push([parseFloat(b[0]), parseFloat(b[1])]));
      snap.asks.forEach((a: string[]) => this.obAsks.push([parseFloat(a[0]), parseFloat(a[1])]));
      
      this.obBids.sort((a, b) => b[0] - a[0]); 
      this.obAsks.sort((a, b) => a[0] - b[0]); 
      
      this.isSnapshotLoaded = true;

      const validEvents = this.buffer.filter(e => e.u > this.lastUpdateId);
      validEvents.forEach(e => this.processDepthUpdate(e));
      this.buffer = [];
    } catch (error) {
      logger.error('Failed to fetch snapshot:', error);
      this.handleReconnect();
    }
  }

  private processDepthUpdate(event: any) {
    if (event.u <= this.lastUpdateId) return;

    event.b.forEach((b: string[]) => {
      this.updateBook(this.obBids, parseFloat(b[0]), parseFloat(b[1]), true); 
    });

    event.a.forEach((a: string[]) => {
      this.updateBook(this.obAsks, parseFloat(a[0]), parseFloat(a[1]), false); 
    });

    this.lastUpdateId = event.u;
    this.emitTick(event.E || Date.now());
  }

  private emitTick(timestamp: number) {
    if (!this.tickCallback) return;

    const sortedBids = this.obBids;
    const sortedAsks = this.obAsks;

    if (sortedBids.length === 0 || sortedAsks.length === 0) return;

    // Use bookTicker for top of book if available, otherwise fallback to depth array
    let topBidPrice = sortedBids[0][0];
    let topBidQty = sortedBids[0][1];
    let topAskPrice = sortedAsks[0][0];
    let topAskQty = sortedAsks[0][1];

    if (this.latestBookTicker) {
      topBidPrice = this.latestBookTicker.bid;
      topBidQty = this.latestBookTicker.bidQty;
      topAskPrice = this.latestBookTicker.ask;
      topAskQty = this.latestBookTicker.askQty;
    }

    const GROUP_SIZE = 10;
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

    const OFI_LEVELS = 5;
    let deltaBid = 0;
    let deltaAsk = 0;
    
    // Create copies of top 20 levels for the engine
    const exportedBids = sortedBids.slice(0, 20).map(x => [...x] as [number, number]);
    const exportedAsks = sortedAsks.slice(0, 20).map(x => [...x] as [number, number]);

    // Force top level to match bookTicker to prevent misalignment in Deep OBI calculations
    if (this.latestBookTicker) {
      if (exportedBids.length > 0 && exportedBids[0][0] === topBidPrice) {
        exportedBids[0][1] = topBidQty;
      }
      if (exportedAsks.length > 0 && exportedAsks[0][0] === topAskPrice) {
        exportedAsks[0][1] = topAskQty;
      }
    }

    if (this.prevBids.length > 0 && this.prevAsks.length > 0) {
      for (let i = 0; i < Math.min(OFI_LEVELS, exportedBids.length, this.prevBids.length); i++) {
        const weight = 1.0 - (i * 0.2); 
        const [currPrice, currQty] = exportedBids[i];
        const [prevPrice, prevQty] = this.prevBids[i];

        if (currPrice > prevPrice) deltaBid += currQty * weight;
        else if (currPrice === prevPrice) deltaBid += (currQty - prevQty) * weight;
        else deltaBid -= prevQty * weight;
      }

      for (let i = 0; i < Math.min(OFI_LEVELS, exportedAsks.length, this.prevAsks.length); i++) {
        const weight = 1.0 - (i * 0.2);
        const [currPrice, currQty] = exportedAsks[i];
        const [prevPrice, prevQty] = this.prevAsks[i];

        if (currPrice < prevPrice) deltaAsk += currQty * weight;
        else if (currPrice === prevPrice) deltaAsk += (currQty - prevQty) * weight;
        else deltaAsk -= prevQty * weight;
      }
    }

    this.prevBids = exportedBids.slice(0, OFI_LEVELS);
    this.prevAsks = exportedAsks.slice(0, OFI_LEVELS);

    const tick: NormalizedTick = {
      timestamp,
      bid: topBidPrice,
      ask: topAskPrice,
      bid_vol: topBidQty,
      ask_vol: topAskQty,
      delta_bid: deltaBid,
      delta_ask: deltaAsk,
      trade_volume: this.accumulatedTradeVol,
      depth: { bids: groupedBids, asks: groupedAsks },
      bids: exportedBids,
      asks: exportedAsks
    };

    this.accumulatedTradeVol = 0;
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
    
    // Convert buffer to hex string
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

    // For POST fapi/v1/order, we must send signature
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
    params.append('symbol', symbol.toUpperCase());
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
      this.publicWs.close();
      this.publicWs = null;
    }
    if (this.userDataWs) {
      this.userDataWs.close();
      this.userDataWs = null;
    }
  }

  subscribe(symbol: string): void {
    console.log(`[BinanceAdapter] Subscribed to ${symbol}`);
  }

  unsubscribe(symbol: string): void {
    console.log(`[BinanceAdapter] Unsubscribed from ${symbol}`);
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
