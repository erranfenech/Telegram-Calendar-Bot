#!/usr/bin/env python3
"""
One-time Google Calendar authorisation script.

Run this on a desktop machine (Windows, Mac, or Linux) to generate
a token.json file, then copy that file to your Linux server.

Usage:
  1. Place this file in the same folder as your client_secret_XXXXXX.json
  2. Update CREDENTIALS_FILE below with your actual filename
  3. Run: python3 auth.py  (or: python auth.py on Windows)
  4. A browser window will open — sign in and grant calendar access
  5. Copy the generated token.json to ~/familybot/ on your server

Requirements:
  pip install google-auth-oauthlib
"""

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

# ============================================================
# Update this with your actual credentials filename
# ============================================================
CREDENTIALS_FILE = "client_secret_XXXXXX.apps.googleusercontent.com.json"

# Both scopes are required — read for /whatsontoday, write for /add
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events"
]


def main():
    # Check the credentials file exists
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"\n❌ Could not find: {CREDENTIALS_FILE}")
        print("Make sure this script is in the same folder as your Google credentials JSON file.")
        print("Update CREDENTIALS_FILE at the top of this script with your actual filename.\n")
        return

    print("\n🔐 Opening browser for Google authorisation...")
    print("Sign in with the Google account that owns your Family calendar.\n")

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open("token.json", "w") as f:
        f.write(creds.to_json())

    print("\n✅ Authorisation complete!")
    print(f"Scopes granted: {creds.scopes}")
    print("\nNext step: copy token.json to your Linux server:")
    print("  scp token.json root@yourserver:~/familybot/\n")

    # Verify both scopes were granted
    scopes = list(creds.scopes)
    if "https://www.googleapis.com/auth/calendar.events" not in scopes:
        print("⚠️  Warning: calendar.events scope was not granted.")
        print("The bot will not be able to add events.")
        print("Delete token.json and run this script again.\n")
    else:
        print("✅ Both read and write scopes confirmed. You're good to go!\n")


if __name__ == "__main__":
    main()
