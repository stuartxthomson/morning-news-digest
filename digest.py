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

        import json

        weather_data = json.loads(data)

        hourly = weather_data["hourly"]
        daily = weather_data["daily"]

        # Find the 7 a.m. forecast.
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

        # Convert Open-Meteo weather codes into
        # simple descriptions.
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
