#!/usr/bin/env -S uv run --script

import json
import pathlib

import async_typer
import pydantic
import typer

from scraper import MeetingMetadata

app = async_typer.AsyncTyper()


def scan_meetings_directory() -> list[MeetingMetadata]:
    """Scan the meetings directory for metadata.json files.

    Returns:
        List of MeetingMetadata objects found in the meetings directory.
    """
    meetings = []
    meetings_dir = pathlib.Path("meetings")

    if not meetings_dir.exists():
        return meetings

    for meeting_dir in meetings_dir.iterdir():
        if meeting_dir.is_dir() and meeting_dir.name.isdigit():
            metadata_file = meeting_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        data = json.load(f)
                        meetings.append(MeetingMetadata.model_validate(data))
                except (json.JSONDecodeError, pydantic.ValidationError) as e:
                    typer.echo(
                        f"Warning: Could not parse {metadata_file}: {e}", err=True
                    )

    return meetings


def group_meetings_by_type_and_year(
    meetings: list[MeetingMetadata],
) -> dict[str, dict[int, list[MeetingMetadata]]]:
    """Group meetings by type and year, then sort each group by date.

    Args:
        meetings: List of MeetingMetadata objects.

    Returns:
        Dictionary mapping meeting types to year dictionaries, which map years to sorted lists of meetings.
    """
    grouped: dict[str, dict[int, list[MeetingMetadata]]] = {}

    for meeting in meetings:
        meeting_type = f"{meeting.group} - {meeting.type}"
        year = meeting.date.year

        if meeting_type not in grouped:
            grouped[meeting_type] = {}
        if year not in grouped[meeting_type]:
            grouped[meeting_type][year] = []

        grouped[meeting_type][year].append(meeting)

    # Sort each group by date (descending - newest first within each year)
    for meeting_type in grouped:
        for year in grouped[meeting_type]:
            grouped[meeting_type][year].sort(key=lambda m: m.date, reverse=True)

    return grouped


def generate_markdown_index(
    grouped_meetings: dict[str, dict[int, list[MeetingMetadata]]],
) -> str:
    """Generate markdown content for the meetings index.

    Args:
        grouped_meetings: Dictionary mapping meeting types to year dictionaries with lists of meetings.

    Returns:
        Markdown content as string.
    """
    lines = ["# RTD Meetings Index", ""]

    # Generate table of contents
    lines.append("## Table of Contents")
    lines.append("")

    sorted_committee_names = sorted(grouped_meetings.keys())
    for committee_name in sorted_committee_names:
        # Create anchor link (GitHub style - lowercase with hyphens)
        anchor = (
            committee_name.lower().replace(" ", "-").replace("(", "").replace(")", "")
        )
        lines.append(f"- [{committee_name}](#{anchor})")

    lines.append("")

    # Generate committee sections
    for committee_name in sorted_committee_names:
        years_dict = grouped_meetings[committee_name]

        lines.append(f"## {committee_name}")
        lines.append("")

        # Sort years in descending order (newest first)
        for year in sorted(years_dict.keys(), reverse=True):
            meetings = years_dict[year]

            lines.append(f"### {year}")
            lines.append("")

            for meeting in meetings:
                # Format date for display
                formatted_date = meeting.date.strftime("%Y-%m-%d %I:%M %p %Z")

                # Check if details.md exists
                meeting_dir = pathlib.Path("meetings") / str(meeting.id)
                details_file = meeting_dir / "details.md"

                if details_file.exists():
                    link_target = f"meetings/{meeting.id}/details.md"
                else:
                    link_target = f"meetings/{meeting.id}/"

                # Add cancelled indicator if meeting was cancelled
                status_indicator = " (CANCELLED)" if meeting.cancelled else ""

                lines.append(
                    f"- **{formatted_date}**: [{meeting.title}]({link_target}){status_indicator}"
                )

            lines.append("")

        lines.append("")

    return "\n".join(lines)


@app.async_command()
async def generate():
    """Generate meetings/index.md file with links to all meeting data organized by type."""
    typer.echo("Scanning meetings directory...")
    meetings = scan_meetings_directory()

    if not meetings:
        typer.echo("No meetings found in meetings/ directory", err=True)
        raise typer.Exit(1)

    typer.echo(f"Found {len(meetings)} meetings")

    typer.echo("Grouping meetings by type and year...")
    grouped = group_meetings_by_type_and_year(meetings)

    typer.echo("Generating markdown index...")
    markdown_content = generate_markdown_index(grouped)

    # Write index file
    index_file = pathlib.Path("meetings") / "index.md"
    with open(index_file, "w") as f:
        f.write(markdown_content)

    typer.echo(f"Generated index with {len(grouped)} meeting types at {index_file}")


if __name__ == "__main__":
    app()
