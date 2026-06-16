# Family Calendar Telegram Bot — Setup Guide

A Telegram bot that uses Claude AI to read and write events to a shared Google Calendar. Family members can add, update and delete events using natural language and check what's on today, tomorrow or for the rest of the week, all from a Telegram group chat.

---

## How It Works

```
Family Telegram Group
        ↓
Telegram Bot (receives commands)
        ↓
Python Script (the glue — runs on your Linux server)
        ↓
Claude AI (understands natural language, formats responses)
        ↓
Google Calendar API (reads and writes events)
```

---

## What You Will Need

- A Linux server (self-hosted or VPS) with Python 3.10+
- A Telegram account
- An Anthropic account (for Claude API access)
- A Google account with Google Calendar

---

## Part 1 — Telegram Bot Setup

### 1.1 Create the Bot

1. Open Telegram and search for **@BotFather**
2. Send the message `/newbot`
3. When prompted, give your bot a name (e.g. `Family Calendar`)
4. Give it a username — must end in `bot` (e.g. `familycal_bot`)
5. BotFather will reply with your **Bot API Token** — save this somewhere safe

### 1.2 Register Commands with BotFather

1. Send `/mybots` to BotFather
2. Select your bot
3. Tap **Edit Bot → Edit Commands**
4. Send the following (exactly as shown):

```
whatsontoday - See what's on today
whatsontomorrow - See what's on tomorrow
whatsonthisweek - See events for the rest of this week
add - Add a new event e.g. /add Dinner Saturday 7pm
delete - Delete an event e.g. /delete Dinner
update - Update an event e.g. /update Doctor
```

BotFather will confirm the commands are set. These appear as a menu when any group member types `/` in the chat.

### 1.3 Disable Privacy Mode

By default Telegram bots cannot read messages in groups. You must disable privacy mode so the bot can receive commands.

1. Send `/mybots` to BotFather
2. Select your bot
3. Tap **Bot Settings → Group Privacy**
4. Tap **Turn off**

> **Important:** If the bot is already in a group, remove it and re-add it after changing this setting. The change only applies to groups the bot joins after the setting is changed.

---

## Part 2 — Anthropic API Key

> **Note:** The Claude API is separate from a Claude.ai Pro subscription. The API is billed on a pay-per-use basis. For a family calendar bot the usage will be very small — typically a few pence per month.

1. Go to **console.anthropic.com** and sign in or create an account
2. In the left menu, click **API Keys**
3. Click **Create Key** and give it a name (e.g. `Family Calendar Bot`)
4. Copy the key immediately — you will only see it once
5. Save it somewhere safe alongside your Telegram token

---

## Part 3 — Google Calendar Setup

### 3.1 Prepare Your Calendar

If you already have a shared family calendar in Google Calendar, skip to Part 3.2.

To create a shared calendar on desktop:

1. Go to **calendar.google.com**
2. In the left sidebar under **Other calendars**, click the **+** icon
3. Select **Create new calendar**
4. Name it (e.g. `Family`)
5. Click **Create calendar**
6. Click the three dots next to your new calendar and select **Settings and sharing**
7. Under **Share with specific people**, add each family member's Gmail address
8. Set their permission to **Make changes to events**

Alternatively, if you use a Google Family Group, the Family calendar is shared automatically with all members at **families.google.com**.

### 3.2 Enable Google Cloud Access

Google requires 2-Step Verification to use the Cloud Console.

1. Go to **myaccount.google.com/security**
2. Under **How you sign in to Google**, enable **2-Step Verification**
3. Follow the prompts to set it up via phone number or authenticator app

### 3.3 Create a Google Cloud Project

1. Go to **console.cloud.google.com**
2. At the top, click the project selector and choose **New Project**
3. Name it (e.g. `Family Calendar Bot`) and click **Create**

### 3.4 Enable the Google Calendar API

1. In the left menu, go to **APIs & Services → Library**
2. Search for **Google Calendar API**
3. Click on it and click **Enable**

### 3.5 Configure the OAuth Consent Screen

1. In the left menu, go to **APIs & Services → OAuth consent screen**
2. Select **External** and click **Create**
3. Fill in the required fields:
   - **App name**: Family Calendar Bot
   - **User support email**: your Gmail address
   - **Developer contact email**: your Gmail address
4. Click **Save and Continue** through the Scopes page without changes
5. On the **Test users** page, click **Add users** and add your own Gmail address
6. Click **Save and Continue**

### 3.6 Create OAuth Credentials

1. In the left menu, go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Set **Application type** to **Desktop app**
4. Name it (e.g. `Family Calendar Bot`) and click **Create**
5. Download the credentials JSON file — named something like:
   `client_secret_XXXXXX.apps.googleusercontent.com.json`
6. Keep this file safe — you will need to copy it to your server

### 3.7 Find Your Calendar ID

Once your server is set up and `token.json` has been generated (see Part 5), run this on your server to list all your calendars and their IDs:

