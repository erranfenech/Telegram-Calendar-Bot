# Family Calendar Telegram Bot — Setup Guide

A Telegram bot that uses Claude AI to read and write events to a shared Google Calendar, with daily weather forecasts, pollen alerts and smart location detection.

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
        ↕
Open-Meteo API (weather and pollen — free, no key needed)
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
add - Add a new event e.g. /add Dinner Saturday 19:00
delete - Delete an event e.g. /delete Dinner
update - Update an event e.g. /update Doctor
weather - Quick weather summary for today
weatherdetail - Full hourly weather breakdown for today
setlocation - Set weather location e.g. /setlocation Warsaw
getlocation - Show current weather location
```

### 1.3 Disable Privacy Mode

By default Telegram bots cannot read messages in groups. You must disable privacy mode.

1. Send `/mybots` to BotFather
2. Select your bot
3. Tap **Bot Settings → Group Privacy**
4. Tap **Turn off**

> **Important:** Remove and re-add the bot to any existing groups after changing this setting.

---

## Part 2 — Anthropic API Key

> **Note:** The Claude API is separate from a Claude.ai Pro subscription and is billed on a pay-per-use basis. For a family calendar bot the usage will be very small — typically a few pence per month.

1. Go to **console.anthropic.com** and sign in or create an account
2. In the left menu, click **API Keys**
3. Click **Create Key** and give it a name (e.g. `Family Calendar Bot`)
4. Copy the key immediately — you will only see it once

---

## Part 3 — Google Calendar Setup

### 3.1 Prepare Your Calendar

If you already have a shared family calendar, skip to Part 3.2.

To create a shared calendar on desktop:

1. Go to **calendar.google.com**
2. In the left sidebar under **Other calendars**, click the **+** icon
3. Select **Create new calendar**, name it (e.g. `Family`) and click **Create**
4. Click the three dots next to your new calendar → **Settings and sharing**
5. Under **Share with specific people**, add each family member's Gmail address
6. Set permission to **Make changes to events**

Alternatively, if you use a Google Family Group, the Family calendar is shared automatically with all members at **families.google.com**.

### 3.2 Enable Google Cloud Access

1. Go to **myaccount.google.com/security**
2. Enable **2-Step Verification**

### 3.3 Create a Google Cloud Project

1. Go to **console.cloud.google.com**
2. Click the project selector at the top → **New Project**
3. Name it (e.g. `Family Calendar Bot`) and click **Create**

### 3.4 Enable the Google Calendar API

1. Go to **APIs & Services → Library**
2. Search for **Google Calendar API**, click it and click **Enable**

### 3.5 Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. Select **External** and click **Create**
3. Fill in: App name, User support email, Developer contact email (all your Gmail)
4. Click **Save and Continue** through the Scopes page
5. On the **Test users** page, add your own Gmail address
6. Click **Save and Continue**

### 3.6 Create OAuth Credentials

1. Go to **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Set **Application type** to **Desktop app**, name it and click **Create**
4. Download the credentials JSON file (e.g. `client_secret_XXXXXX.apps.googleusercontent.com.json`)

### 3.7 Find Your Calendar ID

Once `token.json` has been generated (see Part 5), run this on your server:

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

Look for your Family calendar — the ID will look like:
`family03469910097653568830@group.calendar.google.com`

---

## Part 4 — Linux Server Setup

### 4.1 Create the Project Directory

```bash
mkdir -p ~/familybot && cd ~/familybot
```

### 4.2 Install Required Python Packages

```bash
pip3 install python-telegram-bot google-auth-oauthlib google-api-python-client anthropic pytz apscheduler httpx
```

### 4.3 Copy Your Credentials File

```bash
scp client_secret_XXXXXX.apps.googleusercontent.com.json root@yourserver:~/familybot/
```

### 4.4 Create the Environment File

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
DIGEST_TIME=07:00
DIGEST_TIMEZONE=Europe/London
WEATHER_LAT=52.7720
WEATHER_LON=-2.5217
WEATHER_LOCATION=Newport, Shropshire
RAIN_THRESHOLD=50
UV_THRESHOLD=3
POLLEN_THRESHOLD=low
HAYFEVER_NAME=YourName
```

