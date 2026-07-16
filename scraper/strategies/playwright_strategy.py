"""
scraper/strategies/playwright_strategy.py — PlaywrightScraper implementation.

Uses the Playwright sync API with a SINGLETON Chromium browser.
The browser is launched once per process and reused across all requests.
Each request gets an isolated BrowserContext (separate cookies/cache/session).

Design decisions:
  - sync_api is used because this runs inside asyncio.to_thread()
    (threads have no asyncio event loop, so sync_api is correct here)
  - A class-level lock ensures thread-safe browser initialisation
  - PLAYWRIGHT_HEADLESS env-var controls headless mode (default: False)
    headless=False bypasses Cloudflare/bot detection on portals like 99acres

Features:
  - Cookie banner auto-dismiss
  - Progressive scrolling to trigger lazy loading
  - networkidle wait for JS-rendered content
  - Stealth args to reduce bot-detection fingerprint
"""

from __future__ import annotations

import logging
import os
import threading
import time

from scraper.base import BaseScraper, ScrapeResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config from environment
# ---------------------------------------------------------------------------
_HEADLESS: bool = os.getenv("PLAYWRIGHT_HEADLESS", "false").strip().lower() not in ("false", "0", "no")
_PAGE_TIMEOUT_MS: int = int(os.getenv("PLAYWRIGHT_TIMEOUT_MS", "30000"))
_MAX_SCROLL_ROUNDS: int = 5

# ---------------------------------------------------------------------------
# User-Agent pool (same as rest of project)
# ---------------------------------------------------------------------------
_USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
)

# ---------------------------------------------------------------------------
# JS snippets
# ---------------------------------------------------------------------------

_JS_DISMISS_BANNERS = """
() => {
    const closeKeywords = [
        'ok, got it', 'accept', 'i agree', 'close', 'allow',
        'accept all', 'got it', 'dismiss', 'agree', 'continue',
    ];
    const els = document.querySelectorAll('button, a, div[role="button"], span[role="button"]');
    for (const el of els) {
        const t = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase().trim();
        if (closeKeywords.some(k => t === k) && el.offsetHeight > 0) {
            el.click();
        }
    }
}
"""

_JS_EXTRACT_TEXT = """
() => {
    const remove = (sel) => document.querySelectorAll(sel).forEach(e => e.remove());
    remove('script,style,nav,footer,header,aside,noscript,iframe,svg,form,[aria-hidden="true"]');
    return document.body ? document.body.innerText : '';
}
"""

_JS_SCROLL_DOWN = "window.scrollBy(0, window.innerHeight * 1.5);"

_JS_PAGE_HEIGHT = "() => document.body.scrollHeight"


# ---------------------------------------------------------------------------
# Per-thread browser management (threading.local)
# ---------------------------------------------------------------------------
# Playwright's sync_api binds Browser/Page objects to the greenlet of the
# thread that created them. Sharing a single browser across multiple threads
# causes "greenlet: Cannot switch to a different thread" errors.
# Solution: each worker thread gets its own Playwright instance + browser.
# With Semaphore(2) concurrency, at most 2 Chrome instances run at once.
# ---------------------------------------------------------------------------

_thread_local = threading.local()


