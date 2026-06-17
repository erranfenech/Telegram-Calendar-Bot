#!/usr/bin/env python3
"""
Family Calendar Telegram Bot
Connects Telegram -> Claude -> Google Calendar + Weather + Pollen
Commands:
  /whatsontoday      - List today's events
  /whatsontomorrow   - List tomorrow's events
  /whatsonthisweek   - List events from today to end of week
  /add <event>       - Add a new event with confirmation and clash detection
  /delete <name>     - Delete an event by name
  /update <name>     - Update an event by name
  /setlocation <city>- Set location for weather
  /getlocation       - Show current location being used for weather
  /weather           - Brief weather summary for today
  /weatherdetail     - Full hourly weather breakdown for today
"""

import logging
import os
import json
import httpx
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import anthropic

# ============================================================
# CONFIGURATION — all values loaded from .env file
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE")
GOOGLE_TOKEN_FILE = "token.json"
CALENDAR_ID = os.environ.get("CALENDAR_ID")
TIMEZONE = "Europe/London"

# Digest settings
DIGEST_TIME = os.environ.get("DIGEST_TIME", "07:00")
DIGEST_TIMEZONE = os.environ.get("DIGEST_TIMEZONE", "Europe/London")

# Default home location
DEFAULT_WEATHER_LAT = float(os.environ.get("WEATHER_LAT", "52.7720"))
DEFAULT_WEATHER_LON = float(os.environ.get("WEATHER_LON", "-2.5217"))
DEFAULT_WEATHER_LOCATION = os.environ.get("WEATHER_LOCATION", "Newport, Shropshire")

# Weather thresholds
RAIN_THRESHOLD = int(os.environ.get("RAIN_THRESHOLD", "50"))
UV_THRESHOLD = int(os.environ.get("UV_THRESHOLD", "3"))
POLLEN_THRESHOLD = os.environ.get("POLLEN_THRESHOLD", "low")
HAYFEVER_NAME = os.environ.get("HAYFEVER_NAME", "Erran")

# Security
ALLOWED_CHAT_IDS = [int(x.strip()) for x in os.environ.get("ALLOWED_CHAT_IDS", "0").split(",")]

# ============================================================
# COLOUR MAPPING
# Google Calendar colour IDs:
# 1=Lavender 2=Sage 3=Grape 4=Flamingo 5=Banana
# 6=Tangerine 7=Peacock 8=Graphite 9=Blueberry 10=Basil 11=Tomato
# ============================================================

COLOUR_MAP = {
    "food":          {"colour_id": "11", "emoji": "🍽️"},
    "birthday":      {"colour_id": "2",  "emoji": "🎂"},
    "anniversary":   {"colour_id": "2",  "emoji": "💑"},
    "medical":       {"colour_id": "7",  "emoji": "🏥"},
    "school":        {"colour_id": "5",  "emoji": "🏫"},
    "sport":         {"colour_id": "6",  "emoji": "⚽"},
    "celebration":   {"colour_id": "3",  "emoji": "🎉"},
    "travel":        {"colour_id": "7",  "emoji": "✈️"},
    "general":       {"colour_id": "8",  "emoji": "📅"},
}

POLLEN_LEVELS = ["low", "moderate", "high", "very high"]

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# IN-MEMORY STATE
# ============================================================

pending_events = {}
pending_deletes = {}
pending_updates = {}

location_state = {
    "lat": DEFAULT_WEATHER_LAT,
    "lon": DEFAULT_WEATHER_LON,
    "name": DEFAULT_WEATHER_LOCATION,
    "source": "default"
}

# ============================================================
# GOOGLE CALENDAR SETUP
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events"
]


def get_calendar_service():
    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GOOGLE_TOKEN_FILE, "w") as token:
            token.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def get_events_for_day(target_date: datetime) -> list:
    service = get_calendar_service()
    tz = pytz.timezone(TIMEZONE)
    start = tz.localize(datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0))
    end = tz.localize(datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59))
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return events_result.get("items", [])


def search_events_by_name(query: str) -> list:
    service = get_calendar_service()
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    end = now + timedelta(days=365)
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        q=query,
        singleEvents=True,
        orderBy="startTime",
        maxResults=10,
    ).execute()
    results = events_result.get("items", [])
    if not results:
        first_word = query.split()[0]
        events_result = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            q=first_word,
            singleEvents=True,
            orderBy="startTime",
            maxResults=10,
        ).execute()
        results = events_result.get("items", [])
    return results


def check_for_clashes(event_data: dict) -> list:
    if event_data.get("all_day"):
        return []
    tz = pytz.timezone(TIMEZONE)
    try:
        proposed_dt = tz.localize(datetime.fromisoformat(f"{event_data['date']}T{event_data['time']}:00"))
    except Exception:
        return []
    existing_events = get_events_for_day(proposed_dt)
    clashes = []
    for event in existing_events:
        start = event.get("start", {})
        if "dateTime" in start:
            existing_dt = datetime.fromisoformat(start["dateTime"])
            if existing_dt.tzinfo is None:
                existing_dt = tz.localize(existing_dt)
            diff = abs((proposed_dt - existing_dt).total_seconds()) / 3600
            if diff < 1:
                clashes.append(event)
    return clashes


def create_calendar_event(event_data: dict) -> bool:
    service = get_calendar_service()
    tz = pytz.timezone(TIMEZONE)
    colour_info = COLOUR_MAP.get(event_data.get("category", "general"), COLOUR_MAP["general"])
    if event_data.get("all_day"):
        event_body = {
            "summary": event_data["title"],
            "start": {"date": event_data["date"]},
            "end": {"date": event_data["date"]},
            "colorId": colour_info["colour_id"],
        }
    else:
        start_dt = tz.localize(datetime.fromisoformat(f"{event_data['date']}T{event_data['time']}:00"))
        end_dt = start_dt + timedelta(hours=1)
        event_body = {
            "summary": event_data["title"],
            "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
            "colorId": colour_info["colour_id"],
        }
    if event_data.get("location"):
        event_body["location"] = event_data["location"]
    if event_data.get("recurrence"):
        event_body["recurrence"] = [event_data["recurrence"]]
    service.events().insert(calendarId=CALENDAR_ID, body=event_body).execute()
    return True


