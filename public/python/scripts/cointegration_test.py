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

import sys
from pathlib import Path
# Add public/python to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from analytics_core import (
    interval_seconds_map,
    parse_interval_seconds,
    format_duration,
    get_hurst_exponent_dynamic,
    get_half_life,
    calculate_rolling_metrics,
    optimize_parameters
)
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
parser.add_argument('--backtest', type=float, nargs='?', const=20.0, default=0.0, help='Run an OOS backtest. Specify OOS percentage (default: 20 if flag is present).')
parser.add_argument('--taker-fee', type=float, default=0.05, help='Taker fee in percentage (default: 0.05).')
parser.add_argument('--maker-fee', type=float, default=0.02, help='Maker fee in percentage (default: 0.02).')
parser.add_argument('--ticker-list', nargs='+', help='List of tickers to test against each other. Overrides target/feature ticker args.')
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



# ==============================================================================
# 2. DATA ACQUISITION & ALIGNMENT
# ==============================================================================


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



VOLUME_PRIORITY = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX"]

def resolve_target_feature(ticker_a, ticker_b):
    score_a, score_b = 999, 999
    for idx, coin in enumerate(VOLUME_PRIORITY):
        if coin in ticker_a and score_a == 999: score_a = idx
        if coin in ticker_b and score_b == 999: score_b = idx
    if score_a < score_b: 
        return ticker_b, ticker_a # Target, Feature (A is higher priority, so A is Feature)
    elif score_b < score_a: 
        return ticker_a, ticker_b
    else: 
        sorted_pair = sorted([ticker_a, ticker_b])
        return sorted_pair[0], sorted_pair[1]

