from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
import re

MEETINGS_URL = "https://www.ourcommons.ca/committees/en/Meetings"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def get_page(url):
    request = Request(url, headers=HEADERS)

    with urlopen(request, timeout=30) as response:
        html = response.read()

    return BeautifulSoup(html, "html.parser")


def clean_text(text):
    return " ".join(text.split())


def absolute_url(href):
    if not href:
        return None

    if href.startswith("//"):
        return "https:" + href

    if href.startswith("/"):
        return "https://www.ourcommons.ca" + href

    return href


def find_upcoming_meetings():
    soup = get_page(MEETINGS_URL)

    meeting_blocks = soup.select(
        "div[id^='collapse-meeting-']"
    )

    print(
        f"Found {len(meeting_blocks)} meeting blocks on the page."
    )

    meetings = []

    for block in meeting_blocks:

        # Ignore meetings that have already happened
        # or have been suspended.
        if block.select_one(".is-suspended"):
            continue

        committee_link = block.select_one(
            ".meeting-card-committee-details-name a"
        )

        if not committee_link:
            continue

        committee = clean_text(
            committee_link.get_text()
        )

        datetime_element = block.select_one(
            ".meeting-card-attribute[id^='meeting-datetime-']"
        )

        if not datetime_element:
            continue

        time_text = clean_text(
            datetime_element.get_text()
        )

        location_element = block.select_one(
            ".meeting-location"
        )

        location = ""

        if location_element:
            location = clean_text(
                location_element.get_text()
            )

        broadcast = ""

        broadcast_element = block.select_one(
            ".meeting-card-media-preview .stream-type"
        )

        if broadcast_element:
            broadcast = clean_text(
                broadcast_element.get_text()
            )

        studies = []

        for study in block.select(
            ".meeting-card-studies-list .meeting-card-study"
        ):
            text = clean_text(
                study.get_text()
            )

            if text:
                studies.append(text)

        notice_link = block.select_one(
            "a.btn-meeting-notice"
        )

        notice_url = None

        if notice_link:
            notice_url = absolute_url(
                notice_link.get("href")
            )

        meetings.append({
            "committee": committee,
            "time": time_text,
            "location": location,
            "broadcast": broadcast,
            "studies": studies,
            "notice_url": notice_url
        })

    return meetings


def get_notice_text(notice_url):
    soup = get_page(notice_url)

    # Remove things that aren't part of the actual notice.
    for tag in soup([
        "script",
        "style",
        "noscript",
        "nav",
        "header",
        "footer"
    ]):
        tag.decompose()

    # Remove Parliament/session navigation.
    for element in soup.select(
        ".session-selector, "
        ".session-selector-session, "
        ".session-popover-details, "
        ".session-button-wrapper"
    ):
        element.decompose()

    # Try to find the actual document.
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

        if candidate and len(
            candidate.get_text(" ", strip=True)
        ) > 100:

            container = candidate
            break

    if container is None:
        container = soup.body

    text = container.get_text(
        "\n",
        strip=True
    )

    lines = []

    for line in text.splitlines():

        line = clean_text(line)

        if line:
            lines.append(line)

    return lines


def find_line(lines, phrase):
    """
    Return the first line containing a phrase.
    """

    phrase = phrase.lower()

    for line in lines:

        if phrase in line.lower():
            return line

    return None


