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
from statsmodels.tsa.stattools import adfuller
from statsmodels.regression.rolling import RollingOLS
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
parser.add_argument('--rolling-window', type=int, default=800, help='Rolling window size used for rolling beta and z-score calculations.')
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
rolling_window = args.rolling_window

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

def fetch_binance_data(symbol, interval, start_ts, end_ts):
    """Helper function to fetch and format Binance Kline data."""
    print(f"      -> Downloading Klines for {symbol} from {start_ts} to {end_ts}...")
    klines = client.get_historical_klines(
        symbol,
        interval,
        start_ts.strftime("%d %b, %Y %H:%M:%S"),
        end_ts.strftime("%d %b, %Y %H:%M:%S")
    )
    
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

target_vals = df_returns['Target_Returns'].values
feature_vals = df_returns['Feature_Returns'].values

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

if best_lag > 0:
    print(color_text(f"-> Conclusion: {feature_ticker} LEADS {target_ticker} by {best_lag} periods. (Highly useful)", GREEN))
    print(f"   Aligning data: Shifting Feature forward by {best_lag} periods to prevent lookahead bias.")
    # Shift the feature price forward to align with the target's lead
    df['Feature_Price'] = df['Feature_Price'].shift(best_lag)
    df = df.dropna()
elif best_lag < 0:
    print(color_text(f"-> Conclusion: {target_ticker} LEADS {feature_ticker}. ({feature_ticker} is likely useless for predicting {target_ticker})", RED))
else:
    print(color_text(f"-> Conclusion: Both assets move synchronously. (Useful for mean reversion, but latency execution is tough)", YELLOW))

# ==============================================================================
# 4. STATIC OLS & COINTEGRATION (ADF TEST)
# ==============================================================================
print("\n[4/7] Calculating Static Hedge Ratio and Testing Cointegration...")

X = sm.add_constant(df['Feature_Price'])
Y = df['Close']
static_model = sm.OLS(Y, X).fit()
static_beta = static_model.params['Feature_Price']

df['Static_Spread'] = df['Close'] - (static_beta * df['Feature_Price'])

print(f"Static Hedge Ratio (Beta): {static_beta:.4f}")

try:
    adf_result = adfuller(df['Static_Spread'].dropna())
    p_value = adf_result[1]
    
    print(f"ADF Statistic: {adf_result[0]:.4f}")
    print(f"ADF P-Value: {p_value:.6f}")
except ValueError as e:
    print(f"ADF Error: {e}")
    p_value = 1.0

is_cointegrated = p_value < 0.05
if is_cointegrated:
    print(color_text(f"-> Conclusion: The spread IS stationary (Cointegrated). P-Value < 0.05.", GREEN))
else:
    print(color_text(f"-> Conclusion: The spread is NOT stationary (Not Cointegrated). P-Value >= 0.05.", RED))

# ==============================================================================
# 5. ADVANCED METRICS: HURST & HALF-LIFE
# ==============================================================================
print("\n[5/7] Calculating Hurst Exponent and Mean-Reversion Half-Life...")

def get_hurst_exponent(ts):
    ts_arr = np.asarray(ts)
    lags = np.arange(2, 100)
    tau = [np.std(ts_arr[lag:] - ts_arr[:-lag]) for lag in lags]
    poly = np.polyfit(np.log(lags), np.log(tau), 1)
    return poly[0]

def get_half_life(ts):
    df_temp = pd.DataFrame({'lag': ts.shift(1), 'diff': ts.diff()}).dropna()
    X = sm.add_constant(df_temp['lag'])
    Y = df_temp['diff']
    res = sm.OLS(Y, X).fit()
    if len(res.params) < 2:
        return np.inf
    lam = res.params['lag']
    return -np.log(2) / lam if lam < 0 else np.inf

