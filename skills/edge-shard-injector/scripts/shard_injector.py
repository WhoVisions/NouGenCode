import sqlite3
import os
import json
import glob
from datetime import datetime, timedelta
from pathlib import Path

# CONFIG
DB_PATH = r"./data/memory.db"
BRAIN_DIR = r"C:\Users\super\.gemini\antigravity\brain"
TMP_CHAT_DIR = r"C:\Users\super\.gemini\tmp\super\chats"

class ShardInjector:
    def __init__(self, dry_run=True, limit=None):
        print(f"[*] Connecting to {DB_PATH}...")
        self.conn = sqlite3.connect(DB_PATH, timeout=30)
        self.cursor = self.conn.cursor()
        self.dry_run = dry_run
        self.limit = limit
        self.missing_ids = []

    def get_existing_shard_ids(self):
        print("[*] Fetching existing shard IDs...")
        try:
            self.cursor.execute("SELECT id FROM shards")
            ids = {row[0] for row in self.cursor.fetchall()}
            print(f"[*] Found {len(ids)} existing shards.")
            return ids
        except Exception as e:
            print(f"[!] Error reading existing shards: {e}")
            return set()

    def scan_brain(self, days=30):
        print(f"[*] Scanning brain directory for last {days} days...")
        existing = self.get_existing_shard_ids()
        cutoff = datetime.now() - timedelta(days=days)
        
        if not os.path.exists(BRAIN_DIR):
            print(f"[!] Brain directory not found: {BRAIN_DIR}")
            return

        for folder in os.listdir(BRAIN_DIR):
            folder_path = os.path.join(BRAIN_DIR, folder)
            if not os.path.isdir(folder_path):
                continue
            
            if len(folder) < 30:
                continue
                
            mtime = datetime.fromtimestamp(os.path.getmtime(folder_path))
            if mtime < cutoff:
                continue
            
            if folder not in existing:
                self.missing_ids.append({
                    "id": folder,
                    "source": "brain",
                    "path": folder_path,
                    "created_at": mtime.strftime("%Y-%m-%d %H:%M:%S")
                })

    def scan_tmp(self):
        print("[*] Scanning tmp chat directory...")
        existing = self.get_existing_shard_ids()
        if not os.path.exists(TMP_CHAT_DIR):
            print(f"[!] Tmp chat directory not found: {TMP_CHAT_DIR}")
            return

        logs = glob.glob(os.path.join(TMP_CHAT_DIR, "session-*.json"))
        
        for log_path in logs:
            session_id = os.path.basename(log_path).replace(".json", "")
            if session_id not in existing:
                mtime = datetime.fromtimestamp(os.path.getmtime(log_path))
                self.missing_ids.append({
                    "id": session_id,
                    "source": "tmp",
                    "path": log_path,
                    "created_at": mtime.strftime("%Y-%m-%d %H:%M:%S")
                })

    def inject_missing(self):
        self.missing_ids.sort(key=lambda x: x['created_at'], reverse=True)
        
        if self.limit:
            self.missing_ids = self.missing_ids[:self.limit]

        print(f"[*] Processing {len(self.missing_ids)} shards.")
        
        count = 0
        for item in self.missing_ids:
            title = f"Archived Session: {item['id'][:8]}"
            content = f"Raw source: {item['path']}\nInjected by ShardInjector on {datetime.now().isoformat()}"
            category = "TELEMETRY"
            
            if item['source'] == 'brain':
                overview_path = os.path.join(item['path'], ".system_generated", "logs", "overview.txt")
                if os.path.exists(overview_path):
                    try:
                        with open(overview_path, 'r', encoding='utf-8') as f:
                            lines = f.readlines()
                            if lines:
                                content = "".join(lines[:50])
                                for line in lines:
                                    if line.startswith('{'):
                                        try:
                                            step = json.loads(line)
                                            if step.get('type') == 'USER_INPUT':
                                                title = f"Session {item['id'][:8]} (Start: {step.get('created_at')})"
                                                break
                                        except:
                                            continue
                    except Exception as e:
                        print(f"[!] Error reading overview for {item['id']}: {e}")

            if self.dry_run:
                print(f"[DRY RUN] Would inject: {item['id']} | {title}")
                continue

            try:
                print(f"[*] Injecting {item['id']}...")
                self.cursor.execute("""
                    INSERT INTO shards (id, category, title, content, source, tags, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (item['id'], category, title, content, item['source'], "log,injected", "{}", item['created_at']))
                count += 1
                if count % 10 == 0:
                    self.conn.commit()
                    print(f"[*] Committed {count} shards...")
            except Exception as e:
                print(f"[!] Injection failed for {item['id']}: {e}")

        if not self.dry_run:
            self.conn.commit()
            print(f"[*] Injection complete. {count} shards added.")

if __name__ == "__main__":
    import sys
    args = sys.argv
    dry = "--run" not in args
    limit_val = None
    if "--limit" in args:
        try:
            limit_val = int(args[args.index("--limit") + 1])
        except:
            pass
            
    injector = ShardInjector(dry_run=dry, limit=limit_val)
    injector.scan_brain()
    injector.scan_tmp()
    injector.inject_missing()
