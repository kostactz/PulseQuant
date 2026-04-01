'use client';
import { useEffect, useState, useRef } from 'react';
import { usePythonWorker } from '@/hooks/usePythonWorker';
import { useMarketData } from '@/hooks/useMarketData';
import { SecuritySetupModal } from '@/components/SecuritySetupModal';
import { RealtimeChart } from '@/components/RealtimeChart';
import { OrderBookDepth } from '@/components/OrderBookDepth';
import { TradesList } from '@/components/TradesList';
import { Maximize, Activity, TrendingUp, DollarSign, Play, Pause, Trash2, Settings2, RefreshCw, Briefcase, ArrowUpRight, ArrowDownRight, Bot, Code, X, Video, Zap, Lock } from 'lucide-react';
import { clearRuntimeCredentials } from '@/lib/security/credentials';
import { ErrorBoundary } from '@/components/ErrorBoundary';

export default function Dashboard() {
  const [isUnlocked, setIsUnlocked] = useState(false);
  const [tradingMode, setTradingMode] = useState<'PAPER' | 'TESTNET' | 'MAINNET'>('PAPER');
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);
  const [pendingMode, setPendingMode] = useState<'PAPER' | 'TESTNET' | 'MAINNET' | null>(null);
  
  const handleIntentRef = useRef<((intent: any) => void) | null>(null);
  
  const handleModeSwitch = (newMode: 'PAPER' | 'TESTNET' | 'MAINNET') => {
    if (newMode === tradingMode) return;
    if (newMode === 'MAINNET') {
      setPendingMode('MAINNET');
      setShowLiveConfirm(true);
    } else {
      executeModeSwitch(newMode);
    }
  };

  const executeModeSwitch = (newMode: 'PAPER' | 'TESTNET' | 'MAINNET') => {
    setTradingMode(newMode);
    clearData();
    clearBuffer();
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

  
  const [timeframe, setTimeframe] = useState<number | null>(null);
  const [chartType, setChartType] = useState<'line' | 'candlestick'>('line');
  const [autoScale, setAutoScale] = useState(true);
  const [followLive, setFollowLive] = useState(true);
  const [visibleSeries, setVisibleSeries] = useState({
    ofi: true, ema: true, obi: true, vwap: true, macroSma: true, bb: true
  });
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
    // Poll the python engine for UI deltas
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

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900 p-6 font-sans">
      {!isUnlocked && (
        <SecuritySetupModal onSuccess={() => setIsUnlocked(true)} />
      )}
      
      <div className={`max-w-6xl mx-auto space-y-6 ${!isUnlocked ? 'blur-sm pointer-events-none' : ''}`}>
        <header className="flex items-center justify-between border-b border-gray-200 pb-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">PulseQuant Dashboard</h1>
            <p className="text-sm text-gray-500">Python Pandas Engine via Pyodide WASM</p>
          </div>
          <div className="flex items-center gap-4">
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

        {metrics ? (
          <div className="space-y-6 animate-in fade-in duration-700">
            {/* Paper Trading Simulator Panel */}
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
                      ${metrics.portfolio_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '100,000.00'}
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-6">
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Cash</div>
                    <div className="font-mono text-gray-700">${metrics.capital?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) || '100,000.00'}</div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Position</div>
                    <div className={`font-mono ${metrics.position > 0 ? 'text-emerald-600' : metrics.position < 0 ? 'text-red-600' : 'text-gray-700'}`}>
                      {metrics.position > 0 ? '+' : ''}
                      {metrics.position ? (Number.isInteger(metrics.position) ? metrics.position : metrics.position.toFixed(4)) : 0}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-gray-400 uppercase tracking-wider font-semibold mb-1">Unrealized PnL</div>
                    <div className={`font-mono ${(metrics.portfolio_value - 100000) >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                      {(metrics.portfolio_value - 100000) >= 0 ? '+' : ''}
                      ${(metrics.portfolio_value - 100000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
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
                    onClick={() => executeTrade('buy', tradeSizeBps)}
                    disabled={!isReady || isAutoTrading}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg font-medium bg-emerald-100 text-emerald-600 hover:bg-emerald-200 transition-colors disabled:opacity-50"
                  >
                    <ArrowUpRight className="w-4 h-4" /> Buy
                  </button>
                  <button
                    onClick={() => executeTrade('sell', tradeSizeBps)}
                    disabled={!isReady || isAutoTrading}
                    className="flex items-center gap-1 px-3 py-2 rounded-lg font-medium bg-red-100 text-red-600 hover:bg-red-200 transition-colors disabled:opacity-50"
                  >
                    <ArrowDownRight className="w-4 h-4" /> Sell
                  </button>
                  <div className="w-px h-8 bg-gray-200 mx-2"></div>
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
                  <span className="text-sm font-medium text-gray-500">Strategy Style:</span>
                  <select 
                    className="bg-gray-50 border border-gray-200 text-sm rounded-lg px-3 py-1.5 text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    value={strategyStyle}
                    onChange={(e) => handleStrategyChange(e.target.value, strategySpeed)}
                  >
                    <option value="conservative">Conservative</option>
                    <option value="moderate">Moderate</option>
                    <option value="aggressive">Aggressive</option>
                  </select>
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
                  <DollarSign className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm text-gray-500 font-medium">Last Price</p>
                  <p className="text-xl font-semibold font-mono">${metrics.last_micro_price?.toFixed(2) ?? '0.00'}</p>
                </div>
              </div>

              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-4">
                <div className="p-3 bg-purple-100 text-purple-600 rounded-lg hidden sm:block">
                  <Activity className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm text-gray-500 font-medium">Data Points</p>
                  <p className="text-xl font-semibold font-mono">{metrics.tick_count ?? 0}</p>
                </div>
              </div>

              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-4">
                <div className="p-3 bg-pink-100 text-pink-600 rounded-lg hidden sm:block">
                  <Activity className="w-6 h-6" />
                </div>
                <div>
                  <p className="text-sm text-gray-500 font-medium">OBI (Z-Score)</p>
                  <p className="text-xl font-semibold font-mono">
                    {metrics.last_toxicity_state?.obi?.toFixed(2) ?? "0.00"}
                  </p>
                </div>
              </div>

              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex items-center gap-4">
                <div className="p-3 bg-blue-100 text-blue-600 rounded-lg hidden sm:block">
                  <Zap className="w-6 h-6" />
                </div>
                <div className="flex flex-col">
                  <p className="text-sm text-gray-500 font-medium">Engine Perf</p>
                  <p className="text-xl font-semibold font-mono">{metrics.system_stats?.mps ?? '0.0'} <span className="text-sm text-gray-400 font-sans font-normal">msg/s</span></p>
                  <p className="text-[10px] text-gray-400 mt-1">Net: {metrics.system_stats?.netLat ?? '0.0'}ms | Sys: {metrics.system_stats?.sysLat ?? '0.0'}ms</p>
                </div>
              </div>
            </div>

            {/* Trading Analytics */}
            <div className="grid grid-cols-2 md:grid-cols-7 gap-4">
              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex flex-col justify-center">
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">Profit Factor</p>
                <p className="text-xl font-semibold font-mono">{metrics.analytics?.profit_factor?.toFixed(2) ?? '0.00'}</p>
              </div>
              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex flex-col justify-center">
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">Hit Ratio</p>
                <p className="text-xl font-semibold font-mono">{((metrics.analytics?.hit_ratio ?? 0) * 100).toFixed(1)}%</p>
              </div>
              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex flex-col justify-center">
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">Maker Fill</p>
                <p className="text-xl font-semibold font-mono">{((metrics.analytics?.maker_fill_rate ?? 0) * 100).toFixed(1)}%</p>
              </div>
              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex flex-col justify-center">
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">Avg Hold Time</p>
                <p className="text-xl font-semibold font-mono">{(metrics.analytics?.avg_holding_time / 1000)?.toFixed(1) ?? '0.0'}s</p>
              </div>
              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex flex-col justify-center">
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">Drawdown (Cur/Max)</p>
                <p className="text-lg font-semibold font-mono text-red-600">
                  -{((metrics.current_dd_pct ?? 0) * 100).toFixed(2)}% <span className="text-gray-400 text-sm">/ -{((metrics.max_dd_pct ?? 0) * 100).toFixed(2)}%</span>
                </p>
                <p className="text-[10px] text-gray-400 mt-1">MDD Duration: {((metrics.max_dd_duration ?? 0) / 1000).toFixed(1)}s</p>
              </div>
              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex flex-col justify-center">
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">Pending Makers</p>
                <p className="text-xl font-semibold font-mono">{metrics.pending_order_count ?? 0}</p>
                <p className="text-[10px] text-gray-400 mt-1">Resting limit orders</p>
              </div>
              <div className="bg-white border border-gray-200 shadow-sm p-4 rounded-xl flex flex-col justify-center">
                <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">Microstructure Stops</p>
                <p className="text-xl font-semibold font-mono text-amber-600">{metrics.canceled_orders_total ?? 0}</p>
                <p className="text-[10px] text-gray-400 mt-1">Rate: {((metrics.cancellation_rate ?? 0) * 100).toFixed(1)}%</p>
              </div>
            </div>

            <div className="bg-white border border-gray-200 shadow-sm p-5 rounded-xl h-[500px]">

              <div className="flex flex-col xl:flex-row xl:items-center justify-between mb-4 gap-4">
                <div className="flex flex-col gap-2">
                  <h2 className="text-sm font-medium text-gray-500">Price, VWAP, Macro SMA & OFI</h2>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      className="text-xs bg-gray-50 border border-gray-200 rounded px-2 py-1 outline-none focus:border-blue-400"
                      value={timeframe === null ? 'live' : timeframe}
                      onChange={(e) => setTimeframe(e.target.value === 'live' ? null : Number(e.target.value))}
                    >
                      <option value="live">Live (Tick)</option>
                      <option value="1000">1s</option>
                      <option value="5000">5s</option>
                      <option value="15000">15s</option>
                      <option value="60000">1m</option>
                      <option value="300000">5m</option>
                      <option value="900000">15m</option>
                    </select>
                    <select
                      className="text-xs bg-gray-50 border border-gray-200 rounded px-2 py-1 outline-none focus:border-blue-400"
                      value={chartType}
                      onChange={(e) => setChartType(e.target.value as any)}
                    >
                      <option value="line">Line</option>
                      <option value="candlestick">Candles</option>
                    </select>
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
                
                <div className="flex flex-wrap items-center gap-3 text-xs bg-gray-50 p-2 rounded-lg border border-gray-100">
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input type="checkbox" checked={visibleSeries.vwap} onChange={e => setVisibleSeries(s => ({...s, vwap: e.target.checked}))} className="hidden" />
                    <div className={`w-3 h-1 rounded-sm border-t border-dashed transition-colors ${visibleSeries.vwap ? 'bg-pink-400 border-pink-400' : 'bg-gray-300 border-gray-300'}`}></div>
                    <span className={`transition-colors ${visibleSeries.vwap ? "text-gray-700 font-medium" : "text-gray-400 group-hover:text-gray-500"}`}>VWAP</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input type="checkbox" checked={visibleSeries.macroSma} onChange={e => setVisibleSeries(s => ({...s, macroSma: e.target.checked}))} className="hidden" />
                    <div className={`w-3 h-1 rounded-sm transition-colors ${visibleSeries.macroSma ? 'bg-purple-600/70' : 'bg-gray-300'}`}></div>
                    <span className={`transition-colors ${visibleSeries.macroSma ? "text-gray-700 font-medium" : "text-gray-400 group-hover:text-gray-500"}`}>Macro SMA</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input type="checkbox" checked={visibleSeries.bb} onChange={e => setVisibleSeries(s => ({...s, bb: e.target.checked}))} className="hidden" />
                    <div className={`w-3 h-1 rounded-sm border-t border-dotted transition-colors ${visibleSeries.bb ? 'border-blue-500' : 'border-gray-300'}`}></div>
                    <span className={`transition-colors ${visibleSeries.bb ? "text-gray-700 font-medium" : "text-gray-400 group-hover:text-gray-500"}`}>Bands</span>
                  </label>
                  <div className="w-px h-4 bg-gray-300 mx-1"></div>
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input type="checkbox" checked={visibleSeries.ofi} onChange={e => setVisibleSeries(s => ({...s, ofi: e.target.checked}))} className="hidden" />
                    <div className={`flex rounded-sm overflow-hidden h-3 transition-opacity ${visibleSeries.ofi ? 'opacity-100' : 'opacity-40 grayscale'}`}>
                      <div className="w-1.5 h-3 bg-emerald-600"></div>
                      <div className="w-1.5 h-3 bg-red-600"></div>
                    </div>
                    <span className={`transition-colors ${visibleSeries.ofi ? "text-gray-700 font-medium" : "text-gray-400 group-hover:text-gray-500"}`}>Norm OFI</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input type="checkbox" checked={visibleSeries.ema} onChange={e => setVisibleSeries(s => ({...s, ema: e.target.checked}))} className="hidden" />
                    <div className={`w-3 h-1 rounded-sm transition-colors ${visibleSeries.ema ? 'bg-amber-500' : 'bg-gray-300'}`}></div>
                    <span className={`transition-colors ${visibleSeries.ema ? "text-gray-700 font-medium" : "text-gray-400 group-hover:text-gray-500"}`}>OFI EMA</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input type="checkbox" checked={visibleSeries.obi} onChange={e => setVisibleSeries(s => ({...s, obi: e.target.checked}))} className="hidden" />
                    <div className={`w-3 h-1 rounded-sm transition-colors ${visibleSeries.obi ? 'bg-pink-500' : 'bg-gray-300'}`}></div>
                    <span className={`transition-colors ${visibleSeries.obi ? "text-gray-700 font-medium" : "text-gray-400 group-hover:text-gray-500"}`}>OBI Z-Score</span>
                  </label>
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
                    trades={metrics.recent_trades_full} 
                    timeframeMs={timeframe}
                    chartType={chartType}
                    autoScale={autoScale}
                    followLive={followLive}
                    visibleSeries={visibleSeries}
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
                  <TradesList trades={metrics.recent_trades_full} cancellations={metrics.recent_cancellations ?? []} pendingOrders={metrics.pending_orders ?? []} />
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

        {/* Strategy Explanation Section */}
        <div className="bg-white border border-gray-200 shadow-sm p-6 rounded-xl mt-8">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-gray-900">Trading Strategy Overview</h2>
            <button
              onClick={handleShowCode}
              title="View Python Engine Code"
              className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
            >
              <Code className="w-4 h-4" />
              View Engine Code
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm text-gray-600">
            <div className="space-y-4">
              <div>
                <h3 className="text-emerald-400 font-medium mb-1">1. Micro-Price (The Foundation)</h3>
                <p>Instead of using a naive Mid-Price, the engine uses Micro-Price, which weights the price toward the side with the most volume. This allows indicators to react to liquidity shifts before the actual spread crosses.</p>
              </div>
              <div>
                <h3 className="text-blue-400 font-medium mb-1">2. Normalized OFI EMA & Macro Trend (Momentum)</h3>
                <p>Triggers aggressive taker market orders when normalized Order Flow Imbalance (OFI) EMA exceeds thresholds, aligned with the macro trend (Micro-Price vs Macro SMA). Normalizes OFI using Z-scores to adapt to changing volatility.</p>
              </div>
              <div>
                <h3 className="text-pink-400 font-medium mb-1">3. VWAP & Normalized OBI (Mean Reversion)</h3>
                <p>Buys on deep mean reversion (negative OBI Z-score indicating heavy sell pressure + VWAP discount) combined with OFI absorption. Similarly, shorts on positive OBI Z-scores showing heavy buy pressure and a VWAP premium when OFI shows exhaustion.</p>
              </div>
            </div>
            <div className="space-y-4">
              <div>
                <h3 className="text-amber-400 font-medium mb-1">4. Bollinger Bands (Volatility & Bounds)</h3>
                <p>Computes organic volatility using Bollinger Bands around the Micro-Price. These upper, lower, and mid bands act as dynamic thresholds alongside trailing VWAP/SMA boundaries to visualize abnormal price excursions and compressions.</p>
              </div>
              <div>
                <h3 className="text-purple-400 font-medium mb-1">5. Trend Continuation & Cooldowns</h3>
                <p>Buys minor dips (VWAP discount) in a strong macro uptrend (positive Macro SMA slope) when OFI flips positive. Sells minor rips in strong downtrends. Each execution locks the strategy for 1s to 5s based on strategy style to prevent signal over-firing.</p>
              </div>
              <div>
                <h3 className="text-red-400 font-medium mb-1">6. Risk Management & Sizing</h3>
                <p>Auto-trade dynamically adjusts static position sizes (50 to 250 bps) based on the Strategy Style selected above, overriding manual size. It enforces strict risk parameters, automatically closing positions with taker requests if Micro-Price moves 5% against entry.</p>
              </div>
            </div>
          </div>
        </div>

      </div>

      {/* Engine Code Modal */}
      {showCodeModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white rounded-xl shadow-lg w-full max-w-4xl max-h-[90vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold flex items-center gap-2">
                <Code className="w-5 h-5" />
                engine.py
              </h2>
              <button 
                onClick={() => setShowCodeModal(false)}
                className="p-1 hover:bg-gray-100 rounded-lg transition-colors"
                title="Close"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 overflow-auto bg-[#1e1e1e] flex-1">
              <pre className="text-sm font-mono text-gray-300 whitespace-pre-wrap">
                {engineCode}
              </pre>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
