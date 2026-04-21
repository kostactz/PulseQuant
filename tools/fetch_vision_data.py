import argparse
import datetime
import urllib.request
import zipfile
import io
import os
import tempfile
import json
import csv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_binance_klines_as_ticks(symbol, start_date, end_date):
    """Fallback: Fetch 1s klines from Binance API and simulate ticks."""
    try:
        from binance.client import Client
    except ImportError as exc:
        raise ImportError(
            "python-binance is required for the Binance API fallback path. "
            "Install it with: pip install python-binance"
        ) from exc

    client = Client()
    print(f"Fallback: Fetching 1s klines for {symbol} via Binance API from {start_date} to {end_date}...")

    start_ts = datetime.datetime.combine(start_date, datetime.time.min)
    end_ts = datetime.datetime.combine(end_date, datetime.time.max)
    
    interval_seconds = 1
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
            '1s',
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
            except Exception as e:
                print(f"ERROR fetching chunk {ch[0]} - {ch[1]}: {e}")
                
    results.sort(key=lambda x: x[0])
    for r in results:
        if r[1]:
            klines.extend(r[1])

    events = []
    for row in klines:
        if not row: continue
        ts = int(row[0])
        close_price = float(row[4])
        bid = close_price * 0.9999
        ask = close_price * 1.0001
        events.append({
            'type': 'TICK',
            'data': {
                'symbol': symbol,
                'timestamp': ts,
                'bid': bid,
                'ask': ask
            }
        })
    print(f"Fetched {len(events)} simulated ticks from API for {symbol} from {start_date} to {end_date}.")
    return events

def parse_date(date_str):
    return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + datetime.timedelta(n)

def download_and_extract(url, cache_path):
    """Download a zip from *url*, extract the first file and save to *cache_path*.

    Writes are atomic: content is first written to a temporary file in the same
    directory, then atomically renamed to *cache_path*.  This prevents partially
    written files from poisoning the cache on network interruptions.
    """
    if os.path.exists(cache_path):
        print(f"Cache hit: {cache_path}")
        return True

    print(f"Downloading {url}...")
    cache_dir = os.path.dirname(cache_path) or '.'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            with zipfile.ZipFile(io.BytesIO(response.read())) as z:
                name = z.namelist()[0]
                with z.open(name) as f:
                    content = f.read()
        # Atomic write: temp file → rename
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as tmp_f:
                tmp_f.write(content)
            os.rename(tmp_path, cache_path)
        except Exception:
            os.unlink(tmp_path)
            raise
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"404 Not Found: {url}")
            return False
        else:
            print(f"HTTP Error {e.code}: {url}")
            return False
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return False

def parse_book_ticker_file(filepath, symbol, filter_date=None):
    events = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            # Find indices
            try:
                idx_bid = header.index("best_bid_price")
                idx_ask = header.index("best_ask_price")
                idx_time = header.index("transaction_time")
            except ValueError:
                # Some formats might differ
                idx_bid = 1
                idx_ask = 3
                idx_time = 5
            
            for row in reader:
                if not row: continue
                ts = int(row[idx_time])
                
                if filter_date:
                    ev_date = datetime.datetime.fromtimestamp(
                        ts / 1000.0,
                        tz=datetime.timezone.utc,
                    ).date()
                    if ev_date != filter_date:
                        continue

                bid = float(row[idx_bid])
                ask = float(row[idx_ask])
                events.append({
                    'type': 'TICK',
                    'data': {
                        'symbol': symbol,
                        'timestamp': ts,
                        'bid': bid,
                        'ask': ask
                    }
                })
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
    return events

def parse_agg_trades_file(filepath, symbol, filter_date=None):
    events = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            # Find indices
            try:
                idx_price = header.index("price")
                idx_time = header.index("transact_time")
            except ValueError:
                idx_price = 1
                idx_time = 5
                
            for row in reader:
                if not row: continue
                ts = int(row[idx_time])
                
                if filter_date:
                    ev_date = datetime.datetime.fromtimestamp(
                        ts / 1000.0,
                        tz=datetime.timezone.utc,
                    ).date()
                    if ev_date != filter_date:
                        continue

                price = float(row[idx_price])
                # We use the matched price for both bid and ask as proxy
                events.append({
                    'type': 'TICK',
                    'data': {
                        'symbol': symbol,
                        'timestamp': ts,
                        'bid': price,
                        'ask': price
                    }
                })
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
    return events

def parse_funding_rate_file(filepath, symbol, filter_date=None):
    events = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader)
            try:
                idx_time = header.index("calc_time")
                idx_rate = header.index("last_funding_rate")
            except ValueError:
                idx_time = 0
                idx_rate = 2
            
            for row in reader:
                if not row: continue
                ts = int(row[idx_time])
                
                if filter_date:
                    ev_date = datetime.datetime.fromtimestamp(
                        ts / 1000.0,
                        tz=datetime.timezone.utc,
                    ).date()
                    if ev_date != filter_date:
                        continue

                rate = float(row[idx_rate])
                events.append({
                    'type': 'FUNDING_RATE_UPDATE',
                    'data': {
                        'symbol': symbol,
                        'timestamp': ts,
                        'fundingRate': rate
                    }
                })
    except Exception as e:
        print(f"Error parsing {filepath}: {e}")
    return events

