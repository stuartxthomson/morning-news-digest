import urllib.request
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin


MEETINGS_URL = "https://www.ourcommons.ca/committees/en/Meetings"


def get_page(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Morning News Digest"
        }
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def get_tomorrow_date():
    ottawa = ZoneInfo("America/Toronto")
    today = datetime.now(ottawa).date()
    return today + timedelta(days=1)


def get_committees():

    tomorrow = get_tomorrow_date()

    print()
    print("=" * 60)
    print(f"LOOKING FOR MEETINGS ON {tomorrow}")
    print("=" * 60)
    print()

    html = get_page(MEETINGS_URL)

    soup = BeautifulSoup(html, "html.parser")

    # Find all meeting containers on the page.
    meeting_blocks = soup.select(
        "[id^='collapse-meeting-']"
    )

    print(
        f"Found {len(meeting_blocks)} meeting blocks on the page."
    )
    print()

    found = 0

    for block in meeting_blocks:

        text = block.get_text(" ", strip=True)

        # -----------------------------------------------------
        # DATE CHECK
        # -----------------------------------------------------
        #
        # The House page uses "Tomorrow" for tomorrow's meetings.
        # We only want those meetings.
        #

        if "Tomorrow" not in text:
            continue

        found += 1

        print("=" * 60)
        print("MATCHING MEETING")
        print("=" * 60)

        print()
        print(text)

        # Look for links inside this specific meeting block.
        links = block.find_all("a")

        print()
        print("LINKS FOUND:")

        for link in links:

            link_text = link.get_text(" ", strip=True)

            href = link.get("href")

            if not href:
                continue

            full_url = urljoin(
                MEETINGS_URL,
                href
            )

            print()
            print(f"{link_text}")
            print(full_url)

        print()

    print("=" * 60)
    print(f"MEETINGS FOR TOMORROW FOUND: {found}")
    print("=" * 60)


if __name__ == "__main__":
    get_committees()
