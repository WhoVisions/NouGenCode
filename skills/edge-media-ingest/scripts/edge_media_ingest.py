import os
import sys
import time
import json
import argparse
from pathlib import Path
from typing import List, Dict, Optional

# Add project root to path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from EdgeNode.services.notion import NotionService, retry_with_backoff
from EdgeNode.story.docs_export import get_file_link # Although we use it for local docs, keeping for parity
from google import genai
from google.genai import types
from EdgeNode.core.config import PROJECT_ID

# Direct import of helper from ingest_youtube if possible, else we redefine
try:
    from tools.ingest_youtube import run_ytdlp, get_transcript, summarize_lore
except ImportError:
    # Fallback/Redefine if needed (simpler to keep it self-contained for critical ingestion)
    import subprocess
    def run_ytdlp(args: List[str], timeout: int = 120) -> Optional[str]:
        try:
            cmd = ["yt-dlp"] + args
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.stdout if result.returncode == 0 else None
        except: return None

    # (Simplified versions for brevity, but let's try to use the ones from ingest_youtube)
    # Actually, let's just use the ones from ingest_youtube to maintain chunking/parsing logic.
    pass

# Initialize Notion with Backoff
notion = NotionService()

# Ingestion Database ID from config
INGESTION_DB_ID = "2d90b4b4-0f65-8001-98fe-cbf8a4a2146a"

@retry_with_backoff(initial_delay=15.0)
def push_to_studio_vault(video: Dict, transcript: str, ai_summary: str):
    """Specific pusher for StudioBinder Masterclass."""
    print(f"   📤 Vaulting: {video['title'][:50]}...")
    
    # Notion limit: 2000 characters per block
    chunk_size = 1900 
    blocks = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "icon": {"emoji": "🎬"},
                "rich_text": [{"text": {"content": f"StudioBinder Masterclass: {video['url']}"}}]
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "🧠 Masterclass Summary"}}]
            }
        },
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"text": {"content": ai_summary[:2000]}}]
            }
        },
        {
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "📜 Transcript Highlights"}}]
            }
        }
    ]

    # Add transcript chunks (up to a reasonable limit for Notion pages, e.g., 50 chunks)
    for i in range(0, min(len(transcript), 100000), chunk_size):
        chunk = transcript[i:i + chunk_size]
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"text": {"content": chunk}}]
            }
        })

    properties = {
        "Name": {"title": [{"text": {"content": f"[MASTERCLASS] {video['title']}"[:100]}}]},
        "Status": {"status": {"name": "Active"}},
        "Source URL": {"url": video["url"]}
    }

    try:
        # Create page in Ingestion Queue
        res = notion.client.pages.create(
            parent={"database_id": INGESTION_DB_ID},
            properties=properties,
            children=blocks[:100] # Notion limit is 100 children per create call
        )
        
        # If more blocks, append them
        if len(blocks) > 100:
            page_id = res["id"]
            for i in range(100, len(blocks), 100):
                notion.client.blocks.children.append(
                    block_id=page_id,
                    children=blocks[i:i+100]
                )
        
        print(f"   ✅ Vaulted: {video['title'][:40]}")
        return True
    except Exception as e:
        print(f"   ❌ Vault error: {e}")
        raise e 

def get_existing_urls():
    print("   🔍 Checking for existing videos...")
    existing = set()
    has_more = True
    start_cursor = None
    
    while has_more:
        try:
            body = {"page_size": 100}
            if start_cursor:
                body["start_cursor"] = start_cursor
                
            resp = notion.client.request(
                path=f"databases/{INGESTION_DB_ID}/query",
                method="POST",
                body=body
            )
            
            for page in resp.get("results", []):
                url = page.get("properties", {}).get("Source URL", {}).get("url")
                if url:
                    existing.add(url)
                    
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")
        except Exception as e:
            # Fallback for old client or permission issues
             print(f"   ⚠️ Could not fetch existing URLs (skipping check): {e}")
             return set()
            
    print(f"   ✅ Found {len(existing)} existing videos.")
    return existing

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--links", default="lore/studiobinder_links.txt")
    parser.add_argument("--channel", type=str, help="YouTube channel handle (e.g., @StudioBinder)")
    parser.add_argument("--video", type=str, help="Single video URL")
    parser.add_argument("--limit", type=int, default=250)
    args = parser.parse_args()

    # We need the functions from ingest_youtube
    from tools.ingest_youtube import run_ytdlp, get_transcript, summarize_lore, get_channel_videos

    links = []
    if args.video:
        links = [args.video]
    elif args.channel:
        print(f"📺 Fetching videos from channel: {args.channel}")
        
        # Try native Google API first
        try:
            from EdgeNode.services.google_workspace import GoogleWorkspaceService
            workspace = GoogleWorkspaceService()
            videos_data = workspace.list_channel_videos(args.channel, max_results=args.limit)
            if videos_data:
                print(f"   ✅ [API] Found {len(videos_data)} videos")
                links = [v["url"] for v in videos_data]
        except Exception as e:
            print(f"   ⚠️ Google API listing failed: {e}")
        
        # Fallback to yt-dlp
        if not links:
            print(f"   🔄 Falling back to yt-dlp for listing...")
            videos_data = get_channel_videos(args.channel, limit=args.limit)
            links = [v["url"] for v in videos_data]
    else:
        links_path = Path(args.links)
        if links_path.exists():
            links = [line.strip() for line in links_path.read_text().split("\n") if line.strip()]
        else:
            print(f"File not found: {links_path}")
            return

    links = links[:args.limit]

    print(f"🚀 Starting StudioBinder Ingestion ({len(links)} videos)")
    
    existing_urls = get_existing_urls()
    
    success = 0
    for i, url in enumerate(links, 1):
        if url in existing_urls:
            print(f"   ⏭️ Skipping duplicate: {url}")
            continue

        print(f"\n[{i}/{len(links)}] Processing: {url}")
        
        try:
            # 1. Get info
            output = run_ytdlp(["--dump-json", "--no-playlist", url], timeout=30)
            if not output: continue
            data = json.loads(output)
            video = {
                "id": data.get("id"),
                "title": data.get("title", "Untitled"),
                "url": url
            }

            # 2. Get transcript
            transcript = get_transcript(video["id"], video["title"])
            if not transcript: continue

            # 3. AI Summary (15s backoff handled in Gemini calls if wrapped, or just here)
            # For now, let's assume Gemini is stable, but we should add backoff to summarize_lore too if it hit 429
            ai_summary = summarize_lore(transcript, video["title"])

            # 4. Push to Notion with 15s Backoff
            if push_to_studio_vault(video, transcript, ai_summary):
                success += 1
            
            # Artificial delay between videos to avoid hitting heavy limits too fast
            time.sleep(2)

        except Exception as e:
            print(f"   ⚠️ Failed {url}: {e}")
            continue

    print(f"\n🎉 Ingestion Complete: {success}/{len(links)} successfully vaulted.")

if __name__ == "__main__":
    main()
