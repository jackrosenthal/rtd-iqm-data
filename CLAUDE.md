# CLAUDE.md

This file contains development guidelines and workflow information for the RTD IQM2 Meeting Data Scraper project.

## Code Style Guidelines

### Python Style Guide
This project follows the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) with the following key conventions:

#### Import Style
- **Modules only**: Import modules, not individual classes/functions
- **From imports**: Only allowed for modules, with an exception for the `typing` module

```python
# ✅ Correct - importing modules
import urllib.parse
import bs4
import pydantic
from loguru import logger  # module import

# ❌ Incorrect - importing classes/functions
from urllib.parse import urljoin  # function import
from bs4 import BeautifulSoup     # class import
from pydantic import BaseModel    # class import

# ✅ Exception: typing module imports are allowed
from typing import Optional
```

#### Docstrings
All classes and methods must have Google-style docstrings:

```python
def fetch_page(self, url: str) -> str:
    """Fetch HTML content from a URL.
    
    Args:
        url: The URL to fetch.
        
    Returns:
        The HTML content as a string.
        
    Raises:
        httpx.HTTPStatusError: If the request fails.
    """
```

#### Type Hints
- Use modern Python 3.13+ type syntax
- Meeting IDs should be `int`, not `str`
- Use `int | None` instead of `Optional[int]`

```python
# ✅ Modern syntax
def get_meetings(self, year: int | None = None) -> list[MeetingListItem]:

# ❌ Old syntax
def get_meetings(self, year: Optional[int] = None) -> List[Dict[str, str]]:
```

## Development Workflow

### Code Quality Tools

#### Linting
```bash
ruff check scraper.py
```

#### Code Formatting
```bash
ruff format scraper.py
```

#### Type Checking
```bash
uv run --group dev ty check scraper.py
```

#### Run All Checks
```bash
# Run all quality checks in sequence
ruff check scraper.py && ruff format scraper.py && uv run --group dev ty check scraper.py
```

### Dependencies

Dependencies are documented in `pyproject.toml`. System dependencies are documented in `README.md`.

### Testing the Scraper

#### Single Meeting
```bash
./scraper.py --meeting-id 3799
```

#### Multiple Meetings with Limit
```bash
./scraper.py --year 2007 --limit 5
```

#### Full Year
```bash
./scraper.py --year 2007
```


## Architecture Notes

### Async Design
- All I/O operations are async (HTTP requests, file downloads, subprocess calls)
- Concurrency limited to 5 simultaneous requests to be respectful to the server
- Progress tracking with rich progress bars

### Error Handling
- Graceful handling of missing documents (cancelled meetings, etc.)
- Proper null checking for optional meeting fields
- HTTP errors are propagated appropriately

### Logging and UI
- Loguru for structured logging with rich console integration
- Rich progress bars for visual feedback
- Clean separation between progress indication and log messages

### Data Models
- Pydantic models for type safety and validation
- Integer meeting IDs for semantic correctness
- Structured metadata with cancellation status
- Optional fields for missing agenda/minutes IDs

## Performance Considerations

- **Semaphore limiting**: Max 5 concurrent requests
- **Streaming downloads**: Large PDFs are streamed, not loaded into memory
- **Async subprocess**: PDF-to-text conversion doesn't block other operations
- **Progress feedback**: Users get immediate feedback on long-running operations