def extract_meeting_details(lines):
    details = {
        "date": None,
        "time": None,
        "location": None,
        "televised": False,
        "subject": None,
        "witnesses": []
    }

    # ---------------------------------------------------------
    # DATE
    # ---------------------------------------------------------

    date_pattern = re.compile(
        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
        r"[A-Z][a-z]+ \d{1,2}, \d{4}"
    )

    for line in lines:

        match = date_pattern.search(line)

        if match:
            details["date"] = match.group(0)
            break

    # ---------------------------------------------------------
    # TIME
    # ---------------------------------------------------------

    time_pattern = re.compile(
        r"\d{1,2}:\d{2} [ap]\.m\. to \d{1,2}:\d{2} [ap]\.m\."
    )

    for line in lines:

        match = time_pattern.search(line)

        if match:
            details["time"] = match.group(0)
            break

    # ---------------------------------------------------------
    # LOCATION
    # ---------------------------------------------------------

    location_pattern = re.compile(
        r"(Room .*?)(?:, Televised|, Committee clerk|$)"
    )

    for line in lines:

        if line.startswith("Room "):

            details["location"] = line.strip()

            break

    # ---------------------------------------------------------
    # TELEVISED
    # ---------------------------------------------------------

    for line in lines:

        if line.lower() == "televised":

            details["televised"] = True

            break

    # ---------------------------------------------------------
    # SUBJECT
    # ---------------------------------------------------------

    # The notice generally contains a line beginning with
    # "Meeting" that contains the real purpose of the meeting.
    #
    # Example:
    #
    # Meeting Requested Pursuant to Standing Order 106(4)
    # to Discuss a Request to Undertake a Study of Allegations
    # Concerning the NATO Military Headquarters

    subject_candidates = []

    for line in lines:

        lower = line.lower()

        if (
            lower.startswith("meeting requested")
            or
            lower.startswith("meeting to")
            or
            lower.startswith("meeting for")
        ):

            subject_candidates.append(line)

    if subject_candidates:

        # Usually the longest candidate is the useful one.
        details["subject"] = max(
            subject_candidates,
            key=len
        )

    # ---------------------------------------------------------
    # WITNESSES
    # ---------------------------------------------------------

    witness_start = None

    for i, line in enumerate(lines):

        lower = line.lower()

        if (
            lower == "witnesses"
            or
            lower == "witness"
            or
            lower.startswith("witnesses:")
            or
            lower.startswith("witness:")
        ):

            witness_start = i

            break

    if witness_start is not None:

        # Examine the material after the Witnesses heading.
        #
        # We stop when we encounter a new major section.

        stop_words = {
            "committee clerk",
            "committee members",
            "staff",
            "other business",
            "notice of meeting",
            "evidence",
            "minutes of proceedings"
        }

        for line in lines[witness_start + 1:]:

            lower = line.lower()

            if lower in stop_words:
                break

            # Ignore obvious navigation / boilerplate.
            if lower in {
                "witnesses",
                "witness",
                "appearing"
            }:
                continue

            # Ignore very short junk lines.
            if len(line) < 3:
                continue

            details["witnesses"].append(line)

    # ---------------------------------------------------------
    # NO FALLBACK WITNESS DETECTION
    # ---------------------------------------------------------
    #
    # Only treat text as witnesses if it appears under an
    # explicit Witnesses heading. This prevents committee
    # names, titles and other notice text from being mistaken
    # for witnesses.

    # Remove duplicates while preserving order.

    cleaned_witnesses = []

    for witness in details["witnesses"]:

        if witness not in cleaned_witnesses:
            cleaned_witnesses.append(witness)

    details["witnesses"] = cleaned_witnesses

    return details


def main():

    print("=" * 60)
    print("HOUSE OF COMMONS COMMITTEE TEST")
    print("=" * 60)

    meetings = find_upcoming_meetings()

    print(
        f"\nUpcoming meetings found: {len(meetings)}"
    )

    if not meetings:

        print(
            "\nNo upcoming committee meetings found."
        )

        return

    for meeting in meetings:

        print("\n" + "=" * 60)
        print("MEETING")
        print("=" * 60)

        print(
            f"Committee: {meeting['committee']}"
        )

        print(
            f"Meeting-page time: {meeting['time']}"
        )

        if meeting["location"]:

            print(
                f"Meeting-page location: "
                f"{meeting['location']}"
            )

        if meeting["broadcast"]:

            print(
                f"Meeting-page broadcast: "
                f"{meeting['broadcast']}"
            )

        print("\nStudies / Activities:")

        if meeting["studies"]:

            for study in meeting["studies"]:
                print(f"  - {study}")

        else:

            print("  None listed")

        print(
            f"\nNotice: {meeting['notice_url']}"
        )

        if not meeting["notice_url"]:
            continue

        print(
            "\nReading Notice of Meeting..."
        )

        lines = get_notice_text(
            meeting["notice_url"]
        )

        details = extract_meeting_details(
            lines
        )

        print("\n" + "-" * 60)
        print("NOTICE DETAILS")
        print("-" * 60)

        print(
            f"Date: {details['date'] or 'Not identified'}"
        )

        print(
            f"Time: {details['time'] or 'Not identified'}"
        )

        print(
            f"Location: "
            f"{details['location'] or 'Not identified'}"
        )

        print(
            f"Televised: "
            f"{'Yes' if details['televised'] else 'No / not specified'}"
        )

        print("\nSUBJECT:")

        if details["subject"]:
            print(
                f"  {details['subject']}"
            )
        else:
            print(
                "  Could not identify subject"
            )

        print("\nWITNESSES:")

        if details["witnesses"]:

            for witness in details["witnesses"]:
                print(
                    f"  - {witness}"
                )

        else:

            print(
                "  No witnesses listed"
            )

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