def analyze_pair(target_ticker, feature_ticker, target_df, feature_df, batch_mode=False):
    global rolling_window, sigma_threshold
    import warnings
    import builtins
    warnings.filterwarnings('ignore')
    
    original_print = builtins.print
    def custom_print(*args, **kwargs):
        if not batch_mode:
            original_print(*args, **kwargs)
            
    _print = original_print if not batch_mode else custom_print

    # We map the dataframes correctly
    btc_df = target_df.copy()
    feature_df = feature_df.copy()
    if 'Close' in feature_df.columns:
        feature_df = feature_df.rename(columns={'Close': 'Feature_Price'})
    
    _print(f"\n[2/7] Aligning time series...")

    
    # --- 2C. Time-Series Synchronization ---
    _print("\n[2/7] Aligning time series...")
    
    # If both are from Binance, they share the same UTC timestamps. An inner join drops missing intervals.
    df = btc_df.join(feature_df, how='inner').dropna()
    
    _print(f"Data aligned successfully. Total synchronized data points: {len(df)}")
    
    if df.empty:
        _print(color_text("ERROR: No aligned data points available after merging. Check input time window and data feeds.", RED))
        return None
    
    oos_pct = args.backtest / 100.0 if args.backtest else 0.0
    if args.backtest > 0:
        split_idx = int(len(df) * (1 - oos_pct))
        split_timestamp = df.index[split_idx]
        train_df = df[df.index < split_timestamp].copy()
        test_df = df[df.index >= split_timestamp].copy()
        _print(f"Data split: {len(train_df)} In-Sample rows ({(1-oos_pct):.0%}), {len(test_df)} Out-of-Sample rows ({oos_pct:.0%}).")
    else:
        split_timestamp = df.index[-1] + pd.Timedelta(days=1000)
        train_df = df.copy()
        test_df = pd.DataFrame()

    if len(train_df) < 50:
        _print(f"ERROR: Insufficient data.")
        return None
    
    # ==============================================================================
    # 3. LEAD-LAG ANALYSIS (CROSS-CORRELATION)
    # ==============================================================================
    _print("\n[3/7] Running Lead-Lag Analysis (Cross-Correlation)...")
    
    train_df['Target_Returns'] = np.log(train_df['Close'] / train_df['Close'].shift(1))
    train_df['Feature_Returns'] = np.log(train_df['Feature_Price'] / train_df['Feature_Price'].shift(1))
    df_returns = train_df.dropna()
    
    if df_returns.empty:
        _print(color_text("ERROR: No valid returns rows after differencing; cannot compute lead-lag correlations.", RED))
        return None
    
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
        _print(color_text("ERROR: Unable to compute any valid lag correlation (all values are NaN).", RED))
        return None
    
    best_lag = max(valid_correlations, key=lambda k: abs(valid_correlations[k]))
    best_corr = valid_correlations[best_lag]
    _print(f"Highest correlation ({best_corr:.4f}) found at lag: {best_lag}")
    
    # In this alignment logic:
    # If lag > 0, t_slice is earlier, f_slice is later. e.g. T[0] and F[1]. Target predicts Feature.
    # If lag < 0, t_slice is later, f_slice is earlier. e.g. T[1] and F[0]. Feature predicts Target. We want this!
    if best_lag < 0:
        abs_lag = abs(best_lag)
        _print(color_text(f"-> Conclusion: {feature_ticker} LEADS {target_ticker} by {abs_lag} periods.", GREEN))
        _print("   Aligning feature price to predictive state by shifting forward.")
        df['Feature_Price'] = df['Feature_Price'].shift(abs_lag)
        df = df.dropna()
    elif best_lag > 0:
        _print(color_text(f"-> Conclusion: {target_ticker} LEADS {feature_ticker} by {best_lag} periods. ({feature_ticker} is likely useless).", RED))
    else:
        _print(color_text(f"-> Conclusion: Both assets move synchronously.", YELLOW))
    
    
    # ==============================================================================
    # Helper functions for calculations and Walk-Forward Optimization
    # ==============================================================================
    
    
    # Wrapper to use global args in optimize_parameters
    def optimize_parameters_wrapper(df_in, half_life_periods):
        return optimize_parameters(
            df_in=df_in,
            half_life_periods=half_life_periods,
            interval=args.interval,
            args_rolling_window=args.rolling_window,
            args_sigma_threshold=args.sigma_threshold,
            taker_fee=args.taker_fee,
            verbose=getattr(args, 'verbose', False)
        )
    
    # ==============================================================================
    # 4. ROLLING METRICS & SIGNAL GENERATION
    # ==============================================================================
    if rolling_window == 'auto' or sigma_threshold == 'auto':
        # Base static OLS calculation for half-life
        _print("\n[Prep] Calculating baseline static half-life for optimization...")
        
        # Configurable chunk duration for baseline half-life calculation
        baseline_chunk_duration = '3d'
        chunk_size = parse_interval_seconds(baseline_chunk_duration) // parse_interval_seconds(interval)
        if chunk_size == 0 or chunk_size > len(train_df):
            chunk_size = len(train_df)
            
        local_half_lives = []
        for i in range(0, len(train_df), chunk_size):
            chunk = train_df.iloc[i:i + chunk_size]
            if len(chunk) < 100: continue
            X_stat = sm.add_constant(np.log(chunk['Feature_Price']))
            Y_stat = np.log(chunk['Close'])
            base_model = sm.OLS(Y_stat, X_stat).fit()
            base_spread = base_model.resid
            hl = get_half_life(base_spread, interval)
            if not np.isinf(hl) and not np.isnan(hl) and hl > 0:
                local_half_lives.append(hl)
    
        if local_half_lives:
            base_hl = np.median(local_half_lives)
            _print(f"      Calculated median half-life from {len(local_half_lives)} chunks (duration: {baseline_chunk_duration}).")
        else:
            base_hl = 800 # fallback
            _print(color_text("      -> Could not compute valid local half-lives. Falling back to default window of 800.", YELLOW))
        
        optimal_window, optimal_threshold = optimize_parameters_wrapper(train_df, base_hl)
        if rolling_window == 'auto':
            rolling_window = optimal_window
        if sigma_threshold == 'auto':
            sigma_threshold = optimal_threshold
        
        if rolling_window_only:
            _print(color_text(f"\nOptimization complete. Optimal Window: {rolling_window}. Exiting as requested.", GREEN))
            return None
    
    opt_sigma = sigma_threshold
    
    _print("\n[4/7] Calculating EWM Hedge Ratio (Beta) and Z-Scores...")
    
    df = calculate_rolling_metrics(df, rolling_window)
    
    # Extract rolling variables back for existing downstream logic
    df = df.dropna()
    
    
    df['Z_Above'] = df['Z_Score'] > opt_sigma
    df['Z_Below'] = df['Z_Score'] < -opt_sigma
    
    prev_above = df['Z_Above'].shift(1, fill_value=False)
    prev_below = df['Z_Below'].shift(1, fill_value=False)
    
    df['Signal_Above_Cross'] = df['Z_Above'] & (~prev_above)
    df['Signal_Below_Cross'] = df['Z_Below'] & (~prev_below)
    
    train_eval_df = df[df.index < split_timestamp]
    
    bullish_signals = int(train_eval_df['Signal_Below_Cross'].sum())
    bearish_signals = int(train_eval_df['Signal_Above_Cross'].sum())
    raw_exceedance_count = int(train_eval_df['Z_Above'].sum() + train_eval_df['Z_Below'].sum())
    raw_exceedance_pct = raw_exceedance_count / len(train_eval_df) if len(train_eval_df) > 0 else 0.0
    
    expected_exceedance_rate = 2 * (1 - norm.cdf(opt_sigma))
    
    _print(f"Identified {bullish_signals} bullish signals and {bearish_signals} bearish signals based.")
    _print(f"       Total raw exceedances outside ±{opt_sigma:.2f}σ: {raw_exceedance_count} rows ({raw_exceedance_pct:.2%}), including persistence of the same signal.")
    
    signal_count = bullish_signals + bearish_signals
    signal_pct = signal_count / len(train_eval_df) if len(train_eval_df) > 0 else 0.0
    
    # Flag warning if exceeded significantly more than dynamic normal distribution expectation (e.g., > 1.5x)
    max_expected_pct = expected_exceedance_rate * 1.5
    if raw_exceedance_pct > max_expected_pct:
        _print(color_text("   !!! WARNING: The Z-score exceedance rate is unusually high.", YELLOW))
        _print(color_text(f"       {raw_exceedance_count} out of {len(train_eval_df)} points ({raw_exceedance_pct:.2%}) exceed ±{opt_sigma:.2f}σ.", YELLOW))
        _print(color_text(f"       In a normal distribution, ±{opt_sigma:.2f}σ events should occur only about {expected_exceedance_rate:.2%} of the time.", YELLOW))
        _print(color_text("       This strongly suggests the spread distribution has extremely fat tails, or more likely, the rolling window for Z-score calculation is too short.", YELLOW))
    
    
    # ==============================================================================
    # 5. STATIC OLS & COINTEGRATION (ADF TEST)
    # ==============================================================================
    if len(train_eval_df) < 5:
        _print(color_text("ERROR: Insufficient data in train_eval_df after rolling window drops.", RED))
        return None

    _print("\n[5/7] Calculating Static Hedge Ratio and Testing Cointegration...")
    
    # Calculate static beta for visualization/baseline purposes strictly on training data
    X_train = sm.add_constant(np.log(train_eval_df['Feature_Price']))
    Y_train = np.log(train_eval_df['Close'])
    static_model = sm.OLS(Y_train, X_train).fit()
    static_beta = static_model.params['Feature_Price']
    
    # Apply static beta dynamically to full series for visualization
    X_all = sm.add_constant(np.log(df['Feature_Price']))
    df['Static_Spread'] = np.log(df['Close']) - static_model.predict(X_all) 
    
    _print(f"Static Hedge Ratio (Beta): {static_beta:.4f}")
    
    try:
        _print("      -> Downsampling data for cointegration test to improve performance...")
        # Cointegration is a long-term property. Downsampling to 15-minute intervals drastically speeds up 
        # the ADF lag-search built into the test without losing the macro-equilibrium relationship.
        coint_df = train_eval_df[['Close', 'Feature_Price']].resample('15min').last().dropna() if len(train_eval_df) > 10000 else train_eval_df
        
        # Use the proper Engle-Granger cointegration test on the downsampled concurrent log price series
        coint_score, p_value, critical_values = coint(np.log(coint_df['Close']), np.log(coint_df['Feature_Price']))
        
        _print(f"Engle-Granger T-Statistic: {coint_score:.4f}")
        _print(f"MacKinnon P-Value: {p_value:.6f}")
        _print(f"Critical Values (1%, 5%, 10%): {critical_values}")
    except Exception as e:
        _print(f"Cointegration Test Error: {e}")
        p_value = 1.0
    
    is_cointegrated = p_value < 0.05
    if is_cointegrated:
        _print(color_text(f"-> Conclusion: The pair IS cointegrated (P-Value < 0.05).", GREEN))
    else:
        _print(color_text(f"-> Conclusion: The pair is NOT cointegrated (P-Value >= 0.05).", RED))
    
    # ==============================================================================
    # 6. ADVANCED METRICS: HURST & HALF-LIFE
    # ==============================================================================
    _print("\n[6/7] Calculating Hurst Exponent and Mean-Reversion Half-Life...")
    
    # These functions have been moved up
    
    
    horst_static_input = df.loc[train_eval_df.index, 'Static_Spread'].dropna().values
    hurst_static = get_hurst_exponent_dynamic(horst_static_input, rolling_window)
    hurst = get_hurst_exponent_dynamic(train_eval_df['Dynamic_Spread'].dropna().values, rolling_window)
    half_life = get_half_life(train_eval_df['Dynamic_Spread'].dropna(), interval)
    half_life_seconds = half_life * parse_interval_seconds(interval)
    half_life_readable = format_duration(half_life_seconds)
    
    _print(f"-> Hurst Exponent (Static): {hurst_static:.4f} (Target < 0.5 for mean reversion)")
    _print(f"-> Hurst Exponent (Dynamic): {hurst:.4f} (Target < 0.5 for mean reversion)")
    _print(f"-> Mean Reversion Half-Life: {half_life:.2f} periods (~{half_life_readable})")
    if half_life_seconds > 7200:
        _print(color_text("   !!! WARNING: Half-life exceeds 2 hours. Spread may not revert fast enough for medium-frequency strategies.", YELLOW))

    _spread_bps_calc = train_eval_df['Dynamic_Spread'].dropna().values * 10000
    tmp_avg_abs_spread = float(np.mean(np.abs(_spread_bps_calc))) if len(_spread_bps_calc) else 0.0
    tmp_std_abs_spread = float(np.std(np.abs(_spread_bps_calc))) if len(_spread_bps_calc) else 0.0
    _print(f"-> Average Absolute Spread: {tmp_avg_abs_spread:.2f} bps (±{tmp_std_abs_spread:.2f} bps)")
    
    # ==============================================================================
    # 7. FINAL VERDICT & VISUALIZATION
    # ==============================================================================
    _print("\n[7/7] Final Verdict for Medium-Frequency Trading:")
    
    signal_warning = raw_exceedance_pct > 0.045
    half_life_warning = half_life_seconds > 7200
    mean_reversion_warning = hurst_static >= 0.5 # Adjusted to standard 0.5 threshold
    cointegration_warning = not is_cointegrated
    
    # FIX: If best_lag is >= 0, the feature does not lead. It is useless for anticipation.
    lead_lag_warning = best_lag >= 0 
    
    if lead_lag_warning:
        _print(color_text(f"WARNING: {feature_ticker} does not lead {target_ticker} (lag = {best_lag}). No predictive edge.", YELLOW))
    
    if not is_cointegrated:
        _print(color_text(f"VERDICT: NO. Cointegration is weak or absent (Engle-Granger p-value = {p_value:.6f}).", RED))
    elif mean_reversion_warning:
        _print(color_text(f"VERDICT: NO. Hurst exponent (Static) is {hurst_static:.4f} (close or greater than 0.5), indicating the spread is not reliably mean-reverting.", RED))
        if p_value < 0.05:
            _print(color_text(
                f"       The fact that the ADF p-value is {p_value:.3f} shows that while the spread does eventually revert,"
                " the path it takes to get there is so chaotic and random that the drawdown you experience while waiting for the reversion"
                " will likely trigger your risk limits or liquidate you.", YELLOW))
    elif half_life_warning:
        _print(color_text(f"VERDICT: NO. Estimated half-life is {half_life:.2f} periods (~{half_life_readable}), which is too long for medium-frequency execution.", RED))
    elif signal_warning:
        _print(color_text(f"VERDICT: NO. Excessive ±2σ Z-score signals ({signal_pct:.2%}) indicate fat tails or an unstable Z-score window, reducing strategy reliability.", RED))
    else:
        _print(color_text(f"VERDICT: YES. {feature_ticker} is cointegrated, the spread appears mean-reverting, and the half-life is appropriate.", GREEN))
    
    _print("\n[7/7] Generating Proof Diagrams...")
    
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
    _print(f"Saved plot: {output_validation_path}")
    
    fig = plt.figure(figsize=(16, 12))
    
    ax1 = plt.subplot(2, 2, 1)
    ax1.scatter(df['Feature_Price'], df['Close'], alpha=0.3, color='blue', s=10)
    rolling_pred_close = np.exp(df['Rolling_Alpha'] + df['Rolling_Beta'] * np.log(df['Feature_Price']))
    ax1.scatter(df['Feature_Price'], rolling_pred_close, color='red', alpha=0.5, s=2)
    ax1.set_title(f'Price Scatter: {feature_ticker} vs {target_ticker} (Rolling Mean)')
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
    ax4.hist(df['Z_Score'].clip(-10, 10), bins=60, range=(-10, 10), density=True, color='skyblue', edgecolor='black', alpha=0.7)
    x_vals = np.linspace(-10, 10, 300)
    normal_pdf = (1.0 / np.sqrt(2 * np.pi)) * np.exp(-0.5 * x_vals**2)
    ax4.plot(x_vals, normal_pdf, color='red', linestyle='--', linewidth=2, label='Standard Normal PDF')
    ax4.set_xlim(-10, 10)
    ax4.set_title('Z-Score Distribution vs. Expected Normal')
    ax4.set_xlabel('Z-Score')
    ax4.set_ylabel('Density')
    ax4.legend(loc='upper right')
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_path = 'cointegration_analysis.report.png'
    fig.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    _print(f"Saved plot: {output_path}")
    
    # --- Generate standalone spread chart ---
    df['Spread_bps'] = df['Dynamic_Spread'] * 10000
    
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
    _print(f"Saved plot: {output_spread_path}")
    
    if args.backtest:
        _print("\n[8/7] Running Analytical Performance Backtest...")
        taker_pct = args.taker_fee / 100.0
        maker_pct = args.maker_fee / 100.0
    
        if 'split_timestamp' in locals():
            bt_df = df[df.index >= split_timestamp].copy()
            if bt_df.empty:
                bt_df = df.copy()
        else:
            bt_df = df.copy()
    
        # Retrieve required columns as NumPy arrays for fast iteration
        z = bt_df['Z_Score'].values
        features = bt_df['Feature_Price'].values
        targets = bt_df['Close'].values
        betas = bt_df['Rolling_Beta'].shift(1).fillna(0).values
    
        # Pre-allocate arrays
        n = len(bt_df)
        gross_returns = np.zeros(n)
        net_returns = np.zeros(n)
        positions = np.zeros(n)
    
        pos = 0  # 1 for Long Spread, -1 for Short Spread, 0 for Flat
        trades = 0
    
        active_trade = None
    
        for i in range(1, n):
            # Calculate PnL accurately mapping to Price-Beta Cointegration
            ret_target = np.log(targets[i] / targets[i-1]) if targets[i-1] > 0 and targets[i] > 0 else 0.0
            ret_feature = np.log(features[i] / features[i-1]) if features[i-1] > 0 and features[i] > 0 else 0.0
            
            spread_return = (ret_target - betas[i] * ret_feature) / (1.0 + abs(betas[i])) if (1.0 + abs(betas[i])) > 0 else 0.0
    
            prev_pos = pos
    
            # Transition Logic (0-period latency execution identically to optimizer)
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
            fee = 0.0
            if turnover > 0:
                if prev_pos == 0 and pos != 0:
                    # Entry (Maker)
                    fee = maker_pct
                    if args.verbose:
                        active_trade = {
                            'entry_time': bt_df.index[i-1],
                            'side': 'LONG' if pos == 1 else 'SHORT',
                            'entry_target': targets[i-1],
                            'entry_feature': features[i-1],
                            'entry_spread': z[i-1],
                            'entry_fee': fee,
                            'cum_gross': 0.0
                        }
                elif prev_pos != 0 and pos == 0:
                    # Exit (Taker)
                    fee = taker_pct
                    if args.verbose and active_trade:
                        total_fee = active_trade['entry_fee'] + fee
                        trade_gross = active_trade['cum_gross']
                        trade_net = trade_gross - total_fee
                        _print(f"[Verbose] Trade Closed [{active_trade['side']}]: Entry {active_trade['entry_time']} Target={active_trade['entry_target']:.4f} Feature={active_trade['entry_feature']:.4f} Spread Z={active_trade['entry_spread']:.2f} | Exit {bt_df.index[i-1]} Target={targets[i-1]:.4f} Feature={features[i-1]:.4f} Spread Z={z[i-1]:.2f} | Fees: {total_fee:.4%} | Gross: {trade_gross:.4%} | Net: {trade_net:.4%}")
                        active_trade = None
                elif prev_pos != 0 and pos != 0 and prev_pos != pos:
                    # Flip: Exit current (Taker) and Entry new (Maker)
                    fee = taker_pct + maker_pct
                    if args.verbose and active_trade:
                        total_fee = active_trade['entry_fee'] + taker_pct
                        trade_gross = active_trade['cum_gross']
                        trade_net = trade_gross - total_fee
                        _print(f"[Verbose] Trade Closed [{active_trade['side']}]: Entry {active_trade['entry_time']} Target={active_trade['entry_target']:.4f} Feature={active_trade['entry_feature']:.4f} Spread Z={active_trade['entry_spread']:.2f} | Exit {bt_df.index[i-1]} Target={targets[i-1]:.4f} Feature={features[i-1]:.4f} Spread Z={z[i-1]:.2f} | Fees: {total_fee:.4%} | Gross: {trade_gross:.4%} | Net: {trade_net:.4%}")
                        
                        active_trade = {
                            'entry_time': bt_df.index[i-1],
                            'side': 'LONG' if pos == 1 else 'SHORT',
                            'entry_target': targets[i-1],
                            'entry_feature': features[i-1],
                            'entry_spread': z[i-1],
                            'entry_fee': maker_pct,
                            'cum_gross': 0.0
                        }
    
                period_net_return -= fee
                trades += turnover
                
            if active_trade:
                active_trade['cum_gross'] += gross_returns[i]
    
            net_returns[i] = period_net_return
    
        bt_df['Gross_Return'] = gross_returns
        bt_df['Net_Return'] = net_returns
        bt_df['Cumulative_Gross'] = bt_df['Gross_Return'].cumsum()
        bt_df['Cumulative_Net'] = bt_df['Net_Return'].cumsum()
        bt_df['Position'] = positions
    
        total_gross = bt_df['Cumulative_Gross'].iloc[-1] if len(bt_df) > 0 else 0.0
        total_net = bt_df['Cumulative_Net'].iloc[-1] if len(bt_df) > 0 else 0.0
    
        # Annualized Sharpe (comparing to interval)
        sr_net_mean = np.mean(net_returns)
        sr_net_std = np.std(net_returns) + 1e-10
        interval_sec = parse_interval_seconds(interval)
        # Crypto markets are open 24/7/365
        ann_factor = np.sqrt(365 * 86400 / interval_sec)
        sharpe_net = (sr_net_mean / sr_net_std) * ann_factor
    
        # Max Drawdown
        peak = np.maximum.accumulate(bt_df['Cumulative_Net'])
        drawdown = peak - bt_df['Cumulative_Net']
        max_dd = np.max(drawdown) if len(drawdown) > 0 else 0.0
    
        round_trips = trades // 2
    
        _print(f"      Pairs Traded (Round Trips): {round_trips}")
        _print(f"      Gross Return: {total_gross:.2%}")
        _print(f"      Net Return (After Fees): {total_net:.2%}")
        _print(f"      Annualized Net Sharpe Ratio: {sharpe_net:.2f}")
        _print(f"      Max Drawdown (Net): {max_dd:.2%}")
    
        fig_bt = plt.figure(figsize=(16, 12))
        ax_bt = fig_bt.add_subplot(2, 1, 1)
        ax_bt.plot(bt_df.index, bt_df['Cumulative_Gross'], label='Cumulative Gross Return', color='blue', alpha=0.5)
        ax_bt.plot(bt_df.index, bt_df['Cumulative_Net'], label='Cumulative Net Return', color='red', linewidth=1.5)
        ax_bt.set_title('Backtest Performance: Gross vs Net Return (Out-of-Sample)')
        ax_bt.set_ylabel('Cumulative Return')
        ax_bt.set_xlabel('Datetime')
        ax_bt.legend(loc='upper left')
        ax_bt.grid(True, alpha=0.3)
    
        if not bt_df.empty:
            # Align the logical entry diff with the trigger timestamp (t-1)
            # Position at t represents the holding state arriving at t from t-1.
            # Thus, a change at t means the trade was executed exactly at the close of t-1.
            bt_df['Pos_Diff'] = bt_df['Position'].diff().shift(-1)
            bt_df['Next_Pos'] = bt_df['Position'].shift(-1)
    
            # Entry points
            long_entries = bt_df[(bt_df['Pos_Diff'] > 0) & (bt_df['Next_Pos'] == 1)]
            short_entries = bt_df[(bt_df['Pos_Diff'] < 0) & (bt_df['Next_Pos'] == -1)]
            
            # Exit points (closing a long or a short)
            close_longs = bt_df[(bt_df['Pos_Diff'] < 0) & (bt_df['Next_Pos'] == 0)]
            close_shorts = bt_df[(bt_df['Pos_Diff'] > 0) & (bt_df['Next_Pos'] == 0)]
    
            ax_trades = fig_bt.add_subplot(2, 1, 2)
    
            # Plot the spread itself
            ax_trades.plot(bt_df.index, bt_df['Spread_bps'], color='darkgray', linewidth=1, label='Normalized Spread (bps)', alpha=0.6)
    
            # Plot Long Entries/Exits
            ax_trades.scatter(long_entries.index, long_entries['Spread_bps'], color='green', marker='^', s=100, label='Long Spread Entry', zorder=5)
            ax_trades.scatter(close_longs.index, close_longs['Spread_bps'], color='limegreen', marker='x', s=80, label='Long Spread Exit', zorder=5)
    
            # Plot Short Entries/Exits
            ax_trades.scatter(short_entries.index, short_entries['Spread_bps'], color='red', marker='v', s=100, label='Short Spread Entry', zorder=5)
            ax_trades.scatter(close_shorts.index, close_shorts['Spread_bps'], color='lightcoral', marker='x', s=80, label='Short Spread Exit', zorder=5)
    
            # Helper Threshold lines (Dynamic Rolling Bands)
            if 'Spread_Std' in bt_df.columns:
                dynamic_upper = opt_sigma * bt_df['Spread_Std'] * 10000
                dynamic_lower = -opt_sigma * bt_df['Spread_Std'] * 10000
                ax_trades.plot(bt_df.index, dynamic_upper, color='darkred', linestyle='--', alpha=0.4, label=f'+{opt_sigma}σ Band')
                ax_trades.plot(bt_df.index, dynamic_lower, color='darkgreen', linestyle='--', alpha=0.4, label=f'-{opt_sigma}σ Band')
            else:
                ax_trades.axhline(10.0, color='darkred', linestyle='--', alpha=0.4)
                ax_trades.axhline(-10.0, color='darkgreen', linestyle='--', alpha=0.4)
                
            ax_trades.axhline(0, color='blue', alpha=0.3)
    
            ax_trades.set_title('Out-of-Sample Trade Executions mapped to Normalized Spread (bps)')
            ax_trades.set_ylabel('Spread (bps) [Symlog]')
            ax_trades.set_yscale('symlog', linthresh=10.0)
            ax_trades.set_xlabel('Datetime')
            ax_trades.legend(loc='upper right')
            ax_trades.grid(True, alpha=0.3)
            
        fig_bt.tight_layout()
    
        output_bt_path = 'cointegration_backtest.report.png'
        fig_bt.savefig(output_bt_path, dpi=150, bbox_inches='tight')
        plt.close(fig_bt)
        _print(f"Saved plot: {output_bt_path}")
    
    spread_bps = train_eval_df['Dynamic_Spread'].dropna().values * 10000
    avg_abs_spread = float(np.mean(np.abs(spread_bps))) if len(spread_bps) else 0.0
    std_abs_spread = float(np.std(np.abs(spread_bps))) if len(spread_bps) else 0.0

    return {
        'target': target_ticker,
        'feature': feature_ticker,
        'hurst_stat': hurst_static,
        'hurst': hurst,
        'p_value': p_value,
        'half_life': half_life_seconds,
        'half_life_readable': half_life_readable,
        'cointegrated': is_cointegrated,
        'avg_abs_spread': avg_abs_spread,
        'std_abs_spread': std_abs_spread
    }