For multiple Telegram groups, separate IDs with commas:
```ini
ALLOWED_CHAT_IDS=-123456789,-987654321
```

Lock down the file permissions:
```bash
chmod 600 ~/familybot/.env
```

### 4.5 Environment File Reference

| Setting | Description | Example |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | `7483920174:AAFx...` |
| `ANTHROPIC_API_KEY` | Claude API key | `sk-ant-...` |
| `GOOGLE_CREDENTIALS_FILE` | Google OAuth credentials filename | `client_secret_XXX.json` |
| `CALENDAR_ID` | Google Calendar ID to use | `family03469...@group.calendar.google.com` |
| `ALLOWED_CHAT_IDS` | Telegram group chat IDs (comma separated) | `-123456789` |
| `DIGEST_TIME` | Time to send morning digest in 24hr format | `07:00` |
| `DIGEST_TIMEZONE` | Timezone for digest scheduling | `Europe/London` |
| `WEATHER_LAT` | Default latitude for weather | `52.7720` |
| `WEATHER_LON` | Default longitude for weather | `-2.5217` |
| `WEATHER_LOCATION` | Default location name for display | `Newport, Shropshire` |
| `RAIN_THRESHOLD` | Rain probability % at which to warn | `50` |
| `UV_THRESHOLD` | UV index at which to warn | `3` |
| `POLLEN_THRESHOLD` | Minimum pollen level to warn about | `low` |
| `HAYFEVER_NAME` | Name of hay fever sufferer for personal alerts | `Erran` |

---

## Part 5 — Generate the Google Token

Because the server has no browser, generate `token.json` on a desktop machine first.

### Option A — Windows

1. Install Python from **python.org/downloads** — tick **Add Python to PATH**
2. Open Command Prompt and install the package:

```cmd
pip install google-auth-oauthlib
```

3. Copy your `client_secret_XXXXXX.json` and `auth.py` to a local folder
4. Update `CREDENTIALS_FILE` in `auth.py` with your actual filename
5. Run it:

```cmd
python auth.py
```

6. A browser window will open — sign in and grant calendar access
7. Confirm the output shows both scopes:

```
Done! Scopes granted: {'https://www.googleapis.com/auth/calendar.events', 'https://www.googleapis.com/auth/calendar.readonly'}
```

8. Copy `token.json` to your server:

```cmd
scp token.json root@yourserver:~/familybot/
```

### Option B — Mac or Linux Desktop

1. Open Terminal and install the package:

```bash
pip3 install google-auth-oauthlib
```

2. Copy your credentials file and `auth.py` locally, update the filename in `auth.py`, then run:

```bash
python3 auth.py
```

3. Sign in, grant access, then copy `token.json` to your server:

```bash
scp token.json root@yourserver:~/familybot/
```

### Verifying the Token

```bash
cat ~/familybot/token.json | jq .scopes
```

You should see both:
```json
[
  "https://www.googleapis.com/auth/calendar.readonly",
  "https://www.googleapis.com/auth/calendar.events"
]
```

If only `calendar.readonly` is listed, delete `token.json` and repeat Part 5.

---

## Part 6 — Get Your Telegram Group Chat ID

1. Create a Telegram group, add family members and the bot
2. Temporarily set `ALLOWED_CHAT_IDS=0` in `.env`
3. Start the bot service (see Part 7)
4. Send `/start` in the group and check the logs:

```bash
journalctl -u familybot -f
```

5. Look for: `INFO - Message from chat ID: -987654321`
6. Group chat IDs are always negative numbers
7. Update `ALLOWED_CHAT_IDS` in `.env` and restart the service

---

## Part 7 — Run as a systemd Service

### 7.1 Create the Service File

```bash
sudo nano /etc/systemd/system/familybot.service
```

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

### 7.2 Enable and Start

```bash
systemctl daemon-reload
systemctl enable familybot
systemctl start familybot
systemctl status familybot
```

### 7.3 Useful Commands

```bash
systemctl status familybot       # Check status
journalctl -u familybot -f       # View live logs
systemctl restart familybot      # Restart after changes
systemctl stop familybot         # Stop the bot
```

---

