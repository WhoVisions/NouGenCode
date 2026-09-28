"""
Google Workspace OAuth Flow for NodeWorker
Run once to authenticate and save refresh token.
"""
import os
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Paths - tools/google_auth.py -> NodeWorker/config
ROOT = Path(__file__).parent.parent  # kaedra_proper
CONFIG_DIR = ROOT / "NodeWorker" / "config"
CLIENT_SECRET = CONFIG_DIR / "google_oauth_client.json"
TOKEN_FILE = CONFIG_DIR / "google_token.json"


# Scopes for Google Workspace access
SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/tasks',
    'https://www.googleapis.com/auth/contacts.readonly',
]


def authenticate():
    """Run OAuth flow and save credentials."""
    creds = None
    
    # Check for existing token
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        print(f"✅ Found existing token: {TOKEN_FILE}")
    
    # Refresh or get new token
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 Refreshing expired token...")
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                print(f"❌ Client secret not found: {CLIENT_SECRET}")
                return None
            
            print("🌐 Opening browser for Google OAuth consent...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET), SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # Save token
        TOKEN_FILE.write_text(creds.to_json())
        print(f"✅ Token saved to: {TOKEN_FILE}")
    
    return creds

def test_connection(creds):
    """Quick test of Gmail connection."""
    try:
        from googleapiclient.discovery import build
        
        # Test Gmail
        gmail = build('gmail', 'v1', credentials=creds)
        profile = gmail.users().getProfile(userId='me').execute()
        print(f"📧 Gmail connected: {profile['emailAddress']}")
        
        # Test Calendar
        cal = build('calendar', 'v3', credentials=creds)
        calendars = cal.calendarList().list(maxResults=3).execute()
        print(f"📅 Calendar connected: {len(calendars.get('items', []))} calendars found")
        
        # Test Drive
        drive = build('drive', 'v3', credentials=creds)
        about = drive.about().get(fields='user').execute()
        print(f"📁 Drive connected: {about['user']['displayName']}")
        
        return True
    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("Google Workspace OAuth for NodeWorker")
    print("=" * 50)
    
    creds = authenticate()
    if creds:
        print("\n--- Testing Connections ---")
        test_connection(creds)
        print("\n✅ Google Workspace integration ready!")
    else:
        print("\n❌ Authentication failed.")
