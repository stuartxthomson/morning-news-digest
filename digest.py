import feedparser
import socket
import re

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from sources import FEEDS

# Don't wait forever if a website doesn't respond.
socket.setdefaulttimeout(10)

# Only include stories published in the last 24 hours.
cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

# This will hold every recent story from every source.
all_stories = []


def classify_story(title):
    """Give each story a simple category based on its headline."""

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


def normalize_title(title):
    """
    Make headlines easier to compare.

    This removes punctuation, converts everything to lowercase,
    and removes a few common filler words.
    """

    title = title.lower()

    # Remove punctuation.
    title = re.sub(r"[^a-z0-9\s]", "", title)

    # Common words that don't help us identify a story.
    stop_words = {
        "the", "a", "an", "and", "of", "to", "in",
        "on", "for", "with", "as", "at", "by"
    }

    words = [
        word
        for word in title.split()
        if word not in stop_words
    ]

    return " ".join(words)


def similarity(title_one, title_two):
    """Return a similarity score between 0 and 1."""

    first = normalize_title(title_one)
    second = normalize_title(title_two)

    return SequenceMatcher(None, first, second).ratio()


def find_duplicates(stories):
    """
    Find groups of stories with very similar headlines.

    We use a fairly high threshold because we would rather
    miss a duplicate than accidentally merge two different stories.
    """

    duplicate_groups = []
    used = set()

    for i, story in enumerate(stories):

        if i in used:
            continue

        group = [story]

        for j in range(i + 1, len(stories)):

            if j in used:
                continue

            score = similarity(
                story["title"],
                stories[j]["title"]
            )

            if score >= 0.70:
                group.append(stories[j])
                used.add(j)

        if len(group) > 1:
            duplicate_groups.append(group)

    return duplicate_groups


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

            if not published_time:
                continue

            published = datetime(
                *published_time[:6],
                tzinfo=timezone.utc
            )

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


# Sort newest first.
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


# Find likely duplicate stories.
duplicate_groups = find_duplicates(all_stories)

print("\n\nPOSSIBLE DUPLICATES")
print("=" * 50)

if not duplicate_groups:

    print("No likely duplicate stories found.")

else:

    print(f"Found {len(duplicate_groups)} possible duplicate groups.")

    for number, group in enumerate(duplicate_groups, start=1):

        print(f"\nGROUP {number}")

        for story in group:

            print(
                f"- {story['source']}: "
                f"{story['title']}"
            )
