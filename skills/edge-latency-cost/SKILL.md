---
name: edge-latency-cost
description: MCP tool call latency decomposition benchmarking and historical token price/cost spike detection.
---

# ⚡ Edge Latency & Cost Tracker

## Overview
Decomposes tool execution latency (average, median, p90, p95, p99) and monitors runtime API price spikes and token budget consumption.

## Capabilities
- `mcp_latency_eval.py`: Benchmark round-trip turns across local/remote MCP servers.
- `price_tracker.py`: Track pricing history per SKU and trigger spike alerts.
