import asyncio
import os
import sys

# Set env for local running
os.environ["GOOGLE_CLOUD_PROJECT"] = "gen-lang-client-0939852539" # NodeWorker project

from NodeWorker.services.wispr import WisprService
from NodeWorker.services.memory import MemoryService
# prompt_service is no longer needed for memory bank ingestion

async def process_transcript(sem, transcript, current, total, memory_service):
    """
    Process a single transcript using MemoryService.
    """
    async with sem:
        try:
            # Format content
            text = transcript.get('formattedText') or transcript.get('asrText')
            timestamp = transcript.get('timestamp')
            
            if not text or len(str(text)) < 10:
                print(f"[{current}/{total}] Skipping (too short) - {timestamp}")
                return

            # Insert into Memory Bank Session (creates Event)
            # We don't extract facts manually anymore; Memory Bank does it.
            context = f"Transcription from {timestamp}: {text}"
            memory_service.insert(content=context, role="user")
            
            # Simple log, stripped to 50 chars
            snippet = str(text)[:50].replace('\n', ' ')
            print(f"[{current}/{total}] Added event: {snippet}...")
            
        except Exception as e:
            print(f"[{current}/{total}] Error: {e}")

async def main():
    print(f"[*] Initializing Memory Service (Vertex AI)...")
    try:
        memory_service = MemoryService()
    except Exception as e:
        print(f"[!] Critical: Failed to init MemoryService: {e}")
        return
    
    # Connect to DB
    print(f"[*] Reading Wispr DB...")
    wispr = WisprService()
    transcripts = wispr.get_all_transcripts()
    
    # Use a semaphore to limit concurrent inserts (API rate limits)
    sem = asyncio.Semaphore(10)
    
    total = len(transcripts)
    print(f"[*] Found {total} transcripts. Starting smart ingestion to Memory Bank...")

    tasks = []
    for i, t in enumerate(transcripts):
        tasks.append(process_transcript(sem, t, i+1, total, memory_service))
        
    await asyncio.gather(*tasks)
    
    print("[*] All events added. Triggering consolidation (background generation)...")
    memory_service.consolidate()
    print("[*] Consolidation triggered. Memories will generate in the background.")

if __name__ == "__main__":
    asyncio.run(main())