def delete_calendar_event(event_id: str) -> bool:
    service = get_calendar_service()
    service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
    return True


def update_calendar_event(event_id: str, updates: dict) -> bool:
    service = get_calendar_service()
    tz = pytz.timezone(TIMEZONE)
    event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
    if "title" in updates:
        event["summary"] = updates["title"]
    if "date" in updates or "time" in updates:
        existing_start = event.get("start", {})
        if "dateTime" in existing_start:
            existing_dt = datetime.fromisoformat(existing_start["dateTime"])
            new_date = updates.get("date", existing_dt.strftime("%Y-%m-%d"))
            new_time = updates.get("time", existing_dt.strftime("%H:%M"))
            new_dt = tz.localize(datetime.fromisoformat(f"{new_date}T{new_time}:00"))
            new_end = new_dt + timedelta(hours=1)
            event["start"] = {"dateTime": new_dt.isoformat(), "timeZone": TIMEZONE}
            event["end"] = {"dateTime": new_end.isoformat(), "timeZone": TIMEZONE}
        elif "date" in existing_start:
            new_date = updates.get("date", existing_start["date"])
            event["start"] = {"date": new_date}
            event["end"] = {"date": new_date}
    if "location" in updates:
        event["location"] = updates["location"]
    service.events().update(calendarId=CALENDAR_ID, eventId=event_id, body=event).execute()
    return True


# ============================================================
# WEATHER & POLLEN
# ============================================================

async def get_weather_data(lat: float, lon: float) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,precipitation_probability,weathercode,windspeed_10m,uv_index",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode,uv_index_max,sunrise,sunset",
        "timezone": DIGEST_TIMEZONE,
        "forecast_days": 2,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)
        return response.json()


async def get_pollen_data(lat: float, lon: float) -> dict:
    url = "https://air-quality-api.open-meteo.com/v1/air-quality"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "grass_pollen,tree_pollen,weed_pollen",
        "timezone": DIGEST_TIMEZONE,
        "forecast_days": 2,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)
        return response.json()


def get_weather_description(code: int) -> tuple:
    codes = {
        0: ("Clear sky", "☀️"),
        1: ("Mainly clear", "🌤️"),
        2: ("Partly cloudy", "⛅"),
        3: ("Overcast", "☁️"),
        45: ("Foggy", "🌫️"),
        48: ("Icy fog", "🌫️"),
        51: ("Light drizzle", "🌦️"),
        53: ("Drizzle", "🌦️"),
        55: ("Heavy drizzle", "🌧️"),
        61: ("Light rain", "🌧️"),
        63: ("Rain", "🌧️"),
        65: ("Heavy rain", "🌧️"),
        71: ("Light snow", "🌨️"),
        73: ("Snow", "❄️"),
        75: ("Heavy snow", "❄️"),
        77: ("Snow grains", "❄️"),
        80: ("Light showers", "🌦️"),
        81: ("Showers", "🌧️"),
        82: ("Heavy showers", "⛈️"),
        85: ("Snow showers", "🌨️"),
        86: ("Heavy snow showers", "❄️"),
        95: ("Thunderstorm", "⛈️"),
        96: ("Thunderstorm with hail", "⛈️"),
        99: ("Thunderstorm with heavy hail", "⛈️"),
    }
    return codes.get(code, ("Unknown", "🌡️"))


def classify_pollen(value: float) -> str:
    if value is None:
        return "none"
    if value < 10:
        return "low"
    elif value < 50:
        return "moderate"
    elif value < 200:
        return "high"
    else:
        return "very high"


def pollen_level_index(level: str) -> int:
    try:
        return POLLEN_LEVELS.index(level.lower())
    except ValueError:
        return -1


def should_warn_pollen(level: str) -> bool:
    return pollen_level_index(level) >= pollen_level_index(POLLEN_THRESHOLD)


def get_hour_weather(weather_data: dict, target_hour: int, today: bool = True) -> dict:
    try:
        hourly = weather_data.get("hourly", {})
        times = hourly.get("time", [])
        tz = pytz.timezone(DIGEST_TIMEZONE)
        now = datetime.now(tz)
        target_date = now.date() if today else (now + timedelta(days=1)).date()
        for i, time_str in enumerate(times):
            dt = datetime.fromisoformat(time_str)
            if dt.date() == target_date and dt.hour == target_hour:
                code = hourly.get("weathercode", [])[i] if i < len(hourly.get("weathercode", [])) else 0
                desc, emoji = get_weather_description(code)
                return {
                    "temp": round(hourly.get("temperature_2m", [])[i]) if i < len(hourly.get("temperature_2m", [])) else None,
                    "rain_prob": hourly.get("precipitation_probability", [])[i] if i < len(hourly.get("precipitation_probability", [])) else 0,
                    "uv": hourly.get("uv_index", [])[i] if i < len(hourly.get("uv_index", [])) else 0,
                    "wind": hourly.get("windspeed_10m", [])[i] if i < len(hourly.get("windspeed_10m", [])) else 0,
                    "description": desc,
                    "emoji": emoji,
                }
    except Exception as e:
        logger.error(f"Error getting hour weather: {e}")
    return {}


def get_hour_pollen(pollen_data: dict, target_hour: int, today: bool = True) -> dict:
    try:
        hourly = pollen_data.get("hourly", {})
        times = hourly.get("time", [])
        tz = pytz.timezone(DIGEST_TIMEZONE)
        now = datetime.now(tz)
        target_date = now.date() if today else (now + timedelta(days=1)).date()
        for i, time_str in enumerate(times):
            dt = datetime.fromisoformat(time_str)
            if dt.date() == target_date and dt.hour == target_hour:
                grass = classify_pollen(hourly.get("grass_pollen", [])[i] if i < len(hourly.get("grass_pollen", [])) else None)
                tree = classify_pollen(hourly.get("tree_pollen", [])[i] if i < len(hourly.get("tree_pollen", [])) else None)
                weed = classify_pollen(hourly.get("weed_pollen", [])[i] if i < len(hourly.get("weed_pollen", [])) else None)
                return {"grass": grass, "tree": tree, "weed": weed}
    except Exception as e:
        logger.error(f"Error getting hour pollen: {e}")
    return {}