## Part 8 — Using the Bot

### Calendar Commands

| Command | What it does |
|---|---|
| `/whatsontoday` | Lists today's events |
| `/whatsontomorrow` | Lists tomorrow's events |
| `/whatsonthisweek` | Lists events from today to end of Sunday |
| `/add Dinner at Mum's Saturday 19:00` | Adds event with clash detection |
| `/add John's birthday March 15th` | Adds recurring yearly birthday |
| `/delete Dinner` | Searches and deletes a matching event |
| `/update Doctor` | Searches and updates a matching event |

### Weather Commands

| Command | What it does |
|---|---|
| `/weather` | Brief summary — conditions, high/low, rain, UV, pollen |
| `/weatherdetail` | Full hourly breakdown from now until end of day |
| `/setlocation Warsaw` | Switch weather to a different city |
| `/getlocation` | Show which location is currently being used |

### Location for Weather

The bot uses this priority order for weather location:

1. **Live location** shared in the Telegram group
2. **Location pin** sent to the group
3. **`/setlocation` command**
4. **Default home location** from `.env`

When travelling abroad, share your live location to the group and the bot switches weather automatically. Use `/setlocation` for a quick manual override.

### Morning Digest

Sent automatically at the time set in `DIGEST_TIME`. Includes:

- Warm greeting appropriate for weekday or weekend
- Overall weather summary with high and low temps
- Rain and UV warnings where relevant
- Personalised pollen alerts for hay fever sufferers
- Each calendar event with the weather at that specific time
- Per-event advice such as umbrella, sun cream, or antihistamines

### Adding Events — Examples

```
/add Dinner at Mum's this Saturday at 19:00
/add John's birthday on March 15th
/add Dentist appointment Tuesday 10:00
/add Family holiday to Spain June 28th
/add School sports day Friday all day
/add Wedding anniversary next Monday
```

### Clash Detection

If you try to add an event at the same time as an existing one:

```
⚠️ Heads up — there's already something at this time:
📅 Dentist @ 10:00

Still want to add this?
✅ Yes, add it    ❌ Cancel
```

### Tips for Searching

When using `/delete` or `/update`, shorter search terms work best:

- `/update Doctor` rather than `/update Noah's doctors appointment`
- `/delete Dinner` rather than `/delete Dinner at Mum's on Saturday`

---

## Changing Timezone When Travelling

Update `DIGEST_TIMEZONE` in `.env` to match your destination:

```ini
DIGEST_TIMEZONE=Europe/Warsaw        # Poland
DIGEST_TIMEZONE=Africa/Johannesburg  # South Africa
DIGEST_TIMEZONE=Europe/London        # UK (default)
```

Then restart the service:

```bash
systemctl restart familybot
```

The morning digest will fire at `DIGEST_TIME` in the new timezone.

---

## Troubleshooting

### Bot not responding in the group
- Check `ALLOWED_CHAT_IDS` matches the group chat ID (negative number)
- Make sure privacy mode is disabled in BotFather (Part 1.3)
- Remove and re-add the bot to the group after disabling privacy mode

### 403 insufficientPermissions when adding events
Delete `token.json`, ensure `auth.py` has both scopes, regenerate and copy back.

### Could not locate runnable browser
Generate `token.json` on a desktop machine (Part 5) and copy to the server.

### Delete or update button does nothing
The bot was restarted between the search and the button press, clearing state. Run the command again.

### Weather not showing
Check the server has internet access. Open-Meteo is free and requires no API key — if it fails it will be a connectivity issue.

### Credit balance error from Anthropic
Add credits at **console.anthropic.com** under Plans & Billing.

### Morning digest not sending
Check `DIGEST_TIME` and `DIGEST_TIMEZONE` in `.env` are correct. Check logs with `journalctl -u familybot -f` around the scheduled time.

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

- Keep `.env` permissions at `600`
- Never commit `.env`, `token.json`, or `client_secret_*.json` to a public repository
- Add to `.gitignore`:

```
.env
token.json
client_secret_*.json
```

- Regenerate your Telegram token via BotFather if accidentally exposed
- Set `ALLOWED_CHAT_IDS=0` only temporarily during initial setup
