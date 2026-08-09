import feedparser
import socket
import os
import smtplib

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sources import FEEDS


# Don't wait forever if a website doesn't respond.
socket.setdefaulttimeout(10)


# Get our Gmail credentials from GitHub Secrets.
email_address = os.environ["EMAIL_ADDRESS"]
app_password = os.environ["EMAIL_APP_PASSWORD"]


# Look back 30 hours.
cutoff_time = datetime.now(timezone.utc) - timedelta(hours=30)


# This will hold all recent stories.
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


# Collect stories from every feed.
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

            story = {
                "source": name,
                "title": title,
                "link": link,
                "published": published,
                "category": classify_story(title)
            }

            all_stories.append(story)

    except Exception as error:

        print(f"Could not retrieve {name}. Skipping it.")
        print(f"Error: {error}")


# Sort newest first.
all_stories.sort(
    key=lambda story: story["published"],
    reverse=True
)


# Build the email.
message = EmailMessage()

today = datetime.now().strftime("%B %-d, %Y")

message["Subject"] = f"Morning News Digest — {today}"
message["From"] = email_address
message["To"] = email_address


# Plain-text version of the email.
text_lines = []

text_lines.append("MORNING NEWS DIGEST")
text_lines.append("")
text_lines.append(
    f"Stories from the last 30 hours: {len(all_stories)}"
)
text_lines.append("")


current_source = None

for story in all_stories:

    if story["source"] != current_source:

        current_source = story["source"]

        text_lines.append("")
        text_lines.append(current_source.upper())
        text_lines.append("-" * len(current_source))

    published = story["published"].strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    text_lines.append(
        f"{published} — {story['title']}"
    )

    text_lines.append(
        story["link"]
    )

    text_lines.append("")


message.set_content("\n".join(text_lines))


# Send the email through Gmail.
with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:

    smtp.login(email_address, app_password)

    smtp.send_message(message)


print(
    f"Digest sent successfully! "
    f"{len(all_stories)} stories included."
)
