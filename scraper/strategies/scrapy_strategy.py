"""
scraper/strategies/scrapy_strategy.py — ScrapyScraper implementation.

Runs the standalone spider.py in an isolated subprocess to avoid
Scrapy's Twisted reactor conflicting with the host's asyncio event loop.

Features (applied via spider.py Scrapy settings):
  - AutoThrottle (adaptive request rate)
  - Retry middleware (2 retries on 5xx / 408)
  - Random User-Agent per request
  - HTTP cache DISABLED (always fresh)
  - Robots.txt IGNORED
  - Cookie support
  - Compression (gzip / brotli)
  - DNS cache
  - Connection pooling (via requests session inside subprocess)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from scraper.base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)

# Absolute path to the spider entry-point script
_SPIDER_SCRIPT = Path(__file__).parent.parent / "spider.py"

# Subprocess timeout (seconds): Scrapy init + download + parse
_SUBPROCESS_TIMEOUT = 40

# Check if Scrapy is available at import time (graceful degradation)
try:
    import scrapy  # noqa: F401
    _SCRAPY_AVAILABLE = True
except ImportError:
    _SCRAPY_AVAILABLE = False


class ScrapyScraper(BaseScraper):
    """
    Static-page scraper backed by a real Scrapy spider.

    The spider runs in a subprocess (sys.executable spider.py <url> <tmp>)
    to avoid the asyncio ↔ Twisted reactor conflict. Results are exchanged
    via a temporary JSON file on disk.

    When Scrapy is not installed, returns ScrapeResult(success=False)
    so ScrapeManager falls through to PlaywrightScraper.
    """

    name = "scrapy"

    def scrape(self, url: str) -> ScrapeResult:
        if not _SCRAPY_AVAILABLE:
            logger.warning("[ScrapyScraper] Scrapy not installed — skipping.")
            return ScrapeResult(
                success=False,
                strategy=self.name,
                failure_reason="scrapy not installed",
            )

        tmp_path = ""
        t0 = time.perf_counter()

        try:
            # Create a temp file for the spider to write its JSON result into
            with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w", encoding="utf-8"
            ) as tmp:
                tmp_path = tmp.name

            logger.info("[ScrapyScraper] Starting subprocess spider → %s", url)

            proc = subprocess.run(
                [sys.executable, str(_SPIDER_SCRIPT), url, tmp_path],
                timeout=_SUBPROCESS_TIMEOUT,
                capture_output=True,
                text=True,
                cwd=str(_SPIDER_SCRIPT.parent.parent),  # backend/ directory
            )

            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            if proc.returncode != 0:
                logger.warning(
                    "[ScrapyScraper] Spider subprocess exited %d for %s. stderr: %s",
                    proc.returncode,
                    url,
                    proc.stderr[:300],
                )
                return ScrapeResult(
                    success=False,
                    strategy=self.name,
                    elapsed_ms=elapsed_ms,
                    failure_reason=f"subprocess exit {proc.returncode}",
                )

            # Read the result JSON written by the spider
            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                return ScrapeResult(
                    success=False,
                    strategy=self.name,
                    elapsed_ms=elapsed_ms,
                    failure_reason="spider produced no output file",
                )

            with open(tmp_path, encoding="utf-8") as fh:
                data: dict = json.load(fh)

            status_code: int = data.get("status_code", 0)
            text: str = data.get("text", "")
            error: str | None = data.get("error")

            if error:
                logger.warning("[ScrapyScraper] Spider error for %s: %s", url, error)
                return ScrapeResult(
                    success=False,
                    strategy=self.name,
                    status_code=status_code,
                    elapsed_ms=elapsed_ms,
                    failure_reason=error,
                )

            logger.info(
                "[ScrapyScraper] HTTP %d | %d chars | %dms → %s",
                status_code,
                len(text),
                elapsed_ms,
                url,
            )

            return ScrapeResult(
                success=bool(text),
                text=text,
                strategy=self.name,
                status_code=status_code,
                elapsed_ms=elapsed_ms,
            )

        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.warning("[ScrapyScraper] Subprocess timed out (%ds) for %s", _SUBPROCESS_TIMEOUT, url)
            return ScrapeResult(
                success=False,
                strategy=self.name,
                elapsed_ms=elapsed_ms,
                failure_reason=f"timeout after {_SUBPROCESS_TIMEOUT}s",
            )

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.warning("[ScrapyScraper] Unexpected error for %s: %s", url, exc)
            return ScrapeResult(
                success=False,
                strategy=self.name,
                elapsed_ms=elapsed_ms,
                failure_reason=str(exc),
            )

        finally:
            # Always clean up the temp file
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