def get_daily_summary(weather_data: dict, pollen_data: dict, today: bool = True) -> dict:
    try:
        daily = weather_data.get("daily", {})
        idx = 0 if today else 1
        code = daily.get("weathercode", [0])[idx]
        desc, emoji = get_weather_description(code)
        hourly_pollen = pollen_data.get("hourly", {})
        times = hourly_pollen.get("time", [])
        tz = pytz.timezone(DIGEST_TIMEZONE)
        now = datetime.now(tz)
        target_date = now.date() if today else (now + timedelta(days=1)).date()
        peak_grass = "none"
        peak_tree = "none"
        peak_weed = "none"
        for i, time_str in enumerate(times):
            dt = datetime.fromisoformat(time_str)
            if dt.date() == target_date:
                g = classify_pollen(hourly_pollen.get("grass_pollen", [])[i] if i < len(hourly_pollen.get("grass_pollen", [])) else None)
                t = classify_pollen(hourly_pollen.get("tree_pollen", [])[i] if i < len(hourly_pollen.get("tree_pollen", [])) else None)
                w = classify_pollen(hourly_pollen.get("weed_pollen", [])[i] if i < len(hourly_pollen.get("weed_pollen", [])) else None)
                if pollen_level_index(g) > pollen_level_index(peak_grass):
                    peak_grass = g
                if pollen_level_index(t) > pollen_level_index(peak_tree):
                    peak_tree = t
                if pollen_level_index(w) > pollen_level_index(peak_weed):
                    peak_weed = w
        return {
            "description": desc,
            "emoji": emoji,
            "temp_max": round(daily.get("temperature_2m_max", [None])[idx]),
            "temp_min": round(daily.get("temperature_2m_min", [None])[idx]),
            "rain_prob": daily.get("precipitation_probability_max", [0])[idx],
            "uv_max": daily.get("uv_index_max", [0])[idx],
            "peak_grass_pollen": peak_grass,
            "peak_tree_pollen": peak_tree,
            "peak_weed_pollen": peak_weed,
        }
    except Exception as e:
        logger.error(f"Error getting daily summary: {e}")
        return {}


async def geocode_city(city_name: str) -> dict:
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": city_name, "count": 1, "language": "en", "format": "json"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)
        data = response.json()
        results = data.get("results", [])
        if results:
            r = results[0]
            name = r.get("name", city_name)
            country = r.get("country", "")
            return {
                "lat": r["latitude"],
                "lon": r["longitude"],
                "name": f"{name}, {country}" if country else name,
            }
    return {}


def build_pollen_lines(daily: dict) -> list:
    """Build pollen warning lines from daily summary."""
    lines = []
    if should_warn_pollen(daily.get("peak_grass_pollen", "none")):
        lines.append(f"Grass — {daily['peak_grass_pollen'].title()}")
    if should_warn_pollen(daily.get("peak_tree_pollen", "none")):
        lines.append(f"Tree — {daily['peak_tree_pollen'].title()}")
    if should_warn_pollen(daily.get("peak_weed_pollen", "none")):
        lines.append(f"Weed — {daily['peak_weed_pollen'].title()}")
    return lines


# ============================================================
# CLAUDE INTEGRATION
# ============================================================

def format_events_with_claude(events: list, day_label: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    if not events:
        return f"📅 Nothing scheduled for {day_label}. Enjoy the free time!"
    events_text = []
    for event in events:
        summary = event.get("summary", "Untitled event")
        start = event.get("start", {})
        location = event.get("location", "")
        if "dateTime" in start:
            dt = datetime.fromisoformat(start["dateTime"])
            time_str = dt.strftime("%H:%M")
        else:
            time_str = "All day"
        line = f"- {summary} at {time_str}"
        if location:
            line += f" ({location})"
        events_text.append(line)
    events_summary = "\n".join(events_text)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system="""You are a friendly family calendar assistant.
Format calendar events into a warm easy to read Telegram message for a family group chat.
Rules:
- Use relevant emojis (🎂 birthdays, 🍽️ meals, 🏫 school, 🏥 medical, ⚽ sport, 🎉 celebrations, ✈️ travel, 📅 general)
- Use 24 hour clock for all times
- Keep it concise and friendly
- List all day events at the top
- List timed events in order
- End with a warm one line sign off
- No markdown headers or bullet points, just emojis and line breaks""",
        messages=[{"role": "user", "content": f"Here are the family calendar events for {day_label}:\n\n{events_summary}\n\nPlease format these into a friendly Telegram message."}]
    )
    return message.content[0].text


def format_week_with_claude(events_by_day: dict) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    if not any(events_by_day.values()):
        return "📅 Nothing in the calendar for the rest of this week. Enjoy the quiet!"
    lines = []
    for day_label, events in events_by_day.items():
        if not events:
            lines.append(f"{day_label}: Nothing on")
        else:
            for event in events:
                summary = event.get("summary", "Untitled")
                start = event.get("start", {})
                if "dateTime" in start:
                    dt = datetime.fromisoformat(start["dateTime"])
                    time_str = dt.strftime("%H:%M")
                else:
                    time_str = "All day"
                lines.append(f"{day_label}: {summary} at {time_str}")
    events_summary = "\n".join(lines)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system="""You are a friendly family calendar assistant.
Format a weekly calendar summary into a warm easy to read Telegram message.
Rules:
- Use relevant emojis for each event type
- Use 24 hour clock for all times
- Group events clearly by day with the day name as a header line
- Days with nothing on can be skipped or shown briefly
- Keep it friendly and warm
- End with a cheerful sign off for the week
- No markdown, just emojis and line breaks""",
        messages=[{"role": "user", "content": f"Here is the family calendar for the rest of this week:\n\n{events_summary}\n\nPlease format this into a friendly weekly summary for Telegram."}]
    )
    return message.content[0].text


