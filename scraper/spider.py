#!/usr/bin/env python
"""
scraper/spider.py — Standalone Scrapy spider for single-URL text extraction.

Run as a subprocess:
    python scraper/spider.py <url> <output_json_path>

Writes a JSON object to <output_json_path>:
    {
        "status_code": 200,
        "text": "...",
        "url": "...",
        "error": null
    }

Running in a subprocess isolates Scrapy's Twisted reactor from the host
process's asyncio event loop, avoiding the well-known
"reactor already started" / "cannot install reactor" conflict.

Scrapy settings applied:
  - ROBOTSTXT_OBEY: False          (real estate portals block scrapers)
  - AUTOTHROTTLE: enabled          (adaptive request rate)
  - HTTPCACHE: disabled            (always fetch fresh data)
  - RETRY: enabled (2x)           (transient server errors)
  - COOKIES: enabled               (session cookies required by many portals)
  - COMPRESSION: enabled           (gzip/br support)
  - DNSCACHE: enabled              (reduce DNS lookup latency)
  - LOG: disabled                  (output goes to parent via JSON, not logs)
"""

from __future__ import annotations

import json
import os
import random
import sys

# Suppress Scrapy's default logging to stderr (we log via the parent process)
import logging
logging.disable(logging.CRITICAL)

try:
    import scrapy
    from scrapy.crawler import CrawlerProcess
    from bs4 import BeautifulSoup
except ImportError as exc:
    # If scrapy/bs4 not installed, write error JSON and exit
    print(json.dumps({"status_code": 0, "text": "", "url": "", "error": f"Import error: {exc}"}))
    sys.exit(1)


# ---------------------------------------------------------------------------
# User-Agent pool (same as main listing_extractor for consistency)
# ---------------------------------------------------------------------------
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

_REMOVE_TAGS = [
    "script", "style", "nav", "footer", "header",
    "aside", "noscript", "iframe", "svg", "form",
]

_TEXT_LIMIT = 12_000  # chars — parent process will further cap to 8000


# ---------------------------------------------------------------------------
# Spider
# ---------------------------------------------------------------------------

class SinglePageSpider(scrapy.Spider):
    """Fetches a single URL and writes extracted visible text to a JSON file."""

    name = "single_page"

    custom_settings = {
        # Bot avoidance
        "ROBOTSTXT_OBEY": False,
        # Adaptive throttling
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 0.25,
        "AUTOTHROTTLE_MAX_DELAY": 3.0,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 1.0,
        # Caching — DISABLED (always fresh)
        "HTTPCACHE_ENABLED": False,
        # Retry on transient errors
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 2,
        "RETRY_HTTP_CODES": [500, 502, 503, 504, 408],
        # Browser-like behaviour
        "COOKIES_ENABLED": True,
        "COMPRESSION_ENABLED": True,
        # Performance
        "DOWNLOAD_TIMEOUT": 20,
        "DNSCACHE_ENABLED": True,
        "CONCURRENT_REQUESTS": 1,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        # Silence all logging — parent reads JSON from output file
        "LOG_ENABLED": False,
        "LOG_LEVEL": "CRITICAL",
        # Middlewares
        "DOWNLOADER_MIDDLEWARES": {
            "scrapy.downloadermiddlewares.retry.RetryMiddleware": 90,
            "scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware": 810,
        },
    }

    def __init__(self, url: str, output_file: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_url = url
        self.output_file = output_file
        self._result: dict = {
            "status_code": 0,
            "text": "",
            "url": url,
            "error": None,
        }

    @property
    def start_urls(self) -> list[str]:  # type: ignore[override]
        return [self.target_url]

    def start_requests(self):
        yield scrapy.Request(
            self.target_url,
            headers={
                "User-Agent": random.choice(_USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-IN,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Cache-Control": "max-age=0",
            },
            callback=self.parse,
            errback=self.errback,
            dont_filter=True,
        )

    def parse(self, response):
        self._result["status_code"] = response.status
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(_REMOVE_TAGS):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            self._result["text"] = text[:_TEXT_LIMIT]
        except Exception as exc:
            self._result["error"] = f"Parse error: {exc}"

    def errback(self, failure):
        self._result["error"] = repr(failure.value)
        # Try to capture the HTTP status from the failed response
        if failure.check(scrapy.spidermiddlewares.httperror.HttpError):
            self._result["status_code"] = failure.value.response.status

    def closed(self, reason: str):  # noqa: ARG002
        """Write result JSON when spider finishes."""
        try:
            with open(self.output_file, "w", encoding="utf-8") as fh:
                json.dump(self._result, fh, ensure_ascii=False)
        except Exception as exc:
            # Last-resort: print to stdout so parent can still read something
            print(json.dumps({"error": f"Failed to write output: {exc}"}))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(json.dumps({"error": "Usage: spider.py <url> <output_file>"}))
        sys.exit(1)

    target_url = sys.argv[1]
    output_path = sys.argv[2]

    process = CrawlerProcess()
    process.crawl(SinglePageSpider, url=target_url, output_file=output_path)
    process.start()  # blocks until spider finishes (safe in subprocess)
