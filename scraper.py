#!/usr/bin/env -S uv run --script

import asyncio
import asyncio.subprocess
import datetime
import re
import urllib.parse
import zoneinfo
from pathlib import Path
from typing import Annotated, Optional

import httpx
import bs4
import async_typer
import typer
import pydantic
from loguru import logger
import rich.progress
import rich.console
import rich.text

app = async_typer.AsyncTyper()

console = rich.console.Console(stderr=True)
logger.remove()
logger.add(
    lambda m: console.print(rich.text.Text.from_ansi(m)),
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
    colorize=console.is_terminal,
)

BASE_URL = "https://rtd.iqm2.com"
CALENDAR_URL = f"{BASE_URL}/Citizens/Calendar.aspx"
DENVER_TZ = zoneinfo.ZoneInfo("America/Denver")


def parse_meeting_date(date_str: str) -> datetime.datetime:
    """Parse meeting date string to datetime with Denver timezone.

    Args:
        date_str: Date string in format like "6/3/2025 5:30 PM"

    Returns:
        Datetime object with America/Denver timezone.
    """
    # Parse the date string (format: "6/3/2025 5:30 PM")
    dt = datetime.datetime.strptime(date_str, "%m/%d/%Y %I:%M %p")
    # Add Denver timezone
    return dt.replace(tzinfo=DENVER_TZ)


class MeetingListItem(pydantic.BaseModel):
    id: int
    url: str


class MeetingDownloads(pydantic.BaseModel):
    agenda: str | None = None
    packet: str | None = None
    minutes: str | None = None
    transcript: str | None = None


class MeetingDetail(pydantic.BaseModel):
    id: int
    group: str
    type: str
    date: datetime.datetime
    location: str
    minutes_id: int | None
    agenda_id: int | None
    downloads: MeetingDownloads
    outline_html: str
    cancelled: bool


class MeetingMetadata(pydantic.BaseModel):
    id: int
    title: str
    date: datetime.datetime
    location: str
    group: str
    type: str
    cancelled: bool


