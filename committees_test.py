import urllib.request
from bs4 import BeautifulSoup
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

    meetings = []

    for block in meeting_blocks:

        # Ignore suspended meetings
        if block.select_one(".is-suspended"):
            continue

        # Committee name
        committee_link = block.select_one(
            ".meeting-card-committee-details-name a"
        )

        if not committee_link:
            continue

        committee_name = committee_link.get_text(
            " ",
            strip=True
        )

        # Date / time
        datetime_element = block.select_one(
            ".meeting-card-attribute[id^='meeting-datetime-']"
        )

        if not datetime_element:
            continue

        datetime_text = datetime_element.get_text(
            " ",
            strip=True
        )

        # Upcoming meetings on the House page have only a time.
        # Past meetings have a full date.
        if "2026" in datetime_text or "2025" in datetime_text:
            continue

        # Location
        location_element = block.select_one(
            ".meeting-location"
        )

        location = (
            location_element.get_text(" ", strip=True)
            if location_element
            else "Location not listed"
        )

        # Broadcast status
        televised = "Not specified"

        for attribute in block.select(
            ".meeting-card-attribute"
        ):

            text = attribute.get_text(
                " ",
                strip=True
            ).lower()

            if "televised" in text:
                televised = "Televised"

            elif "no broadcast planned" in text:
                televised = "No broadcast planned"

        # Studies / activities
        studies = []

        for study in block.select(".meeting-card-study"):

            text = study.get_text(
                " ",
                strip=True
            )

            if text:
                studies.append(text)

        # Notice of Meeting
        notice_link = block.select_one(
            "a.btn-meeting-notice"
        )

        notice_url = None

        if notice_link:

            notice_url = urljoin(
                BASE_URL,
                notice_link.get("href", "")
            )

        meetings.append({
            "committee": committee_name,
            "time": datetime_text,
            "location": location,
            "televised": televised,
            "studies": studies,
            "notice_url": notice_url
        })

    return meetings


def get_notice_details(notice_url):

    if not notice_url:
        return {
            "notice_study": None,
            "witnesses": []
        }

    print(
        f"  Reading Notice of Meeting..."
    )

    html = get_page(notice_url)

    soup = BeautifulSoup(html, "html.parser")

    # ---------------------------------------------------------
    # Find the main notice content
    # ---------------------------------------------------------

    text = soup.get_text(
        "\n",
        strip=True
    )

    # ---------------------------------------------------------
    # Study / subject
    #
    # The House page places the study immediately before
    # "Committee clerk".
    # ---------------------------------------------------------

    notice_study = None

    committee_clerk = soup.find(
        string=lambda s: s and "Committee clerk" in s
    )

    if committee_clerk:

        # Look backwards through nearby elements for useful
        # subject/study text.
        current = committee_clerk.parent

        for _ in range(10):

            if current is None:
                break

            previous = current.find_previous(
                string=True
            )

            if previous:

                previous_text = previous.strip()

                if (
                    previous_text
                    and len(previous_text) > 20
                    and "Committee clerk" not in previous_text
                    and "Notice of meeting" not in previous_text
                ):
                    notice_study = previous_text
                    break

            current = current.parent

    # ---------------------------------------------------------
    # Witnesses
    #
    # We look for common witness headings and then extract
    # the names/titles underneath them.
    # ---------------------------------------------------------

    witnesses = []

    # Look for headings containing "Witnesses"
    witness_heading = soup.find(
        string=lambda s: s and s.strip().lower() == "witnesses"
    )

    if witness_heading:

        heading = witness_heading.parent

        # Start examining elements after the heading.
        for element in heading.find_all_next():

            element_text = element.get_text(
                " ",
                strip=True
            )

            if not element_text:
                continue

            # Stop when we reach the committee clerk section.
            if "Committee clerk" in element_text:
                break

            # Avoid collecting the heading itself.
            if element_text.lower() == "witnesses":
                continue

            # Avoid giant parent containers containing everything.
            if len(element_text) > 300:
                continue

            witnesses.append(element_text)

    # Remove duplicates while preserving order.
    cleaned_witnesses = []

    for witness in witnesses:

        if witness not in cleaned_witnesses:
            cleaned_witnesses.append(witness)

    return {
        "notice_study": notice_study,
        "witnesses": cleaned_witnesses
    }


def main():

    print("=" * 60)
    print("HOUSE OF COMMONS COMMITTEE TEST")
    print("=" * 60)
    print()

    try:

        meetings = get_upcoming_meetings()

    except Exception as e:

        print("ERROR RETRIEVING MEETINGS:")
        print(e)
        return

    print(
        f"Upcoming meetings found: {len(meetings)}"
    )

    print()

    for meeting in meetings:

        print("=" * 60)
        print("MEETING")
        print("=" * 60)

        print(
            f"Committee: {meeting['committee']}"
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
            f"Notice: {meeting['notice_url']}"
        )

        print()

        # -----------------------------------------------------
        # Read the Notice of Meeting
        # -----------------------------------------------------

        try:

            details = get_notice_details(
                meeting["notice_url"]
            )

        except Exception as e:

            print(
                f"ERROR READING NOTICE: {e}"
            )

            details = {
                "notice_study": None,
                "witnesses": []
            }

        print()

        print("NOTICE STUDY / SUBJECT:")

        if details["notice_study"]:

            print(
                f"  {details['notice_study']}"
            )

        else:

            print(
                "  Could not identify study/subject"
            )

        print()

        print("WITNESSES:")

        if details["witnesses"]:

            for witness in details["witnesses"]:

                print(
                    f"  - {witness}"
                )

        else:

            print(
                "  No witnesses listed"
            )

        print()

    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
