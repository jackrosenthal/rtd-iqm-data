# RTD IQM2 Meeting Data Scraper

This project scrapes Regional Transportation District (RTD) board meeting data from their IQM2 portal at https://rtd.iqm2.com/Citizens/Calendar.aspx and organizes it into a structured directory format.

📋 **[View Meeting Index](meetings/index.md)** - Browse all meetings organized by committee and year.

## Directory Structure

Each meeting is stored in its own directory under `meetings/MEETING_ID/` with the following structure:

```
meetings/
└── 3741/                    # Meeting ID from IQM2 system
    ├── metadata.json        # Meeting title, date, location, status
    ├── details.md           # Meeting details page converted to Markdown
    ├── agenda.pdf           # Meeting agenda (Type=14)
    ├── agenda.txt           # Agenda converted to plain text via pdftotext
    ├── packet.pdf           # Full agenda packet (Type=1)
    ├── packet.txt           # Packet converted to plain text via pdftotext
    ├── minutes.pdf          # Meeting minutes (Type=15)
    ├── minutes.txt          # Minutes converted to plain text via pdftotext
    ├── transcript.pdf       # Full-text transcript (Type=12)
    ├── transcript.txt       # Transcript in plain text format
    └── attachments/         # Additional meeting attachments
        ├── attachment1.pdf
        └── attachment1.txt
```

## Text Conversion

All PDF files are automatically converted to plain text using `pdftotext` for:
- Improved searchability
- LLM context provision
- Accessibility

## Usage

### Default (Past 60 days to end of current year)
```bash
./scraper.py
```

### Specific Meeting
```bash
./scraper.py --meeting-id 3741
```

### Specific Year
```bash
./scraper.py --year 2024
```

### All Meetings (2007 to present)
```bash
./scraper.py --all
```

### Only Missing Meetings
```bash
./scraper.py --only-missing
```

## System Dependencies

- **pdftotext** (from poppler-utils)

## Development

### Code Quality

```bash
ruff check scraper.py && ruff format scraper.py && uv run --group dev ty check scraper.py
```

### Generate Meeting Index

```bash
./generate_index.py
```

Creates a `meetings/index.md` file with links to all meetings organized by committee type and year.