class RTDScraper:
    """Scraper for RTD meeting data from IQM2 portal."""

    def __init__(self):
        """Initialize the scraper with HTTP client."""
        self.client = httpx.AsyncClient(timeout=60.0)

    async def close(self):
        """Close the HTTP client and cleanup resources."""
        await self.client.aclose()

    async def fetch_page(self, url: str) -> str:
        """Fetch HTML content from a URL.

        Args:
            url: The URL to fetch.

        Returns:
            The HTML content as a string.

        Raises:
            httpx.HTTPStatusError: If the request fails.
        """
        response = await self.client.get(url)
        response.raise_for_status()
        return response.text

    async def download_file(self, url: str, filepath: Path) -> None:
        """Download a file from a URL to a local path.

        Args:
            url: The URL to download from.
            filepath: The local path to save the file.

        Raises:
            httpx.HTTPStatusError: If the download fails.
        """
        filepath.parent.mkdir(parents=True, exist_ok=True)
        async with self.client.stream("GET", url) as response:
            response.raise_for_status()
            with open(filepath, "wb") as f:
                async for chunk in response.aiter_bytes():
                    f.write(chunk)

    async def pdf_to_text(self, pdf_path: Path) -> None:
        """Convert a PDF file to text using pdftotext.

        Args:
            pdf_path: Path to the PDF file to convert.

        Note:
            Creates a .txt file with the same name as the PDF.
        """
        txt_path = pdf_path.with_suffix(".txt")
        process = await asyncio.create_subprocess_exec(
            "pdftotext",
            str(pdf_path),
            str(txt_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()

    async def get_meeting_list(
        self, from_date: str | None = None, to_date: str | None = None
    ) -> list[MeetingListItem]:
        """Get a list of meetings from the RTD calendar.

        Args:
            from_date: Start date in MM/DD/YYYY format. If None, gets all meetings.
            to_date: End date in MM/DD/YYYY format. If None, gets all meetings.

        Returns:
            List of MeetingListItem objects with meeting IDs and URLs.
        """
        if from_date and to_date:
            url = f"{CALENDAR_URL}?From={from_date}&To={to_date}&View=List"
        else:
            url = f"{CALENDAR_URL}?View=List"

        html = await self.fetch_page(url)
        soup = bs4.BeautifulSoup(html, "html.parser")

        meetings = []
        for link in soup.find_all(
            "a", href=re.compile(r"Detail_Meeting\.aspx\?ID=\d+")
        ):
            match = re.search(r"ID=(\d+)", link["href"])
            if match:
                meeting_id = int(match.group(1))
                meetings.append(
                    MeetingListItem(
                        id=meeting_id, url=urllib.parse.urljoin(BASE_URL, link["href"])
                    )
                )

        return meetings

    async def parse_meeting_detail(self, meeting_url: str) -> MeetingDetail:
        """Parse meeting details from a meeting detail page.

        Args:
            meeting_url: URL of the meeting detail page.

        Returns:
            MeetingDetail object with parsed meeting information.
        """
        html = await self.fetch_page(meeting_url)
        soup = bs4.BeautifulSoup(html, "html.parser")

        # Extract basic meeting info
        meeting_group = soup.find(id="ContentPlaceholder1_lblMeetingGroup")
        meeting_type = soup.find(id="ContentPlaceholder1_lblMeetingType")
        meeting_date = soup.find(id="ContentPlaceholder1_lblMeetingDate")

        # Extract IDs from hidden fields
        meeting_id_field = soup.find(id="ContentPlaceholder1_txtMeetingID")
        minutes_id_field = soup.find(id="ContentPlaceholder1_txtMinutesID")
        agenda_id_field = soup.find(id="ContentPlaceholder1_txtAgendaID")

        if meeting_id_field and meeting_id_field.get("value"):
            meeting_id = int(meeting_id_field.get("value"))
        else:
            raise ValueError(f"Problem with page {meeting_url}: meeting ID not found")

        minutes_id = (
            int(minutes_id_field["value"])
            if minutes_id_field and minutes_id_field.get("value")
            else None
        )
        agenda_id = (
            int(agenda_id_field["value"])
            if agenda_id_field and agenda_id_field.get("value")
            else None
        )

        # Extract meeting location
        address_div = soup.find(class_="MeetingAddress")
        location = address_div.get_text(strip=True) if address_div else ""

        # Check if meeting is cancelled
        cancelled_elem = soup.find(class_="MeetingCancelled")
        cancelled = cancelled_elem is not None

        # Extract download links
        downloads = MeetingDownloads()
        download_section = soup.find(class_="MeetingDownloads")
        if download_section:
            for link in download_section.find_all(
                "a", href=re.compile(r"FileOpen\.aspx")
            ):
                href = link["href"]
                parsed_url = urllib.parse.urlparse(href)
                query_params = urllib.parse.parse_qs(parsed_url.query)

                # Get the Type parameter
                type_param = query_params.get("Type", [None])[0]
                full_url = urllib.parse.urljoin(BASE_URL, f"/Citizens/{href}")

                if type_param == "14":  # Agenda
                    downloads.agenda = full_url
                elif type_param == "1":  # Agenda Packet
                    downloads.packet = full_url
                elif type_param == "15":  # Minutes
                    downloads.minutes = full_url
                elif type_param == "12":  # Full-text Transcript
                    downloads.transcript = full_url

        # Extract meeting outline for details.md
        outline_table = soup.find("table", id="MeetingDetail")
        outline_html = str(outline_table) if outline_table else ""

        # Parse the date string to datetime
        date_str = meeting_date.get_text(strip=True) if meeting_date else ""
        if not date_str:
            raise ValueError(f"Missing meeting date for meeting ID {meeting_id}")
        parsed_date = parse_meeting_date(date_str)

        return MeetingDetail(
            id=meeting_id,
            group=meeting_group.get_text(strip=True) if meeting_group else "",
            type=meeting_type.get_text(strip=True) if meeting_type else "",
            date=parsed_date,
            location=location,
            minutes_id=minutes_id,
            agenda_id=agenda_id,
            downloads=downloads,
            outline_html=outline_html,
            cancelled=cancelled,
        )

    def html_to_markdown(self, html: str) -> str:
        """Convert HTML meeting outline to Markdown format.

        Args:
            html: HTML content containing meeting outline table.

        Returns:
            Markdown-formatted string of the meeting outline.
        """
        soup = bs4.BeautifulSoup(html, "html.parser")

        markdown = ""
        current_section = ""

        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue

            # Check for headers at different nesting levels
            if len(cells) >= 2:
                # Check each cell for section numbers
                for i, cell in enumerate(cells):
                    cell_text = cell.get_text(strip=True)

                    # Main section headers (I., II., III., etc.) - usually in first column
                    if cell_text and re.match(r"^[IVX]+\.\s*$", cell_text) and i < 2:
                        # Find title in the next column with content
                        for j in range(i + 1, len(cells)):
                            title_link = cells[j].find("a")
                            if title_link:
                                title = title_link.get_text(strip=True)
                                current_section = f"## {cell_text} {title}"
                                markdown += f"\n{current_section}\n"
                                break
                        break

                    # Subsection headers (A., B., 1., 2., etc.) - can be in various columns
                    elif cell_text and re.match(r"^[A-Z0-9]+\.\s*$", cell_text):
                        # Find title in the next column with content
                        for j in range(i + 1, len(cells)):
                            title_link = cells[j].find("a")
                            if title_link:
                                title = title_link.get_text(strip=True)
                                # Determine nesting level based on column position
                                if i <= 1:
                                    markdown += f"\n### {cell_text} {title}\n"
                                else:
                                    markdown += f"\n#### {cell_text} {title}\n"
                                break
                        break

                    # Lower-level subsections (a., b., c., etc.) - usually in deeper columns
                    elif cell_text and re.match(r"^[a-z]+\.\s*$", cell_text):
                        # Find title in the next column with content
                        for j in range(i + 1, len(cells)):
                            title_link = cells[j].find("a")
                            if title_link:
                                title = title_link.get_text(strip=True)
                                markdown += f"\n##### {cell_text} {title}\n"
                                break
                        break

            # Check for comments/content rows
            for cell in cells:
                if "Comments" in cell.get("class", []):
                    # Extract text content from the Comments cell
                    content = self._extract_text_from_html(cell)
                    if content.strip():
                        markdown += f"\n{content}\n"

        # Clean up excessive linebreaks in the final result
        result = markdown.strip()
        while "\n\n\n" in result:
            result = result.replace("\n\n\n", "\n\n")

        return result

    def _extract_text_from_html(self, element) -> str:
        """Extract readable text from HTML element, preserving some formatting.

        Args:
            element: BeautifulSoup element to extract text from.

        Returns:
            Formatted text string.
        """
        # Convert some HTML elements to markdown-like formatting
        for tag in element.find_all(["strong", "b"]):
            tag.string = f"**{tag.get_text()}**" if tag.string else ""
            tag.unwrap()

        for tag in element.find_all(["em", "i"]):
            tag.string = f"*{tag.get_text()}*" if tag.string else ""
            tag.unwrap()

        # Convert links
        for link in element.find_all("a"):
            href = link.get("href", "")
            text = link.get_text()
            if href and text:
                link.string = f"[{text}]({href})"
                link.unwrap()

        # Add double line breaks after paragraphs to preserve structure in markdown
        for p in element.find_all("p"):
            p.append("\n\n")

        # Get text with some structure preserved
        text = element.get_text()

        # Clean up extra whitespace but preserve paragraph breaks
        lines = [line.strip() for line in text.split("\n")]

        # Convert bullet points (·) to markdown lists
        processed_lines = []
        for line in lines:
            # Check if line contains bullet points with ·
            if "·" in line:
                # Split on · and create markdown list items
                parts = line.split("·")
                # First part might be intro text
                if parts[0].strip():
                    processed_lines.append(parts[0].strip())
                # Rest are bullet items
                for part in parts[1:]:
                    if part.strip():
                        processed_lines.append(f"- {part.strip()}")
            else:
                processed_lines.append(line)

        return "\n".join(processed_lines)

    async def scrape_meeting(self, meeting_id: int) -> None:
        """Scrape all data for a specific meeting.

        Args:
            meeting_id: The meeting ID to scrape.

        Note:
            Creates a directory structure with all meeting documents
            and metadata as specified in the project README.
        """
        meeting_url = f"{BASE_URL}/Citizens/Detail_Meeting.aspx?ID={meeting_id}"

        try:
            meeting_data = await self.parse_meeting_detail(meeting_url)
        except ValueError as e:
            logger.warning(e)
            return

        # Create meeting directory
        meeting_dir = Path("meetings") / str(meeting_id)
        meeting_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata
        metadata = MeetingMetadata(
            id=meeting_data.id,
            title=f"{meeting_data.group} - {meeting_data.type}",
            date=meeting_data.date,
            location=meeting_data.location,
            group=meeting_data.group,
            type=meeting_data.type,
            cancelled=meeting_data.cancelled,
        )

        with open(meeting_dir / "metadata.json", "w") as f:
            f.write(metadata.model_dump_json(indent=2))

        # Convert outline to markdown and save
        if meeting_data.outline_html:
            markdown = self.html_to_markdown(meeting_data.outline_html)
            with open(meeting_dir / "details.md", "w") as f:
                f.write(markdown)

        # Download files
        download_tasks = []
        downloads_dict = meeting_data.downloads.model_dump(exclude_none=True)
        for file_type, url in downloads_dict.items():
            if file_type == "agenda":
                filepath = meeting_dir / "agenda.pdf"
            elif file_type == "packet":
                filepath = meeting_dir / "packet.pdf"
            elif file_type == "minutes":
                filepath = meeting_dir / "minutes.pdf"
            elif file_type == "transcript":
                filepath = meeting_dir / "transcript.pdf"
            else:
                continue

            download_tasks.append(self.download_file(url, filepath))

        # Execute downloads concurrently
        if download_tasks:
            await asyncio.gather(*download_tasks)

        # Convert PDFs to text
        pdf_files = list(meeting_dir.glob("*.pdf"))
        conversion_tasks = [self.pdf_to_text(pdf) for pdf in pdf_files]
        if conversion_tasks:
            await asyncio.gather(*conversion_tasks)

        logger.info("Scraped meeting {}: {}", meeting_id, metadata.title)

    def is_meeting_downloaded(self, meeting_id: int) -> bool:
        """Check if a meeting has already been downloaded.

        Args:
            meeting_id: The meeting ID to check.

        Returns:
            True if the meeting directory and metadata.json exist.
        """
        meeting_dir = Path("meetings") / str(meeting_id)
        metadata_file = meeting_dir / "metadata.json"
        return metadata_file.exists()


@app.async_command()
async def scrape(
    meeting_id: Optional[str] = None,
    year: Optional[int] = None,
    all_meetings: Annotated[
        bool, typer.Option("--all", help="Scrape all meetings for all time")
    ] = False,
    only_missing: Annotated[
        bool, typer.Option("--only-missing", help="Download only missing meetings")
    ] = False,
):
    """Scrape RTD meeting data from IQM2 portal.

    Args:
        meeting_id: Specific meeting ID to scrape. If provided, only scrapes this meeting.
        year: Year to scrape meetings from. If not provided, scrapes past 60 days to end of current year.
        all_meetings: If True, scrape all meetings for all time.
        only_missing: If True, download only meetings that don't already exist locally.
    """
    # Check for mutually exclusive options
    exclusive_options = [meeting_id is not None, year is not None, all_meetings]
    if sum(exclusive_options) > 1:
        raise typer.BadParameter(
            "Options --meeting-id, --year, and --all are mutually exclusive"
        )

    scraper = RTDScraper()

    try:
        if meeting_id:
            # Scrape specific meeting
            with rich.progress.Progress(
                rich.progress.SpinnerColumn(),
                rich.progress.TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(f"Scraping meeting {meeting_id}...", total=1)
                await scraper.scrape_meeting(int(meeting_id))
                progress.advance(task)
        else:
            # Calculate date range
            if all_meetings:
                # Scrape all meetings for all time (query year by year to avoid timeouts)
                today = datetime.datetime.now(DENVER_TZ)
                logger.info("Scraping all meetings from 2007 to {}", today.year)

                meetings = []
                for year in range(2007, today.year + 1):
                    logger.info("Fetching meetings for year {}", year)
                    year_from_date = f"1/1/{year}"
                    year_to_date = f"12/31/{year}"
                    year_meetings = await scraper.get_meeting_list(
                        year_from_date, year_to_date
                    )
                    meetings.extend(year_meetings)
                    logger.info(
                        "Found {} meetings for year {}", len(year_meetings), year
                    )

                logger.info("Total meetings found across all years: {}", len(meetings))
            else:
                # For single year or date range queries
                if year:
                    # Scrape specific year
                    from_date = f"1/1/{year}"
                    to_date = f"12/31/{year}"
                    logger.info("Scraping meetings for year {}", year)
                else:
                    # Scrape past 60 days to end of current year
                    today = datetime.datetime.now(DENVER_TZ)
                    start_date = today - datetime.timedelta(days=60)
                    end_date = datetime.datetime(today.year, 12, 31, tzinfo=DENVER_TZ)

                    from_date = start_date.strftime("%-m/%-d/%Y")
                    to_date = end_date.strftime("%-m/%-d/%Y")
                    logger.info("Scraping meetings from {} to {}", from_date, to_date)

                # Get list of meetings
                meetings = await scraper.get_meeting_list(from_date, to_date)

            # Filter for only missing meetings if requested
            if only_missing:
                original_count = len(meetings)
                meetings = [
                    m for m in meetings if not scraper.is_meeting_downloaded(m.id)
                ]
                logger.info(
                    "Found {} total meetings, {} missing", original_count, len(meetings)
                )
            else:
                logger.info("Found {} meetings to scrape", len(meetings))

            # Scrape meetings with limited concurrency and progress bar
            semaphore = asyncio.Semaphore(5)  # Limit to 5 concurrent requests

            with rich.progress.Progress(
                rich.progress.SpinnerColumn(),
                rich.progress.TextColumn("[progress.description]{task.description}"),
                rich.progress.BarColumn(),
                rich.progress.TaskProgressColumn(),
                rich.progress.TimeElapsedColumn(),
                rich.progress.TimeRemainingColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Scraping meetings...", total=len(meetings))

                async def scrape_with_semaphore(meeting):
                    async with semaphore:
                        await scraper.scrape_meeting(meeting.id)
                        progress.advance(task)

                tasks = [scrape_with_semaphore(meeting) for meeting in meetings]
                await asyncio.gather(*tasks)

            logger.success("Completed scraping {} meetings", len(meetings))

    finally:
        await scraper.close()


if __name__ == "__main__":
    app()
