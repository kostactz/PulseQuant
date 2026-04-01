# ==============================================================================
# 1. SETUP & IMPORTS
# ==============================================================================
# !pip install -q python-binance pandas numpy statsmodels matplotlib

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

# Configuration
target_ticker = 'BTCEUR'          # Binance ticker for BTC-Euro (Target)
feature_ticker = 'BTCUSD'        # Binance ticker for BTC-Tether (Feature)
interval = '1s'                   # 1-second resolution (Binance '1s' requires specific endpoint, using '1m' as per original script's interval config, adjust to '1s' if utilizing Binance spot high-freq)
start_time = datetime.datetime(2025, 12, 9, 0, 0, 0) # Start timestamp
end_time = datetime.datetime(2025, 12, 11, 23, 59, 59) # End timestamp

rolling_window = 60  # Rolling window for intervals
max_lag = 60

print(f"--- High-Frequency Stat Arb Analysis: {target_ticker} vs {feature_ticker} ---")

# ==============================================================================
# 2. DATA ACQUISITION & ALIGNMENT
# ==============================================================================
print(f"\n[1/7] Fetching high-frequency data for {target_ticker} and {feature_ticker} from Binance...")

client = Client()

def fetch_binance_data(symbol, interval, start_ts, end_ts):
    """Helper function to fetch and format Binance Kline data."""
    print(f"      -> Downloading Klines for {symbol}...")
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
    df['Datetime'] = pd.to_datetime(df['Open_time'], unit='ms', utc=True)
    df = df.set_index('Datetime')
    df['Close'] = df['Close'].astype(float)
    return df[['Close']].sort_index()

# --- 2A. Fetch Target Data (BTC-EUR) ---
btc_df = fetch_binance_data(target_ticker, interval, start_time, end_time)
print(f"Fetched {len(btc_df)} data points for {target_ticker}.")

# --- 2B. Fetch Feature Data (BTC-USDT) ---
feature_df = fetch_binance_data(feature_ticker, interval, start_time, end_time)
feature_df = feature_df.rename(columns={'Close': 'Feature_Price'})
print(f"Fetched {len(feature_df)} data points for {feature_ticker}.")

# --- 2C. Time-Series Synchronization ---
print("\n[2/7] Aligning time series...")

# Since both are from Binance, they share the exact same UTC timestamps. 
# An inner join cleanly drops any intervals where one of the pairs might have missing data.
df = btc_df.join(feature_df, how='inner').dropna()

print(f"Data aligned successfully. Total synchronized data points: {len(df)}")

if df.empty:
    print("ERROR: No aligned data points available after merging. Check input time window and data feeds.")
    sys.exit(1)

# ==============================================================================
# 3. LEAD-LAG ANALYSIS (CROSS-CORRELATION)
# ==============================================================================
print("\n[3/7] Running Lead-Lag Analysis (Cross-Correlation)...")

df['Target_Returns'] = np.log(df['Close'] / df['Close'].shift(1))
df['Feature_Returns'] = np.log(df['Feature_Price'] / df['Feature_Price'].shift(1))
df_returns = df.dropna()

if df_returns.empty:
    print("ERROR: No valid returns rows after differencing; cannot compute lead-lag correlations.")
    sys.exit(1)

correlations = {}
for lag in range(-max_lag, max_lag + 1):
    shifted_feature = df_returns['Feature_Returns'].shift(lag)
    corr = df_returns['Target_Returns'].corr(shifted_feature)
    correlations[lag] = corr

valid_correlations = {lag: c for lag, c in correlations.items() if not pd.isna(c)}
if not valid_correlations:
    print("ERROR: Unable to compute any valid lag correlation (all values are NaN).")
    sys.exit(1)

best_lag = max(valid_correlations, key=lambda k: abs(valid_correlations[k]))
best_corr = valid_correlations[best_lag]
print(f"Highest correlation ({best_corr:.4f}) found at lag: {best_lag}")

if best_lag > 0:
    print(f"-> Conclusion: {feature_ticker} LEADS {target_ticker} by {best_lag} periods. (Highly useful)")
    print(f"   Aligning data: Shifting Feature forward by {best_lag} periods to prevent lookahead bias.")
    df['Feature_Price'] = df['Feature_Price'].shift(best_lag)
    df = df.dropna()
elif best_lag < 0:
    print(f"-> Conclusion: {target_ticker} LEADS {feature_ticker}. ({feature_ticker} is likely useless for predicting {target_ticker})")
else:
    print(f"-> Conclusion: Both assets move synchronously. (Useful for mean reversion, but latency execution is tough)")

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

adf_result = adfuller(df['Static_Spread'].dropna())
p_value = adf_result[1]

print(f"ADF Statistic: {adf_result[0]:.4f}")
print(f"ADF P-Value: {p_value:.6f}")

is_cointegrated = p_value < 0.05
if is_cointegrated:
    print(f"-> Conclusion: The spread IS stationary (Cointegrated). P-Value < 0.05.")
