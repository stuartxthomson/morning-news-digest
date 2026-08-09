import feedparser
import socket
from datetime import datetime, timedelta, timezone

from sources import FEEDS

# Don't wait forever if a website doesn't respond.
socket.setdefaulttimeout(10)

# Only include stories published in the last 24 hours.
cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

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

        print(f"Feed contains {len(feed.entries)} total articles")

        # Diagnostic: show the dates of the five newest stories.
        print("Newest stories in feed:")

        for article in feed.entries[:5]:
            title = article.get("title", "No title")
            published_time = article.get("published_parsed")

            if published_time:
                published = datetime(
                    *published_time[:6],
                    tzinfo=timezone.utc
                )
                print(f"  {published.isoformat()} — {title}")
            else:
                print(f"  NO DATE — {title}")

        # Now filter to the last 24 hours.
        recent_articles = []

        for article in feed.entries:
            published_time = article.get("published_parsed")

            if published_time:
                published = datetime(
                    *published_time[:6],
                    tzinfo=timezone.utc
                )

                if published >= cutoff_time:
                    recent_articles.append(article)

        print(f"\nFound {len(recent_articles)} articles from the last 24 hours")

        for article in recent_articles[:5]:
            title = article.get("title", "No title")
            link = article.get("link", "No link")

            published_time = article.get("published_parsed")

            if published_time:
                published = datetime(
                    *published_time[:6],
                    tzinfo=timezone.utc
                )
                published_display = published.strftime("%Y-%m-%d %H:%M UTC")
            else:
                published_display = "Unknown date"

            print(published_display)
            print(title)
            print(link)
            print()

    except Exception as error:
        print("Could not retrieve this feed. Skipping it.")
        print(f"Error: {error}")
        continue
