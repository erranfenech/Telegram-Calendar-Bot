#!/usr/bin/env python3
"""
Family Calendar Telegram Bot
Connects Telegram -> Claude -> Google Calendar
Commands:
  /whatsontoday    - List today's events
  /whatsontomorrow - List tomorrow's events
  /add <event>     - Add a new event with confirmation
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
# CONFIGURATION
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GOOGLE_CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE")
GOOGLE_TOKEN_FILE = "token.json"
CALENDAR_ID = os.environ.get("CALENDAR_ID")
TIMEZONE = "Europe/London"

# ============================================================
# SECURITY
# ============================================================

ALLOWED_CHAT_ID = 1143802660

# ============================================================
# COLOUR MAPPING
# Google Calendar colour IDs:
# 1=Lavender 2=Sage 3=Grape 4=Flamingo 5=Banana
# 6=Tangerine 7=Peacock 8=Graphite 9=Blueberry 10=Basil 11=Tomato
# ============================================================

COLOUR_MAP = {
    "food":          {"colour_id": "11", "emoji": "🍽️"},   # Tomato
    "birthday":      {"colour_id": "2",  "emoji": "🎂"},   # Sage
    "anniversary":   {"colour_id": "2",  "emoji": "💑"},   # Sage
    "medical":       {"colour_id": "7",  "emoji": "🏥"},   # Peacock
    "school":        {"colour_id": "5",  "emoji": "🏫"},   # Banana
    "sport":         {"colour_id": "6",  "emoji": "⚽"},   # Tangerine
    "celebration":   {"colour_id": "3",  "emoji": "🎉"},   # Grape
    "travel":        {"colour_id": "7",  "emoji": "✈️"},   # Peacock
    "general":       {"colour_id": "8",  "emoji": "📅"},   # Graphite
}

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
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE, SCOPES
            )
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


def create_calendar_event(event_data: dict) -> bool:
    """Create an event in Google Calendar. Returns True on success."""
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
        start_dt = datetime.fromisoformat(f"{event_data['date']}T{event_data['time']}:00")
        start_dt = tz.localize(start_dt)
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
- Use relevant emojis for each event type (🎂 birthdays, 🍽️ meals, 🏫 school, 🏥 medical, ⚽ sport, 🎉 celebrations, ✈️ travel, 📅 general)
- Keep it concise and friendly
- List all day events at the top
- List timed events in order with times in natural format
- End with a warm one line sign off
- Do not use markdown headers or bullet points, just emojis and line breaks""",
        messages=[
            {
                "role": "user",
                "content": f"Here are the family calendar events for {day_label}:\n\n{events_summary}\n\nPlease format these into a friendly Telegram message."
            }
        ]
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
        messages=[
            {
                "role": "user",
                "content": user_message
            }
        ]
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


def build_confirmation_message(event_data: dict) -> str:
    """Build a human-readable confirmation message for the user to approve."""
    colour_info = COLOUR_MAP.get(event_data.get("category", "general"), COLOUR_MAP["general"])
    emoji = colour_info["emoji"]

    try:
        date_obj = datetime.strptime(event_data["date"], "%Y-%m-%d")
        date_str = date_obj.strftime("%A %d %B %Y")
    except Exception:
        date_str = event_data["date"]

    lines = [
        f"Got it! Here's what I'll add:\n",
        f"{emoji} *{event_data['title']}*",
        f"📅 {date_str}",
    ]

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

    lines.append("\nIs that correct?")

    return "\n".join(lines)


# ============================================================
# TELEGRAM COMMAND HANDLERS
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store pending events awaiting confirmation
pending_events = {}


def is_allowed(update: Update) -> bool:
    """Check if the message comes from the allowed family chat."""
    return update.effective_chat.id == ALLOWED_CHAT_ID


def is_allowed_query(query) -> bool:
    """Check if a callback query comes from the allowed family chat."""
    return query.message.chat.id == ALLOWED_CHAT_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "👋 Hello! I'm your Family Calendar Bot.\n\n"
        "Here's what I can do:\n"
        "/whatsontoday — See today's events\n"
        "/whatsontomorrow — See tomorrow's events\n"
        "/add <event> — Add a new event\n\n"
        "Example:\n"
        "/add Dinner at Mum's Saturday 7pm\n"
        "/add John's birthday March 15th"
    )


async def whatsontoday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /whatsontoday command."""
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
    """Handle /whatsontomorrow command."""
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


async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /add command — parse event and ask for confirmation."""
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

        chat_id = update.effective_chat.id
        pending_events[chat_id] = event_data

        confirmation_msg = build_confirmation_message(event_data)

        # Inline Yes / No buttons
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, add it", callback_data="confirm_yes"),
                InlineKeyboardButton("❌ Cancel", callback_data="confirm_no"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            confirmation_msg,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"Error in add_event: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again.")


async def handle_confirmation_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Yes/No inline button presses."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press immediately

    if not is_allowed_query(query):
        return

    chat_id = query.message.chat.id

    if chat_id not in pending_events:
        await query.edit_message_text("⚠️ This confirmation has expired. Please use /add again.")
        return

    if query.data == "confirm_yes":
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

    elif query.data == "confirm_no":
        pending_events.pop(chat_id)
        await query.edit_message_text("No problem, event cancelled. Nothing was added. 👍")


# ============================================================
# MAIN
# ============================================================

def main():
    """Start the bot."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("whatsontoday", whatsontoday))
    app.add_handler(CommandHandler("whatsontomorrow", whatsontomorrow))
    app.add_handler(CommandHandler("add", add_event))
    app.add_handler(CallbackQueryHandler(handle_confirmation_button))

    logger.info("Family Calendar Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
