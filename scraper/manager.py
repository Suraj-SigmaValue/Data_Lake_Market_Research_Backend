"""
scraper/manager.py — ScrapeManager: the single public entry point for all page scraping.

Usage:
    from scraper import scrape_page

    text = scrape_page("https://housing.com/in/buy/...")

The rest of the application never imports strategy classes directly.
ScrapeManager handles:
  - Initial strategy selection (Scrapy vs Playwright)
  - Automatic fallback to Playwright when Scrapy is blocked
  - Text cleaning and capping
  - Structured logging at every step
  - Zero-exception guarantee (always returns str, never raises)
"""

from __future__ import annotations

import logging
import time

from scraper.base import ScrapeResult
from scraper.selector import StrategySelector
from scraper.strategies.scrapy_strategy import ScrapyScraper
from scraper.strategies.playwright_strategy import PlaywrightScraper
from scraper.text_cleaner import clean_text

logger = logging.getLogger(__name__)

_DEFAULT_TEXT_LIMIT = 12_000


class ScrapeManager:
    """
    Orchestrates the full scraping flow for a single URL.

    Thread-safe: designed to be called from asyncio.to_thread().
    A single ScrapeManager instance is shared across the application
    (see module-level singleton in scraper/__init__.py).
    """

    def __init__(self) -> None:
        self._scrapy = ScrapyScraper()
        self._playwright = PlaywrightScraper()
        self._selector = StrategySelector()

    def scrape_page(self, url: str, text_limit: int = _DEFAULT_TEXT_LIMIT) -> str:
        """
        Fetch `url` and return clean visible text, capped at `text_limit` chars.

        Flow:
          1. StrategySelector picks initial strategy
          2. Run chosen strategy
          3. If result needs fallback → run Playwright
          4. Clean and return text

        Never raises — returns "" on total failure.
        """
        t0 = time.perf_counter()

        if not url or not url.startswith(("http://", "https://")):
            logger.warning("[ScrapeManager] Invalid URL: %s", url)
            return ""

        # ── Step 1: Select initial strategy ──────────────────────────────
        strategy_name = self._selector.select_initial(url)
        strategy = self._playwright if strategy_name == "playwright" else self._scrapy

        # ── Step 2: Run initial strategy ──────────────────────────────────
        result: ScrapeResult = strategy._timed_scrape(url)

        logger.info(
            "[ScrapeManager] %s → HTTP %d | %d chars | %dms",
            strategy_name.upper(),
            result.status_code,
            result.text_length,
            result.elapsed_ms,
        )

        # ── Step 3: Fallback to Playwright if needed ──────────────────────
        if strategy_name != "playwright" and self._selector.needs_fallback(result):
            logger.info(
                "[ScrapeManager] Fallback Triggered → Playwright Started for %s", url
            )
            playwright_result = self._playwright._timed_scrape(url)

            logger.info(
                "[ScrapeManager] PLAYWRIGHT → HTTP %d | %d chars | %dms",
                playwright_result.status_code,
                playwright_result.text_length,
                playwright_result.elapsed_ms,
            )

            # Use Playwright result if it's better, otherwise keep Scrapy
            if playwright_result.text_length > result.text_length:
                result = playwright_result
            else:
                logger.info(
                    "[ScrapeManager] Playwright returned less text than Scrapy (%d vs %d) — keeping Scrapy result.",
                    playwright_result.text_length,
                    result.text_length,
                )

        # ── Step 4: Clean and return ──────────────────────────────────────
        if not result.text:
            elapsed_total = int((time.perf_counter() - t0) * 1000)
            logger.warning(
                "[ScrapeManager] All strategies failed for %s in %dms. Returning empty.",
                url,
                elapsed_total,
            )
            return ""

        cleaned = clean_text(result.text)
        final_text = cleaned[:text_limit]
        elapsed_total = int((time.perf_counter() - t0) * 1000)

        logger.info(
            "[ScrapeManager] Characters Extracted: %d (raw %d) | Strategy Used: %s | Elapsed Time: %dms → %s",
            len(final_text),
            result.text_length,
            result.strategy,
            elapsed_total,
            url,
        )

        return final_text
