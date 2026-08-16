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
    print(f"COMMITTEE MEETINGS FOR {tomorrow}")
    print("=" * 60)
    print()

    html = get_page(MEETINGS_URL)

    soup = BeautifulSoup(html, "html.parser")

    # Look for the meeting entries on the House page.
    meeting_links = soup.find_all("a")

    found = 0

    for link in meeting_links:

        text = link.get_text(" ", strip=True)

        if not text:
            continue

        # We are looking for links containing meeting times.
        if "a.m." not in text and "p.m." not in text:
            continue

        # Try to identify committee meeting links.
        if not any(
            committee in text
            for committee in [
                "FINA", "SECU", "ETHI", "OGGO", "PROC",
                "JUST", "INDU", "TRAN", "HESA", "CIMM",
                "ENVI", "FAAE", "NDDN", "PACP", "FOPO",
                "CHPC", "AGRI", "FEWO", "HUMA", "INAN",
                "LANG", "RNNR", "SRSR", "ACVA", "CIIT"
            ]
        ):
            continue

        found += 1

        print("MEETING")
        print("-" * 60)
        print(text)

        meeting_url = urljoin(MEETINGS_URL, link.get("href", ""))

        print()
        print("Meeting page:")
        print(meeting_url)
        print()

    if found == 0:
        print("No meetings were found.")
        print()
        print(
            "The House website may have changed its page structure."
        )

    print()
    print(f"Meetings found: {found}")


if __name__ == "__main__":
    get_committees()
