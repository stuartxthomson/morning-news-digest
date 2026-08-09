import feedparser
import socket

# Don't wait forever if a website doesn't respond.
socket.setdefaulttimeout(10)

feeds = {
    "CBC News": "https://rss.cbc.ca/lineup/topstories.xml",
    "CTV News": "https://www.ctvnews.ca/rss/ctvnews-ca-top-stories-public-rss-1.822009",
    "Global News": "https://globalnews.ca/feed/"
}

print("MORNING NEWS DIGEST")
print("=" * 50)

for name, url in feeds.items():
    print(f"\n{name}")
    print("-" * 50)

    feed = feedparser.parse(url)

    print(f"Found {len(feed.entries)} articles")

    for article in feed.entries[:5]:
        print(article.title)
        print(article.link)
        print()
