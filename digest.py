import feedparser
import socket
import os
import smtplib
import html
import urllib.request
import xml.etree.ElementTree as ET

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

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
    Get Ottawa's 7 a.m. forecast and today's forecast
    from Environment Canada.

    Returns:
        {
            "morning_temp": "18°C",
            "morning_condition": "Mainly sunny",
            "high": "27°C",
            "forecast": "Mainly sunny"
        }

    Returns None if the weather service cannot be reached.
    """

    weather_url = (
        "https://weather.gc.ca/rss/hourly/on-118_metric_e.xml"
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

            data = response.read()

        root = ET.fromstring(data)

        items = root.findall(".//item")

        today = datetime.now().date()

        morning_temp = None
        morning_condition = None
        daily_high = None
        daily_forecast = None

        for item in items:

            title_element = item.find("title")

            if title_element is None:
                continue

            title = title_element.text or ""

            description_element = item.find("description")

            if description_element is None:
                continue

            description = description_element.text or ""

            # Look for the 7 a.m. forecast.
            if "07:00" in title or "7:00" in title:

                morning_temp = extract_temperature(
                    title,
                    description
                )

                morning_condition = extract_condition(
                    title,
                    description
                )

            # Look for today's daily forecast.
            if (
                "Today" in title
                or "Today" in description
            ):

                daily_high = extract_high(
                    title,
                    description
                )

                daily_forecast = extract_condition(
                    title,
                    description
                )

        # If we couldn't find the required information,
        # return None so the news digest still works.
        if not morning_temp:
            return None

        return {
            "morning_temp": morning_temp,
            "morning_condition": morning_condition or "Forecast unavailable",
            "high": daily_high or "N/A",
            "forecast": daily_forecast or morning_condition or "Forecast unavailable"
        }

    except Exception as error:

        print("Could not retrieve Ottawa weather.")
        print(f"Error: {error}")

        return None


def extract_temperature(title, description):
    """Extract a temperature from Environment Canada's feed."""

    text = f"{title} {description}"

    import re

    match = re.search(
        r"(-?\d+)\s*°?C",
        text
    )

    if match:
        return f"{match.group(1)}°C"

    return None


def extract_high(title, description):
    """Extract today's high temperature."""

    text = f"{title} {description}"

    import re

    patterns = [
        r"High\s+(-?\d+)\s*°?C",
        r"high of\s+(-?\d+)\s*°?C",
        r"(-?\d+)\s*°?C.*high"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:
            return f"{match.group(1)}°C"

    return None


def extract_condition(title, description):
    """Extract the weather condition."""

    text = f"{title} {description}"

    common_conditions = [
        "A mix of sun and cloud",
        "Mainly sunny",
        "Sunny",
        "Partly cloudy",
        "Mostly cloudy",
        "Cloudy",
        "Clear",
        "A few clouds",
        "A few showers",
        "Showers",
        "Light rain",
        "Rain",
        "Chance of showers",
        "Chance of rain",
        "Periods of rain",
        "Thunderstorms",
        "Snow",
        "Chance of flurries",
        "Flurries"
    ]

    for condition in common_conditions:

        if condition.lower() in text.lower():
            return condition

    return None


weather = get_ottawa_weather()


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
            print(f"Could not retrieve {name}. Skipping it.")
            continue

        for article in feed.entries:

            published_time = article.get("published_parsed")

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

            category = classify_story(title)

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

        print(f"Error: {error}")


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

today = datetime.now().strftime(
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

text_lines.append(today)

text_lines.append("")


# Weather block.
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


text_lines.append(
    f"{len(all_stories)} news stories "
    f"from the last 30 hours."
)

text_lines.append("")


for source in sorted(stories_by_source):

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


# Weather HTML.
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


html_parts.append(
    f"<p>{len(all_stories)} news stories "
    f"from the last 30 hours.</p>"
)


# News stories.
for source in sorted(stories_by_source):

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


# Attach both versions.
message.set_content(
    plain_text
)

message.add_alternative(
    html_body,
    subtype="html"
)


# ---------------------------------------------------------
# SEND EMAIL
# ---------------------------------------------------------

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
    f"{len(all_stories)} news stories included."
)