def parse_event_with_claude(user_message: str) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today = datetime.now(pytz.timezone(TIMEZONE))
    today_str = today.strftime("%Y-%m-%d")
    day_of_week = today.strftime("%A")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=f"""You are a calendar event parser. Today is {day_of_week} {today_str}.
Extract event details from natural language and return ONLY a JSON object with no extra text.

JSON fields:
- title: string (event name)
- date: string (YYYY-MM-DD format)
- time: string or null (HH:MM in 24hr format, null if all day)
- all_day: boolean
- location: string or null
- category: one of: food, birthday, anniversary, medical, school, sport, celebration, travel, general
- recurrence: string or null (use "RRULE:FREQ=YEARLY" for birthdays/anniversaries, null otherwise)

Category guide:
- Dinner, lunch, breakfast, BBQ, restaurant = food
- Birthday = birthday
- Anniversary = anniversary
- Doctor, dentist, hospital, appointment = medical
- School, class, homework, teacher = school
- Football, gym, swimming, sport = sport
- Party, wedding, graduation = celebration
- Holiday, flight, trip, travel = travel
- Anything else = general

If you cannot parse a valid date, return: {{"error": "Could not understand the date"}}
If the message is not a calendar event, return: {{"error": "This does not appear to be an event"}}""",
        messages=[{"role": "user", "content": user_message}]
    )
    response_text = message.content[0].text.strip()
    try:
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {"error": "Could not parse the response"}


def parse_update_with_claude(user_message: str, current_event: dict) -> dict:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today = datetime.now(pytz.timezone(TIMEZONE))
    today_str = today.strftime("%Y-%m-%d")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=f"""You are a calendar update parser. Today is {today_str}.
The user wants to update an existing calendar event. Extract what they want to change.
Return ONLY a JSON object with only the fields that should be changed:
- title: string (new event name, if changing)
- date: string (YYYY-MM-DD, if changing)
- time: string (HH:MM 24hr, if changing)
- location: string (if changing)

Only include fields that are explicitly being changed. Return an empty object {{}} if nothing is clear.""",
        messages=[{"role": "user", "content": f"Current event: {current_event.get('summary')}. User wants to change: {user_message}"}]
    )
    response_text = message.content[0].text.strip()
    try:
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
        return json.loads(response_text)
    except json.JSONDecodeError:
        return {}


async def build_morning_digest(weather_data: dict, pollen_data: dict, events: list, is_weekend: bool, location_name: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    tz = pytz.timezone(DIGEST_TIMEZONE)
    today = datetime.now(tz)
    day_name = today.strftime("%A")
    date_str = today.strftime("%d %B %Y")
    daily = get_daily_summary(weather_data, pollen_data, today=True)
    event_contexts = []
    for event in events:
        start = event.get("start", {})
        summary = event.get("summary", "Untitled")
        if "dateTime" in start:
            dt = datetime.fromisoformat(start["dateTime"])
            hour = dt.hour
            time_str = dt.strftime("%H:%M")
            hour_weather = get_hour_weather(weather_data, hour, today=True)
            hour_pollen = get_hour_pollen(pollen_data, hour, today=True)
            advice = []
            if hour_weather.get("rain_prob", 0) >= RAIN_THRESHOLD:
                advice.append("take an umbrella")
            if hour_weather.get("uv", 0) >= UV_THRESHOLD:
                advice.append("apply sun cream")
            pollen_warnings = []
            if should_warn_pollen(hour_pollen.get("grass", "none")):
                pollen_warnings.append(f"grass pollen {hour_pollen['grass']}")
            if should_warn_pollen(hour_pollen.get("tree", "none")):
                pollen_warnings.append(f"tree pollen {hour_pollen['tree']}")
            if should_warn_pollen(hour_pollen.get("weed", "none")):
                pollen_warnings.append(f"weed pollen {hour_pollen['weed']}")
            event_contexts.append({
                "title": summary,
                "time": time_str,
                "weather_emoji": hour_weather.get("emoji", "📅"),
                "weather_desc": hour_weather.get("description", ""),
                "temp": hour_weather.get("temp"),
                "rain_prob": hour_weather.get("rain_prob", 0),
                "uv": hour_weather.get("uv", 0),
                "wind": hour_weather.get("wind", 0),
                "advice": advice,
                "pollen_warnings": pollen_warnings,
            })
        else:
            event_contexts.append({
                "title": summary,
                "time": "All day",
                "weather_emoji": "📅",
                "weather_desc": "",
                "temp": None,
                "advice": [],
                "pollen_warnings": [],
            })
    day_pollen = build_pollen_lines(daily)
    day_type = "weekend" if is_weekend else "weekday"
    prompt_parts = [
        f"Create a morning digest for the Fenech family for {day_name} {date_str}.",
        f"This is a {day_type}.",
        f"Location: {location_name}",
        f"\nOVERALL WEATHER TODAY:",
        f"Conditions: {daily.get('emoji', '')} {daily.get('description', '')}",
        f"High: {daily.get('temp_max')}°C, Low: {daily.get('temp_min')}°C",
        f"Max rain probability: {daily.get('rain_prob')}%",
        f"Max UV index: {daily.get('uv_max')}",
    ]
    if day_pollen:
        prompt_parts.append(f"\nPOLLEN ALERT for {HAYFEVER_NAME} (hay fever sufferer):")
        for p in day_pollen:
            prompt_parts.append(f"  {p}")
    if event_contexts:
        prompt_parts.append(f"\nTODAY'S EVENTS:")
        for ec in event_contexts:
            prompt_parts.append(f"\n  Event: {ec['title']} at {ec['time']}")
            if ec["temp"] is not None:
                prompt_parts.append(f"  Weather at this time: {ec['weather_emoji']} {ec['weather_desc']}, {ec['temp']}°C, rain {ec['rain_prob']}%, UV {ec['uv']}, wind {ec['wind']}km/h")
            if ec["advice"]:
                prompt_parts.append(f"  General advice: {', '.join(ec['advice'])}")
            if ec["pollen_warnings"]:
                prompt_parts.append(f"  Pollen at this time: {', '.join(ec['pollen_warnings'])} — warn {HAYFEVER_NAME} personally")
    else:
        prompt_parts.append("\nNo events today.")
    prompt_parts.append(f"""
FORMAT RULES:
- Start with a warm good morning greeting for the Fenech family
- Show the overall weather summary clearly at the top
- If there are pollen warnings, show a clear pollen alert section mentioning {HAYFEVER_NAME} by name
- List each event with its weather context and any advice
- For rain warnings suggest umbrella or waterproof jacket
- For UV warnings suggest sun cream
- For high wind suggest being aware outdoors
- For pollen, address {HAYFEVER_NAME} directly and suggest antihistamines
- If weekend, use a warm relaxed tone. If weekday, slightly more structured
- If no events, just give the weather summary and a warm message
- Use 24 hour clock for all times
- Use emojis throughout but keep it readable
- End with an encouraging sign off appropriate for the day
- No markdown, just emojis and line breaks
- Keep it concise — this is a mobile message""")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}]
    )
    return message.content[0].text


