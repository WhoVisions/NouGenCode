import os
import json
import glob
from datetime import datetime, timedelta

BRAIN_DIR = r"C:\Users\super\.gemini\antigravity\brain"
SHARDS_DIR = r"C:\Users\super\Outpost\Yuki-Ai\persistence\shards"

def export_sessions(limit=None):
    if not os.path.exists(SHARDS_DIR):
        os.makedirs(SHARDS_DIR)
        
    folders = [f for f in os.listdir(BRAIN_DIR) if os.path.isdir(os.path.join(BRAIN_DIR, f)) and len(f) > 30]
    
    # Heuristic titles for current context sessions
    titles = {
        "d19030c6-658b-4031-ac3c-0e8cc937ab0b": "Orchestrating Autonomous AI Persistence",
        "3d9c7921-2a03-4c91-987a-624249a563cc": "Fleet Upgrade & Shard Persistence Investigation",
        "31693874-9f26-4d22-959c-6a4221a603cc": "Cortex and MemPalace Integration Pass",
        "5b01f52c-c734-4269-b7f8-1332848eb8ac": "Restoring In-Flight Persistence & Shard Injection"
    }

    count = 0
    for folder in folders:
        if limit and count >= limit:
            break
            
        folder_path = os.path.join(BRAIN_DIR, folder)
        mtime = datetime.fromtimestamp(os.path.getmtime(folder_path)).strftime("%Y-%m-%d %H:%M:%S")
        
        # Check if already exported (basic check)
        target_path = os.path.join(SHARDS_DIR, f"session_{folder[:8]}.json")
        if os.path.exists(target_path):
            continue
            
        title = titles.get(folder, f"Archived Session {folder[:8]}")
        content = f"Archive of session {folder}.\nLocation: {folder_path}\n"
        
        # Try to pull some context from overview.txt
        overview_path = os.path.join(folder_path, ".system_generated", "logs", "overview.txt")
        if os.path.exists(overview_path):
            try:
                with open(overview_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        # Add metadata about steps
                        content += f"Step Count: {len(lines)}\n\n"
                        content += "--- Log Tail ---\n"
                        content += "".join(lines[-20:]) # Last 20 steps
            except:
                pass
        
        shard = {
            "id": folder,
            "title": title,
            "content": content,
            "category": "TELEMETRY",
            "source": "brain",
            "tags": ["session", "injected", "archive"],
            "created_at": mtime
        }
        
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(shard, f, indent=2)
            
        print(f"[*] Exported {folder[:8]} to shards directory.")
        count += 1

if __name__ == "__main__":
    import sys
    limit_val = None
    if "--limit" in sys.argv:
        try:
            limit_val = int(sys.argv[sys.argv.index("--limit") + 1])
        except:
            pass
    export_sessions(limit=limit_val)
