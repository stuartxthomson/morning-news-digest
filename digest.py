import feedparser
import socket
from datetime import datetime, timedelta, timezone

from sources import FEEDS

# Don't wait forever if a website doesn't respond.
socket.setdefaulttimeout(10)

# Only include stories published in the last 24 hours.
cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

# This will hold every recent story from every source.
all_stories = []


def classify_story(title):
    """
    Give each story a simple category based on its headline.
    This is intentionally basic for now.
    """

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


print("MORNING NEWS DIGEST")
print("=" * 50)

for name, url in FEEDS.items():
    print(f"\n{name}")
    print("-" * 50)

    try:
        feed = feedparser.parse(url)

        if feed.bozo and not feed.entries:
            print("Could not retrieve this feed. Skipping it.")
            continue

        source_count = 0

        for article in feed.entries:
            published_time = article.get("published_parsed")

            # Skip articles without a usable publication date.
            if not published_time:
                continue

            published = datetime(
                *published_time[:6],
                tzinfo=timezone.utc
            )

            # Skip anything older than 24 hours.
            if published < cutoff_time:
                continue

            title = article.get("title", "No title")

            story = {
                "source": name,
                "title": title,
                "link": article.get("link", "No link"),
                "published": published,
                "category": classify_story(title)
            }

            all_stories.append(story)
            source_count += 1

        print(f"Found {source_count} recent articles")

    except Exception as error:
        print("Could not retrieve this feed. Skipping it.")
        print(f"Error: {error}")
        continue


# Sort everything by publication time, newest first.
all_stories.sort(
    key=lambda story: story["published"],
    reverse=True
)


print("\n\nALL RECENT STORIES")
print("=" * 50)

print(f"Total stories collected: {len(all_stories)}")

for story in all_stories:
    print(
        f"\n{story['published'].strftime('%Y-%m-%d %H:%M UTC')}"
    )
    print(f"Category: {story['category']}")
    print(f"{story['source']}: {story['title']}")
    print(story["link"])
