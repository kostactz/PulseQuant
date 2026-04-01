import { useEffect, useRef, useState, useCallback } from 'react';
import { logger } from '../lib/logger';

export function usePythonWorker(onIntent?: (intent: any) => void) {
  const workerRef = useRef<Worker | null>(null);
  const onIntentRef = useRef(onIntent);
  useEffect(() => { onIntentRef.current = onIntent; }, [onIntent]);
  const [isReady, setIsReady] = useState(false);
  const [metrics, setMetrics] = useState<any>(null);
  const [uiDelta, setUiDelta] = useState<any>(null);
  const metricsRef = useRef<any>(null);

  useEffect(() => {
    metricsRef.current = metrics;
  }, [metrics]);

  useEffect(() => {
    const logInterval = setInterval(() => {
      if (metricsRef.current) {
        const m = metricsRef.current;
        const extract = {
          portfolio_value: m.portfolio_value,
          capital: m.capital,
          position: m.position,
          last_micro_price: m.last_micro_price,
          analytics: m.analytics,
          current_dd_pct: m.current_dd_pct,
          max_dd_pct: m.max_dd_pct,
          max_dd_duration: m.max_dd_duration
        };
        logger.metrics(extract);
      }
    }, 10000);

    return () => clearInterval(logInterval);
  }, []);

  useEffect(() => {
    const restartAttemptsRef = { current: 0 } as { current: number };
    const maxRestartAttempts = 3;

    const createWorker = () => {
      const w = new Worker(new URL('../workers/pythonEngine.worker.ts', import.meta.url));

      w.onmessage = (event) => {
        if (event.data.type === 'READY') {
          restartAttemptsRef.current = 0;
          setIsReady(true);
          logger.info('Python Engine initialized and ready.');
          return;
        }

        if (event.data.type === 'NOT_READY') {
          setIsReady(false);
          logger.info('Python Engine reported not ready.');
          return;
        }

        if (event.data.type === 'ERROR') {
          setIsReady(false);
          logger.error('Python Engine error: ' + (event.data.error || 'unknown'));
          // Attempt restart with backoff
          if (restartAttemptsRef.current < maxRestartAttempts) {
            const delay = Math.min(5000, 500 * Math.pow(2, restartAttemptsRef.current));
            restartAttemptsRef.current += 1;
            logger.info(`Attempting to restart Python worker in ${delay}ms (attempt ${restartAttemptsRef.current})`);
            setTimeout(() => {
              try {
                w.terminate();
              } catch (e) {
                /* ignore */
              }
              workerRef.current = createWorker();
            }, delay);
          } else {
            logger.error('Max Python worker restart attempts reached');
          }
          return;
        }

                
        if (event.data.type === 'INTENTS') {
          if (onIntentRef.current) {
            event.data.data.forEach((intent: any) => onIntentRef.current!(intent));
          }
          return;
        }

        if (event.data.type === 'UI_DELTA') {
          setUiDelta(event.data.data);
          return;
        }

        if (event.data.type === 'RESULTS') {
          setMetrics(event.data.data);
          return;
        }

        if (event.data.type === 'LOGS') {
          event.data.data.forEach((log: any) => {
            if (log.level === 'TRADE') {
              logger.trade(log.data.side, {
                price: log.data.price,
                qty: log.data.qty,
                order_type: log.data.order_type,
                reason: log.data.reason,
                indicators: log.data.indicators,
                metrics: log.data.metrics
              });
            } else {
              const method = log.level?.toLowerCase() || 'info';
              if (method in logger) {
                (logger as any)[method](log.message, log.data || '');
              } else {
                logger.info(log.message, log.data || '');
              }
            }
          });
        }
      };

      w.onerror = (err) => {
        setIsReady(false);
        logger.error('Python worker runtime error', err);
      };

      w.onmessageerror = (err) => {
        setIsReady(false);
        logger.error('Python worker message error', err);
      };

      w.postMessage({ type: 'INIT' });
      return w;
    };

    workerRef.current = createWorker();

    return () => {
      workerRef.current?.terminate();
    };
  }, []);

  const processBatch = useCallback((data: any[]) => {
    if (isReady && workerRef.current) {
      workerRef.current.postMessage({ type: 'PROCESS', payload: data, enqueuedAt: Date.now() });
    }
  }, [isReady]);

  
  const getUIDelta = useCallback(() => {
    if (isReady && workerRef.current) {
      workerRef.current.postMessage({ type: 'GET_UI_DELTA' });
    }
  }, [isReady]);

  const clearData = useCallback(() => {
    if (isReady && workerRef.current) {
      workerRef.current.postMessage({ type: 'CLEAR' });
      setMetrics(null);
      setUiDelta(null);
    }
  }, [isReady]);

  const clearCache = useCallback(async () => {
    try {
      await caches.delete('pyodide-cache-v1');
      window.location.reload();
    } catch (e) {
      console.error("Failed to clear cache", e);
    }
  }, []);

  const executeTrade = useCallback((side: 'buy' | 'sell', bps: number) => {
    if (isReady && workerRef.current) {
      workerRef.current.postMessage({ type: 'TRADE', side, bps });
    }
  }, [isReady]);

  const setAutoTrade = useCallback((enabled: boolean) => {
    if (isReady && workerRef.current) {
      workerRef.current.postMessage({ type: 'SET_AUTO_TRADE', enabled });
    }
  }, [isReady]);

  const updateStrategy = useCallback((style: string, speed: string) => {
    if (isReady && workerRef.current) {
      workerRef.current.postMessage({ type: 'UPDATE_STRATEGY', style, speed });
    }
  }, [isReady]);

  const setTradeSize = useCallback((bps: number) => {
    if (isReady && workerRef.current) {
      workerRef.current.postMessage({ type: 'SET_TRADE_SIZE', bps });
    }
  }, [isReady]);

  return { isReady, metrics, uiDelta, getUIDelta, processBatch, clearData, clearCache, executeTrade, setAutoTrade, updateStrategy, setTradeSize };
}
