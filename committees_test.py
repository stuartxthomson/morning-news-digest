import requests
from bs4 import BeautifulSoup
from datetime import datetime

MEETINGS_URL = "https://www.ourcommons.ca/committees/en/Meetings"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def clean_text(text):
    return " ".join(text.split())


def find_upcoming_meetings():
    soup = get_page(MEETINGS_URL)

    meeting_blocks = soup.select("div[id^='collapse-meeting-']")

    print(f"Found {len(meeting_blocks)} meeting blocks.")

    meetings = []

    for block in meeting_blocks:
        # Skip suspended meetings
        if block.select_one(".is-suspended"):
            continue

        committee_link = block.select_one(
            ".meeting-card-committee-details-name a"
        )

        if not committee_link:
            continue

        committee = clean_text(committee_link.get_text())

        datetime_element = block.select_one(
            ".meeting-card-attribute[id^='meeting-datetime-']"
        )

        if not datetime_element:
            continue

        date_text = clean_text(datetime_element.get_text())

        # The current/future meetings page often shows only the time
        # for meetings occurring tomorrow/today. That's OK for this test.
        time_text = date_text

        location_element = block.select_one(".meeting-location")
        location = (
            clean_text(location_element.get_text())
            if location_element
            else ""
        )

        broadcast = ""
        broadcast_element = block.select_one(
            ".meeting-card-media-preview .stream-type"
        )

        if broadcast_element:
            broadcast = clean_text(broadcast_element.get_text())

        studies = []
        for study in block.select(
            ".meeting-card-studies-list .meeting-card-study"
        ):
            text = clean_text(study.get_text())
            if text:
                studies.append(text)

        notice_link = block.select_one(
            "a.btn-meeting-notice"
        )

        notice_url = None

        if notice_link:
            href = notice_link.get("href", "")
            if href.startswith("//"):
                notice_url = "https:" + href
            elif href.startswith("/"):
                notice_url = "https://www.ourcommons.ca" + href
            else:
                notice_url = href

        meetings.append({
            "committee": committee,
            "time": time_text,
            "location": location,
            "broadcast": broadcast,
            "studies": studies,
            "notice_url": notice_url
        })

    return meetings


def inspect_notice(notice_url):
    print("\n" + "=" * 60)
    print("NOTICE OF MEETING")
    print("=" * 60)
    print(notice_url)

    soup = get_page(notice_url)

    # Remove navigation, scripts, styles, session selectors, etc.
    for tag in soup([
        "script",
        "style",
        "noscript",
        "nav",
        "header",
        "footer"
    ]):
        tag.decompose()

    # Remove the Parliament/session selector material.
    for element in soup.select(
        ".session-selector, "
        ".session-selector-session, "
        ".session-popover-details, "
        ".session-button-wrapper"
    ):
        element.decompose()

    # Try to identify the main notice content.
    possible_containers = [
        "main",
        "#main-content",
        ".document-content",
        ".document-viewer",
        ".notice-of-meeting",
        ".meeting-notice"
    ]

    container = None

    for selector in possible_containers:
        candidate = soup.select_one(selector)
        if candidate and len(candidate.get_text(" ", strip=True)) > 100:
            container = candidate
            break

    if container is None:
        container = soup.body

    text = container.get_text("\n", strip=True)

    # Clean up blank lines and obvious junk.
    lines = []
    previous_blank = False

    for line in text.splitlines():
        line = clean_text(line)

        if not line:
            if not previous_blank:
                lines.append("")
            previous_blank = True
            continue

        lines.append(line)
        previous_blank = False

    # Print only a reasonable amount for diagnostics.
    print("\nRELEVANT NOTICE TEXT:")
    print("-" * 60)

    output = "\n".join(lines)

    # Look for likely useful sections.
    keywords = [
        "Notice of Meeting",
        "Meeting",
        "Subject",
        "Study",
        "Studies",
        "Witness",
        "Witnesses",
        "Appearing",
        "Time",
        "Location"
    ]

    relevant_lines = []

    for i, line in enumerate(lines):
        if any(keyword.lower() in line.lower() for keyword in keywords):
            start = max(0, i - 2)
            end = min(len(lines), i + 8)

            for nearby in lines[start:end]:
                if nearby not in relevant_lines:
                    relevant_lines.append(nearby)

    if relevant_lines:
        print("\n".join(relevant_lines))
    else:
        print(output[:10000])

    print("\n" + "-" * 60)
    print("END NOTICE DIAGNOSTIC")


def main():
    print("=" * 60)
    print("HOUSE OF COMMONS COMMITTEE TEST")
    print("=" * 60)

    meetings = find_upcoming_meetings()

    print(f"\nUpcoming meetings found: {len(meetings)}")

    for meeting in meetings:
        print("\n" + "=" * 60)
        print("MEETING")
        print("=" * 60)

        print(f"Committee: {meeting['committee']}")
        print(f"Time: {meeting['time']}")

        if meeting["location"]:
            print(f"Location: {meeting['location']}")

        if meeting["broadcast"]:
            print(f"Broadcast: {meeting['broadcast']}")

        print("\nStudies / Activities:")

        for study in meeting["studies"]:
            print(f"  - {study}")

        if meeting["notice_url"]:
            print(f"\nNotice: {meeting['notice_url']}")

            # Inspect the notice.
            inspect_notice(meeting["notice_url"])
        else:
            print("\nNo Notice of Meeting link found.")


if __name__ == "__main__":
    main()