def build_confirmation_message(event_data: dict, clashes: list = None) -> str:
    colour_info = COLOUR_MAP.get(event_data.get("category", "general"), COLOUR_MAP["general"])
    emoji = colour_info["emoji"]
    try:
        date_obj = datetime.strptime(event_data["date"], "%Y-%m-%d")
        date_str = date_obj.strftime("%A %d %B %Y")
    except Exception:
        date_str = event_data["date"]
    lines = ["Got it! Here's what I'll add:\n",
             f"{emoji} *{event_data['title']}*",
             f"📅 {date_str}"]
    if not event_data.get("all_day") and event_data.get("time"):
        lines.append(f"⏰ {event_data['time']}")
    else:
        lines.append("⏰ All day")
    if event_data.get("location"):
        lines.append(f"📍 {event_data['location']}")
    if event_data.get("recurrence"):
        lines.append("🔁 Repeats every year")
    if clashes:
        lines.append("\n⚠️ *Heads up — there's already something at this time:*")
        for clash in clashes:
            clash_summary = clash.get("summary", "Untitled")
            clash_start = clash.get("start", {})
            if "dateTime" in clash_start:
                clash_dt = datetime.fromisoformat(clash_start["dateTime"])
                clash_time = clash_dt.strftime("%H:%M")
                lines.append(f"📅 {clash_summary} @ {clash_time}")
            else:
                lines.append(f"📅 {clash_summary} (all day)")
        lines.append("\nStill want to add this?")
    else:
        lines.append("\nIs that correct?")
    return "\n".join(lines)


def format_event_details(event: dict) -> str:
    summary = event.get("summary", "Untitled")
    start = event.get("start", {})
    location = event.get("location", "")
    if "dateTime" in start:
        dt = datetime.fromisoformat(start["dateTime"])
        date_str = dt.strftime("%A %d %B %Y")
        time_str = dt.strftime("%H:%M")
        details = f"📅 {date_str} ⏰ {time_str}"
    elif "date" in start:
        dt = datetime.strptime(start["date"], "%Y-%m-%d")
        date_str = dt.strftime("%A %d %B %Y")
        details = f"📅 {date_str} ⏰ All day"
    else:
        details = "📅 Date unknown"
    if location:
        details += f" 📍 {location}"
    return f"*{summary}*\n{details}"


# ============================================================
# SECURITY CHECKS
# ============================================================

def is_allowed(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS or ALLOWED_CHAT_IDS == [0]:
        logger.info(f"Message from chat ID: {update.effective_chat.id}")
        return True
    return update.effective_chat.id in ALLOWED_CHAT_IDS


def is_allowed_query(query) -> bool:
    if not ALLOWED_CHAT_IDS or ALLOWED_CHAT_IDS == [0]:
        return True
    return query.message.chat.id in ALLOWED_CHAT_IDS


# ============================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "👋 Hello! I'm your Family Calendar Bot.\n\n"
        "Here's what I can do:\n"
        "/whatsontoday — See today's events\n"
        "/whatsontomorrow — See tomorrow's events\n"
        "/whatsonthisweek — See the rest of this week\n"
        "/add <event> — Add a new event\n"
        "/delete <name> — Delete an event\n"
        "/update <name> — Update an event\n"
        "/weather — Quick weather summary for today\n"
        "/weatherdetail — Full hourly weather breakdown\n"
        "/setlocation <city> — Set location for weather\n"
        "/getlocation — Show current weather location\n\n"
        "Examples:\n"
        "/add Dinner at Mum's Saturday 19:00\n"
        "/add John's birthday March 15th\n"
        "/delete Dinner\n"
        "/update Doctor\n"
        "/setlocation Warsaw"
    )


async def whatsontoday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("Checking today's calendar... 📅")
    try:
        tz = pytz.timezone(TIMEZONE)
        today = datetime.now(tz)
        events = get_events_for_day(today)
        day_label = "today, " + today.strftime("%A %d %B")
        response = format_events_with_claude(events, day_label)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Error in whatsontoday: {e}")
        await update.message.reply_text("Sorry, I couldn't fetch today's events. Please try again.")


async def whatsontomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("Checking tomorrow's calendar... 📅")
    try:
        tz = pytz.timezone(TIMEZONE)
        tomorrow = datetime.now(tz) + timedelta(days=1)
        events = get_events_for_day(tomorrow)
        day_label = "tomorrow, " + tomorrow.strftime("%A %d %B")
        response = format_events_with_claude(events, day_label)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Error in whatsontomorrow: {e}")
        await update.message.reply_text("Sorry, I couldn't fetch tomorrow's events. Please try again.")


async def whatsonthisweek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text("Checking this week's calendar... 📅")
    try:
        tz = pytz.timezone(TIMEZONE)
        today = datetime.now(tz)
        days_until_sunday = 6 - today.weekday()
        end_of_week = today + timedelta(days=days_until_sunday)
        events_by_day = {}
        current = today
        while current.date() <= end_of_week.date():
            day_label = current.strftime("%A %d %B")
            events_by_day[day_label] = get_events_for_day(current)
            current += timedelta(days=1)
        response = format_week_with_claude(events_by_day)
        await update.message.reply_text(response)
    except Exception as e:
        logger.error(f"Error in whatsonthisweek: {e}")
        await update.message.reply_text("Sorry, I couldn't fetch this week's events. Please try again.")


