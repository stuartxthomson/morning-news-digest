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
    from Environment Canada's current hourly forecast page.

    Returns None if the weather service cannot be reached.
    """

    weather_url = (
        "https://weather.gc.ca/en/forecast/hourly/index.html"
        "?coords=45.4215,-75.6972"
    )

    try:

        request = urllib.request.Request(
            weather_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "(compatible; MorningNewsDigest/1.0)"
                )
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:

            page = response.read().decode("utf-8")

        # Environment Canada's current page contains
        # structured JSON-LD data that we can use.
        import re
        import json

        json_blocks = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>'
            r'(.*?)'
            r'</script>',
            page,
            re.DOTALL | re.IGNORECASE
        )

        forecast_data = None

        for block in json_blocks:

            try:

                data = json.loads(block.strip())

                if isinstance(data, dict):
                    forecast_data = data
                    break

            except json.JSONDecodeError:
                continue

        if not forecast_data:
            print(
                "Could not find structured weather data."
            )
            return None

        # The Environment Canada page structure can change,
        # so search the page text for the information we need.
        text = re.sub(
            r"<[^>]+>",
            " ",
            page
        )

        text = re.sub(
            r"\s+",
            " ",
            text
        )

        # Look for temperatures associated with 7 a.m.
        morning_match = re.search(
            r"7\s*:\s*00\s*a\.?m\.?.{0,300}?"
            r"(-?\d+)\s*°?\s*C",
            text,
            re.IGNORECASE
        )

        if not morning_match:

            morning_match = re.search(
                r"7\s*a\.?m\.?.{0,300}?"
                r"(-?\d+)\s*°?\s*C",
                text,
                re.IGNORECASE
            )

        if not morning_match:
            print(
                "Could not find Ottawa's 7 a.m. temperature."
            )
            return None

        morning_temp = (
            f"{morning_match.group(1)}°C"
        )

        # Look for today's high.
        high_match = re.search(
            r"(?:High|high)\s*"
            r"(-?\d+)\s*°?\s*C",
            text
        )

        daily_high = (
            f"{high_match.group(1)}°C"
            if high_match
            else "N/A"
        )

        # Try to identify the forecast description.
        conditions = [
            "Mainly sunny",
            "A mix of sun and cloud",
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

        daily_forecast = None

        for condition in conditions:

            if condition.lower() in text.lower():

                daily_forecast = condition
                break

        if not daily_forecast:
            daily_forecast = "Forecast unavailable"

        return {
            "morning_temp": morning_temp,
            "morning_condition": daily_forecast,
            "high": daily_high,
            "forecast": daily_forecast
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