```bash
python3 -c "
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
creds = Credentials.from_authorized_user_file('/root/familybot/token.json')
service = build('calendar', 'v3', credentials=creds)
calendars = service.calendarList().list().execute()
for c in calendars['items']:
    print(c['summary'], '→', c['id'])
"
```

Look for your Family calendar in the output. The ID will look something like:
`family03469910097653568830@group.calendar.google.com`

---

## Part 4 — Linux Server Setup

### 4.1 Create the Project Directory

SSH into your server and run:

```bash
mkdir -p ~/familybot && cd ~/familybot
```

### 4.2 Install Required Python Packages

```bash
pip3 install python-telegram-bot google-auth-oauthlib google-api-python-client anthropic pytz
```

### 4.3 Copy Your Credentials File

Copy the Google credentials JSON file you downloaded in Part 3.6 to the server:

```bash
scp client_secret_XXXXXX.apps.googleusercontent.com.json root@yourserver:~/familybot/
```

### 4.4 Create the Environment File

Store all credentials in a secure environment file rather than in the script:

```bash
nano ~/familybot/.env
```

Add the following, replacing each placeholder with your actual values:

```ini
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
GOOGLE_CREDENTIALS_FILE=client_secret_XXXXXX.apps.googleusercontent.com.json
CALENDAR_ID=your_family_calendar_id@group.calendar.google.com
ALLOWED_CHAT_IDS=-123456789
```

For multiple Telegram groups, separate IDs with commas:

```ini
ALLOWED_CHAT_IDS=-123456789,-987654321
```

Lock down the file permissions:

```bash
chmod 600 ~/familybot/.env
```

### 4.5 Copy the Bot Script

Copy `familybot.py` to `~/familybot/` on your server. No editing is needed — all configuration is loaded from the `.env` file.

---

## Part 5 — Generate the Google Token

The bot needs a `token.json` file that authorises it to access your Google Calendar. Because the server has no browser, you must generate this on a desktop machine and then copy it to the server.

### Option A — Windows

1. Install Python from **python.org/downloads** — tick **Add Python to PATH** during install
2. Open **Command Prompt** (`Windows + R`, type `cmd`)
3. Install the required package:

```cmd
pip install google-auth-oauthlib
```

