import feedparser
import socket
import os
import smtplib
import html

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


# Store all stories here.
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


# ---------------------------------------------------------
# COLLECT STORIES
# ---------------------------------------------------------

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

            title = article.get("title", "No title")
            link = article.get("link", "")

            category = classify_story(title)

            # For the MVP, only include regular news stories.
            if category != "news":
                continue

            story = {
                "source": name,
                "title": title,
                "link": link,
                "published": published
            }

            all_stories.append(story)

    except Exception as error:

        print(f"Could not retrieve {name}. Skipping it.")
        print(f"Error: {error}")


# ---------------------------------------------------------
# GROUP STORIES BY SOURCE
# ---------------------------------------------------------

stories_by_source = defaultdict(list)

for story in all_stories:
    stories_by_source[story["source"]].append(story)


# Sort each publication's stories newest first.
for source in stories_by_source:

    stories_by_source[source].sort(
        key=lambda story: story["published"],
        reverse=True
    )


# ---------------------------------------------------------
# BUILD THE EMAIL
# ---------------------------------------------------------

today = datetime.now().strftime("%B %-d, %Y")

message = EmailMessage()

message["Subject"] = f"Morning News Digest — {today}"
message["From"] = email_address
message["To"] = email_address


# ---------------------------------------------------------
# PLAIN-TEXT VERSION
# ---------------------------------------------------------

text_lines = []

text_lines.append("MORNING NEWS DIGEST")
text_lines.append(today)
text_lines.append("")
text_lines.append(
    f"{len(all_stories)} news stories from the last 30 hours."
)
text_lines.append("")


# Sort publications alphabetically.
for source in sorted(stories_by_source):

    text_lines.append("")
    text_lines.append(source.upper())
    text_lines.append("=" * len(source))

    for story in stories_by_source[source]:

        text_lines.append("")
        text_lines.append(f"• {story['title']}")
        text_lines.append(story["link"])


plain_text = "\n".join(text_lines)


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
    margin-bottom: 30px;
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

html_parts.append(html.escape(today))

html_parts.append("""
</div>
""")

html_parts.append(
    f"<p>{len(all_stories)} news stories from the last 30 hours.</p>"
)


# Add each publication.
for source in sorted(stories_by_source):

    html_parts.append(
        f'<div class="source">{html.escape(source)}</div>'
    )

    for story in stories_by_source[source]:

        title = html.escape(story["title"])
        link = html.escape(story["link"], quote=True)

        html_parts.append(
            f'''
            <div class="story">
                <a href="{link}">{title}</a>
            </div>
            '''
        )


html_parts.append("""
</div>

</body>
</html>
""")


html_body = "".join(html_parts)


# Attach both versions.
message.set_content(plain_text)

message.add_alternative(
    html_body,
    subtype="html"
)


# ---------------------------------------------------------
# SEND EMAIL
# ---------------------------------------------------------

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:

    smtp.login(email_address, app_password)

    smtp.send_message(message)


print(
    f"Digest sent successfully! "
    f"{len(all_stories)} news stories included."
)
