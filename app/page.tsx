'use client';
import React, { useEffect, useState, useRef } from 'react';
import { usePythonWorker } from '@/hooks/usePythonWorker';
import { useMarketData } from '@/hooks/useMarketData';
import { SecuritySetupModal } from '@/components/SecuritySetupModal';
import { RealtimeChart } from '@/components/RealtimeChart';
import { OrderBookDepth } from '@/components/OrderBookDepth';
import { TradesList } from '@/components/TradesList';
import { Maximize, Activity, TrendingUp, DollarSign, Play, Pause, Trash2, Settings2, RefreshCw, Briefcase, ArrowUpRight, ArrowDownRight, Bot, Code, X, Video, Zap, Lock } from 'lucide-react';
import { clearRuntimeCredentials, clearCredentials, getRuntimeCredentials } from '@/lib/security/credentials';
import { ErrorBoundary } from '@/components/ErrorBoundary';

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
  const { isReady, metrics, uiDelta, getUIDelta, processBatch, clearData, clearCache, executeTrade, setAutoTrade, updateStrategy, setTradeSize } = usePythonWorker((intent) => {
    if (handleIntentRef.current) handleIntentRef.current(intent);
  });
  const { latestDepth, latestTick, getAndClearBuffer, clearBuffer, isPlaying, setIsPlaying, isRecording, toggleRecording, executeIntent } = useMarketData(
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
  const [strategyStyle, setStrategyStyle] = useState('moderate');
  const [strategySpeed, setStrategySpeed] = useState('normal');
  const [tradeSizeBps, setTradeSizeBps] = useState(100);
  const [showCodeModal, setShowCodeModal] = useState(false);
  const [engineCode, setEngineCode] = useState('');

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
    if (isReady) {
      setTradeSize(tradeSizeBps);
    }
  }, [tradeSizeBps, isReady, setTradeSize]);

  const handleStrategyChange = (style: string, speed: string) => {
    setStrategyStyle(style);
    setStrategySpeed(speed);
    updateStrategy(style, speed);
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
      
      <div className={`max-w-6xl mx-auto space-y-6 ${!isUnlocked ? 'blur-sm pointer-events-none' : ''}`}>
        <header className="flex items-center justify-between border-b border-gray-200 pb-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">PulseQuant Dashboard</h1>
            <p className="text-sm text-gray-500">Stat Arb Engine via Pyodide WASM</p>
          </div>
          <div className="flex items-center gap-4">
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
                Lock
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
                Rotate Credentials
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
                Paper
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
                Testnet
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
                Mainnet
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
        <div className="flex flex-wrap items-center justify-between bg-white border border-gray-200 shadow-sm p-4 rounded-xl gap-4">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              disabled={!isReady}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                isPlaying 
                  ? 'bg-amber-500/20 text-amber-500 hover:bg-amber-500/30' 
                  : 'bg-emerald-500/20 text-emerald-500 hover:bg-emerald-500/30'
              }`}
            >
              {isPlaying ? <><Pause className="w-4 h-4" /> Pause Feed</> : <><Play className="w-4 h-4" /> Resume Feed</>}
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
              <Video className="w-4 h-4" /> {isRecording ? 'Recording...' : 'Record Session'}
            </button>
            <button
              onClick={() => {
                clearData();
                clearBuffer();
              }}
              disabled={!isReady}
              className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Trash2 className="w-4 h-4" /> Clear Data
            </button>
            <button
              onClick={clearCache}
              className="flex items-center gap-2 px-4 py-2 rounded-lg font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
              title="Clear Pyodide WASM Cache"
            >
              <RefreshCw className="w-4 h-4" /> Clear Cache
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
                    <div className="text-2xl font-bold text-gray-900 tracking-tight">
                      ${currentState.portfolio_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '100,000.00'}
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-6">
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
                      {currentState.spread_metrics?.beta?.toFixed(4) || 'N/A'}
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
                  <div className="flex items-center bg-gray-50 border border-gray-200 rounded-lg px-2 py-1 mr-2">
                    <input 
                      type="number" 
                      value={isAutoTrading ? (strategyStyle === 'aggressive' ? 250 : strategyStyle === 'conservative' ? 50 : 100) : tradeSizeBps}
                      onChange={(e) => setTradeSizeBps(Math.max(1, parseInt(e.target.value) || 1))}
                      className="bg-transparent text-gray-700 w-16 text-right text-sm focus:outline-none disabled:opacity-50"
                      min="1"
                      disabled={isAutoTrading}
                    />
                    <span className="text-gray-400 text-xs ml-1 font-medium">bps</span>
                  </div>
                  <button
                    onClick={handleAutoTradeToggle}
                    disabled={!isReady}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-colors disabled:opacity-50 ${
                      isAutoTrading 
                        ? 'bg-blue-600 text-white shadow-[0_0_15px_rgba(37,99,235,0.5)]' 
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    <Bot className="w-4 h-4" /> {isAutoTrading ? 'Auto-Trading ON' : 'Auto-Trade'}
                  </button>
                </div>
              </div>

              {/* Strategy Settings */}
              <div className="mt-4 pt-4 border-t border-gray-200 flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium text-gray-500">Positions:</span>
                  <div className="flex gap-4">
                    {currentState.positions && Object.entries(currentState.positions).map(([sym, pos]) => (
                      <div key={sym} className="flex gap-2 items-center bg-gray-50 px-2 py-1 rounded-md border border-gray-200">
                        <span className="text-xs font-semibold text-gray-500">{sym}</span>
                        <span className={`font-mono text-sm ${(pos as number) > 0 ? 'text-emerald-600' : (pos as number) < 0 ? 'text-red-600' : 'text-gray-700'}`}>
                          {(pos as number) > 0 ? '+' : ''}{(pos as number).toFixed(4)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm font-medium text-gray-500">Signal Speed:</span>
                  <select 
                    className="bg-gray-50 border border-gray-200 text-sm rounded-lg px-3 py-1.5 text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    value={strategySpeed}
                    onChange={(e) => handleStrategyChange(strategyStyle, e.target.value)}
                  >
                    <option value="slow">Slow (Lagging)</option>
                    <option value="normal">Normal</option>
                    <option value="fast">Fast (Responsive)</option>
                  </select>
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

            {/* Trading Analytics - Simplified for now, or adapt as needed */}

            <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl h-[500px]">

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
                      <Maximize className="w-3 h-3"/> Fit
                    </button>
                  </div>
                </div>
              </div>
              <div className="w-full h-[calc(100%-4.5rem)]">
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

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl h-[1040px] lg:col-span-1">
                <h2 className="text-sm font-medium text-gray-500 mb-4">Order Book Depth</h2>
                <div className="w-full h-[calc(100%-2rem)]">
                  <OrderBookDepth 
                    bids={latestDepth.bids} 
                    asks={latestDepth.asks} 
                    currentBid={latestTick?.bid}
                    currentAsk={latestTick?.ask}
                  />
                </div>
              </div>
              
              <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl h-[1040px] lg:col-span-2">
                <h2 className="text-sm font-medium text-gray-500 mb-4">Orders Activity (Fills + Cancels + Pending)</h2>
                <div className="w-full h-[calc(100%-2rem)]">
                  <TradesList trades={currentState?.recent_trades ?? []} cancellations={[]} pendingOrders={currentState?.pending_orders ?? []} />
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="h-[400px] flex flex-col items-center justify-center border border-gray-200 border-dashed rounded-xl bg-white/50 shadow-sm">
            <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mb-4" />
            <p className="text-gray-500 font-medium">Initializing...</p>
            <p className="text-sm text-gray-400 mt-2">Loading Python environment with Pandas, NumPy, and SciPy</p>
          </div>
        )}

      </div>
    </main>
  );
}
