import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urljoin
import re

BASE_URL = "https://www.ourcommons.ca"
MEETINGS_URL = "https://www.ourcommons.ca/committees/en/Meetings"


def clean_text(text):
    """Clean up whitespace in scraped text."""
    return re.sub(r"\s+", " ", text).strip()


def get_page(url):
    """Retrieve a webpage."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        )
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def get_upcoming_meetings():
    """Find genuinely upcoming meetings from the House of Commons meetings page."""

    html = get_page(MEETINGS_URL)
    soup = BeautifulSoup(html, "html.parser")

    meeting_blocks = soup.select("div.panel-collapse[id^='collapse-meeting-']")

    print(f"Found {len(meeting_blocks)} meeting blocks on the page.")
    print()

    today = datetime.now(ZoneInfo("America/Toronto")).date()
    upcoming = []

    for block in meeting_blocks:

        # ------------------------------------------------------------
        # Ignore suspended meetings
        # ------------------------------------------------------------
        status = block.select_one(".meeting-card-meeting-status")

        if status:
            status_text = clean_text(status.get_text(" ", strip=True)).lower()

            if "suspended" in status_text:
                continue

        # ------------------------------------------------------------
        # Committee name
        # ------------------------------------------------------------
        committee_link = block.select_one(
            ".meeting-card-committee-details-name a"
        )

        if not committee_link:
            continue

        committee_name = clean_text(committee_link.get_text(" ", strip=True))

        # ------------------------------------------------------------
        # Meeting date/time
        # ------------------------------------------------------------
        datetime_element = block.select_one(
            ".meeting-card-attribute[id^='meeting-datetime-']"
        )

        if not datetime_element:
            continue

        datetime_text = clean_text(
            datetime_element.get_text(" ", strip=True)
        )

        # The page displays the actual date for past meetings,
        # but upcoming meetings may display only the time because
        # the page groups them under "Tomorrow", "Today", etc.
        #
        # We therefore use the page's surrounding accordion heading
        # when necessary and explicitly recognize "Tomorrow".
        meeting_date = None

        # Look for an explicit date anywhere in the meeting block.
        date_match = re.search(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+\d{1,2},\s+\d{4}",
            datetime_text,
            re.IGNORECASE,
        )

        if date_match:
            try:
                meeting_date = datetime.strptime(
                    date_match.group(0),
                    "%B %d, %Y"
                ).date()
            except ValueError:
                pass

        # If there is no explicit date, look at the page heading/group.
        if meeting_date is None:
            for parent in block.parents:
                if parent is None:
                    break

                text = clean_text(parent.get_text(" ", strip=True))

                if "Tomorrow" in text:
                    meeting_date = today + timedelta(days=1)
                    break

        # ------------------------------------------------------------
        # If we still can't determine the date, skip it.
        # ------------------------------------------------------------
        if meeting_date is None:
            continue

        # Only keep future meetings.
        if meeting_date < today:
            continue

        # ------------------------------------------------------------
        # Time
        # ------------------------------------------------------------
        time_text = datetime_text

        # Remove date if present so the output is cleaner.
        if date_match:
            time_text = time_text.replace(date_match.group(0), "").strip()

        # ------------------------------------------------------------
        # Location
        # ------------------------------------------------------------
        location_element = block.select_one(".meeting-location")

        location = ""
        if location_element:
            location = clean_text(
                location_element.get_text(" ", strip=True)
            )

        # ------------------------------------------------------------
        # Broadcast
        # ------------------------------------------------------------
        broadcast = ""

        broadcast_element = block.select_one(
            ".meeting-card-media-preview .stream-type"
        )

        if broadcast_element:
            broadcast = clean_text(
                broadcast_element.get_text(" ", strip=True)
            )

        # ------------------------------------------------------------
        # Studies / activities
        # ------------------------------------------------------------
        studies = []

        for study in block.select(
            ".meeting-card-studies-list .meeting-card-study"
        ):
            text = clean_text(study.get_text(" ", strip=True))

            if text:
                studies.append(text)

        # ------------------------------------------------------------
        # Notice of Meeting link
        # ------------------------------------------------------------
        notice_link = block.select_one(
            "a.btn-meeting-notice"
        )

        notice_url = ""

        if notice_link and notice_link.get("href"):
            notice_url = urljoin(
                BASE_URL,
                notice_link["href"]
            )

        # ------------------------------------------------------------
        # Meeting page
        # ------------------------------------------------------------
        meeting_id = block.get("id", "").replace(
            "collapse-meeting-", ""
        )

        meeting_page = (
            f"{MEETINGS_URL}#collapse-meeting-{meeting_id}"
        )

        upcoming.append({
            "committee": committee_name,
            "date": meeting_date,
            "time": time_text,
            "location": location,
            "broadcast": broadcast,
            "studies": studies,
            "meeting_page": meeting_page,
            "notice_url": notice_url,
        })

    # Sort chronologically.
    upcoming.sort(
        key=lambda x: (
            x["date"],
            x["time"]
        )
    )

    return upcoming


def parse_notice(notice_url):
    """Read a Notice of Meeting and extract subject/witness information."""

    if not notice_url:
        return {
            "date": "",
            "time": "",
            "location": "",
            "televised": False,
            "subject": "",
            "witnesses": [],
        }

    try:
        html = get_page(notice_url)
    except Exception as e:
        print(f"Could not retrieve notice: {e}")

        return {
            "date": "",
            "time": "",
            "location": "",
            "televised": False,
            "subject": "",
            "witnesses": [],
        }

    soup = BeautifulSoup(html, "html.parser")

    # ------------------------------------------------------------
    # Get all visible text
    # ------------------------------------------------------------
    text = soup.get_text("\n", strip=True)

    lines = [
        clean_text(line)
        for line in text.splitlines()
        if clean_text(line)
    ]

    # ------------------------------------------------------------
    # Date
    # ------------------------------------------------------------
    date_value = ""

    date_pattern = re.compile(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December) \d{1,2}, \d{4}$"
    )

    for line in lines:
        if date_pattern.match(line):
            date_value = line
            break

    # ------------------------------------------------------------
    # Time
    # ------------------------------------------------------------
    time_value = ""

    time_pattern = re.compile(
        r"^\d{1,2}:\d{2}\s*(a\.m\.|p\.m\.)\s*to\s*"
        r"\d{1,2}:\d{2}\s*(a\.m\.|p\.m\.)$",
        re.IGNORECASE
    )

    for line in lines:
        if time_pattern.match(line):
            time_value = line
            break

    # ------------------------------------------------------------
    # Location
    # ------------------------------------------------------------
    location_value = ""

    for line in lines:
        if (
            "Building" in line
            and ("Room" in line or "room" in line)
        ):
            location_value = line
            break

    # ------------------------------------------------------------
    # Televised
    # ------------------------------------------------------------
    televised = any(
        line.lower() == "televised"
        for line in lines
    )

    # ------------------------------------------------------------
    # Subject
    #
    # On the notice, this appears after the date/time/location
    # information and before "Committee clerk".
    # ------------------------------------------------------------
    subject = ""

    clerk_index = None

    for i, line in enumerate(lines):
        if line.lower() == "committee clerk":
            clerk_index = i
            break

    if clerk_index is not None:
        # Look backwards for the substantive paragraph.
        candidates = []

        for line in lines[:clerk_index]:
            if len(line) > 50:
                candidates.append(line)

        if candidates:
            # Usually the final long line before the clerk information
            # is the subject.
            subject = candidates[-1]

    # ------------------------------------------------------------
    # Witnesses
    #
    # We deliberately look for actual witness names/titles rather than
    # treating the committee name itself as a witness.
    # ------------------------------------------------------------
    witnesses = []

    # First look for headings such as "Witnesses", "Appearing", etc.
    witness_index = None

    for i, line in enumerate(lines):
        lower = line.lower()

        if lower in (
            "witnesses",
            "witness",
            "appearing",
            "appearing before the committee",
        ):
            witness_index = i
            break

    if witness_index is not None:
        for line in lines[witness_index + 1:]:
            lower = line.lower()

            if lower in (
                "committee clerk",
                "meeting agenda",
                "agenda",
                "notice of meeting",
            ):
                break

            # Skip generic navigation/header text.
            if len(line) < 3:
                continue

            if line.lower().startswith(
                (
                    "standing committee",
                    "committee meeting",
                    "notices of meeting",
                )
            ):
                continue

            witnesses.append(line)

    # Remove duplicates while preserving order.
    cleaned_witnesses = []

    for witness in witnesses:
        if witness not in cleaned_witnesses:
            cleaned_witnesses.append(witness)

    return {
        "date": date_value,
        "time": time_value,
        "location": location_value,
        "televised": televised,
        "subject": subject,
        "witnesses": cleaned_witnesses,
    }


def print_meeting(meeting):
    """Print a meeting in a readable format."""

    print("MEETING")
    print("-" * 60)

    print(f"Committee: {meeting['committee']}")
    print(f"Date: {meeting['date'].strftime('%A, %B %d, %Y')}")
    print(f"Time: {meeting['time']}")

    if meeting["location"]:
        print(f"Location: {meeting['location']}")

    if meeting["broadcast"]:
        print(f"Broadcast: {meeting['broadcast']}")

    print()
    print("Studies / Activities:")

    if meeting["studies"]:
        for study in meeting["studies"]:
            print(f"  - {study}")
    else:
        print("  - None listed")

    print()
    print(f"Meeting page: {meeting['meeting_page']}")

    if meeting["notice_url"]:
        print(f"Notice: {meeting['notice_url']}")

        print()
        print("Reading Notice of Meeting...")

        notice = parse_notice(meeting["notice_url"])

        print()
        print("-" * 60)
        print("NOTICE DETAILS")
        print("-" * 60)

        if notice["date"]:
            print(f"Date: {notice['date']}")

        if notice["time"]:
            print(f"Time: {notice['time']}")

        if notice["location"]:
            print(f"Location: {notice['location']}")

        print(f"Televised: {'Yes' if notice['televised'] else 'No'}")

        print()
        print("SUBJECT:")

        if notice["subject"]:
            print(f"  {notice['subject']}")
        else:
            print("  Could not identify subject")

        print()
        print("WITNESSES:")

        if notice["witnesses"]:
            for witness in notice["witnesses"]:
                print(f"  - {witness}")
        else:
            print("  No witnesses listed")


def main():

    print("=" * 60)
    print("HOUSE OF COMMONS COMMITTEE TEST")
    print("=" * 60)
    print()

    try:
        meetings = get_upcoming_meetings()
    except Exception as e:
        print(f"ERROR retrieving committee meetings: {e}")
        return

    print()
    print("Upcoming meetings found:", len(meetings))
    print()

    if not meetings:
        print("No upcoming committee meetings found.")
        return

    print("=" * 60)
    print("UPCOMING MEETINGS")
    print("=" * 60)
    print()

    for meeting in meetings:
        print_meeting(meeting)
        print()
        print("=" * 60)
        print()

    print("TEST COMPLETE")


if __name__ == "__main__":
    main()
