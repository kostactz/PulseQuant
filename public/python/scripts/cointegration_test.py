"""High-frequency cointegration and stat arb analysis for Binance tickers.

This script performs a multi-step analysis on two Binance symbols:
- a target asset (e.g. BTC/EUR)
- a feature asset (e.g. BTC/USD)

It downloads historical klines, aligns the time series, computes lead/lag cross-correlations,
estimates static and rolling hedge ratios, tests cointegration with the Augmented Dickey-Fuller
test, and generates mean-reversion metrics plus proof plots.

Output:
- metrics printed to console
- `cointegration_validation_timeseries.png`
- `cointegration_report.png`

Usage:
1. Install dependencies in your Python environment:
   pip install -r requirements.txt

2. Run the script from the repository root or this script's directory:
   python public/python/scripts/cointegration_test.py

3. New CLI options are available for local caching and parameter control:
   --use-data      Load cached parquet data for the requested tickers/time window if available.
   --store-data    Save fetched Binance data to parquet cache files for reuse.
   --data-dir      Directory to read/write cached parquet files (default: data).
   --target-ticker Binance ticker for the target asset (default: BTCUSDT).
   --feature-ticker Binance ticker for the feature asset (default: ETHUSDT).
   --interval      Binance klines interval (default: 1s).
   --start-time    Start timestamp in ISO format (default: 2026-01-22T00:00:00).
   --end-time      End timestamp in ISO format (default: 2026-01-26T00:00:00).
   --rolling-window Rolling window size for rolling beta and z-score calculations (default: 800).

4. Example commands:
   python public/python/scripts/cointegration_test.py --store-data
   python public/python/scripts/cointegration_test.py --use-data --store-data
   python public/python/scripts/cointegration_test.py --target-ticker BTCUSDT --feature-ticker ETHUSDT --interval 1m --start-time 2026-01-22T00:00:00 --end-time 2026-01-26T00:00:00
"""

# ==============================================================================
# 1. SETUP & IMPORTS
# ==============================================================================
# !pip install -q python-binance pandas numpy statsmodels matplotlib

import argparse
from pathlib import Path

import pandas as pd
import numpy as np
import sys
import datetime
from binance.client import Client
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller, coint
from statsmodels.regression.rolling import RollingOLS
from scipy.stats import norm
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import warnings

warnings.filterwarnings('ignore') # Suppress warnings for cleaner output

# ANSI terminal colors
RESET = '\033[0m'
YELLOW = '\033[93m'
RED = '\033[91m'
GREEN = '\033[92m'


def color_text(text, color):
    return f"{color}{text}{RESET}"
################################################################################
# Configuration
parser = argparse.ArgumentParser(description='High-frequency cointegration analysis with optional parquet caching.')
parser.add_argument('--use-data', action='store_true', help='Load cached parquet data for the requested tickers/time window if available.')
parser.add_argument('--store-data', action='store_true', help='Save fetched Binance data to parquet cache files for reuse.')
parser.add_argument('--data-dir', default='data', help='Directory to read/write cached parquet files.')
parser.add_argument('--target-ticker', default='BTCUSDT', help='Binance ticker for the target asset.')
parser.add_argument('--feature-ticker', default='ETHUSDT', help='Binance ticker for the feature asset.')
parser.add_argument('--interval', default='1s', help='Binance klines interval.')
parser.add_argument('--start-time', default='2026-01-22T00:00:00', help='Start timestamp in ISO format.')
parser.add_argument('--end-time', default='2026-01-26T00:00:00', help='End timestamp in ISO format.')
parser.add_argument('--rolling-window', default='800', help='Rolling window size used for rolling beta and z-score calculations. Can be "auto".')
parser.add_argument('--sigma-threshold', default='2.0', help='Z-score threshold for trade entry. Can be a float (e.g., 2.5) or "auto".')
parser.add_argument('--rolling-window-only', action='store_true', help='Only calculate the optimal rolling window and exit.')
parser.add_argument('--verbose', action='store_true', help='Show verbose progress updates during data fetching.')
parser.add_argument('--backtest', action='store_true', help='Run an analytical performance backtest accounting for fees.')
parser.add_argument('--taker-fee', type=float, default=0.05, help='Taker fee in percentage (default: 0.05).')
parser.add_argument('--maker-fee', type=float, default=0.02, help='Maker fee in percentage (default: 0.02).')
args = parser.parse_args()

target_ticker = args.target_ticker
feature_ticker = args.feature_ticker
interval = args.interval
start_time = datetime.datetime.fromisoformat(args.start_time)
end_time = datetime.datetime.fromisoformat(args.end_time)
cache_dir = Path(args.data_dir)
cache_dir.mkdir(parents=True, exist_ok=True)
use_cached_data = args.use_data
store_cached_data = args.store_data
if args.rolling_window.lower() == 'auto':
    rolling_window = 'auto'
else:
    rolling_window = int(args.rolling_window)

if args.sigma_threshold.lower() == 'auto':
    sigma_threshold = 'auto'
else:
    sigma_threshold = float(args.sigma_threshold)

rolling_window_only = args.rolling_window_only

# Rolling window for intervals, incl. z-score.
# This should generally be in the range of 1x-2x expected mean reversion half-life to avoid excessive false signals.
max_lag = 30
################################################################################

print(f"--- High-Frequency Stat Arb Analysis: {target_ticker} vs {feature_ticker} ---")

