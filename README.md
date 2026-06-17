# Family Calendar Telegram Bot 🗓️

A Telegram bot that lets your family manage a shared Google Calendar using natural language, with daily weather forecasts and pollen alerts. Powered by Claude AI.

## What It Does

- **Check today, tomorrow or the week ahead** — ask the bot what's on and get a friendly summary with emojis
- **Add events naturally** — just type what's happening and Claude figures out the date, time, location and event type automatically
- **Clash detection** — warns you if something is already booked at that time before adding
- **Colour coded calendar** — birthdays, meals, medical appointments, school events and more are automatically colour coded in Google Calendar
- **Delete events** — search by name and pick which one to remove with a confirmation step
- **Update events** — find an event and tell the bot what to change in plain English
- **Morning digest** — automatic daily message at a set time with today's events, weather and pollen
- **Weather commands** — quick or detailed weather forecast on demand
- **Pollen alerts** — personalised hay fever warnings with antihistamine reminders
- **Smart location** — uses live Telegram location, pinned location, manual city, or home default
- **Confirmation step** — the bot always checks before adding, deleting or updating anything
- **Group chat** — works in a shared Telegram group so the whole family can use it
- **Multi-group support** — can serve multiple Telegram groups from one server

## Example Usage

```
/whatsontoday
/whatsontomorrow
/whatsonthisweek
/add Dinner at Mum's Saturday 19:00
/add John's birthday March 15th
/delete Dinner
/update Doctor
/weather
/weatherdetail
/setlocation Warsaw
/getlocation
```

## How It Works

```
Telegram Group → Bot → Claude AI → Google Calendar
                           ↕
                    Open-Meteo API (weather + pollen)
```

A Python script runs on a Linux server, listening for commands in your family Telegram group. Claude AI parses natural language into structured event data, which is then read from or written to your shared Google Calendar. Weather and pollen data comes from the free Open-Meteo API.

## Tech Stack

- **Python 3.10+**
- **python-telegram-bot** — Telegram integration
- **Anthropic Claude API** — natural language understanding and formatting
- **Google Calendar API** — calendar read and write
- **Open-Meteo API** — weather and pollen forecasts (free, no API key needed)
- **APScheduler** — morning digest scheduling
- **httpx** — async HTTP requests
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
| `/weather` | Quick weather summary for today |
| `/weatherdetail` | Full hourly weather breakdown for today |
| `/setlocation <city>` | Set location for weather forecasts |
| `/getlocation` | Show which location is currently being used |

## Morning Digest

Every morning at a configurable time the bot sends a digest to the family group including:

- Today's events with per-event weather context
- Overall weather summary with high and low temperatures
- Rain warnings with umbrella reminders
- UV index warnings with sun cream reminders
- Personalised pollen alerts for hay fever sufferers
- Different tone for weekdays vs weekends

## Weather Location Priority

The bot determines the weather location using this priority order:

1. **Live location** shared in the Telegram group (most accurate, updates as you move)
2. **Location pin** sent to the group
3. **`/setlocation` command** — manually set by city name
4. **Default home location** set in `.env`

When travelling, share your live location to the group and the bot switches automatically.

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

## Security

Never commit `.env`, `token.json`, or your Google credentials JSON to a public repository. See the security section in [SETUP.md](SETUP.md) for details.

## Credits

Built with [Claude](https://anthropic.com) by Anthropic.
