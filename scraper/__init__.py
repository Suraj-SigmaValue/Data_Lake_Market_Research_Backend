"""
scraper/__init__.py — Public API for the scraping framework.

The rest of the application imports ONLY from here:

    from scraper import scrape_page

That is the ONLY change required in listing_extractor.py.
No other file in the application needs to know about strategies,
selectors, or the manager.

A module-level ScrapeManager singleton is created at import time.
This ensures the Playwright browser is launched only once per
server process, not per request.
"""

from __future__ import annotations

import logging

from scraper.manager import ScrapeManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton — shared across all threads in the same process
# ---------------------------------------------------------------------------
_manager = ScrapeManager()


def scrape_page(url: str, text_limit: int = 8_000) -> str:
    """
    Fetch `url` and return clean visible text (up to `text_limit` chars).

    This is the ONLY function the rest of the application should call.
    Strategy selection, fallback logic, and text cleaning are handled internally.

    Args:
        url:        The page URL to scrape.
        text_limit: Maximum characters to return (default 8000).

    Returns:
        Cleaned text string. Returns "" on total failure — never raises.
    """
    return _manager.scrape_page(url, text_limit=text_limit)


__all__ = ["scrape_page"]
