import os
import requests
import json
import re

TRANSCRIPT_PATH = r"./logs/transcript.log"
MESH_URL = "http://localhost:8765/memory/store"

def sync():
    if not os.path.exists(TRANSCRIPT_PATH):
        print(f"Transcript not found: {TRANSCRIPT_PATH}")
        return

    with open(TRANSCRIPT_PATH, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract the last turn or meaningful chunks
    # For now, we'll post the whole recent activity as a 'mesh_sync' shard
    payload = {
        "category": "project",
        "source": "antigravity_core",
        "finding": "Mesh Transcript Sync",
        "logic": content[-2000:], # Last 2000 chars for context
        "tags": "#transcript #mesh #sync"
    }

    try:
        response = requests.post(MESH_URL, json=payload, timeout=5)
        if response.status_code == 200:
            print("Successfully posted transcript to local_mesh_service.")
        else:
            print(f"Failed to post: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Mesh service not available: {e}. Falling back to direct sharding...")
        # Fallback to direct shard insertion if available
        try:
            from persistence.memory_guard import add_shard_guarded
            add_shard_guarded(
                title="Mesh Transcript Sync [Direct]",
                content=content[-2000:],
                source="antigravity_fallback",
                shard_type="project"
            )
            print("Direct sharding complete.")
        except ImportError:
            print("Direct sharding fallback failed (import error).")

if __name__ == "__main__":
    sync()
