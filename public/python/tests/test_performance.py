import pytest
from public.python.engine import process_events, clear_data, set_auto_trade

def test_throughput_performance(benchmark, mock_tick_data):
    # Setup state
    clear_data()
    set_auto_trade(True)
    
    # Pre-generate a large dataset to isolate benchmarking purely to the engine logic
    # We use 10,000 ticks for a robust performance gauge. Adjust up/down based on hardware.
    data = mock_tick_data(10000, trend='chop')
    
    # Run benchmark
    def run_engine():
        process_events(data)
        
    benchmark(run_engine)
    
    # Cleanup
    clear_data()
