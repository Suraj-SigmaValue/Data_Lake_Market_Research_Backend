"""
scraper/selector.py — StrategySelector: routes URLs to the right scraping strategy.

Rules (applied in order):
  1. If the domain is in PLAYWRIGHT_PORTALS → use Playwright immediately.
  2. Otherwise → attempt Scrapy first.

Fallback rules (checked after Scrapy attempt):
  - HTTP status in FALLBACK_STATUS_CODES (401, 403, 406, 429, 503)
  - Text too short (< MIN_TEXT_LENGTH chars)
  - Bot-detection signal found in the returned text
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from scraper.portals import BOT_SIGNALS, FALLBACK_STATUS_CODES, PLAYWRIGHT_PORTALS
from scraper.base import ScrapeResult

logger = logging.getLogger(__name__)

# Minimum useful text length — shorter results are treated as failures
MIN_TEXT_LENGTH: int = 200


class StrategySelector:
    """
    Determines which scraping strategy to use for a given URL and
    whether a result should trigger a fallback to Playwright.

    Designed to be stateless — safe to share across threads.
    """

    def select_initial(self, url: str) -> str:
        """
        Return 'playwright' if the URL belongs to a known JS-heavy portal,
        otherwise return 'scrapy'.
        """
        domain = self._extract_domain(url)
        for portal in PLAYWRIGHT_PORTALS:
            if portal in domain:
                logger.info(
                    "[StrategySelector] Selected Strategy: playwright (known JS portal: %s) → %s",
                    portal,
                    url,
                )
                return "playwright"

        logger.info("[StrategySelector] Selected Strategy: scrapy → %s", url)
        return "scrapy"

    def needs_fallback(self, result: ScrapeResult) -> bool:
        """
        Return True if the Scrapy result should be retried with Playwright.

        Fallback conditions:
          - HTTP status code indicates bot-blocking
          - Too little text returned
          - Bot-detection phrase found in the text
        """
        # 1. Blocked HTTP status
        if result.status_code in FALLBACK_STATUS_CODES:
            logger.info(
                "[StrategySelector] Fallback Triggered: HTTP %d → will retry with Playwright",
                result.status_code,
            )
            return True

        # 2. Not enough text (either blocked or empty page)
        if result.text_length < MIN_TEXT_LENGTH:
            logger.info(
                "[StrategySelector] Fallback Triggered: only %d chars returned → will retry with Playwright",
                result.text_length,
            )
            return True

        # 3. Bot-detection signal in the page text
        text_lower = result.text.lower()
        for signal in BOT_SIGNALS:
            if signal in text_lower:
                logger.info(
                    "[StrategySelector] Fallback Triggered: bot signal '%s' detected → will retry with Playwright",
                    signal,
                )
                return True

        return False

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Return the bare domain (e.g. '99acres.com') from a full URL."""
        try:
            netloc = urlparse(url).netloc.lower()
            return netloc.replace("www.", "")
        except Exception:
            return url.lower()