async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    user_input = " ".join(context.args)
    if not user_input:
        await update.message.reply_text(
            "Please tell me what to add! For example:\n"
            "/add Dinner at Mum's Saturday 19:00\n"
            "/add John's birthday March 15th"
        )
        return
    await update.message.reply_text("Let me work that out... 🤔")
    try:
        event_data = parse_event_with_claude(user_input)
        if "error" in event_data:
            await update.message.reply_text(
                f"❌ {event_data['error']}\n\nPlease try again, for example:\n"
                "/add Dinner at Mum's Saturday 19:00"
            )
            return
        clashes = check_for_clashes(event_data)
        chat_id = update.effective_chat.id
        pending_events[chat_id] = event_data
        confirmation_msg = build_confirmation_message(event_data, clashes)
        keyboard = [[
            InlineKeyboardButton("✅ Yes, add it", callback_data="add_confirm_yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="add_confirm_no"),
        ]]
        await update.message.reply_text(
            confirmation_msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in add_event: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again.")


async def delete_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    user_input = " ".join(context.args)
    if not user_input:
        await update.message.reply_text("Please tell me what to delete! For example:\n/delete Dinner")
        return
    await update.message.reply_text(f"Searching for '{user_input}'... 🔍")
    try:
        matches = search_events_by_name(user_input)
        if not matches:
            await update.message.reply_text(
                f"❌ I couldn't find any upcoming events matching '{user_input}'.\n"
                "Check the spelling or try a shorter search term."
            )
            return
        chat_id = update.effective_chat.id
        pending_deletes[chat_id] = matches
        msg_lines = [f"Found {len(matches)} matching event(s):\n"]
        keyboard = []
        for i, event in enumerate(matches):
            msg_lines.append(format_event_details(event))
            msg_lines.append("")
            keyboard.append([InlineKeyboardButton(
                f"🗑️ Delete: {event.get('summary', 'Untitled')}",
                callback_data=f"del_{i}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="del_cancel")])
        await update.message.reply_text(
            "\n".join(msg_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in delete_event: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again.")


async def update_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    user_input = " ".join(context.args)
    if not user_input:
        await update.message.reply_text("Please tell me what to update! For example:\n/update Doctor")
        return
    await update.message.reply_text(f"Searching for '{user_input}'... 🔍")
    try:
        matches = search_events_by_name(user_input)
        if not matches:
            await update.message.reply_text(
                f"❌ I couldn't find any upcoming events matching '{user_input}'.\n"
                "Check the spelling or try a shorter search term."
            )
            return
        chat_id = update.effective_chat.id
        pending_updates[chat_id] = {"events": matches, "stage": "select"}
        msg_lines = [f"Found {len(matches)} matching event(s). Which one do you want to update?\n"]
        keyboard = []
        for i, event in enumerate(matches):
            msg_lines.append(format_event_details(event))
            msg_lines.append("")
            keyboard.append([InlineKeyboardButton(
                f"✏️ Update: {event.get('summary', 'Untitled')}",
                callback_data=f"upd_select_{i}"
            )])
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="upd_cancel")])
        await update.message.reply_text(
            "\n".join(msg_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error in update_event: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again.")


async def weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /weather command — brief weather summary."""
    if not is_allowed(update):
        return
    await update.message.reply_text("Fetching weather... 🌤️")
    try:
        weather_data = await get_weather_data(location_state["lat"], location_state["lon"])
        pollen_data = await get_pollen_data(location_state["lat"], location_state["lon"])
        daily = get_daily_summary(weather_data, pollen_data, today=True)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        tz = pytz.timezone(DIGEST_TIMEZONE)
        today = datetime.now(tz)
        pollen_lines = build_pollen_lines(daily)
        prompt = f"""Give a brief friendly weather summary for {location_state['name']} for today, {today.strftime('%A %d %B')}.

Weather data:
Conditions: {daily.get('emoji', '')} {daily.get('description', '')}
High: {daily.get('temp_max')}°C
Low: {daily.get('temp_min')}°C
Max rain probability: {daily.get('rain_prob')}%
Max UV index: {daily.get('uv_max')}
{"Pollen warnings for " + HAYFEVER_NAME + " (hay fever): " + ", ".join(pollen_lines) if pollen_lines else "Pollen: within acceptable levels"}

Format rules:
- Start with the location name and date
- Give a concise 2-3 line weather summary
- Mention rain if probability is {RAIN_THRESHOLD}% or above
- Mention UV if {UV_THRESHOLD} or above
- If pollen warnings exist, address {HAYFEVER_NAME} directly and suggest antihistamines
- Use 24 hour clock
- Use weather emojis
- Keep it short — this is a quick check
- No markdown, just emojis and line breaks"""
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        await update.message.reply_text(message.content[0].text)
    except Exception as e:
        logger.error(f"Error in weather: {e}")
        await update.message.reply_text("Sorry, I couldn't fetch the weather. Please try again.")


async def weather_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /weatherdetail command — full hourly breakdown."""
    if not is_allowed(update):
        return
    await update.message.reply_text("Fetching detailed weather forecast... 🌤️")
    try:
        weather_data = await get_weather_data(location_state["lat"], location_state["lon"])
        pollen_data = await get_pollen_data(location_state["lat"], location_state["lon"])
        daily = get_daily_summary(weather_data, pollen_data, today=True)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        tz = pytz.timezone(DIGEST_TIMEZONE)
        today = datetime.now(tz)
        current_hour = today.hour
        hourly_lines = []
        for hour in range(current_hour, 24, 2):
            hw = get_hour_weather(weather_data, hour, today=True)
            hp = get_hour_pollen(pollen_data, hour, today=True)
            if not hw:
                continue
            pollen_warnings = []
            if should_warn_pollen(hp.get("grass", "none")):
                pollen_warnings.append(f"grass {hp['grass']}")
            if should_warn_pollen(hp.get("tree", "none")):
                pollen_warnings.append(f"tree {hp['tree']}")
            if should_warn_pollen(hp.get("weed", "none")):
                pollen_warnings.append(f"weed {hp['weed']}")
            line = (
                f"{hour:02d}:00 — {hw.get('emoji', '')} {hw.get('description', '')}, "
                f"{hw.get('temp')}°C, rain {hw.get('rain_prob')}%, "
                f"UV {hw.get('uv')}, wind {hw.get('wind')}km/h"
            )
            if pollen_warnings:
                line += f" | Pollen: {', '.join(pollen_warnings)}"
            hourly_lines.append(line)
        pollen_day = build_pollen_lines(daily)
        prompt = f"""Give a detailed hourly weather forecast for {location_state['name']} for today, {today.strftime('%A %d %B')}.

Overall today:
Conditions: {daily.get('emoji', '')} {daily.get('description', '')}
High: {daily.get('temp_max')}°C, Low: {daily.get('temp_min')}°C
Max rain probability: {daily.get('rain_prob')}%
Max UV: {daily.get('uv_max')}
{"Peak pollen warnings for " + HAYFEVER_NAME + " (hay fever sufferer): " + ", ".join(pollen_day) if pollen_day else "Pollen: within acceptable levels today"}

Hourly breakdown (from now):
{chr(10).join(hourly_lines) if hourly_lines else "No more hours remaining today."}

Format rules:
- Start with location name and overall day summary
- Show each 2 hour slot clearly with time, conditions, temp and any warnings
- If rain probability hits {RAIN_THRESHOLD}% or above at any hour, flag it clearly
- If UV hits {UV_THRESHOLD} or above, suggest sun cream for that period
- If wind is above 30km/h mention it
- If pollen warnings exist at any hour, address {HAYFEVER_NAME} directly
- Give an overall pollen summary for the day if warnings exist
- Use 24 hour clock for all times
- Use weather emojis throughout
- End with a brief summary of what to expect for the rest of the day
- No markdown, just emojis and line breaks"""
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        await update.message.reply_text(message.content[0].text)
    except Exception as e:
        logger.error(f"Error in weather_detail: {e}")
        await update.message.reply_text("Sorry, I couldn't fetch the detailed weather. Please try again.")


async def set_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    city_input = " ".join(context.args)
    if not city_input:
        await update.message.reply_text(
            "Please provide a city name! For example:\n"
            "/setlocation Warsaw\n"
            "/setlocation Cape Town\n"
            "/setlocation Newport Shropshire"
        )
        return
    await update.message.reply_text(f"Looking up {city_input}... 🔍")
    try:
        result = await geocode_city(city_input)
        if not result:
            await update.message.reply_text(
                f"❌ I couldn't find '{city_input}'. Try a different spelling or nearby city."
            )
            return
        location_state["lat"] = result["lat"]
        location_state["lon"] = result["lon"]
        location_state["name"] = result["name"]
        location_state["source"] = "command"
        await update.message.reply_text(
            f"✅ Location updated!\n"
            f"📍 Now using: *{result['name']}*\n"
            f"Weather will now reflect this location.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in set_location: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again.")


async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    source_labels = {
        "live": "📡 Live location shared in group",
        "pin": "📌 Location pin shared in group",
        "command": "✏️ Manually set with /setlocation",
        "default": "🏠 Default home location from settings",
    }
    source = location_state.get("source", "default")
    source_label = source_labels.get(source, "Unknown")
    await update.message.reply_text(
        f"📍 Current weather location:\n"
        f"*{location_state['name']}*\n\n"
        f"Source: {source_label}\n\n"
        f"To change it:\n"
        f"/setlocation Warsaw\n"
        f"Or share your live location in the group",
        parse_mode="Markdown"
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    msg = update.message
    if msg.location:
        lat = msg.location.latitude
        lon = msg.location.longitude
        is_live = msg.location.live_period is not None
        source = "live" if is_live else "pin"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={"lat": lat, "lon": lon, "format": "json"},
                    headers={"User-Agent": "FamilyCalendarBot/1.0"},
                    timeout=10
                )
                data = response.json()
                address = data.get("address", {})
                city = address.get("city") or address.get("town") or address.get("village") or "Unknown"
                country = address.get("country", "")
                place_name = f"{city}, {country}" if country else city
        except Exception:
            place_name = f"{lat:.2f}, {lon:.2f}"
        location_state["lat"] = lat
        location_state["lon"] = lon
        location_state["name"] = place_name
        location_state["source"] = source
        location_type = "Live location" if is_live else "Location pin"
        await msg.reply_text(
            f"📍 {location_type} received!\n"
            f"Weather will now use: *{place_name}*\n"
            f"This will be reflected in the morning digest and weather commands.",
            parse_mode="Markdown"
        )


# ============================================================
# CALLBACK QUERY HANDLER
# ============================================================

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_allowed_query(query):
        return
    chat_id = query.message.chat.id
    data = query.data

    if data == "add_confirm_yes":
        if chat_id not in pending_events:
            await query.edit_message_text("⚠️ This confirmation has expired. Please use /add again.")
            return
        event_data = pending_events.pop(chat_id)
        try:
            create_calendar_event(event_data)
            colour_info = COLOUR_MAP.get(event_data.get("category", "general"), COLOUR_MAP["general"])
            emoji = colour_info["emoji"]
            await query.edit_message_text(
                f"Done! {emoji} *{event_data['title']}* has been added to the Family calendar! 🗓️",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error creating event: {e}")
            await query.edit_message_text("❌ Sorry, I couldn't add the event. Please try again.")

    elif data == "add_confirm_no":
        pending_events.pop(chat_id, None)
        await query.edit_message_text("No problem, event cancelled. Nothing was added. 👍")

    elif data.startswith("del_confirm_"):
        event_id = data.replace("del_confirm_", "")
        try:
            delete_calendar_event(event_id)
            pending_deletes.pop(chat_id, None)
            await query.edit_message_text("🗑️ Event deleted successfully.")
        except Exception as e:
            logger.error(f"Error deleting event: {e}")
            await query.edit_message_text("❌ Sorry, I couldn't delete the event. Please try again.")

    elif data == "del_cancel":
        pending_deletes.pop(chat_id, None)
        await query.edit_message_text("Cancelled. Nothing was deleted. 👍")

    elif data.startswith("del_"):
        if chat_id not in pending_deletes:
            await query.edit_message_text("⚠️ This has expired. Please use /delete again.")
            return
        index = int(data.split("_")[1])
        events = pending_deletes[chat_id]
        if index >= len(events):
            await query.edit_message_text("⚠️ Something went wrong. Please try /delete again.")
            return
        event = events[index]
        keyboard = [[
            InlineKeyboardButton("🗑️ Yes, delete it", callback_data=f"del_confirm_{event['id']}"),
            InlineKeyboardButton("❌ Cancel", callback_data="del_cancel"),
        ]]
        await query.edit_message_text(
            f"Are you sure you want to delete:\n\n{format_event_details(event)}\n\nThis cannot be undone.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data == "upd_cancel":
        pending_updates.pop(chat_id, None)
        await query.edit_message_text("Cancelled. Nothing was updated. 👍")

    elif data == "upd_confirm_yes":
        if chat_id not in pending_updates:
            await query.edit_message_text("⚠️ This has expired. Please use /update again.")
            return
        state = pending_updates.pop(chat_id)
        try:
            update_calendar_event(state["selected"]["id"], state["updates"])
            await query.edit_message_text(
                f"✅ *{state['selected'].get('summary', 'Event')}* has been updated! 🗓️",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error updating event: {e}")
            await query.edit_message_text("❌ Sorry, I couldn't update the event. Please try again.")

    elif data == "upd_confirm_no":
        pending_updates.pop(chat_id, None)
        await query.edit_message_text("Cancelled. Nothing was updated. 👍")

    elif data.startswith("upd_select_"):
        if chat_id not in pending_updates:
            await query.edit_message_text("⚠️ This has expired. Please use /update again.")
            return
        index = int(data.split("_")[2])
        events = pending_updates[chat_id]["events"]
        if index >= len(events):
            await query.edit_message_text("⚠️ Something went wrong. Please try /update again.")
            return
        selected = events[index]
        pending_updates[chat_id]["selected"] = selected
        pending_updates[chat_id]["stage"] = "awaiting_changes"
        await query.edit_message_text(
            f"Updating:\n\n{format_event_details(selected)}\n\n"
            f"What would you like to change? Just tell me, for example:\n"
            f"• Change the time to 20:00\n"
            f"• Move it to next Saturday\n"
            f"• Change the title to Family BBQ\n"
            f"• Change location to Grandma's house",
            parse_mode="Markdown"
        )


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    chat_id = update.effective_chat.id
    if update.message and update.message.location:
        await handle_location(update, context)
        return
    if chat_id not in pending_updates:
        return
    state = pending_updates[chat_id]
    if state.get("stage") != "awaiting_changes":
        return
    user_text = update.message.text
    selected = state["selected"]
    await update.message.reply_text("Got it, working that out... 🤔")
    try:
        updates = parse_update_with_claude(user_text, selected)
        if not updates:
            await update.message.reply_text(
                "❌ I couldn't understand what you want to change. Please try again, for example:\n"
                "• Change the time to 20:00\n"
                "• Move it to next Saturday"
            )
            return
        pending_updates[chat_id]["updates"] = updates
        pending_updates[chat_id]["stage"] = "confirming"
        change_lines = [f"Here's what I'll update on *{selected.get('summary', 'the event')}*:\n"]
        if "title" in updates:
            change_lines.append(f"📝 New title: {updates['title']}")
        if "date" in updates:
            try:
                dt = datetime.strptime(updates["date"], "%Y-%m-%d")
                change_lines.append(f"📅 New date: {dt.strftime('%A %d %B %Y')}")
            except Exception:
                change_lines.append(f"📅 New date: {updates['date']}")
        if "time" in updates:
            change_lines.append(f"⏰ New time: {updates['time']}")
        if "location" in updates:
            change_lines.append(f"📍 New location: {updates['location']}")
        change_lines.append("\nShall I go ahead?")
        keyboard = [[
            InlineKeyboardButton("✅ Yes, update it", callback_data="upd_confirm_yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="upd_confirm_no"),
        ]]
        await update.message.reply_text(
            "\n".join(change_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error parsing update: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again.")


# ============================================================
# MORNING DIGEST SCHEDULER
# ============================================================

async def send_morning_digest(app):
    logger.info("Sending morning digest...")
    try:
        tz = pytz.timezone(DIGEST_TIMEZONE)
        today = datetime.now(tz)
        is_weekend = today.weekday() >= 5
        events = get_events_for_day(today)
        try:
            weather_data = await get_weather_data(location_state["lat"], location_state["lon"])
            pollen_data = await get_pollen_data(location_state["lat"], location_state["lon"])
        except Exception as e:
            logger.error(f"Weather/pollen fetch failed: {e}")
            weather_data = {}
            pollen_data = {}
        digest = await build_morning_digest(
            weather_data, pollen_data, events, is_weekend, location_state["name"]
        )
        for chat_id in ALLOWED_CHAT_IDS:
            if chat_id != 0:
                try:
                    await app.bot.send_message(chat_id=chat_id, text=digest)
                except Exception as e:
                    logger.error(f"Failed to send digest to {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Error in morning digest: {e}")


# ============================================================
# MAIN
# ============================================================

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whatsontoday", whatsontoday))
    app.add_handler(CommandHandler("whatsontomorrow", whatsontomorrow))
    app.add_handler(CommandHandler("whatsonthisweek", whatsonthisweek))
    app.add_handler(CommandHandler("add", add_event))
    app.add_handler(CommandHandler("delete", delete_event))
    app.add_handler(CommandHandler("update", update_event))
    app.add_handler(CommandHandler("weather", weather))
    app.add_handler(CommandHandler("weatherdetail", weather_detail))
    app.add_handler(CommandHandler("setlocation", set_location))
    app.add_handler(CommandHandler("getlocation", get_location))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    try:
        digest_hour, digest_minute = map(int, DIGEST_TIME.split(":"))
    except Exception:
        digest_hour, digest_minute = 7, 0
        logger.warning(f"Could not parse DIGEST_TIME '{DIGEST_TIME}', defaulting to 07:00")

    async def post_init(application):
        scheduler = AsyncIOScheduler(timezone=DIGEST_TIMEZONE)
        scheduler.add_job(
            send_morning_digest,
            trigger="cron",
            hour=digest_hour,
            minute=digest_minute,
            args=[application],
        )
        scheduler.start()
        logger.info(f"Morning digest scheduled for {DIGEST_TIME} {DIGEST_TIMEZONE}")

    app.post_init = post_init

    logger.info("Family Calendar Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
