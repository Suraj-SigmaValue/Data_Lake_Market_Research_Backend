"""
scraper/portals.py — Registry of known JS-heavy portals and bot-detection signal phrases.

Add new portals here to route them directly to Playwright without a Scrapy attempt.
Add new bot signals to catch additional anti-scraping responses.
"""

# ---------------------------------------------------------------------------
# Portals that must be scraped with Playwright (JavaScript-heavy / bot-protected)
# ---------------------------------------------------------------------------
PLAYWRIGHT_PORTALS: frozenset[str] = frozenset({
    "99acres.com",
    "housing.com",
    "magicbricks.com",
    "nobroker.in",
    "squareyards.com",
    "nestoria.in",
    "makaan.com",
    "commonfloor.com",
    "proptiger.com",
    "homeproperty.com",
    "indiaproperties.com",
})

# ---------------------------------------------------------------------------
# Text phrases that indicate bot-detection / CAPTCHA pages
# ---------------------------------------------------------------------------
BOT_SIGNALS: tuple[str, ...] = (
    "access denied",
    "verify you are human",
    "cloudflare",
    "captcha",
    "checking your browser",
    "just a moment",
    "please enable cookies",
    "ddos protection",
    "ray id",
    "error 1020",
    "error 1015",
    "security check",
    "enable javascript",
    "browser check",
    "please wait",
    "too many requests",
)

# ---------------------------------------------------------------------------
# HTTP status codes that should trigger a Playwright fallback
# ---------------------------------------------------------------------------
FALLBACK_STATUS_CODES: frozenset[int] = frozenset({
    401, 403, 406, 429, 503
})