interval_seconds_map = {
    's': 1,
    'm': 60,
    'h': 3600,
    'd': 86400,
    'w': 604800,
    'M': 2592000,
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

hurst = get_hurst_exponent(df['Static_Spread'].values)
half_life = get_half_life(df['Static_Spread'])
half_life_seconds = half_life * parse_interval_seconds(interval)
half_life_readable = format_duration(half_life_seconds)

print(f"-> Hurst Exponent: {hurst:.4f} (Target < 0.5 for mean reversion)")
print(f"-> Mean Reversion Half-Life: {half_life:.2f} periods (~{half_life_readable})")
if half_life_seconds > 7200:
    print(color_text("   !!! WARNING: Half-life exceeds 2 hours. Spread may not revert fast enough for medium-frequency strategies.", YELLOW))

# ==============================================================================
# 6. ROLLING METRICS & SIGNAL GENERATION
# ==============================================================================
print("\n[6/7] Calculating Rolling Hedge Ratio (Beta) and Z-Scores...")

roll_cov = df['Close'].rolling(window=rolling_window).cov(df['Feature_Price'])
roll_var = df['Feature_Price'].rolling(window=rolling_window).var()
roll_mean_close = df['Close'].rolling(window=rolling_window).mean()
roll_mean_feature = df['Feature_Price'].rolling(window=rolling_window).mean()

df['Rolling_Beta'] = roll_cov / roll_var
df['Rolling_Alpha'] = roll_mean_close - (df['Rolling_Beta'] * roll_mean_feature)

df['Dynamic_Spread'] = df['Close'] - (df['Rolling_Beta'].shift(1) * df['Feature_Price']) - df['Rolling_Alpha'].shift(1)

df['Spread_Mean'] = df['Dynamic_Spread'].rolling(window=rolling_window).mean()
df['Spread_Std'] = df['Dynamic_Spread'].rolling(window=rolling_window).std()
df = df.dropna()
df['Z_Score'] = (df['Dynamic_Spread'] - df['Spread_Mean'].shift(1)) / df['Spread_Std'].shift(1)
df = df.dropna()

df['Z_Above'] = df['Z_Score'] > 2.0
df['Z_Below'] = df['Z_Score'] < -2.0

prev_above = df['Z_Above'].shift(1, fill_value=False)
prev_below = df['Z_Below'].shift(1, fill_value=False)

df['Signal_Above_Cross'] = df['Z_Above'] & (~prev_above)
df['Signal_Below_Cross'] = df['Z_Below'] & (~prev_below)

bullish_signals = int(df['Signal_Below_Cross'].sum())
bearish_signals = int(df['Signal_Above_Cross'].sum())
raw_exceedance_count = int(df['Z_Above'].sum() + df['Z_Below'].sum())
raw_exceedance_pct = raw_exceedance_count / len(df) if len(df) > 0 else 0.0

print(f"Identified {bullish_signals} bullish signals and {bearish_signals} bearish signals based.")
print(f"       Total raw exceedances outside ±2σ: {raw_exceedance_count} rows ({raw_exceedance_pct:.2%}), including persistence of the same signal.")

signal_count = bullish_signals + bearish_signals
signal_pct = signal_count / len(df) if len(df) > 0 else 0.0
if raw_exceedance_pct > 0.045:
    print(color_text("   !!! WARNING: The Z-score exceedance rate is unusually high.", YELLOW))
    print(color_text(f"       {raw_exceedance_count} out of {len(df)} points ({raw_exceedance_pct:.2%}) exceed ±2σ.", YELLOW))
    print(color_text("       In a normal distribution, ±2σ events should occur only about 4.5% of the time.", YELLOW))
    print(color_text("       This strongly suggests the spread distribution has extremely fat tails, or more likely, the rolling window for Z-score calculation is too short.", YELLOW))


# ==============================================================================
# 7. FINAL VERDICT & VISUALIZATION
# ==============================================================================
print("\n[7/7] Final Verdict for Medium-Frequency Trading:")

signal_warning = raw_exceedance_pct > 0.045
half_life_warning = half_life_seconds > 7200
mean_reversion_warning = hurst >= 0.4
cointegration_warning = not is_cointegrated
lead_lag_warning = best_lag < -1

if not is_cointegrated:
    print(color_text(f"VERDICT: NO. Cointegration is weak or absent (ADF p-value = {p_value:.6f}). Spread is unlikely to be stationary.", RED))
elif lead_lag_warning:
    print(color_text(f"VERDICT: NO. {target_ticker} leads {feature_ticker} (lag = {best_lag}). The feature asset is not useful for predicting the target.", RED))
elif mean_reversion_warning:
    print(color_text(f"VERDICT: NO. Hurst exponent is {hurst:.4f} (close or greater than 0.5), indicating the spread is not reliably mean-reverting.", RED))
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
    print(color_text(f"VERDICT: YES. {feature_ticker} is cointegrated, {best_lag} lag is acceptable, the spread appears mean-reverting, and the half-life is appropriate.", GREEN))

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
output_validation_path = 'cointegration_validation_timeseries.png'
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
ax3.axhline(2.0, color='red', linestyle='--', label='Short Spread (+2 / Overvalued)')
ax3.axhline(-2.0, color='green', linestyle='--', label='Long Spread (-2 / Undervalued)')
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
output_path = 'cointegration_report.png'
fig.savefig(output_path, dpi=150, bbox_inches='tight')
plt.close(fig)
print(f"Saved plot: {output_path}")