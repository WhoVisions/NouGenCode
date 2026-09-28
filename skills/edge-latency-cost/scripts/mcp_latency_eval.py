import time
import statistics
import sys
import os

# Add current dir to path to import yukiai_bridge correctly
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from yukiai_bridge import BRIDGE

NUM_TURNS = 100

def benchmark_bridge_turn(turn_id):
    start_time = time.perf_counter()
    errors = 0
    
    try:
        # Simulate Vision Telemetry Read
        vision = BRIDGE.get_latest_vision()
        if vision.startswith("Optics fault"):
            errors += 1
            
        # Simulate FTS5 Memory Recall
        mem = BRIDGE.query_memory(f"test_query_{turn_id}")
        if mem.startswith("Memory fault"):
            errors += 1
            
    except Exception as e:
        errors += 1

    end_time = time.perf_counter()
    return (end_time - start_time) * 1000, errors

def run_evaluation():
    print(f"[NodeWorker TACTICAL] Initiating {NUM_TURNS}-turn local I/O and Memory latency benchmark...")
    latencies = []
    total_errors = 0
    
    for i in range(1, NUM_TURNS + 1):
        lat, errors = benchmark_bridge_turn(i)
        latencies.append(lat)
        total_errors += errors
        if i % 10 == 0 or i == 1:
            print(f"  [Turn {i:03d}] Latency: {lat:.2f} ms")

    latencies.sort()
    avg_lat = statistics.mean(latencies)
    median_lat = statistics.median(latencies)
    p90 = latencies[int(NUM_TURNS * 0.90)]
    p95 = latencies[int(NUM_TURNS * 0.95)]
    p99 = latencies[int(NUM_TURNS * 0.99) - 1]
    worst = latencies[-1]
    
    print("=== Latency Decomposition (100 Turns) ===")
    print(f"Average: {avg_lat:.2f} ms")
    print(f"Median:  {median_lat:.2f} ms")
    print(f"p90:     {p90:.2f} ms")
    print(f"p95:     {p95:.2f} ms")
    print(f"p99:     {p99:.2f} ms")
    print(f"Max:     {worst:.2f} ms")
    print(f"Errors:  {total_errors}")
    
    anomalies = [l for l in latencies if l > (median_lat * 2)]
    print(f"\nElevations Detected (>2x median): {len(anomalies)} turns ({(len(anomalies)/NUM_TURNS)*100:.2f}%)")

if __name__ == "__main__":
    run_evaluation()
