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

def parse_book_ticker_file(filepath, symbol):
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

def parse_funding_rate_file(filepath, symbol):
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

    all_events = []

    for symbol in args.symbols:
        for single_date in daterange(start_date, end_date):
            date_str = single_date.strftime("%Y-%m-%d")
            
            # bookTicker Daily
            bt_url = f"https://data.binance.vision/data/futures/um/daily/bookTicker/{symbol}/{symbol}-bookTicker-{date_str}.zip"
            bt_cache_path = cache_dir / f"{symbol}-bookTicker-{date_str}.csv"
            
            if download_and_extract(bt_url, bt_cache_path):
                print(f"Parsing {bt_cache_path}...")
                bt_events = parse_book_ticker_file(bt_cache_path, symbol)
                all_events.extend(bt_events)

            # Note: fundingRate is often monthly in vision, sometimes daily. Let's try daily first.
            fr_url = f"https://data.binance.vision/data/futures/um/daily/fundingRate/{symbol}/{symbol}-fundingRate-{date_str}.zip"
            fr_cache_path = cache_dir / f"{symbol}-fundingRate-{date_str}.csv"
            
            if download_and_extract(fr_url, fr_cache_path):
                print(f"Parsing {fr_cache_path}...")
                fr_events = parse_funding_rate_file(fr_cache_path, symbol)
                all_events.extend(fr_events)
            else:
                # Try monthly if daily 404s
                month_str = single_date.strftime("%Y-%m")
                fr_url_m = f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month_str}.zip"
                fr_cache_path_m = cache_dir / f"{symbol}-fundingRate-{month_str}.csv"
                if download_and_extract(fr_url_m, fr_cache_path_m):
                    print(f"Parsing {fr_cache_path_m}...")
                    fr_events_all = parse_funding_rate_file(fr_cache_path_m, symbol)
                    # Filter to this date
                    for ev in fr_events_all:
                        ev_date = datetime.datetime.fromtimestamp(
                            ev['data']['timestamp'] / 1000.0,
                            tz=datetime.timezone.utc,
                        ).date()
                        if ev_date == single_date:
                            all_events.append(ev)

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
