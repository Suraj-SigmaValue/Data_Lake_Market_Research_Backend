"""
scraper/base.py — Abstract base class and shared data structures for all scraping strategies.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ScrapeResult:
    """Structured result returned by every scraping strategy."""

    success: bool = False
    text: str = ""
    strategy: str = ""
    status_code: int = 0
    elapsed_ms: int = 0
    text_length: int = 0
    failure_reason: str = ""

    def __post_init__(self) -> None:
        self.text_length = len(self.text)


class BaseScraper(ABC):
    """
    All scraping strategies must implement this interface.
    The rest of the application only interacts with ScrapeManager,
    which delegates to BaseScraper implementations.

    To add a new strategy:
        1. Subclass BaseScraper
        2. Set a unique `name`
        3. Implement `scrape(url) -> ScrapeResult`
        4. Register in ScrapeManager
    """

    name: str = "base"

    @abstractmethod
    def scrape(self, url: str) -> ScrapeResult:
        """
        Fetch `url` and return cleaned visible text.

        Must NEVER raise — all exceptions should be caught internally
        and returned as ScrapeResult(success=False, failure_reason=...).
        """
        ...

    def _timed_scrape(self, url: str) -> ScrapeResult:
        """Wraps scrape() with elapsed time tracking."""
        t0 = time.perf_counter()
        result = self.scrape(url)
        result.elapsed_ms = int((time.perf_counter() - t0) * 1000)
        result.text_length = len(result.text)
        result.strategy = self.name
        return result