4. Copy your `client_secret_XXXXXX.json` to a folder on Windows (e.g. `C:\familybot\`)
5. Copy `auth.py` to the same folder
6. Update `CREDENTIALS_FILE` in `auth.py` with your actual filename
7. Run it:

```cmd
cd C:\familybot
python auth.py
```

8. A browser window will open — sign in with your Google account and grant calendar access
9. Confirm the output shows both scopes:

```
Done! Scopes granted: {'https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/calendar.readonly'}
```

10. Copy `token.json` to your server:

```cmd
scp token.json root@yourserver:~/familybot/
```

### Option B — Mac or Linux Desktop

1. Open Terminal
2. Install the required package:

```bash
pip3 install google-auth-oauthlib
```

3. Copy your `client_secret_XXXXXX.json` and `auth.py` to a local folder
4. Update `CREDENTIALS_FILE` in `auth.py` with your actual filename
5. Run it:

```bash
python3 auth.py
```

6. A browser window will open — sign in and grant access
7. Confirm both scopes are shown in the output
8. Copy `token.json` to your server:

```bash
scp token.json root@yourserver:~/familybot/
```

### Verifying the Token

On your server, confirm the token has both required scopes:

```bash
cat ~/familybot/token.json | jq .scopes
```

You should see:

```json
[
  "https://www.googleapis.com/auth/calendar.readonly",
  "https://www.googleapis.com/auth/calendar.events"
]
```

If only `calendar.readonly` is listed, delete `token.json` and repeat Part 5 — make sure `auth.py` includes both scopes.

---

## Part 6 — Get Your Telegram Group Chat ID

1. Create a Telegram group and add your family members
2. Add the bot to the group (search by its username)
3. Start the bot service (see Part 7)
4. Temporarily set `ALLOWED_CHAT_IDS=0` in `.env` to allow all chats
5. Send `/start` in the group chat
6. Check the logs:

```bash
journalctl -u familybot -f
```

7. Look for a line like:

```
INFO - Message from chat ID: -987654321
```

Group chat IDs are always negative numbers.

8. Update `ALLOWED_CHAT_IDS` in `.env` with this number
9. Restart the service:

```bash
systemctl restart familybot
```

---

## Part 7 — Run as a systemd Service

### 7.1 Create the Service File

```bash
sudo nano /etc/systemd/system/familybot.service
```

Paste the following:

```ini
[Unit]
Description=Family Calendar Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/familybot
EnvironmentFile=/root/familybot/.env
ExecStart=/usr/bin/python3 /root/familybot/familybot.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 7.2 Enable and Start the Service

```bash
systemctl daemon-reload
systemctl enable familybot
systemctl start familybot
systemctl status familybot
```

### 7.3 Useful Service Commands

```bash
# Check status
systemctl status familybot

# View live logs
journalctl -u familybot -f

# Restart after making changes
systemctl restart familybot

# Stop the bot
systemctl stop familybot
```

---

## Part 8 — Using the Bot

Once everything is running, anyone in the family Telegram group can use these commands:

| Command | What it does |
|---|---|
| `/start` | Shows available commands |
| `/whatsontoday` | Lists today's events |
| `/whatsontomorrow` | Lists tomorrow's events |
| `/whatsonthisweek` | Lists events from today to end of Sunday |
| `/add Dinner at Mum's Saturday 7pm` | Adds a new event with clash detection and confirmation |
| `/add John's birthday March 15th` | Adds a recurring yearly birthday event |
| `/delete Dinner` | Searches for and deletes a matching event |
| `/update Doctor` | Searches for and updates a matching event |

### Adding Events — Examples

```
/add Dinner at Mum's this Saturday at 7pm
/add John's birthday on March 15th
/add Dentist appointment Tuesday 10am
/add Family holiday to Spain June 28th
/add School sports day Friday all day
/add Wedding anniversary next Monday
```

Claude will automatically detect the event type, assign the correct colour, and set recurring events for birthdays and anniversaries.

### Clash Detection

If you try to add an event at the same time as an existing one, the bot will warn you:

```
⚠️ Heads up — there's already something at this time:
📅 Dentist @ 10:00 AM

Still want to add this?
✅ Yes, add it    ❌ Cancel
```

### Deleting Events

```
/delete Dinner
```

The bot will list all matching upcoming events with individual delete buttons. You must confirm before anything is removed.

### Updating Events

```
/update Doctor
```

The bot finds matching events, you select which one, then describe what to change in plain English:

- `Change the time to 2pm`
- `Move it to next Friday`
- `Change location to City Hospital`
- `Rename it to Specialist Appointment`

The bot confirms the changes before saving.

### Tips for Searching

When using `/delete` or `/update`, shorter search terms work best:

- `/update Doctor` rather than `/update Noah's doctors appointment`
- `/delete Dinner` rather than `/delete Dinner at Mum's on Saturday`

---

## Event Types and Colours

| Type | Detected from | Google Calendar Colour | Telegram Emoji |
|---|---|---|---|
| Food / meals | Dinner, lunch, BBQ, restaurant | Tomato (red) | 🍽️ |
| Birthdays | Birthday | Sage (green) | 🎂 |
| Anniversaries | Anniversary | Sage (green) | 💑 |
| Medical | Doctor, dentist, hospital, appointment | Peacock (blue) | 🏥 |
| School | School, class, teacher | Banana (yellow) | 🏫 |
| Sport | Football, gym, swimming | Tangerine (orange) | ⚽ |
| Celebrations | Party, wedding, graduation | Grape (purple) | 🎉 |
| Travel | Holiday, flight, trip | Peacock (blue) | ✈️ |
| General | Everything else | Graphite (grey) | 📅 |

---

## Troubleshooting

### Bot not responding in the group
- Check that `ALLOWED_CHAT_IDS` in `.env` matches the group chat ID (negative number)
- Make sure privacy mode is disabled in BotFather (see Part 1.3)
- Remove and re-add the bot to the group after disabling privacy mode

### 403 insufficientPermissions when adding events
Your `token.json` was generated with read-only access. Delete it, ensure `auth.py` includes both scopes, regenerate and copy back to the server.

### Could not locate runnable browser
The server is headless and cannot open a browser. Generate `token.json` on a desktop machine (see Part 5) and copy it to the server.

### Delete or update button does nothing
This can happen if the bot was restarted between the search and the button press, clearing the in-memory state. Simply run the `/delete` or `/update` command again.

### Credit balance error from Anthropic
Add credits at **console.anthropic.com** under Plans & Billing. Usage for a family bot is very low.

### Telegram token visible in logs
Ensure credentials are in `.env` and loaded via `os.environ.get()` in the script. Confirm `EnvironmentFile` is set in the systemd service file. Regenerate your token via BotFather if it was accidentally exposed.

---

## File Structure

```
~/familybot/
├── familybot.py                          # Main bot script
├── auth.py                               # One-time desktop auth script
├── .env                                  # Credentials (chmod 600)
├── client_secret_XXXXXX.json            # Google OAuth credentials
└── token.json                            # Auto-generated Google auth token
```

---

## Security Notes

- Keep `.env` permissions set to `600` so only root can read it
- Never commit `.env`, `token.json`, or `client_secret_*.json` to a public repository
- Add these to your `.gitignore`:

```
.env
token.json
client_secret_*.json
```

- Regenerate your Telegram bot token via BotFather if it is ever accidentally exposed
- The `ALLOWED_CHAT_IDS` setting ensures only your specified group chats can control the bot
- Set `ALLOWED_CHAT_IDS=0` only temporarily during initial setup to discover your group chat ID
