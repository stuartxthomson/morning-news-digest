import feedparser
import socket
import os
import smtplib
import html
import urllib.request
import urllib.parse
import json
import re
import requests

from bs4 import BeautifulSoup
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sources import FEEDS


# Don't wait forever if a website doesn't respond.
socket.setdefaulttimeout(10)


# ---------------------------------------------------------
# SETTINGS
# ---------------------------------------------------------

email_address = os.environ["EMAIL_ADDRESS"]
app_password = os.environ["EMAIL_APP_PASSWORD"]

cutoff_time = datetime.now(timezone.utc) - timedelta(hours=30)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Morning News Digest/1.0)"
    )
}


# ---------------------------------------------------------
# OTTAWA WEATHER
# ---------------------------------------------------------

def get_ottawa_weather():
    """
    Get Ottawa's 7 a.m. forecast from Open-Meteo.

    No API key or account is required.
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
# COMMITTEE SCRAPER
# ---------------------------------------------------------

COMMITTEE_MEETINGS_URL = (
    "https://www.ourcommons.ca/committees/en/Meetings"
)


def parse_committee_date(text):

    """
    Extract a date from a meeting card.

    This deliberately looks for the actual date rather than
    relying on labels such as 'Tomorrow', 'Later Today',
    or 'Earlier Today'.
    """

    if not text:
        return None

    patterns = [

        r"""
        (?P<month>
            January|February|March|April|May|June|
            July|August|September|October|November|December
        )
        \s+
        (?P<day>\d{1,2})
        (?:st|nd|rd|th)?
        ,?
        \s+
        (?P<year>\d{4})
        """,

        r"""
        (?P<year>\d{4})
        -
        (?P<month>\d{1,2})
        -
        (?P<day>\d{1,2})
        """
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.VERBOSE
        )

        if not match:
            continue

        try:

            if match.group("month").isdigit():

                return datetime(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day"))
                ).date()

            else:

                month_name = (
                    match.group("month").capitalize()
                )

                month_number = datetime.strptime(
                    month_name,
                    "%B"
                ).month

                return datetime(
                    int(match.group("year")),
                    month_number,
                    int(match.group("day"))
                ).date()

        except ValueError:
            return None

    return None


def extract_notice_details(notice_url):

    """
    Read the Notice of Meeting and extract the subject and
    witnesses.
    """

    details = {
        "subject": "",
        "witnesses": []
    }

    try:

        response = requests.get(
            notice_url,
            headers=HEADERS,
            timeout=15
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(
            "\n",
            strip=True
        )

        # -------------------------------------------------
        # SUBJECT
        # -------------------------------------------------

        subject_markers = [
            "Meeting Requested Pursuant to",
            "Study of",
            "Subject:"
        ]

        subject = ""

        for marker in subject_markers:

            index = text.find(marker)

            if index >= 0:

                possible = text[index:]

                lines = [
                    line.strip()
                    for line in possible.splitlines()
                    if line.strip()
                ]

                if lines:

                    for line in lines[:5]:

                        if (
                            "Committee clerk" not in line
                            and "2026-" not in line
                            and len(line) > 20
                        ):
                            subject = line
                            break

                if subject:
                    break

        # A more precise fallback for the common House format.
        if not subject:

            for element in soup.find_all(
                string=re.compile(
                    r"Meeting Requested Pursuant",
                    re.IGNORECASE
                )
            ):

                parent_text = element.parent.get_text(
                    " ",
                    strip=True
                )

                if parent_text:
                    subject = parent_text
                    break

        details["subject"] = subject


        # -------------------------------------------------
        # WITNESSES
        # -------------------------------------------------

        # Witnesses may appear under headings such as
        # "Witnesses" or "Appearing".
        witness_heading = None

        for heading in soup.find_all(
            ["h1", "h2", "h3", "h4", "strong", "b"]
        ):

            heading_text = heading.get_text(
                " ",
                strip=True
            ).lower()

            if heading_text in [
                "witnesses",
                "witnesses:",
                "appearing",
                "appearing:"
            ]:

                witness_heading = heading
                break

        if witness_heading:

            # Collect nearby list items.
            parent = witness_heading.parent

            if parent:

                for li in parent.find_all("li"):

                    witness = li.get_text(
                        " ",
                        strip=True
                    )

                    if witness:
                        details["witnesses"].append(
                            witness
                        )

        # Second approach: inspect text after "Witnesses".
        if not details["witnesses"]:

            lines = [
                line.strip()
                for line in text.splitlines()
                if line.strip()
            ]

            witness_index = None

            for i, line in enumerate(lines):

                if line.lower() in [
                    "witnesses",
                    "witnesses:"
                ]:

                    witness_index = i
                    break

            if witness_index is not None:

                for line in lines[
                    witness_index + 1:
                    witness_index + 15
                ]:

                    if line.lower() in [
                        "committee clerk",
                        "evidence",
                        "minutes of proceedings"
                    ]:
                        break

                    if len(line) > 2:
                        details["witnesses"].append(
                            line
                        )

        # Remove obvious duplicates.
        cleaned_witnesses = []

        for witness in details["witnesses"]:

            if witness not in cleaned_witnesses:
                cleaned_witnesses.append(
                    witness
                )

        details["witnesses"] = cleaned_witnesses

        return details

    except Exception as error:

        print(
            "Could not read Notice of Meeting:"
        )

        print(error)

        return details


def committee_is_important(meeting):

    """
    Flag meetings likely to be particularly useful to
    a political-news digest.
    """

    subject = (
        meeting.get("subject", "")
        .lower()
    )

    witnesses = " ".join(
        meeting.get("witnesses", [])
    ).lower()

    combined = (
        subject + " " + witnesses
    )

    important_terms = [

        # People / government
        "minister",
        "prime minister",
        "privy council",
        "clerk of the privy council",
        "deputy minister",
        "chief of staff",
        "national security adviser",
        "national security",

        # Political subjects
        "cbc",
        "canadian broadcasting corporation",
        "gun control",
        "firearms",
        "carbon tax",
        "carbon pricing",

        # Major controversies / institutions
        "nato",
        "military headquarters",
        "foreign interference",
        "election",
        "elections",
        "china",
        "russia",
        "iran",
        "israel",
        "hamas",
        "trump",
        "border",
        "tariff",
        "tariffs",
        "trade",
        "immigration",
        "crime",
        "policing",
        "rcmp"
    ]

    for term in important_terms:

        if term in combined:
            return True

    return False


def get_committee_meetings():

    """
    Retrieve all House of Commons committee meetings whose
    actual meeting date is TODAY.

    Important:
    We do NOT use 'Tomorrow', 'Later Today', or
    'Earlier Today' to determine whether a meeting belongs
    in the digest.

    We look for the actual date in each meeting block.
    """

    meetings = []

    today = datetime.now().date()

    print("")
    print("Checking House of Commons committees...")

    try:

        response = requests.get(
            COMMITTEE_MEETINGS_URL,
            headers=HEADERS,
            timeout=20
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        blocks = soup.select(
            "div[id^='collapse-meeting-']"
        )

        print(
            f"Found {len(blocks)} meeting blocks."
        )

        for block in blocks:

            # -------------------------------------------------
            # STATUS
            # -------------------------------------------------

            status_element = block.select_one(
                ".meeting-card-meeting-status"
            )

            status = ""

            if status_element:
                status = status_element.get_text(
                    " ",
                    strip=True
                ).lower()

            # Suspended meetings are historical meetings,
            # even though they may still appear on the page.
            if "suspended" in status:
                continue


            # -------------------------------------------------
            # COMMITTEE
            # -------------------------------------------------

            committee_element = block.select_one(
                ".meeting-card-committee-details-name"
            )

            if not committee_element:
                continue

            committee = committee_element.get_text(
                " ",
                strip=True
            )


            # -------------------------------------------------
            # ACTUAL DATE
            # -------------------------------------------------

            date_element = block.select_one(
                ".meeting-card-attribute[id^='meeting-datetime-']"
            )

            if not date_element:
                continue

            date_text = date_element.get_text(
                " ",
                strip=True
            )

            meeting_date = parse_committee_date(
                date_text
            )

            # Some current meetings omit the date from the
            # visible time, so inspect the entire block as a
            # fallback.
            if meeting_date is None:

                block_text = block.get_text(
                    " ",
                    strip=True
                )

                meeting_date = parse_committee_date(
                    block_text
                )

            # If we cannot establish the actual date, do not
            # guess.
            if meeting_date is None:
                continue

            # THIS IS THE IMPORTANT FIX.
            #
            # We compare the actual date with today's date.
            #
            # Therefore a meeting remains eligible after its
            # label changes from "Later Today" to
            # "Earlier Today".
            if meeting_date != today:
                continue


            # -------------------------------------------------
            # TIME
            # -------------------------------------------------

            time_text = date_text

            # Remove date if present.
            time_text = re.sub(
                r"""
                (?P<month>
                    January|February|March|April|May|June|
                    July|August|September|October|November|December
                )
                \s+\d{1,2}(?:st|nd|rd|th)?,?
                \s+\d{4}
                """,
                "",
                time_text,
                flags=re.IGNORECASE | re.VERBOSE
            )

            time_text = re.sub(
                r"\s+",
                " ",
                time_text
            ).strip()


            # -------------------------------------------------
            # LOCATION
            # -------------------------------------------------

            location_element = block.select_one(
                ".meeting-location"
            )

            location = ""

            if location_element:

                location = location_element.get_text(
                    " ",
                    strip=True
                )


            # -------------------------------------------------
            # BROADCAST
            # -------------------------------------------------

            broadcast = ""

            broadcast_element = block.select_one(
                ".meeting-card-media-preview .stream-type"
            )

            if broadcast_element:

                broadcast = broadcast_element.get_text(
                    " ",
                    strip=True
                )

            else:

                # Look for the television attribute.
                attributes = block.select(
                    ".meeting-card-attribute"
                )

                for attribute in attributes:

                    attribute_text = attribute.get_text(
                        " ",
                        strip=True
                    )

                    if "Televised" in attribute_text:

                        broadcast = "Televised"

                        break


            # -------------------------------------------------
            # STUDIES / ACTIVITIES
            # -------------------------------------------------

            studies = []

            for study in block.select(
                ".meeting-card-study"
            ):

                study_text = study.get_text(
                    " ",
                    strip=True
                )

                if study_text:
                    studies.append(
                        study_text
                    )


            # -------------------------------------------------
            # NOTICE URL
            # -------------------------------------------------

            notice_element = block.select_one(
                "a.btn-meeting-notice"
            )

            notice_url = ""

            if notice_element:

                notice_url = (
                    notice_element.get("href", "")
                )

                if notice_url.startswith("//"):

                    notice_url = (
                        "https:" + notice_url
                    )

                elif notice_url.startswith("/"):

                    notice_url = (
                        "https://www.ourcommons.ca"
                        + notice_url
                    )


            # -------------------------------------------------
            # MEETING PAGE
            # -------------------------------------------------

            meeting_id = block.get("id", "")

            meeting_page = (
                COMMITTEE_MEETINGS_URL
            )

            if meeting_id:

                meeting_page = (
                    COMMITTEE_MEETINGS_URL
                    + "#"
                    + meeting_id
                )


            # -------------------------------------------------
            # NOTICE DETAILS
            # -------------------------------------------------

            notice_details = {
                "subject": "",
                "witnesses": []
            }

            if notice_url:

                print(
                    f"Reading Notice of Meeting for "
                    f"{committee}..."
                )

                notice_details = (
                    extract_notice_details(
                        notice_url
                    )
                )


            # -------------------------------------------------
            # IMPORTANT FLAG
            # -------------------------------------------------

            meeting = {

                "committee": committee,
                "date": meeting_date,
                "time": time_text,
                "location": location,
                "broadcast": broadcast,
                "studies": studies,
                "meeting_page": meeting_page,
                "notice_url": notice_url,
                "subject": notice_details.get(
                    "subject",
                    ""
                ),
                "witnesses": notice_details.get(
                    "witnesses",
                    []
                )
            }

            meeting["important"] = (
                committee_is_important(
                    meeting
                )
            )

            meetings.append(
                meeting
            )

    except Exception as error:

        print(
            "Could not retrieve House of Commons "
            "committee meetings."
        )

        print(
            f"Error: {error}"
        )

        return []

    meetings.sort(
        key=lambda meeting: meeting["time"]
    )

    print(
        f"Today's committee meetings found: "
        f"{len(meetings)}"
    )

    return meetings


committee_meetings = get_committee_meetings()


# ---------------------------------------------------------
# COLLECT NEWS STORIES
# ---------------------------------------------------------

all_stories = []


def classify_story(title):

    """Give each story a simple category."""

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

            published_time = (
                article.get(
                    "published_parsed"
                )
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
    ].append(
        story
    )


for source in stories_by_source:

    stories_by_source[source].sort(
        key=lambda story: story["published"],
        reverse=True
    )


# ---------------------------------------------------------
# BUILD EMAIL
# ---------------------------------------------------------

today_display = datetime.now().strftime(
    "%B %-d, %Y"
)

message = EmailMessage()

message["Subject"] = (
    f"Morning News Digest — {today_display}"
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
    today_display
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
# COMMITTEES
# ---------------------------------------------------------

if committee_meetings:

    text_lines.append(
        "HOUSE OF COMMONS COMMITTEES"
    )

    text_lines.append("")

    for meeting in committee_meetings:

        if meeting["important"]:

            text_lines.append(
                "⭐ IMPORTANT MEETING"
            )

        text_lines.append(
            f"{meeting['committee']}"
        )

        text_lines.append(
            f"🕒 {meeting['time']}"
        )

        if meeting["location"]:

            text_lines.append(
                f"📍 {meeting['location']}"
            )

        if meeting["broadcast"]:

            text_lines.append(
                f"📺 {meeting['broadcast']}"
            )

        if meeting["subject"]:

            text_lines.append(
                f"Subject: {meeting['subject']}"
            )

        elif meeting["studies"]:

            text_lines.append(
                "Study / Activity:"
            )

            for study in meeting["studies"]:

                text_lines.append(
                    f"  • {study}"
                )

        if meeting["witnesses"]:

            text_lines.append(
                "Witnesses:"
            )

            for witness in meeting["witnesses"]:

                text_lines.append(
                    f"  • {witness}"
                )

        if meeting["notice_url"]:

            text_lines.append(
                f"Notice: {meeting['notice_url']}"
            )

        text_lines.append("")


    text_lines.append("")


text_lines.append(
    f"{len(all_stories)} news stories "
    f"from the last 30 hours."
)

text_lines.append("")


# ---------------------------------------------------------
# NEWS STORIES
# ---------------------------------------------------------

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

    for story in stories_by_source[
        source
    ]:

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

.weather {
    background-color: #f5f7f9;
    padding: 15px 18px;
    border-radius: 6px;
    margin-bottom: 25px;
}

.weather-title {
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}

.weather-line {
    font-size: 16px;
    margin: 5px 0;
}

.committees {
    background-color: #f5f7f9;
    padding: 15px 18px;
    border-radius: 6px;
    margin-bottom: 25px;
}

.committees-title {
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 0.5px;
    margin-bottom: 15px;
}

.committee {
    border-top: 1px solid #d5d5d5;
    padding-top: 12px;
    margin-top: 12px;
}

.committee:first-child {
    border-top: none;
    padding-top: 0;
    margin-top: 0;
}

.committee-name {
    font-size: 17px;
    font-weight: bold;
    margin-bottom: 5px;
}

.important {
    color: #b00020;
    font-size: 13px;
    font-weight: bold;
    margin-bottom: 4px;
}

.committee-detail {
    font-size: 14px;
    margin: 3px 0;
}

.committee-subject {
    font-size: 14px;
    margin-top: 8px;
    line-height: 1.4;
}

.committee-witnesses {
    font-size: 14px;
    margin-top: 8px;
}

.committee-witness {
    margin: 3px 0;
}

.notice {
    margin-top: 8px;
}

.notice a {
    color: #174a8b;
    text-decoration: none;
    font-size: 14px;
}

.notice a:hover {
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
    html.escape(
        today_display
    )
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
# COMMITTEES HTML
# ---------------------------------------------------------

if committee_meetings:

    html_parts.append(
        """
        <div class="committees">

            <div class="committees-title">
                HOUSE OF COMMONS COMMITTEES
            </div>
        """
    )

    for meeting in committee_meetings:

        html_parts.append(
            '<div class="committee">'
        )

        if meeting["important"]:

            html_parts.append(
                """
                <div class="important">
                    ⭐ IMPORTANT MEETING
                </div>
                """
            )

        html_parts.append(
            f"""
            <div class="committee-name">
                {html.escape(meeting['committee'])}
            </div>
            """
        )

        html_parts.append(
            f"""
            <div class="committee-detail">
                🕒 {html.escape(meeting['time'])}
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

        if meeting["broadcast"]:

            html_parts.append(
                f"""
                <div class="committee-detail">
                    📺 {html.escape(meeting['broadcast'])}
                </div>
                """
            )

        if meeting["subject"]:

            html_parts.append(
                f"""
                <div class="committee-subject">
                    <strong>Subject:</strong>
                    {html.escape(meeting['subject'])}
                </div>
                """
            )

        elif meeting["studies"]:

            html_parts.append(
                """
                <div class="committee-subject">
                    <strong>Study / Activity:</strong>
                </div>
                """
            )

            for study in meeting["studies"]:

                html_parts.append(
                    f"""
                    <div class="committee-detail">
                        • {html.escape(study)}
                    </div>
                    """
                )

        if meeting["witnesses"]:

            html_parts.append(
                """
                <div class="committee-witnesses">
                    <strong>Witnesses:</strong>
                </div>
                """
            )

            for witness in meeting["witnesses"]:

                html_parts.append(
                    f"""
                    <div class="committee-witness">
                        • {html.escape(witness)}
                    </div>
                    """
                )

        if meeting["notice_url"]:

            notice_link = html.escape(
                meeting["notice_url"],
                quote=True
            )

            html_parts.append(
                f"""
                <div class="notice">
                    <a href="{notice_link}">
                        View Notice of Meeting →
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
# STORY COUNT
# ---------------------------------------------------------

html_parts.append(
    f"<p>{len(all_stories)} news stories "
    f"from the last 30 hours.</p>"
)


# ---------------------------------------------------------
# NEWS STORIES HTML
# ---------------------------------------------------------

for source in sorted(
    stories_by_source
):

    html_parts.append(
        f'<div class="source">'
        f'{html.escape(source)}'
        f'</div>'
    )

    for story in stories_by_source[
        source
    ]:

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
    f"{len(all_stories)} news stories included "
    f"and {len(committee_meetings)} committee "
    f"meetings included."
)