if __name__ == "__main__":
    if args.ticker_list and len(args.ticker_list) > 1:
        print(f"--- Batch Mode Cointegration Analysis ---")
        print(f"Fetching data for {len(args.ticker_list)} tickers...")
        data_cache = {}
        for t in args.ticker_list:
            data_cache[t] = get_symbol_data(t)
            print(f"Fetched {len(data_cache[t])} data points for {t}.")
        
        import itertools
        from concurrent.futures import ProcessPoolExecutor, as_completed
        
        pairs = list(itertools.combinations(args.ticker_list, 2))
        print(f"Testing {len(pairs)} pairwise combinations...")
        
        results = []
        
        def run_pair(t1, t2):
            t_name, f_name = resolve_target_feature(t1, t2)
            try:
                res = analyze_pair(t_name, f_name, data_cache[t_name], data_cache[f_name], batch_mode=True)
                return res
            except Exception as e:
                return {"error": f"Failed analysis for {t_name} vs {f_name}: {e}\n"}

        # Use multiprocessing to scale heavily across many assets
        with ProcessPoolExecutor() as executor:
            future_to_pair = {executor.submit(run_pair, t1, t2): (t1, t2) for t1, t2 in pairs}
            for future in as_completed(future_to_pair):
                t1, t2 = future_to_pair[future]
                try:
                    res = future.result()
                    if res and "error" not in res:
                        results.append(res)
                    elif res and "error" in res:
                        print(res["error"])
                except Exception as e:
                    print(f"Process crashed for {t1} vs {t2}: {e}")
                
        print(f"\n{'Target':<10} | {'Feature':<10} | {'Hurst (Stat)':<12} | {'ADF P-Val':<10} | {'Half-life'}")
        print("-" * 65)
        for res in results:
            c_color = GREEN if res['cointegrated'] else RED
            print(color_text(f"{res['target']:<10} | {res['feature']:<10} | {res['hurst_stat']:<12.4f} | {res['p_value']:<10.6f} | {res['half_life_readable']}", c_color))
            
        if results:
            import matplotlib.pyplot as plt
            import numpy as np
            
            results.sort(key=lambda x: x['avg_abs_spread'])
            labels = [f"{r['target']} / {r['feature']}" for r in results]
            means = [r['avg_abs_spread'] for r in results]
            stds = [r['std_abs_spread'] for r in results]
            
            # Professional monochrome styling
            plt.style.use('default')
            fig, ax = plt.subplots(figsize=(10, max(4, len(results) * 0.4)))
            y_pos = np.arange(len(labels))
            
            # Black scatter & hlines
            ax.scatter(means, y_pos, color='#000000', zorder=3, s=30)
            ax.hlines(y_pos, xmin=np.maximum(0, np.array(means) - np.array(stds)), 
                      xmax=np.array(means) + np.array(stds), color='#000000', alpha=0.8, linewidth=1.5, zorder=2)
            
            # Clean spines
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['left'].set_color('#333333')
            ax.spines['bottom'].set_color('#333333')
            
            ax.set_yticks(y_pos)
            ax.set_yticklabels(labels)
            ax.set_xlabel('Average Absolute Spread (Basis Points) ± 1 Std Dev')
            ax.set_title('Batch Cointegration Analysis: Absolute Spread Magnitude (bps)')
            ax.grid(True, alpha=0.3, axis='x')
            ax.axvline(0, color='black', linewidth=1, alpha=0.5)
            ax.axvline(50, color='#880000', linestyle='--', linewidth=1, alpha=0.7, label='Trade Fee Threshold (50 bps)')
            ax.legend(loc='lower right', frameon=False)
            
            if len(means) > 0:
                ax.set_xlim(left=0, right=max([m + s for m, s in zip(means, stds)]) * 1.1)
            
            plt.tight_layout()
            out_path = 'batch_spread_analysis.png'
            fig.savefig(out_path, dpi=150, bbox_inches='tight')
            plt.close(fig)
            print(f"\nSaved divergence comparison plot to: {out_path}")
            
    else:
        print(f"--- High-Frequency Stat Arb Analysis: {target_ticker} vs {feature_ticker} ---")
        print(f"\n[1/7] Fetching high-frequency data for {target_ticker} and {feature_ticker}...")
        target_df = get_symbol_data(target_ticker)
        print(f"Fetched {len(target_df)} data points for {target_ticker}.")
        feature_df = get_symbol_data(feature_ticker)
        print(f"Fetched {len(feature_df)} data points for {feature_ticker}.")
        analyze_pair(target_ticker, feature_ticker, target_df, feature_df, batch_mode=False)
