---
name: edge-voice-watcher
description: Speech-to-text transcript SQLite monitoring, wake word detection, and dynamic audio voice cloning.
---

# ⚡ Edge Voice Watcher & Speech Stream

## Overview
Monitors local speech-to-text SQLite database streams with zero-locking read-only URIs, detects wake words, and provides sample trimming for audio voice cloning.

## Included Modules
- `voice_watcher.py`: Real-time ASR stream watcher with wake word parser.
- `clone_voice.py`: Video/audio extraction and audio resampling (24kHz) for voice reference matching.
