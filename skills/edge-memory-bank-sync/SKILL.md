---
name: edge-memory-bank-sync
description: Asynchronous semaphore-throttled batch ingestion of speech transcripts and logs into durable memory banks.
---

# ⚡ Edge Memory Bank Ingester

## Overview
Reads local SQLite transcript queues and streams them into memory banks with rate-limiting semaphores (e.g. max 10 concurrent async operations).