else:
    print(f"-> Conclusion: The spread is NOT stationary (Not Cointegrated). P-Value >= 0.05.")

# ==============================================================================
# 5. ADVANCED METRICS: HURST & HALF-LIFE
# ==============================================================================
print("\n[5/7] Calculating Hurst Exponent and Mean-Reversion Half-Life...")

def get_hurst_exponent(ts):
    lags = range(2, 20)
    tau = [np.sqrt(np.std(np.subtract(ts[lag:], ts[:-lag]))) for lag in lags]
    poly = np.polyfit(np.log(lags), np.log(tau), 1)
    return poly[0] * 2.0

def get_half_life(ts):
    ts_lag = ts.shift(1).dropna()
    ts_diff = ts.diff().dropna()
    X = sm.add_constant(ts_lag)
    Y = ts_diff
    res = sm.OLS(Y, X).fit()
    lam = res.params.iloc[1]
    return -np.log(2) / lam if lam < 0 else np.inf

hurst = get_hurst_exponent(df['Static_Spread'].values)
half_life = get_half_life(df['Static_Spread'])

print(f"-> Hurst Exponent: {hurst:.4f} (Target < 0.5 for mean reversion)")
print(f"-> Mean Reversion Half-Life: {half_life:.2f} periods")
if half_life > 10:
    print("   !!! WARNING: Half-life is long. Spread may not revert fast enough for 1-10s MFT engines.")

# ==============================================================================
# 6. ROLLING METRICS & SIGNAL GENERATION
# ==============================================================================
print("\n[6/7] Calculating Rolling Hedge Ratio (Beta) and Z-Scores...")

exog = sm.add_constant(df['Feature_Price'])
endog = df['Close']
rols = RollingOLS(endog, exog, window=rolling_window)
rres = rols.fit()

df['Rolling_Beta'] = rres.params['Feature_Price']
df['Dynamic_Spread'] = df['Close'] - (df['Rolling_Beta'] * df['Feature_Price'])

df['Spread_Mean'] = df['Dynamic_Spread'].rolling(window=rolling_window).mean()
df['Spread_Std'] = df['Dynamic_Spread'].rolling(window=rolling_window).std()
df['Z_Score'] = (df['Dynamic_Spread'] - df['Spread_Mean']) / df['Spread_Std']

df = df.dropna()

bullish_signals = len(df[df['Z_Score'] < -2.0])
bearish_signals = len(df[df['Z_Score'] > 2.0])
print(f"Identified {bullish_signals} bullish signals (Z < -2.0) and {bearish_signals} bearish signals (Z > 2.0).")

# ==============================================================================
# 7. FINAL VERDICT & VISUALIZATION
# ==============================================================================
print("\n[7/7] Final Verdict for Medium-Frequency Trading:")

if is_cointegrated and best_lag >= 0 and hurst < 0.5:
    print(f"✅ VERDICT: YES. {feature_ticker} is cointegrated, does not severely lag, and is mean-reverting. Viable statistical oracle.")
elif is_cointegrated and best_lag < 0:
    print(f"❌ VERDICT: NO. While cointegrated, {target_ticker} moves first. You cannot use {feature_ticker} to predict it.")
else:
    print(f"❌ VERDICT: NO. Assets lack strong stationary/mean-reverting properties. Spread will likely wander.")

print("\n[7/7] Generating Proof Diagrams...")

# Validation series plot for cleaned aligned ticks
fig_ts = plt.figure(figsize=(16, 4))
ax_ts = fig_ts.add_subplot(1, 1, 1)
ax_ts.plot(df.index, df['Close']/(df['Close'].sum()/len(df['Close'])), label=f'{target_ticker} Close', color='blue', linewidth=1)
ax_ts.plot(df.index, df['Feature_Price']/(df['Feature_Price'].sum()/len(df['Feature_Price'])), label=f'{feature_ticker} Price', color='orange', linewidth=1)
ax_ts.set_title('Pricing (Normalized)')
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

ax3 = plt.subplot(2, 1, 2)
ax3.plot(df.index, df['Z_Score'], color='black', linewidth=1)
ax3.axhline(2.0, color='red', linestyle='--', label='Short Spread (+2 / Overvalued)')
ax3.axhline(-2.0, color='green', linestyle='--', label='Long Spread (-2 / Undervalued)')
ax3.axhline(0, color='blue', alpha=0.5)
ax3.set_title(f'Rolling Z-Score of the Dynamic {target_ticker} / {feature_ticker} Spread')
ax3.set_ylabel('Z-Score')
ax3.legend(loc='upper right')
ax3.grid(True, alpha=0.3)

plt.tight_layout()
output_path = 'cointegration_report.png'
fig.savefig(output_path, dpi=150, bbox_inches='tight')
plt.close(fig)
print(f"Saved plot: {output_path}")