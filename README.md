# Family Calendar Telegram Bot 🗓️

A Telegram bot that lets your family manage a shared Google Calendar using natural language. Powered by Claude AI.

## What It Does

- **Check today or tomorrow** — ask the bot what's on and get a friendly summary with emojis
- **Add events naturally** — just type what's happening and Claude figures out the date, time, and event type
- **Colour coded calendar** — birthdays, meals, medical appointments, school events and more are automatically colour coded in Google Calendar
- **Confirmation step** — the bot always checks before adding anything to the calendar
- **Group chat** — works in a shared Telegram group so the whole family can use it

## Example Usage

```
/whatsontoday
/whatsontomorrow
/add Dinner at Mum's Saturday 7pm
/add John's birthday March 15th
/add Dentist appointment Tuesday 10am
```

## How It Works

```
Telegram Group → Bot → Claude AI → Google Calendar
```

A Python script runs on a Linux server, listening for commands in your family Telegram group. Claude AI parses natural language into structured event data, which is then written to your shared Google Calendar via the Google Calendar API.

## Tech Stack

- **Python 3.10+**
- **python-telegram-bot** — Telegram integration
- **Anthropic Claude API** — natural language understanding and formatting
- **Google Calendar API** — calendar read and write
- **systemd** — keeps the bot running permanently on your server

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

## Security

Never commit `.env`, `token.json`, or your Google credentials JSON to a public repository. See the security section in [SETUP.md](SETUP.md) for details.

