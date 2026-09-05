import feedparser
import os
import smtplib
import html
import urllib.request
import json
import re
import requests
import time

from bs4 import BeautifulSoup
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from sources import FEEDS


# =========================================================
# RUNTIME / NETWORK SETTINGS
# =========================================================

SCRIPT_START = time.perf_counter()

TORONTO_TZ = ZoneInfo("America/Toronto")

# Hard limits. A slow site gets skipped rather than holding
# up the entire digest.
FEED_TIMEOUT = 12
WEATHER_TIMEOUT = 10
COMMITTEE_TIMEOUT = 15
NOTICE_TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Morning News Digest/1.0)"
    )
}


def elapsed():
    return time.perf_counter() - SCRIPT_START


def log(message):
    print(f"[{elapsed():6.1f}s] {message}")


log("Digest starting.")


# =========================================================
# SETTINGS
# =========================================================

email_address = os.environ["EMAIL_ADDRESS"]
app_password = os.environ["EMAIL_APP_PASSWORD"]

now_toronto = datetime.now(TORONTO_TZ)
today_toronto = now_toronto.date()

# Keep your existing 30-hour window.
cutoff_time = datetime.now(timezone.utc) - timedelta(hours=30)


# =========================================================
# OTTAWA WEATHER
# =========================================================

def get_ottawa_weather():

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
            timeout=WEATHER_TIMEOUT
        ) as response:

            data = response.read().decode("utf-8")

        weather_data = json.loads(data)

        hourly = weather_data["hourly"]
        daily = weather_data["daily"]

        morning_index = None

        for i, forecast_time in enumerate(hourly["time"]):

            if forecast_time.endswith("T07:00"):
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


log("Checking Ottawa weather...")
weather = get_ottawa_weather()
log("Weather check complete.")


# =========================================================
# COMMITTEE SCRAPER
# =========================================================

COMMITTEE_MEETINGS_URL = (
    "https://www.ourcommons.ca/committees/en/Meetings"
)


