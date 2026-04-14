import { logger } from "@/lib/logger";
import { useEffect, useRef, useState, useCallback } from 'react';
import { MarketDataAdapter, NormalizedTick } from '@/lib/market-data/types';
import { BinanceAdapter } from '@/lib/market-data/adapters/BinanceAdapter';
import { MockAdapter } from '@/lib/market-data/adapters/MockAdapter';
import { OrderManager, Intent } from '@/lib/order/OrderManager';

export type TradingMode = 'PAPER' | 'TESTNET' | 'MAINNET';

export function useMarketData(connectEnabled: boolean = true, tradingMode: TradingMode = 'PAPER', onTickImmediate?: (tick: NormalizedTick) => void, onExecutionReportImmediate?: (report: any) => void, onSyncStateImmediate?: (state: any) => void) {
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
  const tradingModeRef = useRef(tradingMode);
  
  // 1. Connection Setup and State Management
  // Manage the WebSocket connection using useRef to ensure it persists across re-renders
  const latestTickRefs = useRef<Record<string, NormalizedTick>>({});
  const orderBookRefs = useRef<Record<string, { bids: [number, number][], asks: [number, number][] }>>({});
  
  useEffect(() => { 
    onTickImmediateRef.current = onTickImmediate; 
    onExecutionReportImmediateRef.current = onExecutionReportImmediate; 
    onSyncStateImmediateRef.current = onSyncStateImmediate;
    tradingModeRef.current = tradingMode;
  }, [onTickImmediate, onExecutionReportImmediate, onSyncStateImmediate, tradingMode]);

  const adapterRef = useRef<MarketDataAdapter | null>(null);
  const orderManagerRef = useRef<OrderManager | null>(null);
  const currentAdapterMode = useRef<TradingMode | null>(null);

  const lastRenderTimeRef = useRef(0);

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
      
      adapterRef.current = new BinanceAdapter(isTestnetEnv, enableUserData);
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
        
        // Use strict time-based throttling for UI rendering (e.g., max 10 FPS = 100ms)
        const now = Date.now();
        if (now - lastRenderTimeRef.current >= 100) {
          setOrderBooks({ ...orderBookRefs.current });
          setLatestTicks({ ...latestTickRefs.current });
          lastRenderTimeRef.current = now;
        }
      });
    }

    if (!orderManagerRef.current) {
      const execFn = async (intent: Intent) => {
        if (!adapterRef.current) return;
        
        if (tradingModeRef.current === 'PAPER') {
          logger.orderFlow('Paper Trading Simulation intent:', intent);
          
          // Fake execution report back to engine to keep the mock portfolio running
          if (intent.action === 'PLACE_ORDER') {
            setTimeout(() => {
              if (onExecutionReportImmediateRef.current) {
                onExecutionReportImmediateRef.current({
                  clientOrderId: intent.clientOrderId,
                  status: 'NEW',
                  lastFilledQuantity: 0,
                  lastFilledPrice: intent.price || 0,
                  transactionTime: Date.now(),
                });
                
                // Simulate fill for market orders or test limits
                setTimeout(() => {
                  onExecutionReportImmediateRef.current!({
                    clientOrderId: intent.clientOrderId,
                    status: 'FILLED',
                    lastFilledQuantity: intent.quantity,
                    lastFilledPrice: intent.price || (intent.side === 'BUY' ? latestTickRefs.current[intent.symbol]?.ask : latestTickRefs.current[intent.symbol]?.bid),
                    transactionTime: Date.now(),
                  });
                }, 500);
              }
            }, 100);
          } else if (intent.action === 'CANCEL_ORDER') {
            setTimeout(() => {
              if (onExecutionReportImmediateRef.current) {
                onExecutionReportImmediateRef.current({
                  clientOrderId: intent.clientOrderId,
                  status: 'CANCELED',
                  lastFilledQuantity: 0,
                  lastFilledPrice: 0,
                  transactionTime: Date.now(),
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
            intent.quantity, 
            intent.price,
            intent.clientOrderId,
            intent.type,
            intent.timeInForce
          );
          if (onExecutionReportImmediateRef.current) {
            onExecutionReportImmediateRef.current({
              clientOrderId: intent.clientOrderId,
              status: 'NEW',
              lastFilledQuantity: 0,
              lastFilledPrice: intent.price || 0,
              transactionTime: Date.now(),
            });
          }
        } else if (intent.action === 'CANCEL_ORDER') {
          await (adapterRef.current as any).cancelOrder(
            intent.symbol,
            intent.clientOrderId
          );
          if (onExecutionReportImmediateRef.current) {
            onExecutionReportImmediateRef.current({
              clientOrderId: intent.clientOrderId,
              status: 'CANCELED',
              lastFilledQuantity: 0,
              lastFilledPrice: 0,
              transactionTime: Date.now(),
            });
          }
        }
      };

      const handleOrderRejected = (intent: Intent, reason: string) => {
        if (onExecutionReportImmediateRef.current) {
          onExecutionReportImmediateRef.current({
            clientOrderId: intent.clientOrderId,
            status: 'REJECTED',
            lastFilledQuantity: 0,
            lastFilledPrice: 0,
            transactionTime: Date.now(),
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
