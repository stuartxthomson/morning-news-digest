import feedparser
import socket
import os
import smtplib
import html
import urllib.request
import json
import requests
import re

from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from urllib.parse import urljoin

from sources import FEEDS


# Don't wait forever if a website doesn't respond.
socket.setdefaulttimeout(10)


# Get Gmail credentials from GitHub Secrets.
email_address = os.environ["EMAIL_ADDRESS"]
app_password = os.environ["EMAIL_APP_PASSWORD"]


# Look back 30 hours.
cutoff_time = datetime.now(timezone.utc) - timedelta(hours=30)


# ---------------------------------------------------------
# OTTAWA WEATHER
# ---------------------------------------------------------

def get_ottawa_weather():
    """
    Get Ottawa's 7 a.m. forecast from Open-Meteo.
    """

    weather_url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=45.4215"
        "&longitude=-75.6972"
        "&hourly=temperature_2m,weather_code"
        "&daily=temperature_2m_max"
        "&timezone=America%2FToronto"
        "&forecast_days=1"
    )

    try:

        request = urllib.request.Request(
            weather_url,
            headers={
                "User-Agent": "Morning News Digest"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            data = response.read().decode("utf-8")

        weather_data = json.loads(data)

        hourly = weather_data["hourly"]
        daily = weather_data["daily"]

        morning_index = None

        for i, time in enumerate(hourly["time"]):

            if time.endswith("T07:00"):
                morning_index = i
                break

        if morning_index is None:

            print(
                "Could not find Ottawa's 7 a.m. forecast."
            )

            return None

        morning_temp = (
            hourly["temperature_2m"][morning_index]
        )

        weather_code = (
            hourly["weather_code"][morning_index]
        )

        daily_high = daily["temperature_2m_max"][0]

        weather_descriptions = {

            0: "Clear",
            1: "Mainly sunny",
            2: "Partly cloudy",
            3: "Cloudy",

            45: "Foggy",
            48: "Foggy",

            51: "Light drizzle",
            53: "Drizzle",
            55: "Heavy drizzle",

            61: "Light rain",
            63: "Rain",
            65: "Heavy rain",

            71: "Light snow",
            73: "Snow",
            75: "Heavy snow",

            80: "Light showers",
            81: "Showers",
            82: "Heavy showers",

            95: "Thunderstorms",
            96: "Thunderstorms",
            99: "Thunderstorms"
        }

        condition = weather_descriptions.get(
            weather_code,
            "Forecast unavailable"
        )

        return {
            "morning_temp": f"{round(morning_temp)}°C",
            "morning_condition": condition,
            "high": f"{round(daily_high)}°C",
            "forecast": condition
        }

    except Exception as error:

        print("Could not retrieve Ottawa weather.")
        print(f"Error: {error}")

        return None


weather = get_ottawa_weather()


# ---------------------------------------------------------
# HOUSE OF COMMONS COMMITTEE MEETINGS
# ---------------------------------------------------------

BASE_URL = "https://www.ourcommons.ca"
MEETINGS_URL = (
    "https://www.ourcommons.ca/committees/en/Meetings"
)


def clean_text(text):
    """Clean up whitespace in scraped text."""

    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def get_committees_page(url):

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        )
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    return response.text


def parse_committee_notice(notice_url):

    try:

        html_text = get_committees_page(
            notice_url
        )

    except Exception as error:

        print(
            f"Could not retrieve committee notice: "
            f"{error}"
        )

        return {
            "date": "",
            "time": "",
            "location": "",
            "televised": False,
            "subject": "",
            "witnesses": []
        }

    soup = BeautifulSoup(
        html_text,
        "html.parser"
    )

    text = soup.get_text(
        "\n",
        strip=True
    )

    lines = [
        clean_text(line)
        for line in text.splitlines()
        if clean_text(line)
    ]

    date_value = ""

    date_pattern = re.compile(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|"
        r"Saturday|Sunday), "
        r"(January|February|March|April|May|June|July|"
        r"August|September|October|November|December) "
        r"\d{1,2}, \d{4}$"
    )

    for line in lines:

        if date_pattern.match(line):

            date_value = line

            break


    time_value = ""

    time_pattern = re.compile(
        r"^\d{1,2}:\d{2}\s*(a\.m\.|p\.m\.)\s*to\s*"
        r"\d{1,2}:\d{2}\s*(a\.m\.|p\.m\.)$",
        re.IGNORECASE
    )

    for line in lines:

        if time_pattern.match(line):

            time_value = line

            break


    location_value = ""

    for line in lines:

        if (
            "Building" in line
            and (
                "Room" in line
                or "room" in line
            )
        ):

            location_value = line

            break


    televised = any(
        line.lower() == "televised"
        for line in lines
    )


    # The subject appears immediately before
    # "Committee clerk" on the notice.
    subject = ""

    clerk_index = None

    for i, line in enumerate(lines):

        if line.lower() == "committee clerk":

            clerk_index = i

            break


    if clerk_index is not None:

        candidates = []

        for line in lines[:clerk_index]:

            if len(line) > 50:

                candidates.append(line)

        if candidates:

            subject = candidates[-1]


    # -----------------------------------------------------
    # WITNESSES
    # -----------------------------------------------------

    witnesses = []

    witness_index = None

    for i, line in enumerate(lines):

        lower = line.lower()

        if lower in (
            "witnesses",
            "witness",
            "appearing",
            "appearing before the committee"
        ):

            witness_index = i

            break


    if witness_index is not None:

        for line in lines[witness_index + 1:]:

            lower = line.lower()

            if lower in (
                "committee clerk",
                "meeting agenda",
                "agenda",
                "notice of meeting"
            ):

                break

            if len(line) < 3:
                continue

            if lower.startswith(
                (
                    "standing committee",
                    "committee meeting",
                    "notices of meeting"
                )
            ):

                continue

            witnesses.append(line)


    cleaned_witnesses = []

    for witness in witnesses:

        if witness not in cleaned_witnesses:

            cleaned_witnesses.append(
                witness
            )


    return {
        "date": date_value,
        "time": time_value,
        "location": location_value,
        "televised": televised,
        "subject": subject,
        "witnesses": cleaned_witnesses
    }


def get_upcoming_committee_meetings():

    try:

        page_html = get_committees_page(
            MEETINGS_URL
        )

    except Exception as error:

        print(
            f"Could not retrieve committee meetings: "
            f"{error}"
        )

        return []


    soup = BeautifulSoup(
        page_html,
        "html.parser"
    )

    meeting_blocks = soup.select(
        "div.panel-collapse[id^='collapse-meeting-']"
    )

    print(
        f"Found {len(meeting_blocks)} committee "
        f"meeting blocks."
    )


    # Use Ottawa time, not GitHub runner time.
    today = datetime.now(
        ZoneInfo("America/Toronto")
    ).date()


    upcoming = []


    for block in meeting_blocks:

        # -----------------------------------------------------
        # Ignore suspended meetings.
        # -----------------------------------------------------

        status = block.select_one(
            ".meeting-card-meeting-status"
        )

        if status:

            status_text = clean_text(
                status.get_text(
                    " ",
                    strip=True
                )
            ).lower()

            if "suspended" in status_text:

                continue


        # -----------------------------------------------------
        # Committee name.
        # -----------------------------------------------------

        committee_link = block.select_one(
            ".meeting-card-committee-details-name a"
        )

        if not committee_link:

            continue

        committee_name = clean_text(
            committee_link.get_text(
                " ",
                strip=True
            )
        )


        # -----------------------------------------------------
        # Date / time.
        # -----------------------------------------------------

        datetime_element = block.select_one(
            ".meeting-card-attribute[id^='meeting-datetime-']"
        )

        if not datetime_element:

            continue

        datetime_text = clean_text(
            datetime_element.get_text(
                " ",
                strip=True
            )
        )


        meeting_date = None


        date_match = re.search(
            r"(January|February|March|April|May|June|July|"
            r"August|September|October|November|December) "
            r"\d{1,2}, \d{4}",
            datetime_text,
            re.IGNORECASE
        )


        if date_match:

            try:

                meeting_date = datetime.strptime(
                    date_match.group(0),
                    "%B %d, %Y"
                ).date()

            except ValueError:

                pass

        # -----------------------------------------------------
        # Upcoming meetings sometimes say "Today" or "Tomorrow"
        # rather than giving the date.
        # -----------------------------------------------------

        if meeting_date is None:
    
            for parent in block.parents:
        
                if parent is None:
                    break

                text = clean_text(
                    parent.get_text(
                        " ",
                        strip=True
                    )
                )

        if "Today" in text:
            meeting_date = today
            break

        if "Tomorrow" in text:
            meeting_date = (
                today + timedelta(days=1)
            )
            break


        if meeting_date is None:

            continue


        if meeting_date < today:

            continue


        # -----------------------------------------------------
        # Time.
        # -----------------------------------------------------

        time_text = datetime_text

        if date_match:

            time_text = (
                time_text
                .replace(
                    date_match.group(0),
                    ""
                )
                .strip()
            )


        # -----------------------------------------------------
        # Location.
        # -----------------------------------------------------

        location_element = block.select_one(
            ".meeting-location"
        )

        location = ""

        if location_element:

            location = clean_text(
                location_element.get_text(
                    " ",
                    strip=True
                )
            )


        # -----------------------------------------------------
        # Broadcast.
        # -----------------------------------------------------

        broadcast = ""

        broadcast_element = block.select_one(
            ".meeting-card-media-preview .stream-type"
        )

        if broadcast_element:

            broadcast = clean_text(
                broadcast_element.get_text(
                    " ",
                    strip=True
                )
            )


        # -----------------------------------------------------
        # Studies / activities.
        # -----------------------------------------------------

        studies = []

        for study in block.select(
            ".meeting-card-studies-list "
            ".meeting-card-study"
        ):

            study_text = clean_text(
                study.get_text(
                    " ",
                    strip=True
                )
            )

            if study_text:

                studies.append(
                    study_text
                )


        # -----------------------------------------------------
        # Notice link.
        # -----------------------------------------------------

        notice_link = block.select_one(
            "a.btn-meeting-notice"
        )

        notice_url = ""

        if (
            notice_link
            and notice_link.get("href")
        ):

            notice_url = urljoin(
                BASE_URL,
                notice_link["href"]
            )


        # -----------------------------------------------------
        # Meeting page.
        # -----------------------------------------------------

        meeting_id = (
            block.get("id", "")
            .replace(
                "collapse-meeting-",
                ""
            )
        )

        meeting_page = (
            f"{MEETINGS_URL}"
            f"#collapse-meeting-{meeting_id}"
        )


        meeting = {
            "committee": committee_name,
            "date": meeting_date,
            "time": time_text,
            "location": location,
            "broadcast": broadcast,
            "studies": studies,
            "meeting_page": meeting_page,
            "notice_url": notice_url
        }


        # -----------------------------------------------------
        # Read Notice of Meeting.
        # -----------------------------------------------------

        if notice_url:

            notice = parse_committee_notice(
                notice_url
            )

            meeting["notice"] = notice

        else:

            meeting["notice"] = {
                "date": "",
                "time": "",
                "location": "",
                "televised": False,
                "subject": "",
                "witnesses": []
            }


        upcoming.append(
            meeting
        )


    upcoming.sort(
        key=lambda meeting: (
            meeting["date"],
            meeting["time"]
        )
    )


    return upcoming


committee_meetings = (
    get_upcoming_committee_meetings()
)


# ---------------------------------------------------------
# COLLECT NEWS STORIES
# ---------------------------------------------------------

all_stories = []


def classify_story(title):

    title_lower = title.lower()

    if any(word in title_lower for word in [
        "recipe",
        "air fryer",
        "dorm-friendly"
    ]):

        return "lifestyle"


    if any(word in title_lower for word in [
        "letters:",
        "letter:",
        "opinion:",
        "column:",
        "view:"
    ]):

        return "opinion"


    if any(word in title_lower for word in [
        "podcast",
        "video",
        "gallery",
        "cartoonists"
    ]):

        return "feature"


    return "news"


for name, url in FEEDS.items():

    print(f"Checking {name}...")

    try:

        feed = feedparser.parse(url)

        if feed.bozo and not feed.entries:

            print(
                f"Could not retrieve {name}. "
                f"Skipping it."
            )

            continue


        for article in feed.entries:

            published_time = article.get(
                "published_parsed"
            )

            if not published_time:

                continue


            published = datetime(
                *published_time[:6],
                tzinfo=timezone.utc
            )


            if published < cutoff_time:

                continue


            title = article.get(
                "title",
                "No title"
            )


            link = article.get(
                "link",
                ""
            )


            category = classify_story(
                title
            )


            # MVP: only include regular news.
            if category != "news":

                continue


            all_stories.append({
                "source": name,
                "title": title,
                "link": link,
                "published": published
            })


    except Exception as error:

        print(
            f"Could not retrieve {name}. "
            f"Skipping it."
        )

        print(
            f"Error: {error}"
        )


# ---------------------------------------------------------
# GROUP STORIES BY SOURCE
# ---------------------------------------------------------

stories_by_source = defaultdict(list)


for story in all_stories:

    stories_by_source[
        story["source"]
    ].append(story)


for source in stories_by_source:

    stories_by_source[source].sort(
        key=lambda story: story["published"],
        reverse=True
    )


# ---------------------------------------------------------
# BUILD EMAIL
# ---------------------------------------------------------

today = datetime.now(
    ZoneInfo("America/Toronto")
).strftime(
    "%B %-d, %Y"
)


message = EmailMessage()


message["Subject"] = (
    f"Morning News Digest — {today}"
)


message["From"] = email_address
message["To"] = email_address


# ---------------------------------------------------------
# PLAIN TEXT VERSION
# ---------------------------------------------------------

text_lines = []


text_lines.append(
    "MORNING NEWS DIGEST"
)

text_lines.append(
    today
)

text_lines.append("")


# ---------------------------------------------------------
# WEATHER
# ---------------------------------------------------------

if weather:

    text_lines.append(
        "OTTAWA WEATHER"
    )

    text_lines.append(
        f"🌡️ {weather['morning_temp']} at 7 a.m."
    )

    text_lines.append(
        f"☀️ Today's forecast: "
        f"{weather['high']} — "
        f"{weather['forecast']}"
    )

    text_lines.append("")


# ---------------------------------------------------------
# COMMITTEE WATCH
# ---------------------------------------------------------

if committee_meetings:

    text_lines.append(
        "COMMITTEE WATCH"
    )

    text_lines.append("")


    for meeting in committee_meetings:

        notice = meeting["notice"]


        text_lines.append(
            f"🏛️ {meeting['committee']}"
        )

        text_lines.append(
            f"{meeting['time']} — "
            f"{notice['subject'] or 'Subject not listed'}"
        )


        if meeting["location"]:

            text_lines.append(
                f"📍 {meeting['location']}"
            )


        if (
            meeting["broadcast"]
            or notice["televised"]
        ):

            text_lines.append(
                "📺 Televised"
            )


        if notice["witnesses"]:

            text_lines.append(
                "Witnesses:"
            )

            for witness in notice["witnesses"]:

                text_lines.append(
                    f"  • {witness}"
                )


        if meeting["notice_url"]:

            text_lines.append(
                f"Notice: {meeting['notice_url']}"
            )


        text_lines.append("")


text_lines.append(
    f"{len(all_stories)} news stories "
    f"from the last 30 hours."
)

text_lines.append("")


for source in sorted(
    stories_by_source
):

    text_lines.append("")

    text_lines.append(
        source.upper()
    )

    text_lines.append(
        "=" * len(source)
    )


    for story in stories_by_source[source]:

        text_lines.append("")

        text_lines.append(
            f"• {story['title']}"
        )

        text_lines.append(
            story["link"]
        )


plain_text = "\n".join(
    text_lines
)


# ---------------------------------------------------------
# HTML VERSION
# ---------------------------------------------------------

html_parts = []


html_parts.append("""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">

<style>

body {
    font-family: Arial, Helvetica, sans-serif;
    color: #222222;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
}

.container {
    max-width: 700px;
    margin: 0 auto;
    padding: 30px 20px;
}

h1 {
    font-size: 28px;
    margin-bottom: 5px;
}

.date {
    color: #666666;
    margin-bottom: 25px;
}

.weather,
.committees {
    background-color: #f5f7f9;
    padding: 15px 18px;
    border-radius: 6px;
    margin-bottom: 25px;
}

.weather-title,
.committee-title {
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}

.weather-line {
    font-size: 16px;
    margin: 5px 0;
}

.committee {
    padding: 12px 0;
    border-top: 1px solid #dddddd;
}

.committee:first-of-type {
    border-top: none;
    padding-top: 0;
}

.committee-name {
    font-weight: bold;
    font-size: 16px;
    margin-bottom: 5px;
}

.committee-subject {
    font-size: 15px;
    line-height: 1.4;
    margin-bottom: 6px;
}

.committee-detail {
    font-size: 14px;
    color: #555555;
    margin: 3px 0;
}

.committee-link {
    font-size: 14px;
    margin-top: 6px;
}

.committee-link a {
    color: #174a8b;
    text-decoration: none;
}

.committee-link a:hover {
    text-decoration: underline;
}

.source {
    font-size: 20px;
    font-weight: bold;
    border-bottom: 2px solid #222222;
    padding-bottom: 6px;
    margin-top: 30px;
    margin-bottom: 12px;
}

.story {
    margin-bottom: 14px;
}

.story a {
    color: #174a8b;
    text-decoration: none;
    font-size: 16px;
    line-height: 1.4;
}

.story a:hover {
    text-decoration: underline;
}

</style>
</head>

<body>

<div class="container">

<h1>Morning News Digest</h1>

<div class="date">
""")


html_parts.append(
    html.escape(today)
)

html_parts.append(
    "</div>"
)


# ---------------------------------------------------------
# WEATHER HTML
# ---------------------------------------------------------

if weather:

    html_parts.append(
        f"""
        <div class="weather">

            <div class="weather-title">
                OTTAWA WEATHER
            </div>

            <div class="weather-line">
                🌡️ <strong>
                {html.escape(weather['morning_temp'])}
                at 7 a.m.
                </strong>
            </div>

            <div class="weather-line">
                ☀️ Today's forecast:
                <strong>
                {html.escape(weather['high'])}
                </strong>
                — {html.escape(weather['forecast'])}
            </div>

        </div>
        """
    )


# ---------------------------------------------------------
# COMMITTEE HTML
# ---------------------------------------------------------

if committee_meetings:

    html_parts.append(
        """
        <div class="committees">

            <div class="committee-title">
                🏛️ COMMITTEE WATCH
            </div>
        """
    )


    for meeting in committee_meetings:

        notice = meeting["notice"]


        html_parts.append(
            '<div class="committee">'
        )


        html_parts.append(
            f"""
            <div class="committee-name">
                {html.escape(meeting['committee'])}
            </div>
            """
        )


        subject = (
            notice["subject"]
            or "Subject not listed"
        )


        html_parts.append(
            f"""
            <div class="committee-subject">
                <strong>
                {html.escape(meeting['time'])}
                </strong>
                — {html.escape(subject)}
            </div>
            """
        )


        if meeting["location"]:

            html_parts.append(
                f"""
                <div class="committee-detail">
                    📍 {html.escape(meeting['location'])}
                </div>
                """
            )


        if (
            meeting["broadcast"]
            or notice["televised"]
        ):

            html_parts.append(
                """
                <div class="committee-detail">
                    📺 Televised
                </div>
                """
            )


        if notice["witnesses"]:

            html_parts.append(
                """
                <div class="committee-detail">
                    <strong>Witnesses:</strong>
                </div>
                """
            )

            for witness in notice["witnesses"]:

                html_parts.append(
                    f"""
                    <div class="committee-detail">
                        • {html.escape(witness)}
                    </div>
                    """
                )


        if meeting["notice_url"]:

            safe_notice_url = html.escape(
                meeting["notice_url"],
                quote=True
            )

            html_parts.append(
                f"""
                <div class="committee-link">
                    <a href="{safe_notice_url}">
                        Notice of Meeting →
                    </a>
                </div>
                """
            )


        html_parts.append(
            "</div>"
        )


    html_parts.append(
        "</div>"
    )


# ---------------------------------------------------------
# NEWS COUNT
# ---------------------------------------------------------

html_parts.append(
    f"<p>{len(all_stories)} news stories "
    f"from the last 30 hours.</p>"
)


# ---------------------------------------------------------
# NEWS STORIES
# ---------------------------------------------------------

for source in sorted(
    stories_by_source
):

    html_parts.append(
        f'<div class="source">'
        f'{html.escape(source)}'
        f'</div>'
    )


    for story in stories_by_source[source]:

        title = html.escape(
            story["title"]
        )

        link = html.escape(
            story["link"],
            quote=True
        )


        html_parts.append(
            f"""
            <div class="story">
                <a href="{link}">
                    {title}
                </a>
            </div>
            """
        )


html_parts.append("""
</div>

</body>
</html>
""")


html_body = "".join(
    html_parts
)


# ---------------------------------------------------------
# SEND EMAIL
# ---------------------------------------------------------

message.set_content(
    plain_text
)

message.add_alternative(
    html_body,
    subtype="html"
)


with smtplib.SMTP_SSL(
    "smtp.gmail.com",
    465
) as smtp:

    smtp.login(
        email_address,
        app_password
    )

    smtp.send_message(
        message
    )


print(
    f"Digest sent successfully! "
    f"{len(all_stories)} news stories included. "
    f"{len(committee_meetings)} committee meetings included."
)
