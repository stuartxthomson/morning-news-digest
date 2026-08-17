import urllib.request
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin


MEETINGS_URL = "https://www.ourcommons.ca/committees/en/Meetings"
BASE_URL = "https://www.ourcommons.ca"


def get_page(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Morning News Digest)"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def get_upcoming_meetings():

    html = get_page(MEETINGS_URL)

    soup = BeautifulSoup(html, "html.parser")

    meeting_blocks = soup.select("[id^='collapse-meeting-']")

    print("=" * 60)
    print("HOUSE OF COMMONS COMMITTEE MEETINGS")
    print("=" * 60)
    print()

    print(f"Found {len(meeting_blocks)} meeting blocks on the page.")
    print()

    meetings = []

    for block in meeting_blocks:

        # ---------------------------------------------------------
        # Ignore suspended meetings
        # ---------------------------------------------------------

        suspended = block.select_one(".is-suspended")

        if suspended:
            continue

        # ---------------------------------------------------------
        # Committee name
        # ---------------------------------------------------------

        committee_link = block.select_one(
            ".meeting-card-committee-details-name a"
        )

        if not committee_link:
            continue

        committee_name = committee_link.get_text(
            " ",
            strip=True
        )

        committee_url = urljoin(
            BASE_URL,
            committee_link.get("href", "")
        )

        # ---------------------------------------------------------
        # Date / time
        #
        # Past meetings have a full date, e.g.:
        #
        # April 20, 2026 11:05 a.m. (EDT)
        #
        # Upcoming meetings have only the time, e.g.:
        #
        # 3:00 p.m. - 5:00 p.m. (EDT)
        # ---------------------------------------------------------

        datetime_element = block.select_one(
            ".meeting-card-attribute[id^='meeting-datetime-']"
        )

        if not datetime_element:
            continue

        datetime_text = datetime_element.get_text(
            " ",
            strip=True
        )

        # If the field contains a four-digit year, it is a
        # past/specific-date meeting rather than an upcoming one.
        if "2026" in datetime_text or "2025" in datetime_text:
            continue

        # ---------------------------------------------------------
        # Time
        # ---------------------------------------------------------

        meeting_time = datetime_text

        # ---------------------------------------------------------
        # Location
        # ---------------------------------------------------------

        location_element = block.select_one(
            ".meeting-location"
        )

        if location_element:
            location = location_element.get_text(
                " ",
                strip=True
            )
        else:
            location = "Location not listed"

        # ---------------------------------------------------------
        # Television / broadcast status
        # ---------------------------------------------------------

        attributes = block.select(
            ".meeting-card-attribute"
        )

        televised = "Not specified"

        for attribute in attributes:

            text = attribute.get_text(
                " ",
                strip=True
            ).lower()

            if "televised" in text:
                televised = "Televised"

            elif "no broadcast planned" in text:
                televised = "No broadcast planned"

        # ---------------------------------------------------------
        # Studies and activities
        # ---------------------------------------------------------

        study_elements = block.select(
            ".meeting-card-study"
        )

        studies = []

        for study in study_elements:

            text = study.get_text(
                " ",
                strip=True
            )

            if text:
                studies.append(text)

        # ---------------------------------------------------------
        # Notice of Meeting
        # ---------------------------------------------------------

        notice_link = block.select_one(
            "a.btn-meeting-notice"
        )

        if notice_link:

            notice_url = urljoin(
                BASE_URL,
                notice_link.get("href", "")
            )

        else:

            notice_url = None

        # ---------------------------------------------------------
        # Meeting ID
        # ---------------------------------------------------------

        meeting_id = block.get("id", "")

        meeting_id = meeting_id.replace(
            "collapse-meeting-",
            ""
        )

        # ---------------------------------------------------------
        # Store meeting
        # ---------------------------------------------------------

        meetings.append({
            "meeting_id": meeting_id,
            "committee": committee_name,
            "committee_url": committee_url,
            "time": meeting_time,
            "location": location,
            "televised": televised,
            "studies": studies,
            "notice_url": notice_url
        })

    return meetings


def main():

    try:

        meetings = get_upcoming_meetings()

    except Exception as e:

        print()
        print("ERROR:")
        print(e)
        return

    print("=" * 60)
    print("UPCOMING MEETINGS FOUND")
    print("=" * 60)
    print()

    if not meetings:

        print("No upcoming meetings found.")
        return

    for meeting in meetings:

        print("MEETING")
        print("-" * 60)

        print(
            f"{meeting['committee']}"
        )

        print(
            f"Time: {meeting['time']}"
        )

        print(
            f"Location: {meeting['location']}"
        )

        print(
            f"Broadcast: {meeting['televised']}"
        )

        print()

        print("Studies / Activities:")

        if meeting["studies"]:

            for study in meeting["studies"]:
                print(f"  - {study}")

        else:

            print("  None listed")

        print()

        print(
            f"Meeting page: "
            f"{BASE_URL}/committees/en/Meetings"
        )

        if meeting["notice_url"]:

            print(
                f"Notice of Meeting: "
                f"{meeting['notice_url']}"
            )

        else:

            print(
                "Notice of Meeting: Not available"
            )

        print()

    print("=" * 60)

    print(
        f"Total upcoming meetings: {len(meetings)}"
    )

    print("=" * 60)


if __name__ == "__main__":
    main()
