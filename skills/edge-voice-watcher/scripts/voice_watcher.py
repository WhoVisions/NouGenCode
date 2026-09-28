import sqlite3
import time
import os
import shutil
from datetime import datetime

# Original DB path
DB_PATH = r"./data"
# Temp path to copy to avoid locking issues (if potential for conflict, though WAL should handle it)
# For now, let's try direct access in read-only mode first to avoid IO overhead of copying
# If that fails or locks, we will switch to copy strategy.

def get_latest_transcript():
    try:
        # Open in read-only mode with URI
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        # Get the latest entry from History based on timestamp
        query = """
        SELECT asrText, formattedText, timestamp, status 
        FROM History 
        ORDER BY timestamp DESC 
        LIMIT 1
        """
        cursor.execute(query)
        row = cursor.fetchone()
        
        conn.close()
        return row
    except sqlite3.OperationalError as e:
        print(f"DB locked or inaccessible: {e}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

def monitor():
    print(f"Monitoring Wispr Flow DB at: {DB_PATH}")
    last_timestamp = None
    
    while True:
        row = get_latest_transcript()
        if row:
            asr_text, formatted_text, timestamp, status = row
            
            # Simple check to see if it's a new record
            if timestamp != last_timestamp:
                print(f"\n[{timestamp}] New Transcript Found:")
                print(f"Raw: {asr_text}")
                print(f"Formatted: {formatted_text}")
                print(f"Status: {status}")
                
                last_timestamp = timestamp
                
                # Wake word check prototype
                text = (formatted_text or asr_text or "").lower()
                if "hey NodeWorker" in text or "hey kedra" in text or "hey kaydra" in text:
                     print(">>> WAKE WORD DETECTED: 'Hey NodeWorker' <<<")
                     # Split and find command
                     parts = text.split("hey NodeWorker")
                     if len(parts) > 1:
                         command = parts[1].strip()
                         print(f">>> COMMAND: {command}")

        time.sleep(1)

if __name__ == "__main__":
    monitor()
