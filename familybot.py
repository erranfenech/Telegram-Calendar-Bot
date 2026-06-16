#!/usr/bin/env python3
"""
Family Calendar Telegram Bot
Connects Telegram -> Claude -> Google Calendar
Commands:
  /whatsontoday    - List today's events
  /whatsontomorrow - List tomorrow's events
  /whatsonthisweek - List events from today to end of week
  /add <event>     - Add a new event with confirmation and clash detection
  /delete <name>   - Delete an event by name
  /update <name>   - Update an event by name
"""

import logging
import os
import json
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
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

# ============================================================
# SECURITY
# Supports multiple group chat IDs as a comma-separated list
# in .env: ALLOWED_CHAT_IDS=-123456789,-987654321
# Set to 0 or leave empty to allow all chats (for initial setup only)
# ============================================================

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

# ============================================================
# GOOGLE CALENDAR SETUP
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events"
]


def get_calendar_service():
    """Authenticate and return a Google Calendar service object."""
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
    """Fetch all calendar events for a given day."""
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


def get_events_for_range(start_date: datetime, end_date: datetime) -> list:
    """Fetch all calendar events between two dates."""
    service = get_calendar_service()
    tz = pytz.timezone(TIMEZONE)
    start = tz.localize(datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0))
    end = tz.localize(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59))
    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    return events_result.get("items", [])


def search_events_by_name(query: str) -> list:
    """Search for upcoming events by name."""
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

    # If no results, retry with just the first word
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
    """Check if the proposed event clashes with any existing events on the same day."""
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
    """Create an event in Google Calendar."""
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
    """Delete an event from Google Calendar by its ID."""
    service = get_calendar_service()
    service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
    return True


def update_calendar_event(event_id: str, updates: dict) -> bool:
    """Update specific fields of an existing Google Calendar event."""
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
# CLAUDE INTEGRATION
# ============================================================

def format_events_with_claude(events: list, day_label: str) -> str:
    """Format calendar events into a friendly Telegram message."""
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
            time_str = dt.strftime("%I:%M %p").lstrip("0")
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
Format calendar events into a warm, easy to read Telegram message for a family group chat.
Rules:
- Use relevant emojis (🎂 birthdays, 🍽️ meals, 🏫 school, 🏥 medical, ⚽ sport, 🎉 celebrations, ✈️ travel, 📅 general)
- Keep it concise and friendly
- List all day events at the top
- List timed events in order with times in natural format
- End with a warm one line sign off
- No markdown headers or bullet points, just emojis and line breaks""",
        messages=[{"role": "user", "content": f"Here are the family calendar events for {day_label}:\n\n{events_summary}\n\nPlease format these into a friendly Telegram message."}]
    )
    return message.content[0].text


def format_week_with_claude(events_by_day: dict) -> str:
    """Format a week's worth of events into a friendly Telegram message."""
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
                    time_str = dt.strftime("%I:%M %p").lstrip("0")
                else:
                    time_str = "All day"
                lines.append(f"{day_label}: {summary} at {time_str}")

    events_summary = "\n".join(lines)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system="""You are a friendly family calendar assistant.
Format a weekly calendar summary into a warm, easy to read Telegram message.
Rules:
- Use relevant emojis for each event type
- Group events clearly by day with the day name as a header line
- Days with nothing on can be skipped or shown briefly
- Keep it friendly and warm
- End with a cheerful sign off for the week
- No markdown, just emojis and line breaks""",
        messages=[{"role": "user", "content": f"Here is the family calendar for the rest of this week:\n\n{events_summary}\n\nPlease format this into a friendly weekly summary for Telegram."}]
    )
    return message.content[0].text


def parse_event_with_claude(user_message: str) -> dict:
    """Use Claude to parse a natural language event description into structured data."""
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
    """Use Claude to parse what the user wants to update about an event."""
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


def build_confirmation_message(event_data: dict, clashes: list = None) -> str:
    """Build a human-readable confirmation message, with clash warning if needed."""
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
        try:
            time_obj = datetime.strptime(event_data["time"], "%H:%M")
            time_str = time_obj.strftime("%I:%M %p").lstrip("0")
        except Exception:
            time_str = event_data["time"]
        lines.append(f"⏰ {time_str}")
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
                clash_time = clash_dt.strftime("%I:%M %p").lstrip("0")
                lines.append(f"📅 {clash_summary} @ {clash_time}")
            else:
                lines.append(f"📅 {clash_summary} (all day)")
        lines.append("\nStill want to add this?")
    else:
        lines.append("\nIs that correct?")

    return "\n".join(lines)


def format_event_details(event: dict) -> str:
    """Format a single event's details for display."""
    summary = event.get("summary", "Untitled")
    start = event.get("start", {})
    location = event.get("location", "")

    if "dateTime" in start:
        dt = datetime.fromisoformat(start["dateTime"])
        date_str = dt.strftime("%A %d %B %Y")
        time_str = dt.strftime("%I:%M %p").lstrip("0")
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
        "/update <name> — Update an event\n\n"
        "Examples:\n"
        "/add Dinner at Mum's Saturday 7pm\n"
        "/add John's birthday March 15th\n"
        "/delete Dinner\n"
        "/update Doctor"
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
            "/add Dinner at Mum's Saturday 7pm\n"
            "/add John's birthday March 15th"
        )
        return

    await update.message.reply_text("Let me work that out... 🤔")

    try:
        event_data = parse_event_with_claude(user_input)

        if "error" in event_data:
            await update.message.reply_text(
                f"❌ {event_data['error']}\n\nPlease try again, for example:\n"
                "/add Dinner at Mum's Saturday 7pm"
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
        await update.message.reply_text(
            "Please tell me what to delete! For example:\n"
            "/delete Dinner"
        )
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
        await update.message.reply_text(
            "Please tell me what to update! For example:\n"
            "/update Doctor"
        )
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


# ============================================================
# CALLBACK QUERY HANDLER — handles all button presses
# ============================================================

async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_allowed_query(query):
        return

    chat_id = query.message.chat.id
    data = query.data

    # ── ADD EVENT ───────────────────────────────────────────

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

    # ── DELETE EVENT — final confirmation first ─────────────

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

    # ── UPDATE EVENT ────────────────────────────────────────

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
            f"• Change the time to 8pm\n"
            f"• Move it to next Saturday\n"
            f"• Change the title to Family BBQ\n"
            f"• Change location to Grandma's house",
            parse_mode="Markdown"
        )


# ============================================================
# MESSAGE HANDLER — catches free text for update flow
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free text messages — used for the update flow."""
    if not is_allowed(update):
        return

    chat_id = update.effective_chat.id

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
                "• Change the time to 8pm\n"
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
            try:
                t = datetime.strptime(updates["time"], "%H:%M")
                change_lines.append(f"⏰ New time: {t.strftime('%I:%M %p').lstrip('0')}")
            except Exception:
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
# MAIN
# ============================================================

def main():
    """Start the bot."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whatsontoday", whatsontoday))
    app.add_handler(CommandHandler("whatsontomorrow", whatsontomorrow))
    app.add_handler(CommandHandler("whatsonthisweek", whatsonthisweek))
    app.add_handler(CommandHandler("add", add_event))
    app.add_handler(CommandHandler("delete", delete_event))
    app.add_handler(CommandHandler("update", update_event))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Family Calendar Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