def parse_committee_date(text):

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

            month_value = match.group("month")

            if month_value.isdigit():

                return datetime(
                    int(match.group("year")),
                    int(month_value),
                    int(match.group("day"))
                ).date()

            month_number = datetime.strptime(
                month_value.capitalize(),
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


def infer_relative_meeting_date(block):

    possible_text = []

    possible_text.append(
        block.get_text(
            " ",
            strip=True
        )
    )

    ancestor = block.parent

    for _ in range(4):

        if ancestor is None:
            break

        possible_text.append(
            ancestor.get_text(
                " ",
                strip=True
            )
        )

        ancestor = ancestor.parent

    combined_text = " ".join(
        possible_text
    )

    combined_lower = combined_text.lower()

    for label in [
        "later today",
        "earlier today",
        "today"
    ]:

        if label in combined_lower:

            return today_toronto

    if "tomorrow" in combined_lower:

        return today_toronto + timedelta(days=1)

    return None


def extract_notice_details(notice_url):

    details = {
        "subject": "",
        "witnesses": []
    }

    try:

        response = requests.get(
            notice_url,
            headers=HEADERS,
            timeout=NOTICE_TIMEOUT
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

        subject = ""

        for element in soup.find_all(
            string=re.compile(
                r"Meeting Requested Pursuant",
                re.IGNORECASE
            )
        ):

            candidate = element.parent.get_text(
                " ",
                strip=True
            )

            if candidate and len(candidate) > 20:

                subject = candidate
                break

        if not subject:

            lines = [
                line.strip()
                for line in text.splitlines()
                if line.strip()
            ]

            for i, line in enumerate(lines):

                if (
                    "Meeting Requested Pursuant" in line
                    or line.lower() == "subject:"
                ):

                    for candidate in lines[i:i + 5]:

                        if (
                            len(candidate) > 20
                            and "Committee clerk"
                            not in candidate
                            and "Notice of meeting"
                            not in candidate
                        ):

                            subject = candidate
                            break

                    if subject:
                        break

        details["subject"] = subject

        # -------------------------------------------------
        # WITNESSES
        # -------------------------------------------------

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
                    witness_index + 20
                ]:

                    if line.lower() in [
                        "committee clerk",
                        "evidence",
                        "minutes of proceedings"
                    ]:

                        break

                    if len(line) > 2:

                        if line not in [
                            "Watch on ParlVU",
                            "Notice of meeting",
                            "Meetings"
                        ]:

                            details["witnesses"].append(
                                line
                            )

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

        "minister",
        "prime minister",
        "privy council",
        "clerk of the privy council",
        "deputy minister",
        "chief of staff",
        "national security adviser",
        "national security",

        "cbc",
        "canadian broadcasting corporation",
        "gun control",
        "firearms",
        "carbon tax",
        "carbon pricing",

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

    return any(
        term in combined
        for term in important_terms
    )


def get_committee_meetings():

    meetings = []

    print("")
    print(
        f"Committee date we're looking for: "
        f"{today_toronto}"
    )

    try:

        response = requests.get(
            COMMITTEE_MEETINGS_URL,
            headers=HEADERS,
            timeout=COMMITTEE_TIMEOUT
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

            if "suspended" in status:

                print(
                    "Skipping suspended meeting."
                )

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
            # DATE / TIME
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

            date_source = "explicit date"

            if meeting_date is None:

                meeting_date = (
                    infer_relative_meeting_date(
                        block
                    )
                )

                date_source = "relative label"

            if meeting_date is None:

                block_text = block.get_text(
                    " ",
                    strip=True
                )

                meeting_date = parse_committee_date(
                    block_text
                )

                date_source = "block text"

            if meeting_date is None:

                print(
                    f"Could not determine date for "
                    f"{committee}. Skipping."
                )

                continue

            print(
                f"{committee}: {meeting_date} "
                f"({date_source})"
            )

            if meeting_date != today_toronto:

                print(
                    f"Skipping {committee}: "
                    f"not today's meeting."
                )

                continue

            # -------------------------------------------------
            # TIME
            # -------------------------------------------------

            time_text = date_text

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

            for attribute in block.select(
                ".meeting-card-attribute"
            ):

                attribute_text = attribute.get_text(
                    " ",
                    strip=True
                )

                if "Televised" in attribute_text:

                    broadcast = "Televised"
                    break

            if not broadcast:

                broadcast_element = (
                    block.select_one(
                        ".meeting-card-media-preview "
                        ".stream-type"
                    )
                )

                if broadcast_element:

                    broadcast = (
                        broadcast_element.get_text(
                            " ",
                            strip=True
                        )
                    )

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
                    notice_element.get(
                        "href",
                        ""
                    )
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

            meeting_id = block.get(
                "id",
                ""
            )

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

                notice_start = time.perf_counter()

                notice_details = (
                    extract_notice_details(
                        notice_url
                    )
                )

                notice_elapsed = (
                    time.perf_counter()
                    - notice_start
                )

                if notice_elapsed > 5:

                    print(
                        f"WARNING: Notice for "
                        f"{committee} took "
                        f"{notice_elapsed:.1f}s"
                    )

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

            meetings.append(meeting)

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


log("Checking House of Commons committees...")
committee_meetings = get_committee_meetings()
log("Committee scraping complete.")


# =========================================================
# STORY CLASSIFICATION
# =========================================================

def classify_story(title):

    title_lower = title.lower()

    # ---------------------------------------------------------
    # OBVIOUS NON-NEWS / NON-POLITICAL CONTENT
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # POLITICAL RELEVANCE
    # ---------------------------------------------------------

    political_score = 0

    strong_terms = [

        "prime minister",
        "parliament",
        "house of commons",
        "senate",
        "cabinet",
        "minister",
        "mp ",
        "mps ",
        "member of parliament",
        "conservative party",
        "liberal party",
        "ndp",
        "bloc québécois",
        "bloc quebecois",
        "green party",
        "new democratic party",
        "political party",
        "opposition",
        "caucus",
        "election",
        "elections",
        "by-election",
        "byelection",
        "legislation",
        "bill ",
        "confidence vote",
        "throne speech",
        "budget",
        "government",
        "federal government",
        "privy council",
        "elections canada"
    ]

    politician_terms = [

        "mark carney",
        "pierre poilievre",
        "danielle smith",
        "jagmeet singh",
        "yves-françois blanchet",
        "yves-francois blanchet",
        "elizabeth may",
        "donald trump",
        "justin trudeau",
        "christia freeland",
        "melanie joly",
        "dominique leblanc",
        "françois-philippe champagne",
        "francois-philippe champagne"
    ]

    policy_terms = [

        "tariff",
        "tariffs",
        "trade deal",
        "trade talks",
        "trade negotiations",
        "immigration",
        "asylum",
        "refugee",
        "border",
        "foreign interference",
        "national security",
        "defence",
        "defense",
        "military",
        "nato",
        "crime bill",
        "gun control",
        "firearms",
        "carbon tax",
        "carbon pricing",
        "tax hike",
        "tax cut",
        "taxes",
        "health transfer",
        "equalization",
        "pipeline",
        "energy policy",
        "oil and gas",
        "climate policy",
        "artificial intelligence policy",
        "housing policy",
        "affordable housing",
        "indigenous affairs",
        "first nations",
        "supreme court",
        "rcmp",
        "public safety",
        "foreign policy"
    ]

    institution_terms = [

        "ottawa",
        "parliament hill",
        "treasury board",
        "finance canada",
        "global affairs canada",
        "public safety canada",
        "immigration, refugees and citizenship canada",
        "ircc",
        "department of national defence",
        "national defence",
        "house committee",
        "parliamentary committee",
        "committee hearing"
    ]

    for term in strong_terms:

        if term in title_lower:

            political_score += 3

    for term in politician_terms:

        if term in title_lower:

            political_score += 4

    for term in policy_terms:

        if term in title_lower:

            political_score += 2

    for term in institution_terms:

        if term in title_lower:

            political_score += 1

    # ---------------------------------------------------------
    # TRUMP SPECIAL CASE
    # ---------------------------------------------------------

    if "trump" in title_lower:

        canadian_angle_terms = [

            "canada",
            "canadian",
            "carney",
            "poilievre",
            "ottawa",
            "tariff",
            "tariffs",
            "trade",
            "border",
            "north america",
            "mexico",
            "usmca",
            "cusma"
        ]

        if any(
            term in title_lower
            for term in canadian_angle_terms
        ):

            political_score += 3

        else:

            political_score -= 2

    if political_score >= 3:

        print(
            f"✓ POLITICAL ({political_score}): "
            f"{title}"
        )

        return "news"

    print(
        f"✗ NON-POLITICAL ({political_score}): "
        f"{title}"
    )

    return "non_political"


# =========================================================
# FETCH ONE FEED
# =========================================================

def fetch_feed(name, url):

    start = time.perf_counter()

    print(
        f"Checking {name}..."
    )

    try:

        # Use requests rather than feedparser's built-in
        # URL fetching so that the timeout is explicit.
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=FEED_TIMEOUT
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

        if feed.bozo and not feed.entries:

            elapsed_feed = (
                time.perf_counter()
                - start
            )

            print(
                f"WARNING: {name} returned no usable "
                f"entries after {elapsed_feed:.1f}s."
            )

            return name, []

        stories = []

        for article in feed.entries:

            published_time = (
                article.get(
                    "published_parsed"
                )
            )

            if not published_time:

                published_time = (
                    article.get(
                        "updated_parsed"
                    )
                )

            if not published_time:

                continue

            try:

                published = datetime(
                    *published_time[:6],
                    tzinfo=timezone.utc
                )

            except Exception:

                continue

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

            if category != "news":

                continue

            stories.append({

                "source": name,
                "title": title,
                "link": link,
                "published": published
            })

        elapsed_feed = (
            time.perf_counter()
            - start
        )

        if elapsed_feed > 5:

            print(
                f"WARNING: {name} took "
                f"{elapsed_feed:.1f}s "
                f"and produced {len(stories)} stories."
            )

        else:

            print(
                f"{name} completed in "
                f"{elapsed_feed:.1f}s "
                f"({len(stories)} stories)."
            )

        return name, stories

    except requests.exceptions.Timeout:

        elapsed_feed = (
            time.perf_counter()
            - start
        )

        print(
            f"TIMEOUT: {name} took "
            f"{elapsed_feed:.1f}s and was skipped."
        )

        return name, []

    except Exception as error:

        elapsed_feed = (
            time.perf_counter()
            - start
        )

        print(
            f"ERROR: {name} failed after "
            f"{elapsed_feed:.1f}s: {error}"
        )

        return name, []


# =========================================================
# COLLECT NEWS STORIES — IN PARALLEL
# =========================================================

log(
    f"Starting parallel collection from "
    f"{len(FEEDS)} news feeds..."
)

all_stories = []

feed_start = time.perf_counter()

with ThreadPoolExecutor(
    max_workers=min(8, len(FEEDS))
) as executor:

    future_to_name = {
        executor.submit(
            fetch_feed,
            name,
            url
        ): name

        for name, url in FEEDS.items()
    }

    for future in as_completed(
        future_to_name
    ):

        name = future_to_name[future]

        try:

            feed_name, stories = (
                future.result()
            )

            all_stories.extend(
                stories
            )

        except Exception as error:

            print(
                f"Unexpected error processing "
                f"{name}: {error}"
            )

feed_elapsed = (
    time.perf_counter()
    - feed_start
)

log(
    f"All feeds complete in "
    f"{feed_elapsed:.1f}s."
)


# =========================================================
# GROUP STORIES BY SOURCE
# =========================================================

stories_by_source = defaultdict(
    list
)

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


# =========================================================
# BUILD EMAIL
# =========================================================

today_display = now_toronto.strftime(
    "%B %-d, %Y"
)

message = EmailMessage()

message["Subject"] = (
    f"Morning News Digest — "
    f"{today_display}"
)

message["From"] = email_address
message["To"] = email_address


# =========================================================
# PLAIN TEXT VERSION
# =========================================================

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
            meeting["committee"]
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
                f"Notice: "
                f"{meeting['notice_url']}"
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


# =========================================================
# HTML VERSION
# =========================================================

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


# =========================================================
# WEATHER HTML
# =========================================================

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


# =========================================================
# COMMITTEES HTML
# =========================================================

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
                {html.escape(
                    meeting['committee']
                )}
            </div>
            """
        )

        html_parts.append(
            f"""
            <div class="committee-detail">
                🕒 {html.escape(
                    meeting['time']
                )}
            </div>
            """
        )

        if meeting["location"]:

            html_parts.append(
                f"""
                <div class="committee-detail">
                    📍 {html.escape(
                        meeting['location']
                    )}
                </div>
                """
            )

        if meeting["broadcast"]:

            html_parts.append(
                f"""
                <div class="committee-detail">
                    📺 {html.escape(
                        meeting['broadcast']
                    )}
                </div>
                """
            )

        if meeting["subject"]:

            html_parts.append(
                f"""
                <div class="committee-subject">
                    <strong>Subject:</strong>
                    {html.escape(
                        meeting['subject']
                    )}
                </div>
                """
            )

        elif meeting["studies"]:

            html_parts.append(
                """
                <div class="committee-subject">
                    <strong>
                        Study / Activity:
                    </strong>
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


# =========================================================
# STORY COUNT
# =========================================================

html_parts.append(
    f"<p>{len(all_stories)} news stories "
    f"from the last 30 hours.</p>"
)


# =========================================================
# NEWS STORIES HTML
# =========================================================

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


# =========================================================
# SEND EMAIL
# =========================================================

log("Preparing email...")

message.set_content(
    plain_text
)

message.add_alternative(
    html_body,
    subtype="html"
)

email_start = time.perf_counter()

try:

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
        timeout=20
    ) as smtp:

        smtp.login(
            email_address,
            app_password
        )

        smtp.send_message(
            message
        )

except Exception as error:

    log(
        f"EMAIL ERROR: {error}"
    )

    raise

email_elapsed = (
    time.perf_counter()
    - email_start
)

log(
    f"Email sent in {email_elapsed:.1f}s."
)


# =========================================================
# FINAL DIAGNOSTICS
# =========================================================

total_elapsed = elapsed()

print("")
print("=" * 60)
print("DIGEST COMPLETE")
print("=" * 60)
print(
    f"Total runtime: {total_elapsed:.1f} seconds"
)
print(
    f"News stories: {len(all_stories)}"
)
print(
    f"Committee meetings: "
    f"{len(committee_meetings)}"
)
print(
    f"Weather retrieved: "
    f"{'Yes' if weather else 'No'}"
)
print("=" * 60)
