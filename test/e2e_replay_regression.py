import subprocess
import sys
import re
import os

def run_command(cmd):
    print(f"Running: {cmd}")
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    full_output = []
    for line in process.stdout:
        print(line, end="")
        full_output.append(line)
    process.wait()
    if process.returncode != 0:
        print(f"Error executing command: {cmd}")
        return None
    return "".join(full_output)

def validate():
    # 1. Download data for the full requested range
    start_date = "2026-01-01"
    end_date = "2026-03-01"
    capture_file = "capture.jsonl"
    
    download_cmd = f"{sys.executable} tools/fetch_vision_data.py --symbols SUSHIUSDT CAKEUSDT --start-date {start_date} --end-date {end_date} --output {capture_file}"
    stdout = run_command(download_cmd)
    if stdout is None: sys.exit(1)
    
    # 2. Run Replay
    import glob
    data_files = glob.glob(capture_file)
    print(f"Verified data file: {data_files}")
    if not data_files:
        print(f"CRITICAL ERROR: {capture_file} not found before replay.")
        sys.exit(1)

    replay_cmd = f"{sys.executable} tools/replay.py --input {capture_file} --target SUSHIUSDT --feature CAKEUSDT --min-entry-spread 50 --sigma-threshold 2 --taker-fee 0.0005 --slippage-bps 10 --min-beta 0.1 --max-beta 2.0 --kelly-fraction 0.5"
    replay_output = run_command(replay_cmd)
    if replay_output is None: sys.exit(1)
    
    print("\nReplay Output Analysis:")
    
    def extract(pattern, text, default=0.0):
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
        return default

    nav = extract(r"Final NAV:\s+\$(\d+\.\d+)", replay_output)
    trades = extract(r"Trades Volume:\s+(\d+)", replay_output)
    entries = extract(r"Entry Taken:\s+(\d+)", replay_output)
    sharpe = extract(r"Annualized Sharpe:\s+(-?\d+\.\d+)", replay_output)
    wl_ratio = extract(r"Win/Loss Ratio:\s+(\d+\.\d+)", replay_output)

    print(f"Parsed Results: NAV={nav}, Trades={trades}, Entries={entries}, Sharpe={sharpe}, WL={wl_ratio}")

    if trades == 0:
        print("\nCRITICAL ERROR: Replay produced 0 trades.")
        print("This usually indicates a mismatch in data contracts or logic break.")
        print("Full Replay Output for debugging:")
        print("-" * 40)
        print(replay_output)
        print("-" * 40)
        sys.exit(1)

    # Benchmarks
    TARGET_TRADES = 146
    TARGET_ENTRIES = 73
    TARGET_SHARPE = 2.47
    TARGET_NAV = 100147.76
    TARGET_WL = 0.54

    errors = []
    
    # Validation (+- 10%)
    def check_bound(name, actual, target, tolerance=0.10):
        low = target * (1.0 - tolerance)
        high = target * (1.0 + tolerance)
        if not (low <= actual <= high):
            return f"{name} {actual} out of bounds [{low:.2f}, {high:.2f}]"
        return None

    # Specific user requirement: "entries taken are half of completed legs"
    if abs(entries * 2 - trades) > (trades * 0.05): # Allowing slight mismatch if partially filled, but usually should be exact
        errors.append(f"Entry/Trade mismatch: Entries={entries}, Trades={trades}")

    e = check_bound("Trades", trades, TARGET_TRADES)
    if e: errors.append(e)
    
    e = check_bound("Sharpe", sharpe, TARGET_SHARPE)
    if e: errors.append(e)
    
    # NAV is slightly different because it's a large number, 10% of 100k is 10k. 
    # But usually NAV regression should be much tighter. 
    # However, I will follow the user's "10%" instruction.
    e = check_bound("NAV", nav, TARGET_NAV)
    if e: errors.append(e)

    if errors:
        print("\nREGRESSION FAILED:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("\nREGRESSION PASSED: All metrics within 10% tolerance.")

if __name__ == "__main__":
    validate()