def _get_browser():
    """
    Return (or lazily create) a per-thread Playwright Chromium browser.
    Each call from a new thread creates its own Playwright + browser.
    The browser is reused for subsequent calls from the same thread.
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
    except ImportError:
        raise RuntimeError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    # Start playwright instance for this thread if not already done
    if not getattr(_thread_local, "pw", None):
        _thread_local.pw = sync_playwright().start()
        _thread_local.browser = None
        logger.info(
            "[PlaywrightScraper] Launched Playwright for thread %s (headless=%s)",
            threading.current_thread().name,
            _HEADLESS,
        )

    # Launch browser if not yet created or if it disconnected
    browser = getattr(_thread_local, "browser", None)
    if browser is None:
        try:
            if browser is not None and not browser.is_connected():
                browser = None
        except Exception:
            browser = None

    if browser is None:
        _thread_local.browser = _thread_local.pw.chromium.launch(
            headless=_HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-infobars",
            ],
        )
        logger.info(
            "[PlaywrightScraper] Chromium launched on thread %s",
            threading.current_thread().name,
        )

    return _thread_local.browser



# ---------------------------------------------------------------------------
# Strategy class
# ---------------------------------------------------------------------------

class PlaywrightScraper(BaseScraper):
    """
    JS-capable scraper using a persistent Playwright Chromium browser.

    Each call gets an isolated BrowserContext so cookies/sessions don't
    bleed between requests. The browser itself is reused across calls
    to avoid 3-5 second Chrome launch overhead on every URL.
    """

    name = "playwright"

    def scrape(self, url: str) -> ScrapeResult:  # noqa: PLR0912
        try:
            from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
        except ImportError:
            return ScrapeResult(
                success=False,
                strategy=self.name,
                failure_reason="playwright not installed",
            )

        import random  # noqa: PLC0415

        t0 = time.perf_counter()
        context = None

        try:
            browser = _get_browser()

            # Isolated context per request (separate cookies, localStorage, etc.)
            context = browser.new_context(
                user_agent=random.choice(_USER_AGENTS),
                viewport={"width": 1920, "height": 1080},
                locale="en-IN",
                java_script_enabled=True,
                ignore_https_errors=True,
                extra_http_headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "en-IN,en;q=0.9",
                },
            )

            page = context.new_page()

            # Hide webdriver flag (stealth)
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            logger.info("[PlaywrightScraper] Navigating → %s", url)

            try:
                response = page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=_PAGE_TIMEOUT_MS,
                )
            except PlaywrightError:
                # networkidle can timeout on heavy sites; fall back to domcontentloaded
                try:
                    response = page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=_PAGE_TIMEOUT_MS,
                    )
                except PlaywrightError as exc:
                    elapsed_ms = int((time.perf_counter() - t0) * 1000)
                    logger.warning("[PlaywrightScraper] Navigation failed for %s: %s", url, exc)
                    return ScrapeResult(
                        success=False,
                        strategy=self.name,
                        elapsed_ms=elapsed_ms,
                        failure_reason=str(exc),
                    )

            status_code: int = response.status if response else 0
            logger.info("[PlaywrightScraper] HTTP %d → %s", status_code, url)

            # Dismiss cookie / consent banners
            self._dismiss_banners(page)

            # Progressive scroll to trigger lazy-loaded content
            self._scroll_progressively(page)

            # Extract clean visible text via JS
            try:
                text: str = page.evaluate(_JS_EXTRACT_TEXT) or ""
            except PlaywrightError:
                text = page.inner_text("body") if page.query_selector("body") else ""

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "[PlaywrightScraper] Text Extracted: %d chars | %dms → %s",
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

        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.warning("[PlaywrightScraper] Unexpected error for %s: %s", url, exc)
            return ScrapeResult(
                success=False,
                strategy=self.name,
                elapsed_ms=elapsed_ms,
                failure_reason=str(exc),
            )

        finally:
            # Always close the context — keeps the singleton browser clean
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dismiss_banners(page) -> None:
        """Try to close cookie consent / GDPR banners."""
        try:
            page.evaluate(_JS_DISMISS_BANNERS)
            page.wait_for_timeout(500)
        except Exception:
            pass

    @staticmethod
    def _scroll_progressively(page) -> None:
        """
        Scroll down in increments to trigger lazy loading.
        Stops early if the page height stops growing (content is fully loaded).
        """
        try:
            prev_height: int = 0
            stable_rounds: int = 0

            for _ in range(_MAX_SCROLL_ROUNDS):
                page.evaluate(_JS_SCROLL_DOWN)
                page.wait_for_timeout(800)

                current_height: int = page.evaluate(_JS_PAGE_HEIGHT)
                if current_height == prev_height:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break  # DOM has stabilised — no more content to load
                else:
                    stable_rounds = 0

                prev_height = current_height

        except Exception:
            pass

    @classmethod
    def shutdown(cls) -> None:
        """
        Cleanly close the browser and Playwright for the CURRENT thread.
        Call this at application shutdown or in tests after scraping is done.
        """
        browser = getattr(_thread_local, "browser", None)
        if browser is not None:
            try:
                browser.close()
                logger.info(
                    "[PlaywrightScraper] Browser closed for thread %s",
                    threading.current_thread().name,
                )
            except Exception:
                pass
            _thread_local.browser = None

        pw = getattr(_thread_local, "pw", None)
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass
            _thread_local.pw = None
