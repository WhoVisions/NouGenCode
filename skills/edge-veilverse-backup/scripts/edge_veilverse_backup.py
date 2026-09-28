"""
VeilVerse Universe Backup Tool
Pulls all entities from OLD Notion workspace and stores in local SQLite.
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from notion_client import Client

# OLD Workspace credentials (Dave Meralus's Space)
OLD_TOKEN = "ntn_Q30316993016t1Tl4w10dpwEk2yN3SB4PN9An9z71xJfrH"
OLD_DB_ID = "2d90b4b4-0f65-8001-98fe-cbf8a4a2146a"

# Local backup path
BACKUP_DIR = Path(__file__).parent.parent / "data"
BACKUP_DB = BACKUP_DIR / "veilverse_backup.db"


def init_database(conn: sqlite3.Connection):
    """Create tables matching the VeilVerse Universe schema."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            notion_id TEXT UNIQUE,
            name TEXT NOT NULL,
            category TEXT,
            status TEXT,
            canon_status TEXT,
            description TEXT,
            notes TEXT,
            abilities_powers TEXT,
            affiliation TEXT,
            alias TEXT,  -- JSON array
            appears_in TEXT,  -- JSON array
            tags TEXT,  -- JSON array
            power_level TEXT,
            timeline_year INTEGER,
            universe_era TEXT,
            importance_score REAL,
            last_updated TEXT,
            connected_to TEXT,  -- JSON array of IDs
            raw_properties TEXT,  -- Full JSON dump
            synced_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT,
            entity_id TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            details TEXT
        )
    """)
    conn.commit()
    print("✅ Database schema initialized")


def extract_property(props: dict, key: str, prop_type: str = "text") -> any:
    """Extract value from Notion property with null-safety."""
    prop = props.get(key, {})
    if not prop:
        return None
    
    dtype = prop.get("type", "")
    
    try:
        if dtype == "title":
            arr = prop.get("title", [])
            return arr[0].get("text", {}).get("content", "") if arr else ""
        elif dtype == "rich_text":
            arr = prop.get("rich_text", [])
            return arr[0].get("text", {}).get("content", "") if arr else ""
        elif dtype == "select":
            sel = prop.get("select")
            return sel.get("name", "") if sel else ""
        elif dtype == "multi_select":
            arr = prop.get("multi_select", [])
            return json.dumps([item.get("name", "") for item in arr])
        elif dtype == "status":
            stat = prop.get("status")
            return stat.get("name", "") if stat else ""
        elif dtype == "number":
            return prop.get("number")
        elif dtype == "date":
            d = prop.get("date")
            return d.get("start", "") if d else ""
        elif dtype == "relation":
            arr = prop.get("relation", [])
            return json.dumps([item.get("id", "") for item in arr])
        elif dtype == "url":
            return prop.get("url", "")
    except Exception:
        return None
    return None


def backup_from_notion():
    """Pull all entities from OLD Notion workspace."""
    print("=" * 60)
    print("🔄 VEILVERSE BACKUP TOOL")
    print("=" * 60)
    
    # Ensure backup directory exists
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    
    # Initialize client
    client = Client(auth=OLD_TOKEN)
    print(f"\n[1] Connecting to OLD workspace...")
    print(f"    Database: {OLD_DB_ID}")
    
    # Query all entities with pagination using httpx (notion-client doesn't have query)
    import httpx
    
    print(f"\n[2] Fetching entities...")
    all_results = []
    has_more = True
    start_cursor = None
    
    headers = {
        "Authorization": f"Bearer {OLD_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json"
    }
    
    with httpx.Client(timeout=30.0) as http_client:
        while has_more:
            payload = {"page_size": 100}
            if start_cursor:
                payload["start_cursor"] = start_cursor
            
            response = http_client.post(
                f"https://api.notion.com/v1/databases/{OLD_DB_ID}/query",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            all_results.extend(results)
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")
            print(f"    Fetched {len(all_results)} entities...")
    
    print(f"✅ Total entities fetched: {len(all_results)}")
    
    # Initialize SQLite
    print(f"\n[3] Writing to SQLite: {BACKUP_DB}")
    conn = sqlite3.connect(BACKUP_DB)
    init_database(conn)
    
    # Insert entities
    inserted = 0
    updated = 0
    
    for entity in all_results:
        props = entity.get("properties", {})
        notion_id = entity.get("id", "")
        
        # Extract all properties
        data = {
            "notion_id": notion_id,
            "name": extract_property(props, "Name", "title"),
            "category": extract_property(props, "Category", "select"),
            "status": extract_property(props, "Status", "status"),
            "canon_status": extract_property(props, "Canon Status", "select"),
            "description": extract_property(props, "Description", "text"),
            "notes": extract_property(props, "Notes", "text"),
            "abilities_powers": extract_property(props, "Abilities/Powers", "text"),
            "affiliation": extract_property(props, "Affiliation", "text"),
            "alias": extract_property(props, "Alias", "multi_select"),
            "appears_in": extract_property(props, "Appears In", "multi_select"),
            "tags": extract_property(props, "Tags", "multi_select"),
            "power_level": extract_property(props, "Power Level", "select"),
            "timeline_year": extract_property(props, "Timeline Year", "number"),
            "universe_era": extract_property(props, "Universe Era", "select"),
            "importance_score": extract_property(props, "Importance Score", "number"),
            "last_updated": extract_property(props, "Last Updated", "date"),
            "connected_to": extract_property(props, "Connected To", "relation"),
            "raw_properties": json.dumps(props),
            "synced_at": datetime.utcnow().isoformat()
        }
        
        # Upsert
        try:
            conn.execute("""
                INSERT INTO entities (
                    id, notion_id, name, category, status, canon_status,
                    description, notes, abilities_powers, affiliation, alias,
                    appears_in, tags, power_level, timeline_year, universe_era,
                    importance_score, last_updated, connected_to, raw_properties, synced_at
                ) VALUES (
                    :notion_id, :notion_id, :name, :category, :status, :canon_status,
                    :description, :notes, :abilities_powers, :affiliation, :alias,
                    :appears_in, :tags, :power_level, :timeline_year, :universe_era,
                    :importance_score, :last_updated, :connected_to, :raw_properties, :synced_at
                )
                ON CONFLICT(notion_id) DO UPDATE SET
                    name = :name,
                    category = :category,
                    status = :status,
                    canon_status = :canon_status,
                    description = :description,
                    notes = :notes,
                    abilities_powers = :abilities_powers,
                    affiliation = :affiliation,
                    alias = :alias,
                    appears_in = :appears_in,
                    tags = :tags,
                    power_level = :power_level,
                    timeline_year = :timeline_year,
                    universe_era = :universe_era,
                    importance_score = :importance_score,
                    last_updated = :last_updated,
                    connected_to = :connected_to,
                    raw_properties = :raw_properties,
                    synced_at = :synced_at
            """, data)
            inserted += 1
        except Exception as e:
            print(f"    [!] Error inserting {data.get('name', 'Unknown')}: {e}")
    
    conn.commit()
    
    # Log the sync
    conn.execute("""
        INSERT INTO sync_log (action, details, status)
        VALUES ('FULL_BACKUP', ?, 'SUCCESS')
    """, (f"Backed up {inserted} entities from OLD workspace",))
    conn.commit()
    
    # Summary stats
    cursor = conn.execute("SELECT category, COUNT(*) FROM entities GROUP BY category ORDER BY COUNT(*) DESC")
    stats = cursor.fetchall()
    
    print(f"\n[4] Backup Summary:")
    print(f"    Total entities: {inserted}")
    print(f"    By category:")
    for cat, count in stats:
        print(f"      - {cat or 'Uncategorized'}: {count}")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print(f"✅ BACKUP COMPLETE: {BACKUP_DB}")
    print("=" * 60)
    
    return inserted


if __name__ == "__main__":
    backup_from_notion()
