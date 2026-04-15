import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.stattools import coint
import math

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
        ts_1m = ts.resample('1min').last().dropna()
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
    has_minute_freq = hasattr(ts_1m.index, 'freq') and isinstance(getattr(ts_1m.index, 'freq', None), pd.offsets.Minute)
    if has_minute_freq or (len(ts_1m) != len(ts)):
        hl_periods = hl_periods * (resampled_sec / original_sec)
    return hl_periods

def calculate_rolling_metrics(df_in, window_size, delta=1e-5, r_var=1e-3):
    df_calc = df_in.copy()
    if 'Log_Close' not in df_calc:
        df_calc['Log_Close'] = np.log(df_calc['Close'])
    if 'Log_Feature' not in df_calc:
        df_calc['Log_Feature'] = np.log(df_calc['Feature_Price'])
    
    y = df_calc['Log_Close'].values
    x = df_calc['Log_Feature'].values
    n = len(y)
    
    beta = np.zeros(n)
    alpha = np.zeros(n)
    
    if n > 0:
        burn_in = min(n, max(100, window_size if isinstance(window_size, int) else 100))
        if burn_in > 5:
            try:
                X_burn = sm.add_constant(x[:burn_in])
                y_burn = y[:burn_in]
                res = sm.OLS(y_burn, X_burn).fit()
                state0 = res.params[0]
                state1 = res.params[1] if len(res.params) > 1 else 0.0
            except Exception:
                state0 = y[0]
                state1 = 0.0
        else:
            state0 = y[0]
            state1 = 0.0
            
        p00 = 1.0; p01 = 0.0; p10 = 0.0; p11 = 1.0
        
        for i in range(n):
            p00 += delta
            p11 += delta
            
            xi = x[i]
            yi = y[i]
            
            y_pred = state0 + state1 * xi
            e = yi - y_pred
            
            S = (p00 + p01*xi) + xi*(p10 + p11*xi) + r_var
            
            k0 = (p00 + p01*xi) / S
            k1 = (p10 + p11*xi) / S
            
            state0 += k0 * e
            state1 += k1 * e
            
            new_p00 = p00 - k0 * (p00 + xi*p10)
            new_p01 = p01 - k0 * (p01 + xi*p11)
            new_p10 = p10 - k1 * (p00 + xi*p10)
            new_p11 = p11 - k1 * (p01 + xi*p11)
            
            p00, p01, p10, p11 = new_p00, new_p01, new_p10, new_p11
            
            alpha[i] = state0
            beta[i] = state1

    df_calc['Rolling_Beta'] = beta
    df_calc['Rolling_Alpha'] = alpha
    
    df_calc['Dynamic_Spread'] = (df_calc['Log_Close'] - 
                                 (df_calc['Rolling_Beta'].shift(1) * df_calc['Log_Feature']) - 
                                 df_calc['Rolling_Alpha'].shift(1))
    
    # df_calc['Spread_Mean'] = df_calc['Dynamic_Spread'].rolling(window=window_size).mean() # Removed to prevent double filtering
    df_calc['Spread_Std'] = df_calc['Dynamic_Spread'].rolling(window=window_size).std()
    
    df_calc['Z_Score'] = df_calc['Dynamic_Spread'] / (df_calc['Spread_Std'] + 1e-10)
    return df_calc

def optimize_parameters(df_in, half_life_periods, interval, args_rolling_window='auto', args_sigma_threshold='auto', taker_fee=0.05, verbose=False):
    # ANSI terminal colors
    RESET = '\033[0m'
    YELLOW = '\033[93m'
    GREEN = '\033[92m'
    def color_text(text, color):
        return f"{color}{text}{RESET}"

    print(f"\n[Opt] Starting Walk-Forward Optimization for Rolling Window & Sigma Threshold...")
    print(f"      Baseline Half-Life: {half_life_periods:.2f} periods")
    
    if np.isinf(half_life_periods) or np.isnan(half_life_periods) or half_life_periods <= 0:
        print(color_text("      -> Half-Life is invalid. Falling back to default window of 800.", YELLOW))
        half_life_periods = 800
    elif half_life_periods > 10000:
        print(color_text(f"      -> Half-Life ({half_life_periods:.2f}) exceeds cap (10,000). Capping to prevent window expansion issues.", YELLOW))
        half_life_periods = 10000

    if str(args_rolling_window).lower() == 'auto':
        start_val = max(50, int(1 * half_life_periods))
        end_val = max(100, int(20 * half_life_periods))
        raw_candidates = np.geomspace(start_val, end_val, num=10)
        candidate_windows = sorted(list(set([int(round(x)) for x in raw_candidates])))
    else:
        candidate_windows = [int(args_rolling_window)]
        
    if str(args_sigma_threshold).lower() == 'auto':
        candidate_thresholds = list(np.arange(1.5, 6.5, 0.5))
    else:
        candidate_thresholds = [float(args_sigma_threshold)]
    
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
    taker_pct = taker_fee / 100.0
    
    for w in candidate_windows:
        if verbose:
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
                    ret_target = np.log(targets[i] / targets[i-1]) if targets[i-1] > 0 and targets[i] > 0 else 0.0
                    ret_feature = np.log(features[i] / features[i-1]) if features[i-1] > 0 and features[i] > 0 else 0.0
                    
                    gross_spread_return = (ret_target - betas[i] * ret_feature) / (1.0 + abs(betas[i])) if (1.0 + abs(betas[i])) > 0 else 0.0
                    
                    prev_pos = pos

                    if pos == 0:
                        if z[i-1] < -thr: pos = 1
                        elif z[i-1] > thr: pos = -1
                    elif pos == 1 and z[i-1] >= 0: pos = 0
                    elif pos == -1 and z[i-1] <= 0: pos = 0
                    
                    turnover = abs(pos - prev_pos)
                    fee = turnover * taker_pct
                    spread_returns[i] = (pos * gross_spread_return) - fee
                    
                all_spread_returns.extend(spread_returns)
                
                cum_returns = np.cumsum(spread_returns)
                peak = np.maximum.accumulate(cum_returns)
                drawdown = peak - cum_returns
                all_mdds.append(np.max(drawdown))
                
                try:
                    pval = coint(np.log(test_calc['Close']), np.log(test_calc['Feature_Price']))[1]
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
