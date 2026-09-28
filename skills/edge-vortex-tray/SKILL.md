---
name: edge-vortex-tray
description: Native OS system tray controller for monitoring background AI processes, model VRAM flushes, and service health.
---

# ⚡ Edge Vortex System Tray Controller

## Overview
Provides a native desktop system tray controller (using `pystray`) to monitor local AI background processes, check node status, and trigger atomic VRAM flushes (`keep_alive=0` against resident models).

## Features
- Background process polling with zero UI latency
- Single-instance mutex lock
- Instant VRAM unload trigger for local LLMs
