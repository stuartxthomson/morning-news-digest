import urllib.request
from bs4 import BeautifulSoup


NOTICE_URL = "https://www.ourcommons.ca/DocumentViewer/en/45-1/SECU/meeting-46/notice"


def get_page(url):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; Morning News Digest)"
        }
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def main():

    print("=" * 60)
    print("NOTICE OF MEETING DIAGNOSTIC")
    print("=" * 60)
    print()

    html = get_page(NOTICE_URL)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # Print the visible text first.
    print("=" * 60)
    print("VISIBLE TEXT")
    print("=" * 60)
    print()

    print(
        soup.get_text(
            "\n",
            strip=True
        )
    )

    print()

    print("=" * 60)
    print("HEADINGS")
    print("=" * 60)
    print()

    for heading in soup.find_all(
        ["h1", "h2", "h3", "h4", "h5"]
    ):

        text = heading.get_text(
            " ",
            strip=True
        )

        if text:
            print(
                f"{heading.name}: {text}"
            )

    print()

    print("=" * 60)
    print("LINKS")
    print("=" * 60)
    print()

    for link in soup.find_all("a"):

        text = link.get_text(
            " ",
            strip=True
        )

        href = link.get("href")

        if text:

            print(
                f"{text} -> {href}"
            )

    print()

    print("=" * 60)
    print("RAW HTML")
    print("=" * 60)
    print()

    print(
        soup.prettify()
    )


if __name__ == "__main__":
    main()
