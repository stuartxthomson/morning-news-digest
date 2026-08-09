import feedparser
import socket

from sources import FEEDS

# Don't wait forever if a website doesn't respond.
socket.setdefaulttimeout(10)

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

        print(f"Found {len(feed.entries)} articles")

        for article in feed.entries[:5]:
            print(article.title)
            print(article.link)
            print()

    except Exception as error:
        print("Could not retrieve this feed. Skipping it.")
        print(f"Error: {error}")
        continue