# ==============================================================================
# 2. DATA ACQUISITION & ALIGNMENT
# ==============================================================================
print(f"\n[1/7] Fetching high-frequency data for {target_ticker} and {feature_ticker}...")

client = Client()

import re

def get_cached_files_info(symbol: str, interval: str):
    """Scan cache directory for files matching the symbol and interval."""
    files_info = []
    pattern = re.compile(rf"^{symbol}_{interval}_(\d{{14}})_(\d{{14}})\.parquet$")
    for p in cache_dir.glob(f"{symbol}_{interval}_*.parquet"):
        match = pattern.match(p.name)
        if match:
            s_str, e_str = match.groups()
            s_dt = datetime.datetime.strptime(s_str, '%Y%m%d%H%M%S')
            e_dt = datetime.datetime.strptime(e_str, '%Y%m%d%H%M%S')
            files_info.append((s_dt, e_dt, p))
    return files_info

def calculate_missing_ranges(req_start: datetime.datetime, req_end: datetime.datetime, covered_ranges: list):
    """Determine the gaps between requested range and available covered ranges."""
    missing = [(req_start, req_end)]
    for cov_start, cov_end in covered_ranges:
        new_missing = []
        for m_start, m_end in missing:
            # If no overlap
            if cov_end <= m_start or cov_start >= m_end:
                new_missing.append((m_start, m_end))
            else:
                # Overlap exists, split the missing range
                if m_start < cov_start:
                    new_missing.append((m_start, cov_start))
                if m_end > cov_end:
                    new_missing.append((cov_end, m_end))
        missing = new_missing
    return missing

from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_binance_data(symbol, interval, start_ts, end_ts):
    """Helper function to fetch and format Binance Kline data concurrently."""
    print(f"      -> Downloading Klines for {symbol} from {start_ts} to {end_ts}...")
    
    interval_unit = interval[-1]
    interval_val = int(interval[:-1])
    unit_map = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800, 'M': 2592000}
    interval_seconds = interval_val * unit_map.get(interval_unit, 60)
    
    # Group by 10,000 data points per chunk (~10 pagination requests per worker)
    chunk_seconds = 10000 * interval_seconds
    chunk_delta = datetime.timedelta(seconds=chunk_seconds)
    
    chunks = []
    curr = start_ts
    while curr < end_ts:
        next_curr = curr + chunk_delta
        if next_curr > end_ts:
            next_curr = end_ts
        chunks.append((curr, next_curr))
        curr = next_curr

    klines = []
    
    def fetch_chunk(s, e):
        return client.get_historical_klines(
            symbol,
            interval,
            s.strftime("%d %b, %Y %H:%M:%S"),
            e.strftime("%d %b, %Y %H:%M:%S")
        )

    completed = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_chunk, ch[0], ch[1]): (i, ch) for i, ch in enumerate(chunks)}
        results = []
        for f in as_completed(futures):
            i, ch = futures[f]
            try:
                data = f.result()
                results.append((i, data))
                completed += 1
                if getattr(args, 'verbose', False):
                    print(f"         [Verbose] Downloaded chunk {completed}/{len(chunks)} for {symbol}...")
            except Exception as e:
                print(f"         ERROR fetching chunk {ch[0]} - {ch[1]}: {e}")
                
    results.sort(key=lambda x: x[0])
    for r in results:
        if r[1]:
            klines.extend(r[1])

    if not klines:
        return pd.DataFrame()
        
    columns = [
        'Open_time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close_time', 
        'Quote_asset_volume', 'Number_of_trades', 'Taker_buy_base_asset_volume', 
        'Taker_buy_quote_asset_volume', 'Ignore'
    ]
    df = pd.DataFrame(klines, columns=columns)
    if df.empty:
        return pd.DataFrame()
    df['Datetime'] = pd.to_datetime(df['Open_time'], unit='ms', utc=True)
    df = df.set_index('Datetime')
    df['Close'] = df['Close'].astype(float)
    return df[['Close']].sort_index()


def get_symbol_data(symbol):
    dfs = []
    req_start = start_time
    req_end = end_time

    if use_cached_data:
        files_info = get_cached_files_info(symbol, interval)
        overlapping_files = []
        covered_ranges = []
        
        for s, e, p in files_info:
            if s < req_end and e > req_start:
                overlapping_files.append(p)
                covered_ranges.append((s, e))
        
        for p in overlapping_files:
            print(f"      -> Loading cached parquet for {symbol} from {p.name}")
            try:
                dfs.append(pd.read_parquet(p))
            except Exception as e:
                print(f"      -> Failed to load {p.name}: {e}")

        missing_ranges = calculate_missing_ranges(req_start, req_end, covered_ranges)
    else:
        missing_ranges = [(req_start, req_end)]

    for m_start, m_end in missing_ranges:
        print(f"      -> Missing data detected for {symbol}, fetching range: {m_start} to {m_end}")
        df_new = fetch_binance_data(symbol, interval, m_start, m_end)
        
        if not df_new.empty:
            dfs.append(df_new)
            if store_cached_data:
                gap_path = cache_dir / f"{symbol}_{interval}_{m_start.strftime('%Y%m%d%H%M%S')}_{m_end.strftime('%Y%m%d%H%M%S')}.parquet"
                print(f"      -> Saving gap parquet cache for {symbol} to {gap_path}")
                df_new.to_parquet(gap_path)

    if not dfs:
        return pd.DataFrame()

    combined = pd.concat(dfs)
    combined = combined[~combined.index.duplicated(keep='last')]
    combined = combined.sort_index()
    
    # Filter strictly to requested range. 
    # Index is UTC aware, so converting req_start and req_end to UTC tz-aware.
    req_start_tz = pd.to_datetime(req_start, utc=True)
    req_end_tz = pd.to_datetime(req_end, utc=True)
    combined = combined[(combined.index >= req_start_tz) & (combined.index <= req_end_tz)]
    
    return combined

