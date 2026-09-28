"""
NodeWorker Agent-Layer Automations
Handles complex conditional logic and cross-database workflows for the VeilVerse Universe.
"""
import sys
import random
from pathlib import Path

# Add project root
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import requests
import toml

class VeilVerseAutomator:
    def __init__(self):
        config_path = ROOT / "NodeWorker" / "config" / "notion.toml"
        self.config = toml.load(config_path)
        self.token = self.config["notion"]["token"]
        self.universe_ds = self.config["databases"]["universe_ds"]
        self.ingestion_ds = self.config["databases"]["ingestion_ds"]
        self.universe_db = self.config["databases"]["universe_db"]
        
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2025-09-03",
            "Content-Type": "application/json"
        }

    def run_universe_checks(self):
        """Perform recurring checks on the Universe data source."""
        print("🌌 Running Universe Agent-Layer Automations...")
        
        url = f"https://api.notion.com/v1/data_sources/{self.universe_ds}/query"
        resp = requests.post(url, headers=self.headers, json={})
        
        if resp.status_code != 200:
            print(f"   ❌ Query failed: {resp.text}")
            return

        pages = resp.json().get("results", [])
        print(f"   🔎 Checking {len(pages)} recent entries...")
        
        for page in pages:
            props = page.get("properties", {})
            page_id = page["id"]
            
            updates = {}
            
            # #2 Retcon Safety Net
            canon_prop = props.get("Canon Status", {}) or {}
            canon_val_obj = canon_prop.get("select") or {}
            canon_status = canon_val_obj.get("name") if isinstance(canon_val_obj, dict) else None
            
            name_prop = props.get("Name", {}) or {}
            name_obj = name_prop.get("title", []) if name_prop else []
            current_name = name_obj[0]["text"]["content"] if name_obj else "Untitled"
            
            if canon_status == "Retconned" and not current_name.startswith("[RETCONNED]"):
                print(f"   🛡️ Safety: Retconning {current_name}")
                updates["Name"] = {"title": [{"text": {"content": f"[RETCONNED] {current_name}"}}]}
                updates["Status"] = {"status": {"name": "Inactive"}}

            # #5 Timeline Validator
            year_prop = props.get("Timeline Year", {}) or {}
            year_val = year_prop.get("number")
            if year_val is not None:
                era = "Unknown"
                if year_val < 0: era = "Ancient Era"
                elif 0 <= year_val <= 2000: era = "Classical Era"
                elif 2001 <= year_val <= 2100: era = "Modern Era"
                else: era = "Future Era"
                
                era_prop = props.get("Universe Era", {}) or {}
                era_val_obj = era_prop.get("select") or {}
                current_era = era_val_obj.get("name") if isinstance(era_val_obj, dict) else None
                if current_era != era:
                    print(f"   ⏳ Timeline: Setting {current_name} to {era}")
                    updates["Universe Era"] = {"select": {"name": era}}

            # #6 Character Power Tracking
            cat_prop = props.get("Category", {}) or {}
            cat_val_obj = cat_prop.get("select") or {}
            category = cat_val_obj.get("name") if isinstance(cat_val_obj, dict) else None
            
            pwr_prop = props.get("Power Level", {}) or {}
            pwr_val_obj = pwr_prop.get("select") or {}
            power_level = pwr_val_obj.get("name") if isinstance(pwr_val_obj, dict) else None
            
            if category == "Character" and power_level:
                score_map = {
                    "Cosmic": (90, 99), "God-Tier": (90, 99),
                    "High": (70, 89), "Mid": (50, 69),
                    "Low": (30, 49), "None": (30, 49)
                }
                if power_level in score_map:
                    low, high = score_map[power_level]
                    score_prop = props.get("Importance Score", {}) or {}
                    current_score = score_prop.get("number")
                    if current_score is None or not (low <= current_score <= high):
                        new_score = random.randint(low, high)
                        print(f"   ⚡ Power: Scaling {current_name} to {new_score}")
                        updates["Importance Score"] = {"number": new_score}

            # #9 Media Release Notification
            prod_prop = props.get("Production Status", {}) or {}
            prod_val_obj = prod_prop.get("select") or {}
            prod_status = prod_val_obj.get("name") if isinstance(prod_val_obj, dict) else None
            
            if prod_status == "Released":
                # Check if already processed
                meta_notified = props.get("_meta_notified", {}).get("checkbox", False)
                if not meta_notified:
                    print(f"   🚀 Media Release: Found {current_name}")
                    self._notify_dav3(f"Media released: {current_name}")
                    
                    # Upgrade Semi-Canon to Canon
                    if canon_status == "Semi-Canon":
                        updates["Canon Status"] = {"select": {"name": "Canon"}}
                    
                    # Mark notified
                    updates["_meta_notified"] = {"checkbox": True}
                    updates["Status"] = {"status": {"name": "Completed"}}

            if updates:
                requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=self.headers, json={"properties": updates})

    def run_weekly_review(self):
        """#4 Weekly Concept Review (Every Monday or manual)."""
        import datetime
        now = datetime.datetime.now()
        
        # Only run on Mondays (unless forced)
        # if now.weekday() != 0: return

        print("📋 Running Weekly Concept Review...")
        url = f"https://api.notion.com/v1/data_sources/{self.universe_ds}/query"
        query = {
            "filter": {
                "and": [
                    {"property": "Production Status", "select": {"equals": "Concept"}},
                    {"property": "Canon Status", "select": {"equals": "Canon"}}
                ]
            }
        }
        resp = requests.post(url, headers=self.headers, json=query)
        if resp.status_code == 200:
            pages = resp.json().get("results", [])
            if pages:
                names = [p["properties"]["Name"]["title"][0]["text"]["content"] for p in pages if p["properties"].get("Name", {}).get("title")]
                names_subset = names[:5]
                msg = f"📋 Weekly canon concept review [{now.strftime('%Y-%m-%d')}] — these need dev work:\n- " + "\n- ".join(names_subset)
                if len(names) > 5:
                    msg += f"\n...and {len(names)-5} more."
                print(f"   📢 {len(pages)} concepts need review")
                self._notify_dav3(msg)

    def _notify_dav3(self, message: str):
        """Send notification (simulated via print for now, could be Slack/Notion)."""
        print(f"   🔔 NOTIFICATION: {message}")

    def run_ingestion_promotion(self):
        """#11 Ingestion → Canon Promotion."""
        print("🚚 Checking Ingestion Queue for Promotion...")
        
        url = f"https://api.notion.com/v1/data_sources/{self.ingestion_ds}/query"
        query = {
            "filter": {
                "property": "Status",
                "select": {"equals": "Approved"}
            }
        }
        resp = requests.post(url, headers=self.headers, json=query)
        if resp.status_code != 200:
            print(f"   ❌ Ingestion Query failed: {resp.text}")
            return

        pages = resp.json().get("results", [])
        
        for page in pages:
            props = page.get("properties", {})
            title_prop = props.get("Title", {})
            title_obj = title_prop.get("title", []) if title_prop else []
            name = title_obj[0].get("text", {}).get("content", "Untitled Ingestion") if title_obj else "Untitled"
            source_url = props.get("Source URL", {}).get("url")
            
            print(f"   🏆 Promoting: {name}")
            
            # Create in Universe (Database parent)
            new_page = {
                "parent": {"database_id": self.universe_db},
                "properties": {
                    "Name": {"title": [{"text": {"content": name}}]},
                    "Canon Status": {"select": {"name": "Canon"}},
                    "Production Status": {"select": {"name": "Concept"}},
                    "Category": {"select": {"name": "Intelligence"}}, 
                    "Source URL": {"url": source_url or ""}
                }
            }
            create_resp = requests.post("https://api.notion.com/v1/pages", headers=self.headers, json=new_page)
            
            if create_resp.status_code == 200:
                # Update Ingestion to 'Imported'
                requests.patch(f"https://api.notion.com/v1/pages/{page['id']}", headers=self.headers, json={
                    "properties": {"Status": {"select": {"name": "Imported"}}}
                })
                print(f"   ✅ Successfully promoted {name}")

    def run_all(self):
        self.run_universe_checks()
        self.run_ingestion_promotion()
        self.run_weekly_review()

if __name__ == "__main__":
    automator = VeilVerseAutomator()
    automator.run_all()
