'use client';
import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from 'recharts';
import { usePythonWorker } from '@/hooks/usePythonWorker';
import { useMarketData } from '@/hooks/useMarketData';
import { SecuritySetupModal } from '@/components/SecuritySetupModal';
import { RealtimeChart } from '@/components/RealtimeChart';
import { OrderBookDepth } from '@/components/OrderBookDepth';
import { TradesList } from '@/components/TradesList';
import { Maximize, Activity, TrendingUp, TrendingDown, DollarSign, Play, Pause, Trash2, Settings2, RefreshCw, Briefcase, ArrowUpRight, ArrowDownRight, Bot, Code, X, Video, Zap, Lock, AlertTriangle, CheckCircle } from 'lucide-react';
import { clearRuntimeCredentials, clearCredentials, getRuntimeCredentials } from '@/lib/security/credentials';
import { ErrorBoundary } from '@/components/ErrorBoundary';

const CHART_MARGIN = { top: 20, right: 30, left: 20, bottom: 20 };
const XAXIS_LABEL = { value: 'Z-Score', position: 'insideBottom', offset: -10 };
const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];

export default function Dashboard() {
  const [isUnlocked, setIsUnlocked] = useState(true);
  const [tradingMode, setTradingMode] = useState<'PAPER' | 'TESTNET' | 'MAINNET'>('PAPER');
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);
  const [pendingMode, setPendingMode] = useState<'PAPER' | 'TESTNET' | 'MAINNET' | null>(null);
  const [showWelcome, setShowWelcome] = useState(false);
  
  const handleIntentRef = useRef<((intent: any) => void) | null>(null);
  
  const executeModeSwitch = (newMode: 'PAPER' | 'TESTNET' | 'MAINNET') => {
    setTradingMode(newMode);
    clearData();
    clearBuffer();

    if (newMode === 'PAPER') {
      setIsUnlocked(true);
    } else if (getRuntimeCredentials()) {
      setIsUnlocked(true);
    } else {
      setIsUnlocked(false);
    }
  };

  const handleModeSwitch = (newMode: 'PAPER' | 'TESTNET' | 'MAINNET') => {
    if (newMode === tradingMode) return;
    if (newMode === 'MAINNET') {
      setPendingMode('MAINNET');
      setShowLiveConfirm(true);
    } else {
      executeModeSwitch(newMode);
    }
  };
  const { isReady, metrics, uiDelta, getUIDelta, processBatch, clearData, clearCache, executeTrade, setAutoTrade, configureStrategy, runAdhocAnalysis, adhocResult, setStrategyParams } = usePythonWorker((intent) => {
    if (handleIntentRef.current) handleIntentRef.current(intent);
  });
  const { orderBooks, latestTicks, getAndClearBuffer, clearBuffer, isPlaying, setIsPlaying, isRecording, toggleRecording, executeIntent, setSymbols } = useMarketData(
    isUnlocked, 
    tradingMode,
    (tick) => {
      if (isReady && isPlaying && isUnlocked) {
        processBatch([{ type: 'TICK', data: tick }]);
      }
    },
    (report) => {
      if (isReady && isUnlocked) {
        processBatch([{ type: 'EXECUTION_REPORT', data: report }]);
      }
    },
    (state) => {
      if (isReady && isUnlocked) {
        processBatch([{ type: 'SYNC_STATE', data: state }]);
      }
    },
    (fundingEvent) => {
      if (isReady && isUnlocked) {
        processBatch([fundingEvent]);
      }
    }
  );
  
  
  useEffect(() => {
    handleIntentRef.current = executeIntent;
  }, [executeIntent]);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const seenWelcome = localStorage.getItem('PulseQuant_welcome_shown');
    if (!seenWelcome) {
      /* eslint-disable-next-line react-hooks/set-state-in-effect */
      setShowWelcome(true);
    }
  }, []);

  const [timeframe, setTimeframe] = useState<number | null>(null);
  const [chartType, setChartType] = useState<'line' | 'candlestick'>('line');
  const [autoScale, setAutoScale] = useState(true);
  const [followLive, setFollowLive] = useState(true);
  const chartRef = useRef<any>(null);

  const [uiRefreshInterval, setUiRefreshInterval] = useState(500);
  const [isAutoTrading, setIsAutoTrading] = useState(false);
  const [showCodeModal, setShowCodeModal] = useState(false);
  const [engineCode, setEngineCode] = useState('');

  // Mobile view tabs: 'sim' = top simulator/metrics, 'chart' = realtime chart, 'books' = orderbooks+trades
  const [mobileView, setMobileView] = useState<'sim' | 'chart' | 'books'>('chart');

  const [targetAsset, setTargetAsset] = useState('SUSHIUSDT');
  const [featureAsset, setFeatureAsset] = useState('CAKEUSDT');
  const [isFetchingHistory, setIsFetchingHistory] = useState(false);
  const [analysisPair, setAnalysisPair] = useState<string | null>(null);

  const AVAILABLE_ASSETS = ['ORDIUSDC', 'SUIUSDC', 'ETHUSDT', 'BTCUSDT', 'SUSHIUSDT', 'CAKEUSDT', 'SOLUSDC', 'XRPUSDC'];

  const formatTick = useCallback((val: number) => val.toFixed(2), []);
  const formatTooltipValue = useCallback((value: any) => [Number(value), 'Frequency'], []);
  const formatTooltipLabel = useCallback((label: any) => `Z-Score: ${Number(label).toFixed(2)}`, []);
  const posRecSigmaLabel = useMemo(() => ({ position: 'top', value: '+Rec Sigma', fill: '#10b981' } as any), []);
  const negRecSigmaLabel = useMemo(() => ({ position: 'top', value: '-Rec Sigma', fill: '#10b981' } as any), []);

  const handleRunAnalysis = useCallback(async () => {
    setIsFetchingHistory(true);
    try {
      const fetchHistory = async (symbol: string) => {
        const allKlines: any[] = [];
        const endTime = Date.now();
        const startTime = endTime - (30 * 24 * 60 * 60 * 1000); // 30 days
        let currentStart = startTime;
        while (currentStart < endTime) {
          const res = await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${symbol}&interval=1m&startTime=${currentStart}&endTime=${endTime}&limit=1500`);
          const data = await res.json();
          if (!data || !Array.isArray(data) || data.length === 0) break;
          data.forEach((k: any) => allKlines.push([k[0], parseFloat(k[4])]));
          currentStart = data[data.length - 1][0] + 1;
        }
        return allKlines;
      };

      const targetData = await fetchHistory(targetAsset);
      const featureData = await fetchHistory(featureAsset);
      
      await runAdhocAnalysis(targetData, featureData, 800);
    } catch (e) {
      console.error(e);
    } finally {
      setIsFetchingHistory(false);
    }
  }, [targetAsset, featureAsset, runAdhocAnalysis]);

  const fetchRegimeData = useCallback(async (target: string, feature: string) => {
    if (!isReady) return;
    try {
      const fetchHistory = async (symbol: string) => {
        const allKlines: any[] = [];
        const endTime = Date.now();
        const startTime = endTime - (30 * 24 * 60 * 60 * 1000); // 30 days
        let currentStart = startTime;
        while (currentStart < endTime) {
          const res = await fetch(`https://fapi.binance.com/fapi/v1/klines?symbol=${symbol}&interval=1m&startTime=${currentStart}&endTime=${endTime}&limit=1500`);
          const data = await res.json();
          if (!data || !Array.isArray(data) || data.length === 0) break;
          data.forEach((k: any) => allKlines.push([k[0], parseFloat(k[4])]));
          currentStart = data[data.length - 1][0] + 1;
        }
        return allKlines;
      };

      const targetData = await fetchHistory(target);
      const featureData = await fetchHistory(feature);
      
      if (targetData.length > 0 && featureData.length > 0) {
        processBatch([{ type: 'REGIME_DATA', data: { targetData, featureData } }]);
      }
    } catch (e) {
      console.error('Failed to fetch regime data', e);
    }
  }, [isReady, processBatch]);

  useEffect(() => {
    if (isReady && isUnlocked) {
      fetchRegimeData(targetAsset, featureAsset);
      const interval = setInterval(() => {
        fetchRegimeData(targetAsset, featureAsset);
      }, 15 * 60 * 1000); // Every 15 minutes
      return () => clearInterval(interval);
    }
  }, [isReady, isUnlocked, targetAsset, featureAsset, fetchRegimeData]);

  useEffect(() => {
    if (!isReady) return;

    void (async () => {
      await setSymbols(targetAsset, featureAsset);
      configureStrategy(targetAsset, featureAsset);
    })();
  }, [isReady, targetAsset, featureAsset, setSymbols, configureStrategy]);

  useEffect(() => {
    if (isReady && !isFetchingHistory && analysisPair !== `${targetAsset}-${featureAsset}`) {
      setAnalysisPair(`${targetAsset}-${featureAsset}`);
      handleRunAnalysis();
    }
  }, [isReady, targetAsset, featureAsset, isFetchingHistory, analysisPair, handleRunAnalysis]);

  useEffect(() => {
    if (adhocResult && !adhocResult.error && adhocResult.recommended_sigma) {
      setStrategyParams({ sigma_threshold: adhocResult.recommended_sigma });
    }
  }, [adhocResult, setStrategyParams]);

  const handlePairChange = async (newTarget: string, newFeature: string) => {
    if (newTarget === newFeature) return;
    
    // Prevent switching if there are active positions
    if (currentState?.positions) {
      const hasOpenPos = Object.values(currentState.positions).some((pos) => Math.abs(pos as number) > 1e-8);
      if (hasOpenPos) {
        alert("Cannot change pairs while you have an open position. Close it first.");
        return;
      }
    }

    if (isAutoTrading) {
      setIsAutoTrading(false);
      setAutoTrade(false);
    }
    
    setTargetAsset(newTarget);
    setFeatureAsset(newFeature);
    
    clearData();
    clearBuffer();
    
    await setSymbols(newTarget, newFeature);
    configureStrategy(newTarget, newFeature);
  };

  const handleShowCode = async () => {
    if (!engineCode) {
      try {
        const res = await fetch('/python/engine.py');
        const text = await res.text();
        setEngineCode(text);
      } catch (e) {
        console.error('Failed to load engine code', e);
        setEngineCode('Failed to load code.');
      }
    }
    setShowCodeModal(true);
  };

  useEffect(() => {
    const interval = setInterval(() => {
      if (isReady && isPlaying) {
        getUIDelta();
      }
    }, uiRefreshInterval);

    return () => clearInterval(interval);
  }, [isReady, isPlaying, uiRefreshInterval, getUIDelta]);

  const handleAutoTradeToggle = () => {
    const newState = !isAutoTrading;
    setIsAutoTrading(newState);
    setAutoTrade(newState);
  };

  // State data is now from uiDelta directly or fallback to metrics for backwards compatibility
  const currentState = uiDelta || metrics;

  const targetDepth = orderBooks[targetAsset] || { bids: [], asks: [] };
  const targetTick = latestTicks[targetAsset];
  
  const featureDepth = orderBooks[featureAsset] || { bids: [], asks: [] };
  const featureTick = latestTicks[featureAsset];

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900 p-6 font-sans">
      {showWelcome && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl p-6 max-w-lg w-full">
            <h2 className="text-xl font-bold mb-2">Welcome to PulseQuant</h2>
            <p className="text-sm text-gray-600 mb-4">
              Paper mode is enabled by default so you can try strategies without Binance credentials. You can switch to Testnet/Mainnet whenever you are ready.
            </p>
            <button
              onClick={() => {
                localStorage.setItem('PulseQuant_welcome_shown', '1');
                setShowWelcome(false);
              }}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700"
            >
              Got it!
            </button>
          </div>
        </div>
      )}

      {!isUnlocked && tradingMode !== 'PAPER' && (
        <SecuritySetupModal
          onSuccess={() => setIsUnlocked(true)}
          onSkip={() => executeModeSwitch('PAPER')}
        />
      )}
      
      <div className={`max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 space-y-6 ${!isUnlocked ? 'blur-sm pointer-events-none' : ''}`}>
        <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-gray-200 pb-4 gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">PulseQuant Dashboard</h1>
            <p className="text-sm text-gray-500">Stat Arb Engine via Pyodide WASM</p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            {tradingMode !== 'PAPER' && (
              <button
                onClick={() => {
                  clearRuntimeCredentials();
                  setIsUnlocked(false);
                }}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold transition-all shadow-sm bg-gray-100 text-gray-700 border border-gray-200 hover:bg-gray-200"
                title="Lock Application"
              >
                <Lock className="w-4 h-4" />
                <span className="hidden sm:inline">Lock</span>
              </button>
            )}
            {(tradingMode === 'TESTNET' || tradingMode === 'MAINNET') && getRuntimeCredentials() && (
              <button
                onClick={() => {
                  clearCredentials();
                  clearRuntimeCredentials();
                  setIsUnlocked(false);
                }}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold transition-all shadow-sm bg-red-100 text-red-700 border border-red-200 hover:bg-red-200"
                title="Rotate Credentials"
              >
                <span className="hidden sm:inline">Rotate Credentials</span>
              </button>
            )}
            <div className="flex items-center bg-gray-100 p-1 rounded-lg border border-gray-200">
              <button
                onClick={() => handleModeSwitch('PAPER')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-semibold transition-all ${
                  tradingMode === 'PAPER' 
                    ? 'bg-white text-blue-600 shadow-sm' 
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Bot className="w-4 h-4" />
                <span className="hidden sm:inline">Paper</span>
              </button>
              <button
                onClick={() => handleModeSwitch('TESTNET')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-semibold transition-all ${
                  tradingMode === 'TESTNET' 
                    ? 'bg-amber-100 text-amber-700 shadow-sm border border-amber-200' 
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                <Activity className="w-4 h-4" />
                <span className="hidden sm:inline">Testnet</span>
              </button>
              <button
                onClick={() => handleModeSwitch('MAINNET')}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-semibold transition-all ${
                  tradingMode === 'MAINNET' 
                    ? 'bg-red-500 text-white shadow-sm shadow-red-500/30 animate-pulse' 
                    : 'text-gray-500 hover:text-red-500'
                }`}
              >
                <Zap className="w-4 h-4" />
                <span className="hidden sm:inline">Mainnet</span>
              </button>
            </div>
             <div className="flex items-center gap-3 ml-2">
               <div className={`w-3 h-3 rounded-full ${isReady ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'}`} />
               <span className="text-sm font-medium text-gray-700">
                 {isReady ? 'Engine Ready' : 'Booting Pandas...'}
               </span>
             </div>
          </div>
        </header>

        {showLiveConfirm && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
            <div className="bg-white rounded-xl shadow-2xl p-6 max-w-md w-full mx-4 border border-red-200">
              <div className="flex items-center gap-3 text-red-600 mb-4">
                <Zap className="w-6 h-6" />
                <h2 className="text-xl font-bold">Enable Live Trading?</h2>
              </div>
              <p className="text-gray-600 mb-6">
                You are about to enable live trading on Binance Mainnet. Your orders will be sent directly to the exchange and filled using real funds.
              </p>
              <p className="text-gray-600 mb-6 font-semibold">
                Are you sure you want to proceed?
              </p>
              <div className="flex justify-end gap-3">
                <button
                  onClick={() => {
                    setPendingMode(null);
                    setShowLiveConfirm(false);
                  }}
                  className="px-4 py-2 rounded-lg font-medium bg-gray-100 text-gray-700 hover:bg-gray-200"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    if (pendingMode) {
                      executeModeSwitch(pendingMode);
                    }
                    setShowLiveConfirm(false);
                  }}
                  className="px-4 py-2 rounded-lg font-medium bg-red-600 text-white hover:bg-red-700 shadow-lg shadow-red-600/30"
                >
                  Enable Live Trading
                </button>
              </div>
            </div>
          </div>
        )}

         {/* Control Bar */}
         <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between bg-white border border-gray-200 shadow-sm p-4 rounded-xl gap-4">
           <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              disabled={!isReady}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                isPlaying 
                  ? 'bg-amber-500/20 text-amber-500 hover:bg-amber-500/30' 
                  : 'bg-emerald-500/20 text-emerald-500 hover:bg-emerald-500/30'
              }`}
            >
              {isPlaying ? (
                <span className="flex items-center">
                  <Pause className="w-4 h-4" />
                  <span className="hidden sm:inline">Pause Feed</span>
                </span>
              ) : (
                <span className="flex items-center">
                  <Play className="w-4 h-4" />
                  <span className="hidden sm:inline">Resume Feed</span>
                </span>
              )}
            </button>
            <button
              onClick={toggleRecording}
              disabled={!isReady || !isPlaying}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                isRecording
                  ? 'bg-red-500/20 text-red-600 hover:bg-red-500/30 shadow-[0_0_10px_rgba(239,68,68,0.3)] animate-pulse'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
              }`}
              title="Capture market data to a JSONL file"
            >
              <Video className="w-4 h-4" /> <span className="hidden sm:inline">{isRecording ? 'Recording...' : 'Record Session'}</span>
            </button>
            <button
              onClick={() => {
                clearData();
                clearBuffer();
              }}
              disabled={!isReady}
              className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Trash2 className="w-4 h-4" /> <span className="hidden sm:inline">Clear Data</span>
            </button>
            <button
              onClick={clearCache}
              className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
              title="Clear Pyodide WASM Cache"
            >
              <RefreshCw className="w-4 h-4" /> <span className="hidden sm:inline">Clear Cache</span>
            </button>
          </div>
          
           <div className="flex items-center gap-4 text-sm text-gray-500">
             <div className="flex items-center gap-2">
              <Settings2 className="w-4 h-4" />
              <span>UI Refresh Rate:</span>
            </div>
             <input 
               type="range" 
               min="100" 
               max="2000" 
               step="100" 
               value={uiRefreshInterval} 
               onChange={(e) => setUiRefreshInterval(Number(e.target.value))}
               className="w-32 accent-blue-500"
             />
             <span className="font-mono w-12 text-right">{uiRefreshInterval}ms</span>
          </div>
        </div>

        {currentState ? (
          <div className="space-y-6 animate-in fade-in duration-700">
            {/* Mobile tab bar (small screens only) */}
            <div className="sm:hidden flex items-center justify-around bg-white p-2 rounded-lg shadow-sm">
              <button onClick={() => setMobileView('sim')} className={`flex flex-col items-center text-xs py-1 px-3 rounded ${mobileView === 'sim' ? 'bg-blue-50 text-blue-700' : 'text-gray-500'}`}>
                <Briefcase className="w-4 h-4" />
                <span>Sim</span>
              </button>
              <button onClick={() => setMobileView('chart')} className={`flex flex-col items-center text-xs py-1 px-3 rounded ${mobileView === 'chart' ? 'bg-blue-50 text-blue-700' : 'text-gray-500'}`}>
                <Maximize className="w-4 h-4" />
                <span>Chart</span>
              </button>
              <button onClick={() => setMobileView('books')} className={`flex flex-col items-center text-xs py-1 px-3 rounded ${mobileView === 'books' ? 'bg-blue-50 text-blue-700' : 'text-gray-500'}`}>
                <Activity className="w-4 h-4" />
                <span>Books</span>
              </button>
            </div>

            {/* Top simulator & metrics (hidden on mobile unless selected) */}
            <div className={`sm:block ${mobileView === 'sim' ? 'block' : 'hidden'}`}>
              {/* Stat Arb Trading Simulator Panel */}
              <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl">
             <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-blue-100 rounded-lg">
                    <Briefcase className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <h2 className="text-sm font-medium text-gray-500">
                      {tradingMode === 'PAPER' ? 'Paper Trading Simulator' : 
                       tradingMode === 'TESTNET' ? 'Binance Testnet Engine' : 
                       'Binance Mainnet Engine'}
                    </h2>
                    <div className="flex gap-4 items-center">
                      <div className="flex flex-col">
                        <div className="text-2xl font-bold text-gray-900 tracking-tight">
                          ${currentState.portfolio_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '100,000.00'}
                        </div>
                        {currentState.unrealized_pnl && Object.values(currentState.unrealized_pnl as Record<string, number>).reduce((a: number, b: number) => a + b, 0) !== 0 && (
                          <div className={`text-xs font-semibold font-mono ${Object.values(currentState.unrealized_pnl as Record<string, number>).reduce((a: number, b: number) => a + b, 0) > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                            {Object.values(currentState.unrealized_pnl as Record<string, number>).reduce((a: number, b: number) => a + b, 0) > 0 ? '+' : ''}
                            {Object.values(currentState.unrealized_pnl as Record<string, number>).reduce((a: number, b: number) => a + b, 0).toFixed(2)} uPnL
                          </div>
                        )}
                      </div>
                      <div className="flex gap-2 items-center text-sm ml-4 border-l border-gray-300 pl-4">
                         <select className="bg-gray-50 border border-gray-200 rounded p-1" value={targetAsset} onChange={(e) => handlePairChange(e.target.value, featureAsset)}>
                             {AVAILABLE_ASSETS.map(a => <option key={a} disabled={a === featureAsset}>{a}</option>)}
                         </select>
                         <span className="text-gray-500">vs</span>
                         <select className="bg-gray-50 border border-gray-200 rounded p-1" value={featureAsset} onChange={(e) => handlePairChange(targetAsset, e.target.value)}>
                             {AVAILABLE_ASSETS.map(a => <option key={a} disabled={a === targetAsset}>{a}</option>)}
                         </select>
                      </div>
                    </div>
                  </div>
                </div>

                 <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Cash</div>
                    <div className="font-mono text-gray-700">${currentState.capital?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '100,000.00'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Net Delta</div>
                    <div className={`font-mono ${currentState.net_delta > 0 ? 'text-emerald-600' : currentState.net_delta < 0 ? 'text-red-600' : 'text-gray-700'}`}>
                      {currentState.net_delta > 0 ? '+' : ''}{currentState.net_delta?.toFixed(4) || '0.00'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Hedge Ratio (Beta)</div>
                    <div className="font-mono text-gray-700">
                      {currentState.spread_metrics?.beta != null ? currentState.spread_metrics.beta.toFixed(4) : (
                        <span className="text-gray-400 flex items-center gap-1">
                          <div className="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                          <span>Calc...</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Hurst Exponent</div>
                    <div className="font-mono text-gray-700">
                      {currentState.spread_metrics?.hurst != null ? currentState.spread_metrics.hurst.toFixed(4) : (
                        <span className="text-gray-400 flex items-center gap-1">
                          <div className="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                          <span>Calc...</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Half-life (mins)</div>
                    <div className="font-mono text-gray-700">
                      {currentState.spread_metrics?.half_life != null ? currentState.spread_metrics.half_life.toFixed(1) : (
                        <span className="text-gray-400 flex items-center gap-1">
                          <div className="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                          <span>Calc...</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">ADF p-value</div>
                    <div className="font-mono text-gray-700">
                      {currentState.spread_metrics?.adf_pvalue != null ? currentState.spread_metrics.adf_pvalue.toFixed(4) : (
                        <span className="text-gray-400 flex items-center gap-1">
                          <div className="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                          <span>Calc...</span>
                        </span>
                      )}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Toxicity Flag</div>
                    <div className={`font-mono ${currentState.toxicity_flag ? 'text-red-600 font-bold' : 'text-emerald-600'}`}>
                      {currentState.toxicity_flag ? 'TOXIC' : 'SAFE'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Execution State</div>
                    <div className="font-mono text-gray-700">
                      {currentState.execution_state || 'IDLE'}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={handleAutoTradeToggle}
                    disabled={!isReady}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 ${
                      isAutoTrading 
                        ? 'bg-blue-600 text-white shadow-[0_0_15px_rgba(37,99,235,0.5)]' 
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    <span className="inline-flex items-center gap-2"><Bot className="w-4 h-4" /> <span>{isAutoTrading ? 'Auto-Trading ON' : 'Auto-Trade'}</span></span>
                  </button>
                </div>
              </div>

              {/* Strategy Settings & Positions */}
               <div className="mt-4 pt-4 border-t border-gray-200 flex flex-wrap items-start justify-between gap-4">
                <div className="flex flex-col gap-2 flex-1">
                  <span className="text-sm font-medium text-gray-500">Active Positions:</span>
                  <div className="flex flex-wrap gap-3">
                    {currentState.positions && Object.entries(currentState.positions).map(([sym, pos]) => {
                      if (Math.abs(pos as number) < 1e-8) return null;
                      const avgEntry = currentState.avg_entry_prices?.[sym] || 0;
                      const upnl = currentState.unrealized_pnl?.[sym] || 0;
                        return (
                          <div key={sym} className="flex flex-col bg-gray-50 px-3 py-2 rounded-lg border border-gray-200 shadow-sm min-w-0 w-full sm:w-auto sm:min-w-[140px]">
                          <div className="flex justify-between items-center mb-1">
                            <span className="text-xs font-bold text-gray-700">{sym}</span>
                            <span className={`font-mono text-sm font-semibold ${(pos as number) > 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                              {(pos as number) > 0 ? 'LONG' : 'SHORT'} {(pos as number).toFixed(4)}
                            </span>
                          </div>
                          <div className="flex justify-between items-center text-xs">
                            <span className="text-gray-500">Entry:</span>
                            <span className="font-mono text-gray-800">{avgEntry.toFixed(2)}</span>
                          </div>
                          <div className="flex justify-between items-center text-xs mt-0.5">
                            <span className="text-gray-500">uPnL:</span>
                            <span className={`font-mono font-medium ${upnl > 0 ? 'text-emerald-600' : upnl < 0 ? 'text-red-600' : 'text-gray-500'}`}>
                              {upnl > 0 ? '+' : ''}{upnl.toFixed(2)}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                    {(!currentState.positions || Object.values(currentState.positions).every(p => Math.abs(p as number) < 1e-8)) && (
                      <span className="text-sm text-gray-400 italic py-2">No open positions</span>
                    )}
                  </div>
                </div>
                
            </div>

            {/* General Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              
             <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-4">
                <div className="p-3 bg-emerald-100 text-emerald-600 rounded-lg hidden sm:block">
                  <Activity className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm text-gray-500 font-medium">Spread</p>
                  <p className="text-xl font-semibold font-mono">{currentState.spread_metrics?.current_spread?.toFixed(4) ?? '0.00'}</p>
                </div>
              </div>

             <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-4">
                <div className="p-3 bg-purple-100 text-purple-600 rounded-lg hidden sm:block">
                  <TrendingUp className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm text-gray-500 font-medium">Z-Score</p>
                  <p className={`text-xl font-semibold font-mono ${currentState.spread_metrics?.z_score > 2 ? 'text-red-600' : currentState.spread_metrics?.z_score < -2 ? 'text-emerald-600' : 'text-gray-900'}`}>
                    {currentState.spread_metrics?.z_score?.toFixed(2) ?? '0.00'}
                  </p>
                </div>
              </div>

             <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-4">
                <div className="p-3 bg-pink-100 text-pink-600 rounded-lg hidden sm:block">
                  <DollarSign className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm text-gray-500 font-medium">Target Price</p>
                  <p className="text-xl font-semibold font-mono">
                    {currentState.spread_metrics?.target_price?.toFixed(2) ?? "0.00"}
                  </p>
                </div>
              </div>

             <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-4">
                <div className="p-3 bg-blue-100 text-blue-600 rounded-lg hidden sm:block">
                  <DollarSign className="w-6 h-6" />
                </div>
                <div className="flex flex-col">
                  <p className="text-sm text-gray-500 font-medium">Feature Price</p>
                  <p className="text-xl font-semibold font-mono">{currentState.spread_metrics?.feature_price?.toFixed(2) ?? '0.00'}</p>
                </div>
              </div>
            </div>

            {/* === Death Spiral Cost Accounting === */}
             {(() => {
              const grossPnl = (currentState.realized_pnl ?? 0);
              const totalFees = (currentState.total_fees_paid ?? 0);
              const totalFunding = (currentState.total_funding_paid ?? 0);
              const netPnl = grossPnl - totalFees - totalFunding;
              const dynamicHurdleBps = (currentState.dynamic_hurdle_bps ?? 0);
              const currentSpreadBps = Math.abs((currentState.spread_metrics?.current_spread ?? 0)) * 10000;
              const isBlocked = dynamicHurdleBps >= currentSpreadBps || currentSpreadBps < 0.001;
              const maxBar = Math.max(dynamicHurdleBps, currentSpreadBps, 1);
              return (
                <div className="space-y-3">
                  {/* Row 1: PnL breakdown */}
                 <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {/* Gross PnL */}
                     <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-3">
                      <div className="p-2.5 bg-blue-100 text-blue-600 rounded-lg shrink-0">
                        <TrendingUp className="w-5 h-5" />
                      </div>
                      <div>
                        <p className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Gross PnL</p>
                        <p className={`text-lg font-bold font-mono ${
                          grossPnl > 0 ? 'text-emerald-600' : grossPnl < 0 ? 'text-red-600' : 'text-gray-700'
                        }`}>
                          {grossPnl >= 0 ? '+' : ''}{grossPnl.toFixed(2)}
                        </p>
                        <p className="text-xs text-gray-400">Before costs</p>
                      </div>
                    </div>

                    {/* Net PnL */}
                     <div className={`border shadow-sm p-4 rounded-xl flex items-center gap-3 ${
                      netPnl < -50 ? 'bg-red-50 border-red-300' :
                      netPnl < 0 ? 'bg-orange-50 border-orange-200' :
                      'bg-white border-gray-200'
                    }`}>
                      <div className={`p-2.5 rounded-lg shrink-0 ${
                        netPnl < 0 ? 'bg-red-100 text-red-600' : 'bg-emerald-100 text-emerald-600'
                      }`}>
                        {netPnl < 0 ? <span className="inline-flex items-center"><TrendingDown className="w-5 h-5" /></span> : <span className="inline-flex items-center"><TrendingUp className="w-5 h-5" /></span>}
                      </div>
                      <div>
                        <p className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Net PnL</p>
                        <p className={`text-lg font-bold font-mono ${
                          netPnl > 0 ? 'text-emerald-600' : 'text-red-600'
                        }`}>
                          {netPnl >= 0 ? '+' : ''}{netPnl.toFixed(2)}
                        </p>
                        <p className="text-xs text-gray-400">After fees & funding</p>
                      </div>
                    </div>

                    {/* Total Fees */}
                     <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-3">
                      <div className="p-2.5 bg-amber-100 text-amber-600 rounded-lg shrink-0">
                        <DollarSign className="w-5 h-5" />
                      </div>
                      <div>
                        <p className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Total Fees Paid</p>
                        <p className="text-lg font-bold font-mono text-amber-600">
                          -{totalFees.toFixed(4)}
                        </p>
                        <p className="text-xs text-gray-400">Maker/Taker</p>
                      </div>
                    </div>

                    {/* Funding Paid */}
                     <div className={`border shadow-sm p-4 rounded-xl flex items-center gap-3 ${
                      totalFunding > 10 ? 'bg-red-50 border-red-200' : 'bg-white border-gray-200'
                    }`}>
                      <div className={`p-2.5 rounded-lg shrink-0 ${
                        totalFunding > 0 ? 'bg-red-100 text-red-600' : 'bg-emerald-100 text-emerald-600'
                      }`}>
                        <DollarSign className="w-5 h-5" />
                      </div>
                      <div>
                        <p className="text-xs text-gray-400 uppercase tracking-wider font-semibold">Funding Paid</p>
                        <p className={`text-lg font-bold font-mono ${
                          totalFunding > 0 ? 'text-red-600' : totalFunding < 0 ? 'text-emerald-600' : 'text-gray-700'
                        }`}>
                          {totalFunding >= 0 ? '-' : '+'}{Math.abs(totalFunding).toFixed(4)}
                        </p>
                        <p className="text-xs text-gray-400">{totalFunding < 0 ? 'Earned (credit)' : 'Paid (debit)'}</p>
                      </div>
                    </div>
                  </div>

                  {/* Row 2: Dynamic Hurdle vs Spread */}
                 <div className={`border shadow-sm p-5 rounded-xl ${
                     isBlocked ? 'bg-red-50 border-red-200' : 'bg-emerald-50 border-emerald-200'
                   }`}>
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-2">
                        <div className={`p-1.5 rounded-lg ${
                          isBlocked ? 'bg-red-100 text-red-600' : 'bg-emerald-100 text-emerald-600'
                        }`}>
                          {isBlocked ? <span className="inline-flex items-center"><AlertTriangle className="w-4 h-4" /></span> : <span className="inline-flex items-center"><CheckCircle className="w-4 h-4" /></span>}
                        </div>
                        <h3 className="text-sm font-bold text-gray-800">Dynamic Hurdle vs Current Spread</h3>
                        <span className={`text-xs font-bold px-2.5 py-1 rounded-full ${
                          isBlocked
                            ? 'bg-red-500 text-white'
                            : 'bg-emerald-500 text-white'
                        }`}>
                          {isBlocked ? 'BLOCKED' : 'CLEAR'}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500">
                        {isBlocked
                          ? 'Spread too thin to cover costs — engine will not trade'
                          : 'Edge exceeds costs — engine may signal entry'}
                      </p>
                    </div>

                    <div className="space-y-3">
                      {/* Dynamic Hurdle bar */}
                      <div>
                        <div className="flex justify-between text-xs mb-1">
                          <span className="font-semibold text-red-600 flex items-center gap-1">
                            <span className="inline-flex items-center gap-2"><AlertTriangle className="w-3 h-3" /> <span>Dynamic Hurdle</span></span>
                          </span>
                          <span className="font-mono font-bold text-red-600">{dynamicHurdleBps.toFixed(2)} bps</span>
                        </div>
                        <div className="h-4 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-red-400 rounded-full transition-all duration-500"
                            style={{ width: `${Math.min(100, (dynamicHurdleBps / maxBar) * 100)}%` }}
                          />
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">Maker fee + taker fee + slippage + funding drag</p>
                      </div>

                      {/* Current spread bar */}
                      <div>
                        <div className="flex justify-between text-xs mb-1">
                          <span className={`font-semibold flex items-center gap-1 ${
                            isBlocked ? 'text-gray-500' : 'text-emerald-600'
                          }`}>
                            <span className="inline-flex items-center gap-2"><Activity className="w-3 h-3" /> <span>Current Spread</span></span>
                          </span>
                          <span className={`font-mono font-bold ${
                            isBlocked ? 'text-gray-500' : 'text-emerald-600'
                          }`}>{currentSpreadBps.toFixed(2)} bps</span>
                        </div>
                        <div className="h-4 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full transition-all duration-500 ${
                              isBlocked ? 'bg-gray-400' : 'bg-emerald-500'
                            }`}
                            style={{ width: `${Math.min(100, (currentSpreadBps / maxBar) * 100)}%` }}
                          />
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">Available gross edge (before any costs)</p>
                      </div>

                      {/* Gap summary */}
                      <div className={`mt-1 text-xs font-semibold text-right ${
                        isBlocked ? 'text-red-600' : 'text-emerald-600'
                      }`}>
                        {isBlocked
                          ? `Deficit: ${(dynamicHurdleBps - currentSpreadBps).toFixed(2)} bps needs to close before a trade triggers`
                          : `Surplus: +${(currentSpreadBps - dynamicHurdleBps).toFixed(2)} bps above the hurdle`
                        }
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}

            </div>

            {/* Trading Analytics (chart) - hidden on mobile unless selected */}
            <div className={`sm:block ${mobileView === 'chart' ? 'block' : 'hidden'}`}>
              <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl h-auto md:h-[500px] min-h-[320px]">

               <div className="flex flex-col xl:flex-row xl:items-center justify-between mb-4 gap-4">
                <div className="flex flex-col gap-2">
                  <h2 className="text-sm font-medium text-gray-500">Stat Arb Spread & Z-Score</h2>
                  <div className="flex flex-wrap items-center gap-2">
                    <label className="text-xs flex items-center gap-1 cursor-pointer bg-gray-50 border border-gray-200 rounded px-2 py-1 hover:bg-gray-100 select-none">
                      <input type="checkbox" checked={autoScale} onChange={e => setAutoScale(e.target.checked)} className="accent-blue-500" />
                      Auto-Scale
                    </label>
                    <label className="text-xs flex items-center gap-1 cursor-pointer bg-gray-50 border border-gray-200 rounded px-2 py-1 hover:bg-gray-100 select-none">
                      <input type="checkbox" checked={followLive} onChange={e => setFollowLive(e.target.checked)} className="accent-blue-500" />
                      Follow Live
                    </label>
                    <button onClick={() => chartRef.current?.fitContent()} className="text-xs bg-blue-50 text-blue-600 border border-blue-200 px-2 py-1 rounded hover:bg-blue-100 flex items-center gap-1">
                      <span className="inline-flex items-center gap-2"><Maximize className="w-3 h-3"/> <span>Fit</span></span>
                    </button>
                  </div>
                </div>
              </div>
               <div className="w-full h-[calc(100%-4.5rem)] min-h-0">
                <ErrorBoundary
                  fallback={(error, resetError) => (
                    <div className="w-full h-full border border-red-200 rounded-lg bg-red-50 p-4 flex flex-col justify-center">
                      <p className="text-sm text-red-700 mb-3">Chart failed to load: {error.message}</p>
                      <button
                        onClick={resetError}
                        className="self-start px-3 py-1.5 rounded bg-red-600 text-white text-sm hover:bg-red-700"
                      >
                        Reload Chart
                      </button>
                    </div>
                  )}
                >
                  <RealtimeChart 
                    ref={chartRef}
                    data={uiDelta} 
                    trades={currentState?.recent_trades} 
                    autoScale={autoScale}
                    followLive={followLive}
                  />
                </ErrorBoundary>
              </div>

            </div>

            </div>

            {/* Order Books + Trades grid - hidden on mobile unless selected */}
            <div className={`sm:block ${mobileView === 'books' ? 'block' : 'hidden'}`}>
              <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
              <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl h-auto md:h-[520px] lg:h-[1040px] lg:col-span-1 min-h-0">
                <h2 className="text-sm font-medium text-gray-500 mb-4">{targetAsset} Order Book</h2>
                <div className="w-full h-[calc(100%-2rem)] min-h-0 overflow-y-auto">
                  <OrderBookDepth 
                    bids={targetDepth.bids} 
                    asks={targetDepth.asks} 
                    currentBid={targetTick?.bid}
                    currentAsk={targetTick?.ask}
                    activeMakerPrice={currentState?.pending_orders?.find((o: any) => o.symbol === targetAsset)?.price}
                  />
                </div>
              </div>

              <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl h-auto md:h-[520px] lg:h-[1040px] lg:col-span-1 min-h-0">
                <h2 className="text-sm font-medium text-gray-500 mb-4">{featureAsset} Order Book</h2>
                <div className="w-full h-[calc(100%-2rem)] min-h-0 overflow-y-auto">
                  <OrderBookDepth 
                    bids={featureDepth.bids} 
                    asks={featureDepth.asks} 
                    currentBid={featureTick?.bid}
                    currentAsk={featureTick?.ask}
                    activeMakerPrice={currentState?.pending_orders?.find((o: any) => o.symbol === featureAsset)?.price}
                  />
                </div>
              </div>
              <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl h-auto md:h-[520px] lg:h-[1040px] lg:col-span-2 min-h-0">
                <h2 className="text-sm font-medium text-gray-500 mb-4">Orders Activity (Fills + Cancels + Pending)</h2>
                <div className="w-full h-[calc(100%-2rem)] min-h-0">
                  <TradesList trades={currentState?.recent_trades ?? []} cancellations={[]} pendingOrders={currentState?.pending_orders ?? []} />
                </div>
              </div>
            </div>

            {/* Ad-Hoc Analysis Section */}
            <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl mt-6">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                <div>
                  <h2 className="text-lg font-bold text-gray-900">Historical Ad-Hoc Analysis</h2>
                  <p className="text-sm text-gray-500">Run a 1-month retrospective analysis on the current pair to identify Z-score distribution and optimal sigma thresholds.</p>
                </div>
                <button
                  onClick={handleRunAnalysis}
                  disabled={isFetchingHistory || !isReady}
                  className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                    isFetchingHistory
                      ? 'bg-blue-100 text-blue-700' 
                      : 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm shadow-blue-500/30'
                  }`}
                >
                  {isFetchingHistory ? (
                    <span className="inline-flex items-center gap-2"><div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /> <span>Fetching Data...</span></span>
                  ) : (
                    <span className="inline-flex items-center gap-2"><Activity className="w-4 h-4" /> <span>Run Analysis</span></span>
                  )}
                </button>
              </div>

              {adhocResult && !adhocResult.error && (
                <div className="space-y-6">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
                      <p className="text-xs text-gray-500 uppercase font-semibold">Total Data Points</p>
                      <p className="text-lg font-mono font-bold text-gray-900">{adhocResult.total_points?.toLocaleString()}</p>
                    </div>
                    <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
                      <p className="text-xs text-gray-500 uppercase font-semibold">Z-Score Mean</p>
                      <p className="text-lg font-mono font-bold text-gray-900">{adhocResult.mean?.toFixed(4)}</p>
                    </div>
                    <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
                      <p className="text-xs text-gray-500 uppercase font-semibold">Z-Score Std Dev</p>
                      <p className="text-lg font-mono font-bold text-gray-900">{adhocResult.std?.toFixed(4)}</p>
                    </div>
                    <div className="bg-emerald-50 p-4 rounded-lg border border-emerald-200">
                      <p className="text-xs text-emerald-600 uppercase font-semibold">Recommended Sigma</p>
                      <p className="text-lg font-mono font-bold text-emerald-700">±{adhocResult.recommended_sigma?.toFixed(2)}</p>
                    </div>
                  </div>

                  <div className="h-[400px] w-full mt-6">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={adhocResult.bins} margin={CHART_MARGIN}>
                        <XAxis 
                          dataKey="bin" 
                          tickFormatter={formatTick} 
                          label={XAXIS_LABEL} 
                        />
                        <YAxis />
                        <Tooltip formatter={formatTooltipValue} labelFormatter={formatTooltipLabel} />
                        <Bar dataKey="count" fill="#3b82f6" radius={BAR_RADIUS} />
                        <ReferenceLine x={adhocResult.recommended_sigma} stroke="#10b981" strokeDasharray="3 3" label={posRecSigmaLabel} />
                        <ReferenceLine x={-adhocResult.recommended_sigma} stroke="#10b981" strokeDasharray="3 3" label={negRecSigmaLabel} />
                        <ReferenceLine x={0} stroke="#ef4444" strokeWidth={1} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
              
              {adhocResult?.error && (
                <div className="bg-red-50 border border-red-200 p-4 rounded-lg text-red-700">
                  <p className="font-bold">Analysis Failed</p>
                  <p className="text-sm">{adhocResult.error}</p>
                </div>
              )}
            </div>

          </div>
        </div>
        </div>
      ) : (
          <div className="h-[400px] flex flex-col items-center justify-center border border-gray-200 border-dashed rounded-xl bg-white/50 shadow-sm">
            <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4" />
            <p className="text-gray-500 font-medium">Initializing...</p>
            <p className="text-sm text-gray-400 mt-2">Loading Python environment</p>
          </div>
        )}

        
    </div>
    </main>
  );
}
