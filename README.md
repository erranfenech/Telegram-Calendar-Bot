# Family Calendar Telegram Bot 🗓️

A Telegram bot that lets your family manage a shared Google Calendar using natural language. Powered by Claude AI.

## What It Does

- **Check today, tomorrow or the week ahead** — ask the bot what's on and get a friendly summary with emojis
- **Add events naturally** — just type what's happening and Claude figures out the date, time, location and event type automatically
- **Clash detection** — warns you if something is already booked at that time before adding
- **Colour coded calendar** — birthdays, meals, medical appointments, school events and more are automatically colour coded in Google Calendar
- **Delete events** — search by name and pick which one to remove with a confirmation step
- **Update events** — find an event and tell the bot what to change in plain English
- **Confirmation step** — the bot always checks before adding, deleting or updating anything
- **Group chat** — works in a shared Telegram group so the whole family can use it
- **Multi-group support** — can serve multiple Telegram groups from one server

## Example Usage

```
/whatsontoday
/whatsontomorrow
/whatsonthisweek
/add Dinner at Mum's Saturday 7pm
/add John's birthday March 15th
/delete Dinner
/update Doctor
```

## How It Works

```
Telegram Group → Bot → Claude AI → Google Calendar
```

A Python script runs on a Linux server, listening for commands in your family Telegram group. Claude AI parses natural language into structured event data, which is then read from or written to your shared Google Calendar via the Google Calendar API.

## Tech Stack

- **Python 3.10+**
- **python-telegram-bot** — Telegram integration
- **Anthropic Claude API** — natural language understanding and formatting
- **Google Calendar API** — calendar read and write
- **systemd** — keeps the bot running permanently on your server

## Commands

| Command | Description |
|---|---|
| `/start` | Show available commands |
| `/whatsontoday` | See today's events |
| `/whatsontomorrow` | See tomorrow's events |
| `/whatsonthisweek` | See events from today to end of the week |
| `/add <event>` | Add a new event with clash detection and confirmation |
| `/delete <name>` | Search for and delete an event |
| `/update <name>` | Search for and update an event |

## Event Types and Colours

Claude automatically detects the event type and assigns a colour in Google Calendar:

| Type | Google Calendar Colour | Telegram Emoji |
|---|---|---|
| Food / meals / dinner | Tomato (red) | 🍽️ |
| Birthdays | Sage (green) | 🎂 |
| Anniversaries | Sage (green) | 💑 |
| Medical / appointments | Peacock (blue) | 🏥 |
| School | Banana (yellow) | 🏫 |
| Sport / activities | Tangerine (orange) | ⚽ |
| Celebrations / parties | Grape (purple) | 🎉 |
| Travel / holidays | Peacock (blue) | ✈️ |
| General | Graphite (grey) | 📅 |

## Getting Started

See the full step-by-step setup guide: **[SETUP.md](SETUP.md)**

## Files

| File | Description |
|---|---|
| `familybot.py` | Main bot script |
| `auth.py` | One-time Google authentication script (run on desktop) |
| `SETUP.md` | Full setup guide |
| `.env` | Your credentials — never commit this |
| `token.json` | Auto-generated Google auth token — never commit this |

## Tips for Searching

When using `/delete` or `/update`, shorter search terms work best:

- `/update Doctor` rather than `/update Noah's doctors appointment`
- `/delete Dinner` rather than `/delete Dinner at Mum's on Saturday`

Google Calendar search will find partial matches so keep it simple.

## Security

Never commit `.env`, `token.json`, or your Google credentials JSON to a public repository. See the security section in [SETUP.md](SETUP.md) for details.

## Credits

Built with [Claude](https://anthropic.com) by Anthropic.