# --- 2A. Fetch Target Data ---
btc_df = get_symbol_data(target_ticker)
print(f"Fetched {len(btc_df)} data points for {target_ticker}.")

# --- 2B. Fetch Feature Data ---
feature_df = get_symbol_data(feature_ticker)
feature_df = feature_df.rename(columns={'Close': 'Feature_Price'})
print(f"Fetched {len(feature_df)} data points for {feature_ticker}.")

# --- 2C. Time-Series Synchronization ---
print("\n[2/7] Aligning time series...")

# If both are from Binance, they share the same UTC timestamps. An inner join drops missing intervals.
df = btc_df.join(feature_df, how='inner').dropna()

print(f"Data aligned successfully. Total synchronized data points: {len(df)}")

if df.empty:
    print(color_text("ERROR: No aligned data points available after merging. Check input time window and data feeds.", RED))
    sys.exit(1)

# ==============================================================================
# 3. LEAD-LAG ANALYSIS (CROSS-CORRELATION)
# ==============================================================================
print("\n[3/7] Running Lead-Lag Analysis (Cross-Correlation)...")

df['Target_Returns'] = np.log(df['Close'] / df['Close'].shift(1))
df['Feature_Returns'] = np.log(df['Feature_Price'] / df['Feature_Price'].shift(1))
df_returns = df.dropna()

if df_returns.empty:
    print(color_text("ERROR: No valid returns rows after differencing; cannot compute lead-lag correlations.", RED))
    sys.exit(1)

# Use the first 20% of the data for finding the lead-lag relationship to avoid look-ahead bias
split_idx = int(len(df_returns) * 0.2)
train_returns = df_returns.iloc[:split_idx].copy()

# Smooth returns to reduce microstructure noise
train_returns['Target_Returns_Smoothed'] = train_returns['Target_Returns'].ewm(span=5, adjust=False).mean()
train_returns['Feature_Returns_Smoothed'] = train_returns['Feature_Returns'].ewm(span=5, adjust=False).mean()

target_vals = train_returns['Target_Returns_Smoothed'].values
feature_vals = train_returns['Feature_Returns_Smoothed'].values

correlations = {}
for lag in range(-max_lag, max_lag + 1):
    if lag < 0:
        t_slice = target_vals[-lag:]
        f_slice = feature_vals[:lag]
    elif lag > 0:
        t_slice = target_vals[:-lag]
        f_slice = feature_vals[lag:]
    else:
        t_slice = target_vals
        f_slice = feature_vals
        
    if len(t_slice) > 1:
        corr = np.corrcoef(t_slice, f_slice)[0, 1]
    else:
        corr = np.nan
    correlations[lag] = corr

valid_correlations = {lag: c for lag, c in correlations.items() if not pd.isna(c)}
if not valid_correlations:
    print(color_text("ERROR: Unable to compute any valid lag correlation (all values are NaN).", RED))
    sys.exit(1)

best_lag = max(valid_correlations, key=lambda k: abs(valid_correlations[k]))
best_corr = valid_correlations[best_lag]
print(f"Highest correlation ({best_corr:.4f}) found at lag: {best_lag}")

# In this alignment logic:
# If lag > 0, t_slice is earlier, f_slice is later. e.g. T[0] and F[1]. Target predicts Feature.
# If lag < 0, t_slice is later, f_slice is earlier. e.g. T[1] and F[0]. Feature predicts Target. We want this!
if best_lag < 0:
    abs_lag = abs(best_lag)
    print(color_text(f"-> Conclusion: {feature_ticker} LEADS {target_ticker} by {abs_lag} periods.", GREEN))
    print("   Maintaining concurrent alignment for strict stat-arb execution.")
    # REMOVED: df['Feature_Price'] = df['Feature_Price'].shift(abs_lag)
elif best_lag > 0:
    print(color_text(f"-> Conclusion: {target_ticker} LEADS {feature_ticker} by {best_lag} periods. ({feature_ticker} is likely useless).", RED))
else:
    print(color_text(f"-> Conclusion: Both assets move synchronously.", YELLOW))


# ==============================================================================
# Helper functions for calculations and Walk-Forward Optimization
# ==============================================================================
interval_seconds_map = {
    's': 1, 'm': 60, 'h': 3600, 'd': 86400, 'w': 604800, 'M': 2592000,
}

def parse_interval_seconds(interval_str):
    unit = interval_str[-1]
    value = int(interval_str[:-1])
    return value * interval_seconds_map.get(unit, 0)

def format_duration(seconds):
    if seconds == np.inf:
        return 'infinite'
    if seconds >= 3600:
        return f'{seconds / 3600:.2f} hours'
    if seconds >= 60:
        return f'{seconds / 60:.2f} minutes'
    return f'{seconds:.2f} seconds'

