import { logger } from "@/lib/logger";
import { useEffect, useRef, useState, useCallback } from 'react';
import { FundingRateData, MarketDataAdapter, NormalizedTick } from '@/lib/market-data/types';
import { BinanceAdapter } from '@/lib/market-data/adapters/BinanceAdapter';
import { MockAdapter } from '@/lib/market-data/adapters/MockAdapter';
import { OrderManager, Intent } from '@/lib/order/OrderManager';

export type TradingMode = 'PAPER' | 'TESTNET' | 'MAINNET';

export function useMarketData(connectEnabled: boolean = true, tradingMode: TradingMode = 'PAPER', onTickImmediate?: (tick: NormalizedTick) => void, onExecutionReportImmediate?: (report: any) => void, onSyncStateImmediate?: (state: any) => void, onFundingRateImmediate?: (event: any) => void) {
  const [orderBooks, setOrderBooks] = useState<Record<string, { bids: [number, number][], asks: [number, number][] }>>({});
  const [latestTicks, setLatestTicks] = useState<Record<string, NormalizedTick>>({});
  const buffer = useRef<NormalizedTick[]>([]);
  const [isPlaying, setIsPlaying] = useState(true);
  
  // Data capture state
  const [isRecording, setIsRecording] = useState(false);
  const recordedTicks = useRef<NormalizedTick[]>([]);
  const recordStateRef = useRef(false); // Ref for sync access in onTick
  const onTickImmediateRef = useRef(onTickImmediate);
  const onExecutionReportImmediateRef = useRef(onExecutionReportImmediate);
  const onSyncStateImmediateRef = useRef(onSyncStateImmediate);
  const onFundingRateImmediateRef = useRef(onFundingRateImmediate);
  const tradingModeRef = useRef(tradingMode);
  
  // 1. Connection Setup and State Management
  // Manage the WebSocket connection using useRef to ensure it persists across re-renders
  const latestTickRefs = useRef<Record<string, NormalizedTick>>({});
  const orderBookRefs = useRef<Record<string, { bids: [number, number][], asks: [number, number][] }>>({});
  
  useEffect(() => { 
    onTickImmediateRef.current = onTickImmediate; 
    onExecutionReportImmediateRef.current = onExecutionReportImmediate; 
    onSyncStateImmediateRef.current = onSyncStateImmediate;
    onFundingRateImmediateRef.current = onFundingRateImmediate;
    tradingModeRef.current = tradingMode;
  }, [onTickImmediate, onExecutionReportImmediate, onSyncStateImmediate, onFundingRateImmediate, tradingMode]);

  const adapterRef = useRef<MarketDataAdapter | null>(null);
  const orderManagerRef = useRef<OrderManager | null>(null);
  const currentAdapterMode = useRef<TradingMode | null>(null);

  const scheduledFlushRef = useRef(false);
  const flushTimeoutRef = useRef<number | null>(null);
  const flushCounterRef = useRef(0);

  const scheduleTickFlush = useCallback(() => {
    if (scheduledFlushRef.current) return;
    scheduledFlushRef.current = true;
    flushTimeoutRef.current = window.setTimeout(() => {
      setOrderBooks({ ...orderBookRefs.current });
      setLatestTicks({ ...latestTickRefs.current });
      scheduledFlushRef.current = false;
      flushTimeoutRef.current = null;
      flushCounterRef.current += 1;
      if (flushCounterRef.current % 10 === 0) {
        logger.debug(`[useMarketData] tick flush #${flushCounterRef.current} executed`);
      }
    }, 100);
  }, []);

  useEffect(() => {
    // For PAPER mode, connect to Mainnet (isTestnet = false) but disable User Data Stream.
    // For TESTNET mode, connect to Testnet and enable User Data.
    // For MAINNET mode, connect to Mainnet and enable User Data.
    const isTestnetEnv = tradingMode === 'TESTNET';
    const enableUserData = tradingMode !== 'PAPER';

    // Initialize or recreate the adapter if mode changed
    if (!adapterRef.current || currentAdapterMode.current !== tradingMode) {
      if (adapterRef.current) {
        adapterRef.current.disconnect();
      }
      
      const useMock = typeof window !== 'undefined' && window.location.search.includes('mock=true');
      adapterRef.current = useMock ? new MockAdapter() : new BinanceAdapter(isTestnetEnv, enableUserData);
      currentAdapterMode.current = tradingMode;
      
      if (adapterRef.current.onExecutionReport) {
        adapterRef.current.onExecutionReport((report) => {
          if (onExecutionReportImmediateRef.current) {
            onExecutionReportImmediateRef.current(report);
          }
        });
      }

      if (adapterRef.current.onSyncState) {
        adapterRef.current.onSyncState((state) => {
          if (onSyncStateImmediateRef.current) {
            onSyncStateImmediateRef.current(state);
          }
        });
      }

      if (adapterRef.current.onMarkPriceUpdate) {
        adapterRef.current.onMarkPriceUpdate((fundingData: FundingRateData) => {
          if (onFundingRateImmediateRef.current) {
            onFundingRateImmediateRef.current({ type: 'FUNDING_RATE_UPDATE', data: fundingData });
          }
        });
      }

      adapterRef.current.onTick((tick) => {
        buffer.current.push(tick);
        const sym = tick.symbol || 'UNKNOWN';
        latestTickRefs.current[sym] = tick;
        orderBookRefs.current[sym] = tick.depth;
        
        if (onTickImmediateRef.current) {
          onTickImmediateRef.current(tick);
        }
        
        if (recordStateRef.current) {
          recordedTicks.current.push(tick);
        }
        
        scheduleTickFlush();
      });
    }

    if (!orderManagerRef.current) {
      const execFn = async (intent: Intent) => {
        if (!adapterRef.current) return;
        
        const qty = intent.quantity || (intent as any).qty || 0;
        const orderId = intent.clientOrderId || (intent as any).order_id || `sim-${Date.now()}`;
        const price = intent.price || (intent as any).price || 0;

        if (tradingModeRef.current === 'PAPER') {
          logger.orderFlow('Paper Trading Simulation intent:', intent);
          
          if (intent.action === 'PLACE_ORDER') {
            const normalizedIntentSymbol = intent.symbol.toLowerCase();
            const latestTick =
              latestTickRefs.current[normalizedIntentSymbol] ??
              latestTickRefs.current[intent.symbol] ??
              latestTickRefs.current[intent.symbol.toUpperCase()];

            setTimeout(() => {
              if (onExecutionReportImmediateRef.current) {
                onExecutionReportImmediateRef.current({
                  order_id: orderId,
                  clientOrderId: orderId,
                  status: 'NEW',
                  symbol: intent.symbol,
                  side: intent.side,
                  quantity: qty,
                  filled_qty: 0,
                  price: price,
                  is_maker: intent.type === 'LIMIT',
                  transaction_time: Date.now(),
                });
                
                // Simulate fill for market orders or test limits
                setTimeout(() => {
                  const fillPrice = price || (intent.side === 'BUY' ? (latestTick?.ask || 100.05) : (latestTick?.bid || 100.00));
                  onExecutionReportImmediateRef.current!({
                    order_id: orderId,
                    clientOrderId: orderId,
                    status: 'FILLED',
                    symbol: intent.symbol,
                    side: intent.side,
                    quantity: qty,
                    filled_qty: qty,
                    price: fillPrice,
                    is_maker: intent.type === 'LIMIT',
                    transaction_time: Date.now(),
                  });
                }, 500);
              }
            }, 100);
          } else if (intent.action === 'CANCEL_ORDER') {
            setTimeout(() => {
              if (onExecutionReportImmediateRef.current) {
                onExecutionReportImmediateRef.current({
                  order_id: orderId,
                  clientOrderId: orderId,
                  status: 'CANCELED',
                  symbol: intent.symbol,
                  filled_qty: 0,
                  price: 0,
                  transaction_time: Date.now(),
                });
              }
            }, 100);
          }
          return;
        }

        if (intent.action === 'PLACE_ORDER') {
          await (adapterRef.current as any).placeOrder(
            intent.symbol, 
            intent.side, 
            qty, 
            price,
            orderId,
            intent.type,
            intent.timeInForce
          );
          if (onExecutionReportImmediateRef.current) {
            onExecutionReportImmediateRef.current({
              order_id: orderId,
              clientOrderId: orderId,
              status: 'NEW',
              symbol: intent.symbol,
              side: intent.side,
              quantity: qty,
              filled_qty: 0,
              price: price,
              is_maker: intent.type === 'LIMIT',
              transaction_time: Date.now(),
            });
          }
        } else if (intent.action === 'CANCEL_ORDER') {
          await (adapterRef.current as any).cancelOrder(
            intent.symbol,
            intent.clientOrderId
          );
          if (onExecutionReportImmediateRef.current) {
            onExecutionReportImmediateRef.current({
              order_id: intent.clientOrderId,
              status: 'CANCELED',
              symbol: intent.symbol,
              filled_qty: 0,
              price: 0,
              transaction_time: Date.now(),
            });
          }
        }
      };

      const handleOrderRejected = (intent: Intent, reason: string) => {
        if (onExecutionReportImmediateRef.current) {
          onExecutionReportImmediateRef.current({
            order_id: intent.clientOrderId,
            status: 'REJECTED',
            symbol: intent.symbol,
            side: intent.side,
            filled_qty: 0,
            price: 0,
            transaction_time: Date.now(),
            cancelReason: reason
          });
        }
      };
      
      orderManagerRef.current = new OrderManager(execFn, 40, 20, handleOrderRejected); // 40 tokens max, refill 20/sec
    }

    const adapter = adapterRef.current;
    const manager = orderManagerRef.current;

    let isStale = false;

    if (isPlaying && connectEnabled) {
      void (async () => {
        try {
          await adapter.connect();
          if (isStale) {
            // Effect was cleaned up or dependencies changed while connecting
            try {
              await adapter.disconnect();
            } catch (disconnectError) {
              logger.error("Error during stale adapter.disconnect()", disconnectError);
            }
            return;
          }
          manager.startLoop();
        } catch (error) {
          logger.error("Error during adapter.connect()", error);
        }
      })();
    } else {
      void (async () => {
        try {
          await adapter.disconnect();
        } catch (error) {
          logger.error("Error during adapter.disconnect()", error);
        }
        manager.stopLoop();
      })();
    }

    return () => {
      // Cleanup on unmount or dependency change
      isStale = true;
      if (flushTimeoutRef.current !== null) {
        window.clearTimeout(flushTimeoutRef.current);
        flushTimeoutRef.current = null;
        scheduledFlushRef.current = false;
      }
      void (async () => {
        try {
          await adapter.disconnect();
        } catch (error) {
          logger.error("Error during cleanup adapter.disconnect()", error);
        }
        manager.stopLoop();
      })();
    };
  }, [isPlaying, connectEnabled, tradingMode]);

  const getAndClearBuffer = useCallback(() => {
    const data = [...buffer.current];
    buffer.current = [];
    return data;
  }, []);

  const clearBuffer = useCallback(() => {
    buffer.current = [];
  }, []);

  const toggleRecording = useCallback(() => {
    setIsRecording(prev => {
      const newState = !prev;
      recordStateRef.current = newState;
      
      if (!newState) {
        // Stop recording and download
        if (recordedTicks.current.length > 0) {
          const jsonl = recordedTicks.current.map(tick => JSON.stringify(tick)).join('\n');
          const blob = new Blob([jsonl], { type: 'application/jsonlines' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `capture_btcusdt_${Date.now()}.jsonl`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }
        recordedTicks.current = [];
      } else {
        // Start recording
        recordedTicks.current = [];
      }
      
      return newState;
    });
  }, []);

  
  const executeIntent = useCallback((intent: any) => {
    if (orderManagerRef.current) {
      orderManagerRef.current.enqueueIntent(intent);
    }
  }, []);

  const setSymbols = useCallback(async (target: string, feature: string) => {
    if (adapterRef.current && adapterRef.current.setSymbols) {
      await adapterRef.current.setSymbols(target, feature);
    }
  }, []);

  return {
    orderBooks,
    latestTicks,
    getAndClearBuffer,
    clearBuffer,
    isPlaying,
    setIsPlaying,
    isRecording,
    toggleRecording,
    executeIntent,
    setSymbols,
  };
}