def get_vision_events(symbol, data_type, date_obj, missing_months, vision_lock, cache_dir):
    """
    data_type: 'bookTicker' or 'aggTrades' or 'fundingRate'
    Returns a list of parsed events, or None if completely missing.
    """
    date_str = date_obj.strftime("%Y-%m-%d")
    month_str = date_obj.strftime("%Y-%m")
    
    url = f"https://data.binance.vision/data/futures/um/daily/{data_type}/{symbol}/{symbol}-{data_type}-{date_str}.zip"
    cache_path = cache_dir / f"{symbol}-{data_type}-{date_str}.csv"
    
    url_m = f"https://data.binance.vision/data/futures/um/monthly/{data_type}/{symbol}/{symbol}-{data_type}-{month_str}.zip"
    cache_path_m = cache_dir / f"{symbol}-{data_type}-{month_str}.csv"

    skip = False
    use_monthly = False

    with vision_lock:
        if month_str in missing_months:
            skip = True
        elif cache_path_m.exists():
            use_monthly = True

    if skip:
        return None

    events = []
    parser_func = {
        'bookTicker': parse_book_ticker_file,
        'aggTrades': parse_agg_trades_file,
        'fundingRate': parse_funding_rate_file
    }[data_type]

    if use_monthly:
        print(f"Using cached monthly {data_type} for {symbol} {month_str} on {date_str}...")
        events = parser_func(cache_path_m, symbol, filter_date=date_obj)
        return events

    if download_and_extract(url, cache_path):
        print(f"Parsing {cache_path}...")
        return parser_func(cache_path, symbol)
    else:
        with vision_lock:
            if month_str in missing_months:
                skip = True
            elif cache_path_m.exists():
                use_monthly = True
            else:
                if download_and_extract(url_m, cache_path_m):
                    use_monthly = True
                else:
                    print(f"Both daily and monthly {data_type} archives 404'd for {symbol} on {date_str}.")
                    missing_months.add(month_str)
                    skip = True
        
        if skip:
            return None
        if use_monthly:
            print(f"Using cached monthly {data_type} for {symbol} {month_str} on {date_str}...")
            events = parser_func(cache_path_m, symbol, filter_date=date_obj)
            return events
    return None
def main():
    parser = argparse.ArgumentParser(
        description="Fetch Binance Vision Futures Data (bookTicker + fundingRate).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--symbols', nargs='+', required=True,
                        help='Symbols to fetch (e.g., ORDIUSDC SUIUSDC)')
    parser.add_argument('--start-date', required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='End date YYYY-MM-DD')
    parser.add_argument('--cache-dir', default='.cache/vision',
                        help='Directory to store unzipped CSVs')
    parser.add_argument('--output', default=None, help='Output .jsonl path')
    parser.add_argument('--include-aggtrades', action='store_true', default=False,
                        help='(Future) also fetch aggTrades for empirical slippage modelling')

    args = parser.parse_args()
    if args.include_aggtrades:
        print("[INFO] --include-aggtrades requested but not yet implemented; skipping.")

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    out_dir = Path("test/resources/captures")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if not args.output:
        out_name = f"{'_'.join(args.symbols)}_vision_{args.start_date}_{args.end_date}.jsonl"
        args.output = out_dir / out_name

    import threading
    all_events = []
    events_lock = threading.Lock()

    def process_symbol_date(symbol, single_date, missing_bt, missing_at, missing_fr, vision_lock):
        local_events = []
        
        # 1. Try bookTicker
        bt_events = get_vision_events(symbol, 'bookTicker', single_date, missing_bt, vision_lock, cache_dir)
        if bt_events is not None and len(bt_events) > 0:
            local_events.extend(bt_events)
        else:
            print(f"[{symbol} | {single_date}] bookTicker unavailable. Trying aggTrades...")
            # 2. Try aggTrades
            at_events = get_vision_events(symbol, 'aggTrades', single_date, missing_at, vision_lock, cache_dir)
            if at_events is not None and len(at_events) > 0:
                local_events.extend(at_events)
            else:
                print(f"[{symbol} | {single_date}] aggTrades unavailable. Falling back to Binance API (1s klines)...")
                # 3. Fallback to Binance API 1s Klines
                api_events = fetch_binance_klines_as_ticks(symbol, single_date, single_date)
                local_events.extend(api_events)

        # 4. Fetch fundingRate
        fr_events = get_vision_events(symbol, 'fundingRate', single_date, missing_fr, vision_lock, cache_dir)
        if fr_events is not None:
            local_events.extend(fr_events)

        return local_events

    for symbol in args.symbols:
        missing_vision_bt_months = set()
        missing_vision_at_months = set()
        missing_vision_fr_months = set()
        vision_lock = threading.Lock()

        tasks = list(daterange(start_date, end_date))
        
        print(f"Processing {len(tasks)} days for {symbol} in parallel...")
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_date = {executor.submit(process_symbol_date, symbol, d, missing_vision_bt_months, missing_vision_at_months, missing_vision_fr_months, vision_lock): d for d in tasks}
            for future in as_completed(future_to_date):
                single_date = future_to_date[future]
                try:
                    events = future.result()
                    with events_lock:
                        all_events.extend(events)
                except Exception as e:
                    print(f"Error processing {symbol} on {single_date}: {e}")

    print(f"Sorting {len(all_events)} events...")
    all_events.sort(key=lambda x: x['data']['timestamp'])

    # Atomic write for the output JSONL as well
    out_path = str(args.output)
    out_dir = os.path.dirname(out_path) or '.'
    print(f"Writing to {out_path}...")
    fd, tmp_out = tempfile.mkstemp(dir=out_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            for ev in all_events:
                f.write(json.dumps(ev) + '\n')
        os.rename(tmp_out, out_path)
    except Exception:
        if os.path.exists(tmp_out):
            os.unlink(tmp_out)
        raise

    print("Done!")

if __name__ == '__main__':
    main()