def get_hurst_exponent_dynamic(ts, rolling_window):
    ts_arr = np.asarray(ts)
    max_lag = min(len(ts_arr) // 2, rolling_window)
    if max_lag > 500:
        lags = np.unique(np.geomspace(2, max_lag, num=50).astype(int))
    else:
        lags = np.arange(2, max_lag)
    tau = np.array([np.var(ts_arr[lag:] - ts_arr[:-lag]) for lag in lags])
    poly = np.polyfit(np.log(lags), np.log(tau + 1e-10), 1)
    return poly[0] / 2.0

def get_half_life(ts, interval_str):
    try:
        ts_1m = ts.resample('1T').last().dropna()
        if len(ts_1m) < 10:
            ts_1m = ts
    except Exception:
        ts_1m = ts
    df_temp = pd.DataFrame({'lag': ts_1m.shift(1), 'diff': ts_1m.diff()}).dropna()
    X = sm.add_constant(df_temp['lag'])
    Y = df_temp['diff']
    res = sm.OLS(Y, X).fit()
    if len(res.params) < 2:
        return np.inf
    lam = res.params['lag']
    hl_periods = -np.log(2) / lam if lam < 0 else np.inf
    original_sec = parse_interval_seconds(interval_str)
    resampled_sec = 60
    if isinstance(ts_1m.index.freq, pd.offsets.Minute) or (len(ts_1m) != len(ts)):
        hl_periods = hl_periods * (resampled_sec / original_sec)
    return hl_periods

def calculate_rolling_metrics(df_in, window_size):
    df_calc = df_in.copy()
    df_calc['EWM_Cov'] = df_calc['Close'].ewm(span=window_size).cov(df_calc['Feature_Price'])
    df_calc['EWM_Var'] = df_calc['Feature_Price'].ewm(span=window_size).var()
    df_calc['EWM_Mean_Close'] = df_calc['Close'].ewm(span=window_size).mean()
    df_calc['EWM_Mean_Feature'] = df_calc['Feature_Price'].ewm(span=window_size).mean()
    
    df_calc['Rolling_Beta'] = df_calc['EWM_Cov'] / df_calc['EWM_Var']
    df_calc['Rolling_Alpha'] = df_calc['EWM_Mean_Close'] - (df_calc['Rolling_Beta'] * df_calc['EWM_Mean_Feature'])
    
    df_calc['Dynamic_Spread'] = (df_calc['Close'] - 
                                 (df_calc['Rolling_Beta'].shift(1) * df_calc['Feature_Price']) - 
                                 df_calc['Rolling_Alpha'].shift(1))
    
    df_calc['Spread_Mean'] = df_calc['Dynamic_Spread'].rolling(window=window_size).mean()
    df_calc['Spread_Std'] = df_calc['Dynamic_Spread'].rolling(window=window_size).std()
    
    df_calc['Z_Score'] = (df_calc['Dynamic_Spread'] - df_calc['Spread_Mean']) / (df_calc['Spread_Std'] + 1e-10)
    return df_calc

def optimize_parameters(df_in, half_life_periods):
    print(f"\n[Opt] Starting Walk-Forward Optimization for Rolling Window & Sigma Threshold...")
    print(f"      Baseline Half-Life: {half_life_periods:.2f} periods")
    
    if np.isinf(half_life_periods) or np.isnan(half_life_periods):
        print(color_text("      -> Half-Life is invalid. Falling back to default window of 800.", YELLOW))
        half_life_periods = 800

    if args.rolling_window.lower() == 'auto':
        start_val = max(50, int(1 * half_life_periods))
        end_val = max(100, int(20 * half_life_periods))
        raw_candidates = np.geomspace(start_val, end_val, num=10)
        candidate_windows = sorted(list(set([int(round(x)) for x in raw_candidates])))
    else:
        candidate_windows = [int(args.rolling_window)]
        
    if args.sigma_threshold.lower() == 'auto':
        candidate_thresholds = list(np.arange(1.5, 6.5, 0.5))
    else:
        candidate_thresholds = [float(args.sigma_threshold)]
    
    print(f"      Candidate Windows: {candidate_windows}")
    print(f"      Candidate Thresholds: {candidate_thresholds}")
    
    # Walk-forward split: chronological chunks, train on 70%, test on 30% of each chunk
    chunk_size = int(parse_interval_seconds('8h') / parse_interval_seconds(interval)) # ~8 hours
    
    end_val_max = max(candidate_windows)
    min_required_chunk = int(end_val_max / 0.7) + 500
    if chunk_size < min_required_chunk:
        chunk_size = min_required_chunk
        
    chunk_size = min(len(df_in), chunk_size)
    
    if chunk_size < 500:
        chunk_size = len(df_in)
    
    chunks = [df_in.iloc[i:i + chunk_size] for i in range(0, len(df_in), chunk_size)]
    if len(chunks) > 1 and len(chunks[-1]) < 0.2 * chunk_size:
        chunks.pop() # Drop extremely small last chunk
    
    scores = {(w, t): {'returns': [], 'mdd': [], 'pvalue': []} for w in candidate_windows for t in candidate_thresholds}
    taker_pct = args.taker_fee / 100.0
    
    for w in candidate_windows:
        if getattr(args, 'verbose', False):
            print(f"         [Verbose] Evaluating Window {w} across full dataset...")
            
        full_calc = calculate_rolling_metrics(df_in, w)
        
        for thr in candidate_thresholds:
            all_spread_returns = []
            all_mdds = []
            all_pvals = []
            
            for c_idx, chunk in enumerate(chunks):
                train_len = int(len(chunk) * 0.7)
                if train_len < end_val_max: continue
                
                chunk_test_start = chunk.index[train_len]
                chunk_test_end = chunk.index[-1]
                test_calc = full_calc.loc[chunk_test_start:chunk_test_end].copy().dropna(subset=['Z_Score'])
                
                if len(test_calc) < 10: continue
                
                z = test_calc['Z_Score'].values
                pos = 0
                features = test_calc['Feature_Price'].values
                targets = test_calc['Close'].values
                betas = test_calc['Rolling_Beta'].shift(1).fillna(0).values
                
                spread_returns = np.zeros(len(test_calc))
                for i in range(1, len(test_calc)):
                    target_diff = targets[i] - targets[i-1]
                    feature_diff = features[i] - features[i-1]
                    total_capital = targets[i-1] + abs(betas[i]) * features[i-1]
                    gross_spread_return = (target_diff - betas[i] * feature_diff) / total_capital if total_capital > 0 else 0.0
                    
                    prev_pos = pos

                    if pos == 0:
                        if z[i-1] < -thr: pos = 1
                        elif z[i-1] > thr: pos = -1
                    elif pos == 1 and z[i-1] >= 0: pos = 0
                    elif pos == -1 and z[i-1] <= 0: pos = 0
                    
                    turnover = abs(pos - prev_pos)
                    fee = turnover * taker_pct
                    spread_returns[i] = (prev_pos * gross_spread_return) - fee
                    
                all_spread_returns.extend(spread_returns)
                
                cum_returns = np.cumsum(spread_returns)
                peak = np.maximum.accumulate(cum_returns)
                drawdown = peak - cum_returns
                all_mdds.append(np.max(drawdown))
                
                try:
                    pval = coint(test_calc['Close'], test_calc['Feature_Price'])[1]
                except Exception:
                    pval = 1.0
                all_pvals.append(pval)

            if len(all_spread_returns) > 0:
                returns_arr = np.array(all_spread_returns)
                sr_mean = np.mean(returns_arr)
                sr_std = np.std(returns_arr) + 1e-10
                sharpe = (sr_mean / sr_std) * np.sqrt(365 * 86400 / parse_interval_seconds(interval))
                
                scores[(w, thr)]['returns'] = returns_arr
                scores[(w, thr)]['sharpe'] = sharpe
                scores[(w, thr)]['mdd'] = np.mean(all_mdds) if all_mdds else 0
                scores[(w, thr)]['pvalue'] = np.mean(all_pvals) if all_pvals else 1.0

    best_score = -np.inf
    best_w = candidate_windows[0]
    best_thr = candidate_thresholds[0]
    
    print("\n      Optimization Results Summary:")
    for (w, thr) in scores:
        if 'sharpe' not in scores[(w, thr)]: continue
        
        avg_sharpe = scores[(w, thr)]['sharpe']
        avg_mdd = scores[(w, thr)]['mdd']
        avg_pval = scores[(w, thr)]['pvalue']
        
        penalty = 1.0
        if avg_pval > 0.05:
            penalty = 0.5
        
        score = (avg_sharpe - avg_mdd * 10) * penalty
        
        print(f"      Window {w:4d} | Thr {thr:.1f}: Sharpe={avg_sharpe:6.2f}, MaxDD={avg_mdd:6.4f}, ADF P-Val={avg_pval:6.4f}, Score={score:6.2f}")
        
        if score > best_score:
            best_score = score
            best_w = w
            best_thr = thr

    print(color_text(f"      -> Optimal Parameters Selected: Window={best_w}, Threshold={best_thr} (Score: {best_score:.2f})", GREEN))
    return best_w, best_thr

# ==============================================================================
# 4. ROLLING METRICS & SIGNAL GENERATION
# ==============================================================================
if rolling_window == 'auto' or sigma_threshold == 'auto':
    # Base static OLS calculation for half-life
    print("\n[Prep] Calculating baseline static half-life for optimization...")
    
    # Configurable chunk duration for baseline half-life calculation
    baseline_chunk_duration = '3d'
    chunk_size = parse_interval_seconds(baseline_chunk_duration) // parse_interval_seconds(interval)
    if chunk_size == 0 or chunk_size > len(df):
        chunk_size = len(df)
        
    local_half_lives = []
    for i in range(0, len(df), chunk_size):
        chunk = df.iloc[i:i + chunk_size]
        if len(chunk) < 100: continue
        X_stat = sm.add_constant(chunk['Feature_Price'])
        Y_stat = chunk['Close']
        base_model = sm.OLS(Y_stat, X_stat).fit()
        base_spread = base_model.resid
        hl = get_half_life(base_spread, interval)
        if not np.isinf(hl) and not np.isnan(hl) and hl > 0:
            local_half_lives.append(hl)

    if local_half_lives:
        base_hl = np.median(local_half_lives)
        print(f"      Calculated median half-life from {len(local_half_lives)} chunks (duration: {baseline_chunk_duration}).")
    else:
        base_hl = 800 # fallback
        print(color_text("      -> Could not compute valid local half-lives. Falling back to default window of 800.", YELLOW))
    
    optimal_window, optimal_threshold = optimize_parameters(df, base_hl)
    if rolling_window == 'auto':
        rolling_window = optimal_window
    if sigma_threshold == 'auto':
        sigma_threshold = optimal_threshold
    
    if rolling_window_only:
        print(color_text(f"\nOptimization complete. Optimal Window: {rolling_window}. Exiting as requested.", GREEN))
        sys.exit(0)

opt_sigma = sigma_threshold

print("\n[4/7] Calculating EWM Hedge Ratio (Beta) and Z-Scores...")

df = calculate_rolling_metrics(df, rolling_window)

# Extract rolling variables back for existing downstream logic
df = df.dropna()


df['Z_Above'] = df['Z_Score'] > opt_sigma
df['Z_Below'] = df['Z_Score'] < -opt_sigma

prev_above = df['Z_Above'].shift(1, fill_value=False)
prev_below = df['Z_Below'].shift(1, fill_value=False)

df['Signal_Above_Cross'] = df['Z_Above'] & (~prev_above)
df['Signal_Below_Cross'] = df['Z_Below'] & (~prev_below)

bullish_signals = int(df['Signal_Below_Cross'].sum())
bearish_signals = int(df['Signal_Above_Cross'].sum())
raw_exceedance_count = int(df['Z_Above'].sum() + df['Z_Below'].sum())
raw_exceedance_pct = raw_exceedance_count / len(df) if len(df) > 0 else 0.0

expected_exceedance_rate = 2 * (1 - norm.cdf(opt_sigma))

print(f"Identified {bullish_signals} bullish signals and {bearish_signals} bearish signals based.")
print(f"       Total raw exceedances outside ±{opt_sigma:.2f}σ: {raw_exceedance_count} rows ({raw_exceedance_pct:.2%}), including persistence of the same signal.")

signal_count = bullish_signals + bearish_signals
signal_pct = signal_count / len(df) if len(df) > 0 else 0.0

# Flag warning if exceeded significantly more than dynamic normal distribution expectation (e.g., > 1.5x)
max_expected_pct = expected_exceedance_rate * 1.5
if raw_exceedance_pct > max_expected_pct:
    print(color_text("   !!! WARNING: The Z-score exceedance rate is unusually high.", YELLOW))
    print(color_text(f"       {raw_exceedance_count} out of {len(df)} points ({raw_exceedance_pct:.2%}) exceed ±{opt_sigma:.2f}σ.", YELLOW))
    print(color_text(f"       In a normal distribution, ±{opt_sigma:.2f}σ events should occur only about {expected_exceedance_rate:.2%} of the time.", YELLOW))
    print(color_text("       This strongly suggests the spread distribution has extremely fat tails, or more likely, the rolling window for Z-score calculation is too short.", YELLOW))


# ==============================================================================
# 5. STATIC OLS & COINTEGRATION (ADF TEST)
# ==============================================================================
print("\n[5/7] Calculating Static Hedge Ratio and Testing Cointegration...")

# Calculate static beta for visualization/baseline purposes
X = sm.add_constant(df['Feature_Price'])
Y = df['Close']
static_model = sm.OLS(Y, X).fit()
static_beta = static_model.params['Feature_Price']
df['Static_Spread'] = static_model.resid 

print(f"Static Hedge Ratio (Beta): {static_beta:.4f}")

try:
    print("      -> Downsampling data for cointegration test to improve performance...")
    # Cointegration is a long-term property. Downsampling to 15-minute intervals drastically speeds up 
    # the ADF lag-search built into the test without losing the macro-equilibrium relationship.
    coint_df = df[['Close', 'Feature_Price']].resample('15min').last().dropna() if len(df) > 10000 else df
    
    # Use the proper Engle-Granger cointegration test on the downsampled concurrent price series
    coint_score, p_value, critical_values = coint(coint_df['Close'], coint_df['Feature_Price'])
    
    print(f"Engle-Granger T-Statistic: {coint_score:.4f}")
    print(f"MacKinnon P-Value: {p_value:.6f}")
    print(f"Critical Values (1%, 5%, 10%): {critical_values}")
except Exception as e:
    print(f"Cointegration Test Error: {e}")
    p_value = 1.0

is_cointegrated = p_value < 0.05
if is_cointegrated:
    print(color_text(f"-> Conclusion: The pair IS cointegrated (P-Value < 0.05).", GREEN))
else:
    print(color_text(f"-> Conclusion: The pair is NOT cointegrated (P-Value >= 0.05).", RED))

# ==============================================================================
# 6. ADVANCED METRICS: HURST & HALF-LIFE
# ==============================================================================
print("\n[6/7] Calculating Hurst Exponent and Mean-Reversion Half-Life...")

# These functions have been moved up


hurst_static = get_hurst_exponent_dynamic(df['Static_Spread'].dropna().values, rolling_window)
hurst = get_hurst_exponent_dynamic(df['Dynamic_Spread'].dropna().values, rolling_window)
half_life = get_half_life(df['Dynamic_Spread'].dropna(), interval)
half_life_seconds = half_life * parse_interval_seconds(interval)
half_life_readable = format_duration(half_life_seconds)

print(f"-> Hurst Exponent (Static): {hurst_static:.4f} (Target < 0.5 for mean reversion)")
print(f"-> Hurst Exponent (Dynamic): {hurst:.4f} (Target < 0.5 for mean reversion)")
print(f"-> Mean Reversion Half-Life: {half_life:.2f} periods (~{half_life_readable})")
if half_life_seconds > 7200:
    print(color_text("   !!! WARNING: Half-life exceeds 2 hours. Spread may not revert fast enough for medium-frequency strategies.", YELLOW))

# ==============================================================================
# 7. FINAL VERDICT & VISUALIZATION
# ==============================================================================
print("\n[7/7] Final Verdict for Medium-Frequency Trading:")

signal_warning = raw_exceedance_pct > 0.045
half_life_warning = half_life_seconds > 7200
mean_reversion_warning = hurst_static >= 0.5 # Adjusted to standard 0.5 threshold
cointegration_warning = not is_cointegrated

# FIX: If best_lag is >= 0, the feature does not lead. It is useless for anticipation.
lead_lag_warning = best_lag >= 0 

if lead_lag_warning:
    print(color_text(f"WARNING: {feature_ticker} does not lead {target_ticker} (lag = {best_lag}). No predictive edge.", YELLOW))

if not is_cointegrated:
    print(color_text(f"VERDICT: NO. Cointegration is weak or absent (Engle-Granger p-value = {p_value:.6f}).", RED))
elif mean_reversion_warning:
    print(color_text(f"VERDICT: NO. Hurst exponent (Static) is {hurst_static:.4f} (close or greater than 0.5), indicating the spread is not reliably mean-reverting.", RED))
    if p_value < 0.05:
        print(color_text(
            f"       The fact that the ADF p-value is {p_value:.3f} shows that while the spread does eventually revert,"
            " the path it takes to get there is so chaotic and random that the drawdown you experience while waiting for the reversion"
            " will likely trigger your risk limits or liquidate you.", YELLOW))
elif half_life_warning:
    print(color_text(f"VERDICT: NO. Estimated half-life is {half_life:.2f} periods (~{half_life_readable}), which is too long for medium-frequency execution.", RED))
elif signal_warning:
    print(color_text(f"VERDICT: NO. Excessive ±2σ Z-score signals ({signal_pct:.2%}) indicate fat tails or an unstable Z-score window, reducing strategy reliability.", RED))
else:
    print(color_text(f"VERDICT: YES. {feature_ticker} is cointegrated, the spread appears mean-reverting, and the half-life is appropriate.", GREEN))

print("\n[7/7] Generating Proof Diagrams...")

# Validation series plot for cleaned aligned ticks
fig_ts = plt.figure(figsize=(16, 4))
ax_ts = fig_ts.add_subplot(1, 1, 1)
ax_ts.plot(df.index, (df['Close'] - df['Static_Spread'].mean())/static_beta - df['Feature_Price'].mean(), label=f'{target_ticker} Close', color='blue', linewidth=1)
ax_ts.plot(df.index, df['Feature_Price'] - df['Feature_Price'].mean(), label=f'{feature_ticker} Price', color='orange', linewidth=1)

ax_ts.set_title('Pricing (Normalized over Feature Price)')
ax_ts.set_xlabel('Datetime')
ax_ts.set_ylabel('Price')
ax_ts.legend(loc='upper left')
ax_ts.grid(True, alpha=0.3)
fig_ts.tight_layout()
output_validation_path = 'cointegration_validation_timeseries.report.png'
fig_ts.savefig(output_validation_path, dpi=150, bbox_inches='tight')
plt.close(fig_ts)
print(f"Saved plot: {output_validation_path}")

fig = plt.figure(figsize=(16, 12))

ax1 = plt.subplot(2, 2, 1)
ax1.scatter(df['Feature_Price'], df['Close'], alpha=0.3, color='blue', s=10)
ax1.plot(df['Feature_Price'], static_model.predict(sm.add_constant(df['Feature_Price'])), color='red', linewidth=2)
ax1.set_title(f'Price Scatter: {feature_ticker} vs {target_ticker} (OLS Line)')
ax1.set_xlabel(f'{feature_ticker} Price')
ax1.set_ylabel(f'{target_ticker} Price')
ax1.grid(True, alpha=0.3)

ax2 = plt.subplot(2, 2, 2)
ax2.plot(df.index, df['Rolling_Beta'], color='purple', linewidth=1.5)
ax2.set_title('Rolling Hedge Ratio (Beta) Stability')
ax2.set_ylabel('Beta Value')
ax2.grid(True, alpha=0.3)

ax3 = plt.subplot(2, 2, 3)
ax3.plot(df.index, df['Z_Score'], color='black', linewidth=1)
ax3.axhline(opt_sigma, color='red', linestyle='--', label=f'Short Spread (+{opt_sigma:.2f} / Overvalued)')
ax3.axhline(-opt_sigma, color='green', linestyle='--', label=f'Long Spread (-{opt_sigma:.2f} / Undervalued)')
ax3.axhline(0, color='blue', alpha=0.5)
ax3.set_title(f'Rolling Z-Score of the Dynamic {target_ticker} / {feature_ticker} Spread')
ax3.set_ylabel('Z-Score')
ax3.legend(loc='upper right')
ax3.grid(True, alpha=0.3)

ax4 = plt.subplot(2, 2, 4)
ax4.hist(df['Z_Score'], bins=60, density=True, color='skyblue', edgecolor='black', alpha=0.7)
x_vals = np.linspace(df['Z_Score'].min(), df['Z_Score'].max(), 300)
normal_pdf = (1.0 / np.sqrt(2 * np.pi)) * np.exp(-0.5 * x_vals**2)
ax4.plot(x_vals, normal_pdf, color='red', linestyle='--', linewidth=2, label='Standard Normal PDF')
ax4.set_title('Z-Score Distribution vs. Expected Normal')
ax4.set_xlabel('Z-Score')
ax4.set_ylabel('Density')
ax4.legend(loc='upper right')
ax4.grid(True, alpha=0.3)

plt.tight_layout()
output_path = 'cointegration_analysis.report.png'
fig.savefig(output_path, dpi=150, bbox_inches='tight')
plt.close(fig)
print(f"Saved plot: {output_path}")

# --- Generate standalone spread chart ---
df['Spread_bps'] = (df['Dynamic_Spread'] / df['Close']) * 10000

fig_spread = plt.figure(figsize=(16, 4))
ax_spread = fig_spread.add_subplot(1, 1, 1)
ax_spread.plot(df.index, df['Spread_bps'], color='teal', linewidth=1)
ax_spread.axhline(10.0, color='orange', linestyle='--', label='+10 bps (Typical 0.1% Fee Threshold)')
ax_spread.axhline(-10.0, color='orange', linestyle='--')
ax_spread.axhline(20.0, color='darkorange', linestyle=':', label='+20 bps (Round-Trip Fee Threshold)')
ax_spread.axhline(-20.0, color='darkorange', linestyle=':')
ax_spread.set_title('Normalized Spread (in Basis Points) vs Fee Thresholds')
ax_spread.set_ylabel('Spread (bps)')
ax_spread.set_xlabel('Datetime')
ax_spread.legend(loc='upper right')
ax_spread.grid(True, alpha=0.3)

fig_spread.tight_layout()
output_spread_path = 'cointegration_spread_bps.report.png'
fig_spread.savefig(output_spread_path, dpi=150, bbox_inches='tight')
plt.close(fig_spread)
print(f"Saved plot: {output_spread_path}")

if args.backtest:
    print("\n[8/7] Running Analytical Performance Backtest...")
    taker_pct = args.taker_fee / 100.0
    maker_pct = args.maker_fee / 100.0

    # Retrieve required columns as NumPy arrays for fast iteration
    z = df['Z_Score'].values
    features = df['Feature_Price'].values
    targets = df['Close'].values
    betas = df['Rolling_Beta'].shift(1).fillna(0).values

    # Pre-allocate arrays
    n = len(df)
    gross_returns = np.zeros(n)
    net_returns = np.zeros(n)
    positions = np.zeros(n)

    pos = 0  # 1 for Long Spread, -1 for Short Spread, 0 for Flat
    trades = 0

    for i in range(1, n):
        # Calculate PnL accurately mapping to Price-Beta Cointegration
        target_diff = targets[i] - targets[i-1]
        feature_diff = features[i] - features[i-1]
        total_capital = targets[i-1] + abs(betas[i]) * features[i-1]
        spread_return = (target_diff - betas[i] * feature_diff) / total_capital if total_capital > 0 else 0.0

        prev_pos = pos

        # Transition Logic (5. Zero latency execution identical to optimizer)
        if pos == 0:
            if z[i-1] < -opt_sigma:
                pos = 1
            elif z[i-1] > opt_sigma:
                pos = -1
        elif pos == 1:
            if z[i-1] >= 0.0:
                pos = 0
        elif pos == -1:
            if z[i-1] <= 0.0:
                pos = 0
        
        # Store gross return applied to the position held during this step
        gross_returns[i] = pos * spread_return
        period_net_return = gross_returns[i]

        positions[i] = pos

        # Fee Logic - Exact percentage allocation of capital
        turnover = abs(pos - prev_pos)
        if turnover > 0:
            # We pay taker fee on both legs proportionally across the total capital allocated to the spread
            fee = turnover * taker_pct
            period_net_return -= fee
            trades += turnover
            
        net_returns[i] = period_net_return

    df['Gross_Return'] = gross_returns
    df['Net_Return'] = net_returns
    df['Cumulative_Gross'] = df['Gross_Return'].cumsum()
    df['Cumulative_Net'] = df['Net_Return'].cumsum()

    total_gross = df['Cumulative_Gross'].iloc[-1]
    total_net = df['Cumulative_Net'].iloc[-1]

    # Annualized Sharpe (comparing to interval)
    sr_net_mean = np.mean(net_returns)
    sr_net_std = np.std(net_returns) + 1e-10
    interval_sec = parse_interval_seconds(interval)
    # Crypto markets are open 24/7/365
    ann_factor = np.sqrt(365 * 86400 / interval_sec)
    sharpe_net = (sr_net_mean / sr_net_std) * ann_factor

    # Max Drawdown
    peak = np.maximum.accumulate(df['Cumulative_Net'])
    drawdown = peak - df['Cumulative_Net']
    max_dd = np.max(drawdown)

    round_trips = trades // 2

    print(f"      Pairs Traded (Round Trips): {round_trips}")
    print(f"      Gross Return: {total_gross:.2%}")
    print(f"      Net Return (After Fees): {total_net:.2%}")
    print(f"      Annualized Net Sharpe Ratio: {sharpe_net:.2f}")
    print(f"      Max Drawdown (Net): {max_dd:.2%}")

    fig_bt = plt.figure(figsize=(16, 6))
    ax_bt = fig_bt.add_subplot(1, 1, 1)
    ax_bt.plot(df.index, df['Cumulative_Gross'], label='Cumulative Gross Return', color='blue', alpha=0.5)
    ax_bt.plot(df.index, df['Cumulative_Net'], label='Cumulative Net Return', color='red', linewidth=1.5)
    ax_bt.set_title('Backtest Performance: Gross vs Net Return')
    ax_bt.set_ylabel('Cumulative Return')
    ax_bt.set_xlabel('Datetime')
    ax_bt.legend(loc='upper left')
    ax_bt.grid(True, alpha=0.3)
    fig_bt.tight_layout()

    output_bt_path = 'cointegration_backtest.report.png'
    fig_bt.savefig(output_bt_path, dpi=150, bbox_inches='tight')
    plt.close(fig_bt)
    print(f"Saved plot: {output_bt_path}")
