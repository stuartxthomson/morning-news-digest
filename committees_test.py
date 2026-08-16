import urllib.request
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


MEETINGS_URL = "https://www.ourcommons.ca/committees/en/Meetings"


def get_page(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Morning News Digest"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=20
    ) as response:

        return response.read().decode("utf-8")


def get_tomorrow_date():

    ottawa = ZoneInfo("America/Toronto")

    today = datetime.now(ottawa).date()

    return today + timedelta(days=1)


def get_committees():

    tomorrow = get_tomorrow_date()

    print()
    print("=" * 60)
    print(f"DIAGNOSTIC TEST — {tomorrow}")
    print("=" * 60)
    print()

    html = get_page(MEETINGS_URL)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    meeting_blocks = soup.select(
        "[id^='collapse-meeting-']"
    )

    print(
        f"Found {len(meeting_blocks)} meeting blocks."
    )

    print()

    for number, block in enumerate(
        meeting_blocks,
        start=1
    ):

        print("=" * 60)
        print(f"MEETING BLOCK {number}")
        print("=" * 60)

        print()

        # Print the HTML itself so we can see
        # exactly how the date is represented.
        print(block.prettify())

        print()


if __name__ == "__main__":

    get_committees()
