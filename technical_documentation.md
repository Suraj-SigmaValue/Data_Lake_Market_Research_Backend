# Data Lake Market Research — Technical Documentation

**Version:** 2.0 · **Stack:** FastAPI · Playwright · Scrapy · AWS Bedrock · OpenAI  
**Last Updated:** July 2026

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Module Map](#3-module-map)
4. [Scraping Framework — Deep Dive](#4-scraping-framework--deep-dive)
5. [Listing Extraction Pipeline](#5-listing-extraction-pipeline)
6. [Market Analysis Pipeline](#6-market-analysis-pipeline)
7. [API Reference](#7-api-reference)
8. [Data Flow — End to End](#8-data-flow--end-to-end)
9. [Configuration Reference](#9-configuration-reference)
10. [Dependency Graph](#10-dependency-graph)
11. [Error Handling Strategy](#11-error-handling-strategy)
12. [Performance & Scalability](#12-performance--scalability)
13. [Extending the System](#13-extending-the-system)
14. [Operational Guide](#14-operational-guide)

---

## 1. System Overview

Data Lake Market Research is a **production-grade AI-powered real estate intelligence platform**. Given a location and a project name, it:

1. Discovers listing URLs for the project across all major Indian real estate portals.
2. Scrapes each portal page using a bot-resistant multi-strategy scraping framework.
3. Extracts structured property listings from raw page text using a Large Language Model (LLM).
4. Validates extracted listings with a second semantic LLM pass.
5. Deduplicates and streams results to the frontend in real time via Server-Sent Events.

In parallel, it runs a market analysis pipeline that aggregates data across portals, identifies price trends, appreciation rates, and produces final executive summaries — all using AWS Bedrock and OpenAI models concurrently.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          FRONTEND (React)                           │
│                       npm run dev · port 5173                       │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTP / SSE (Server-Sent Events)
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FastAPI Server (Uvicorn)                        │
│                    python -m uvicorn main:app                       │
│                                                                     │
│  POST /analyze                POST /extract-listings-stream         │
│  POST /trend                  POST /extract-listings                │
│  POST /appreciation           POST /final-analysis                  │
└──────────┬────────────────────────────────┬────────────────────────-┘
           │                                │
           ▼                                ▼
┌──────────────────┐            ┌───────────────────────┐
│  Market Analysis │            │  Listing Extraction   │
│  pipeline.py     │            │  listing_extractor.py │
└──────────┬───────┘            └──────────┬────────────┘
           │                               │
           │                               ▼
           │                  ┌────────────────────────┐
           │                  │   Scraping Framework   │
           │                  │   scraper/             │
           │                  │  ┌──────────────────┐  │
           │                  │  │ StrategySelector │  │
           │                  │  └────────┬─────────┘  │
           │                  │           │             │
           │                  │   ┌───────┴────────┐   │
           │                  │   ▼                ▼   │
           │                  │ Scrapy          Playwright│
           │                  │ (subprocess)    (singleton│
           │                  │                  browser)│
           │                  └────────────────────────┘
           │                               │
           ▼                               ▼
┌──────────────────────────────────────────────────────┐
│               LLM Layer                              │
│                                                      │
│   AWS Bedrock (google.gemma-3-4b-it)                │
│   OpenAI (gpt-4o / gpt-4o-mini)                     │
│                                                      │
│   Pass 1: Listing Extraction                         │
│   Pass 2: Semantic Validation                        │
│   Market Analysis: Concurrent category summaries    │
└──────────────────────────────────────────────────────┘
```

---

## 3. Module Map

```
backend/
├── main.py                    ← FastAPI app, all HTTP endpoints
├── pipeline.py                ← Market analysis (OpenAI + Bedrock concurrent)
├── listing_extractor.py       ← URL discovery + LLM extraction pipeline
├── models.py                  ← Pydantic models for all API I/O
├── prompt.py                  ← All LLM prompt templates (Stage 1–4)
├── utils.py                   ← parse_llm_json, extract_token_usage (shared)
├── requirements.txt
├── .env                       ← API keys and environment config
│
└── scraper/                   ← ★ Scraping Framework (v2.0)
    ├── __init__.py            ← Public API: scrape_page(url) → str
    ├── base.py                ← ScrapeResult dataclass + BaseScraper ABC
    ├── portals.py             ← PLAYWRIGHT_PORTALS registry, BOT_SIGNALS
    ├── text_cleaner.py        ← Unicode normalise, deduplicate, strip HTML
    ├── selector.py            ← StrategySelector: routing + fallback logic
    ├── manager.py             ← ScrapeManager: orchestration + logging
    ├── spider.py              ← Standalone Scrapy spider (subprocess entry)
    └── strategies/
        ├── __init__.py
        ├── scrapy_strategy.py      ← ScrapyScraper (subprocess isolated)
        └── playwright_strategy.py  ← PlaywrightScraper (singleton browser)
```

---

## 4. Scraping Framework — Deep Dive

### 4.1 Design Principles

| Principle | Implementation |
|---|---|
| **Single public interface** | `scrape_page(url) → str` is the only function any consumer calls |
| **Strategy pattern** | All scrapers implement `BaseScraper.scrape(url) → ScrapeResult` |
| **Zero exceptions** | Every strategy catches all exceptions and returns `ScrapeResult(success=False, ...)` |
| **Singleton browser** | Playwright's Chromium is launched once per process, reused across all requests |
| **Reactor isolation** | Scrapy runs in a subprocess to avoid Twisted ↔ asyncio event loop conflict |
| **Automatic fallback** | Any non-200 / bot-detected / short-text Scrapy result triggers Playwright retry |

---

### 4.2 Class Diagram

```
BaseScraper (ABC)
│
├── ScrapyScraper          name = "scrapy"
│     scrape(url) → ScrapeResult
│     └── runs: python scraper/spider.py <url> <tmpfile.json>
│
└── PlaywrightScraper      name = "playwright"
      scrape(url) → ScrapeResult
      └── singleton Chromium browser (per process)
            └── per-request: new BrowserContext → Page → close

ScrapeResult (dataclass)
  .success: bool
  .text: str
  .strategy: str
  .status_code: int
  .elapsed_ms: int
  .text_length: int
  .failure_reason: str

StrategySelector
  .select_initial(url) → "scrapy" | "playwright"
  .needs_fallback(result) → bool

ScrapeManager
  .scrape_page(url, text_limit) → str
  ├── _scrapy: ScrapyScraper
  ├── _playwright: PlaywrightScraper
  └── _selector: StrategySelector

scraper/__init__.py
  └── _manager = ScrapeManager()   ← module-level singleton
      scrape_page(url) → str       ← only public export
```

---

### 4.3 Request Flow — Scraping a Single URL

```
scrape_page("https://housing.com/in/buy/...")
        │
        ▼
ScrapeManager.scrape_page()
        │
        ▼
StrategySelector.select_initial(url)
        │
        ├── domain in PLAYWRIGHT_PORTALS?
        │         YES → strategy = "playwright"
        │         NO  → strategy = "scrapy"
        │
        ▼
Run initial strategy
        │
        ├── [ScrapyScraper]
        │     subprocess.run(python spider.py <url> <tmp.json>)
        │     Scrapy spider: retry middleware, autothrottle,
        │                    random UA, cookies, compression
        │     Parse BS4: remove script/style/nav/footer/header
        │     Write JSON → tmp file → ScrapyScraper reads it
        │     Return ScrapeResult
        │
        └── [PlaywrightScraper]
              _get_browser() → singleton Chromium (launched once)
              browser.new_context() → isolated session per request
              page.goto(url, wait_until="networkidle")
              _dismiss_banners() → JS click cookie consent buttons
              _scroll_progressively() → 5 rounds, lazy load trigger
              page.evaluate(JS_EXTRACT_TEXT) → body.innerText
              context.close() → context destroyed, browser kept
              Return ScrapeResult
        │
        ▼
StrategySelector.needs_fallback(result)?
        │
        ├── status_code in {401, 403, 406, 429, 503} → YES
        ├── text_length < 200 chars → YES
        ├── BOT_SIGNALS found in text → YES
        └── else → NO
        │
        ├── YES and initial was "scrapy":
        │       Run PlaywrightScraper
        │       Use better of two results
        │
        └── NO or initial was already "playwright":
                Use as-is
        │
        ▼
clean_text(result.text)
        │
        Unicode NFKC → strip HTML tags → collapse whitespace
        → split lines → filter short/blank → deduplicate lines
        → rejoin → [:text_limit]
        │
        ▼
return str   ← always a string, never an exception
```

---

### 4.4 Scrapy Spider — Subprocess Architecture

**Why subprocess?**

Scrapy uses the Twisted async framework internally. FastAPI uses asyncio. If Scrapy's `CrawlerProcess` is run inside the same Python process as Uvicorn, the two reactors conflict and cause `ReactorNotRestartable` errors.

**Solution:** Run `scraper/spider.py` as a child process:

```
FastAPI process (asyncio)
    │
    └── asyncio.to_thread(scrape_listing_page, url)
              │
              └── ScrapyScraper.scrape(url)
                        │
                        └── subprocess.run([python, spider.py, url, tmp.json])
                                  │
                                  [Child Process — own Twisted reactor]
                                  │
                                  CrawlerProcess.start()
                                  SinglePageSpider.parse()
                                  writes: tmp.json
                                  [Child exits]
                        │
                        ScrapyScraper reads tmp.json
                        return ScrapeResult
```

**Scrapy settings applied in `spider.py`:**

| Setting | Value | Purpose |
|---|---|---|
| `ROBOTSTXT_OBEY` | `False` | Real estate portals block all bots in robots.txt |
| `AUTOTHROTTLE_ENABLED` | `True` | Adaptive rate — won't hammer servers |
| `AUTOTHROTTLE_START_DELAY` | `0.25s` | Initial delay before autothrottle takes over |
| `HTTPCACHE_ENABLED` | `False` | Always fetch fresh listing data |
| `RETRY_ENABLED` | `True` | Retry on 500/502/503/504/408 |
| `RETRY_TIMES` | `2` | Up to 2 retries per URL |
| `COOKIES_ENABLED` | `True` | Maintain session cookies |
| `COMPRESSION_ENABLED` | `True` | Accept gzip/brotli responses |
| `DNSCACHE_ENABLED` | `True` | Reduce DNS lookup overhead |
| `LOG_ENABLED` | `False` | Suppress Scrapy logs (parent handles logging) |

---

### 4.5 Playwright Browser — Singleton Architecture

```
Process lifetime:
┌─────────────────────────────────────────────────────────────────────┐
│  PlaywrightScraper._playwright_instance (module-level singleton)    │
│  PlaywrightScraper._browser            (Chromium, launched once)    │
│                                                                     │
│  Request 1:                                                         │
│    browser.new_context() ─── Page ─── page.goto() ─── context.close│
│                                                                     │
│  Request 2:                                                         │
│    browser.new_context() ─── Page ─── page.goto() ─── context.close│
│                                                                     │
│  [Browser stays alive between requests]                             │
└─────────────────────────────────────────────────────────────────────┘

Thread safety: _browser_lock (threading.Lock) guards all initialisation.
Each request creates its own BrowserContext → completely isolated cookies,
localStorage, and session state.
```

**Playwright launch flags:**

| Argument | Purpose |
|---|---|
| `--no-sandbox` | Required in containerised / restricted environments |
| `--disable-blink-features=AutomationControlled` | Hides Playwright's automation flag from JS detection |
| `--disable-dev-shm-usage` | Prevents Chrome from running out of shared memory |
| `--disable-extensions` | Faster startup, smaller footprint |

---

### 4.6 Portal Registry

Portals routed **directly to Playwright** (no Scrapy attempt):

| Portal | Domain | Bot Protection |
|---|---|---|
| 99acres | `99acres.com` | Akamai Bot Manager |
| Housing | `housing.com` | Cloudflare |
| MagicBricks | `magicbricks.com` | Imperva |
| NoBroker | `nobroker.in` | Custom WAF |
| SquareYards | `squareyards.com` | Cloudflare |
| Nestoria | `nestoria.in` | Cloudflare |
| Makaan | `makaan.com` | Standard |
| CommonFloor | `commonfloor.com` | Standard |
| PropTiger | `proptiger.com` | Standard |

**To add a new portal**, add its domain to `scraper/portals.py`:
```python
PLAYWRIGHT_PORTALS: frozenset[str] = frozenset({
    ...
    "newportal.com",   # ← add here
})
```

---

## 5. Listing Extraction Pipeline

### 5.1 Overview

```
POST /extract-listings-stream
        │
        ▼
stream_extract_listings(project_name, location, urls, provider, property_type)
        │
        ▼
asyncio.Semaphore(2)   ← max 2 concurrent URL extractions
        │
        ▼
_async_scrape_and_extract(url_idx, url_obj, ...)   [per URL, concurrent]
        │
        ├── scrape_listing_page(href)              ← NEW: scraper package
        │         └── ScrapeManager.scrape_page()
        │
        ├── MIN_EXTRACTABLE_TEXT guard (200 chars)
        │
        ├── Save debug .txt: {ProjectName}_{portal}.txt
        │
        ├── Property keyword pre-filter
        │         (bhk / price / sqft / crore / lakh / office / retail ...)
        │
        └── extract_listings_from_text(page_text, project_name, ...)
                  │
                  ├── Pass 1: LLM Extraction (Bedrock)
                  │     Prompt: project name + category + page_text[:8000]
                  │     Returns: {"listings": [...]}
                  │
                  └── Pass 2: Semantic Validation (Bedrock)
                        Validates each listing belongs to requested category
                        Fallback: if Pass 2 fails or rejects ALL → trust Pass 1
```

### 5.2 LLM Extraction Prompt (Pass 1)

The prompt instructs the LLM to:

1. **Dynamic Section Understanding** — Mentally scan page sections and classify each by intent (Overview, Floor Plans, Pricing, Related Projects, etc.)
2. **IGNORE** sections for Recommended / Nearby / Related projects
3. **IGNORE** wrong categories (e.g. residential listings on an office search)
4. Apply a 4-step **Validation Pipeline** per listing:
   - Project Validation (name must match or be an obvious abbreviation)
   - Category Validation (must match requested type)
   - Listing Validation (is it a real property config?)
   - Extraction → JSON

**Output schema:**
```json
{
  "listings": [
    {
      "project_name": "Nivaas Business Square",
      "category": "office",
      "title": "Office Space",
      "price": "74.43 Lacs",
      "currency": "₹",
      "area": "827",
      "area_type": "sq.ft. Carpet Area",
      "location": "Hinjewadi, Pune"
    }
  ]
}
```

### 5.3 Pass 2 — Semantic Validation

| Scenario | Outcome |
|---|---|
| LLM returns valid `is_valid: true` for each listing | Use filtered list |
| LLM returns empty `validation: []` | Trust Pass 1 entirely (log warning) |
| LLM rejects ALL Pass 1 listings | Trust Pass 1 entirely (log warning) |
| LLM call raises exception | Trust Pass 1 entirely (log error) |

This prevents a Gemma 3 4B model failure in Pass 2 from silently wiping valid listings.

### 5.4 Deduplication

After extraction, each listing is fingerprinted:

```python
fp = hashlib.md5(
    f"{title.lower().strip()}{price.strip()}{area.strip()}".encode()
).hexdigest()
```

Only listings with unseen fingerprints are added to the result set.

### 5.5 Debug File Naming

Each successfully scraped page (≥ 200 chars, passes keyword filter) writes a debug file:

```
{Sanitized_Project_Name}_{portal_name}.txt

Examples:
  Nivaas_Business_Square_floortap.txt
  Kolte_Patil_Life_Republic_housing.txt
  Gera_Adara_99acres.txt
```

Files are auto-managed: maximum 10 kept, oldest deleted beyond cap. `requirements.txt` is always excluded.

---

## 6. Market Analysis Pipeline

### 6.1 Concurrent Category Analysis

```
POST /analyze  →  run_openai_analysis() + run_bedrock_analysis()
                              [concurrent via asyncio.gather]
        │
        ▼
For each category: residential · office · retail · land
        │
        ThreadPoolExecutor(4)
        │
        ├── get_search_context(location, category)
        │         DDG search → top results → scrape top 2 URLs → combine context
        │         (Tavily fallback if DDG fails)
        │
        └── LLM(stage_prompt, context)
                  ├── OpenAI: gpt-4o / gpt-4o-mini
                  └── Bedrock: google.gemma-3-4b-it
```

### 6.2 4-Stage Analysis Pipeline

| Stage | Prompt | Output |
|---|---|---|
| Stage 1 (`/analyze`) | Location identification + property categories with price ranges | `PipelineResult` with `PropertyCategories` |
| Stage 2 (`/trend`) | Market trend analysis (6/12/24 month price trend) | `TrendResponse` |
| Stage 3 (`/appreciation`) | Appreciation rate analysis + projections | `AppreciationResponse` |
| Stage 4 (`/final-analysis`) | Executive summary combining all 3 stages | `FinalAnalysisResponse` |

### 6.3 URL Discovery (fetch_project_urls)

After Stage 1 identifies project names, `fetch_project_urls()` runs for each project:

```
project_name + location + category
        │
        ▼
build_queries()  →  ['"ProjectName" real estate project, Location office sales listing']
        │
        ▼
DDGS().text(query)   ← DuckDuckGo search
        │ (if fails)
        └── Tavily fallback search
        │
        ▼
Filter results:
  - URL must contain real estate portal domain
  - URL not already seen (dedup by URL)
  - Max max_urls=15 per project
        │
        ▼
Return: [{portal: "99acres", url: "https://..."}, ...]
```

---

## 7. API Reference

### `POST /analyze`

**Request:**
```json
{
  "latitude": 18.5942,
  "longitude": 73.7381,
  "location": "hinjewadi, pune"
}
```

**Response:** `AnalyzeResponse` — OpenAI + Bedrock results for all 4 categories with token usage.

---

### `POST /extract-listings-stream`

**Request:**
```json
{
  "project_name": "Nivaas Business Square",
  "location": "Hinjewadi, Pune",
  "property_type": "office",
  "provider": "bedrock",
  "urls": [
    {"portal": "floortap", "url": "https://floortap.com/..."},
    {"portal": "housing",  "url": "https://housing.com/..."}
  ]
}
```

**Response:** `text/event-stream` (SSE). Events:

| Event | Payload |
|---|---|
| `status` | `{"msg": "Scraping floortap…"}` |
| `listing` | Full listing JSON object |
| `tokens` | `{"input_tokens": 1200, "output_tokens": 340, ...}` |
| `error` | `{"msg": "Scraping error on housing: ..."}` |
| `done` | `{"total": 3}` |

---

### `POST /extract-listings`

Same request as stream endpoint. Returns all listings at once (non-streaming). Used for batch/testing.

---

### `POST /trend`, `POST /appreciation`, `POST /final-analysis`

Run the respective pipeline stage. Each accepts the same `AnalyzeRequest` (plus stage-specific data for `/final-analysis`) and returns the dual OpenAI + Bedrock result.

---

## 8. Data Flow — End to End

```
User types "Hinjewadi, Pune" in frontend
        │
        ▼
Frontend: POST /analyze { location, latitude, longitude }
        │
        ▼
pipeline.py:
  ┌─── run_openai_analysis() ───────────────────────────────────────┐
  │    4 categories × DDG search × deep scrape × OpenAI prompt      │
  └─────────────────────────────────────────────────────────────────┘
  ┌─── run_bedrock_analysis() ──────────────────────────────────────┐
  │    Same, using AWS Bedrock endpoint                              │
  └─────────────────────────────────────────────────────────────────┘
  Both run concurrently via asyncio.gather()
        │
        ▼
Stage 1 identifies projects:
  residential: [Kolte Patil Life Republic, Gera Adara, ...]
  office:      [Nivaas Business Square, ...]
  retail:      [Xion Mall, ...]
  land:        [Blue Ridge, ...]
        │
        ▼
fetch_project_urls() per project [ThreadPoolExecutor(4)]
  → DDG / Tavily search
  → Returns list of {portal, url} per project
        │
        ▼
Frontend displays project cards with portal URLs
        │
User clicks "Extract Listings" for a project
        │
        ▼
Frontend: POST /extract-listings-stream {project_name, location, urls, property_type}
        │
        ▼
stream_extract_listings() [async generator]
  asyncio.Semaphore(2)   ← 2 concurrent URL tasks
        │
        For each URL:
        ▼
_async_scrape_and_extract()
  ├── scrape_listing_page(url)     ← scraper package
  │     StrategySelector → Scrapy or Playwright
  │     ScrapeManager → clean text
  │
  ├── Keyword pre-filter
  │
  ├── extract_listings_from_text() [Pass 1: LLM extraction]
  │     Bedrock Gemma → {"listings": [...]}
  │
  ├── _validate_extracted_listings() [Pass 2: semantic validation]
  │     Bedrock Gemma → filter by category
  │
  └── Yield SSE events to frontend:
        event: listing → {project_name, category, title, price, area, ...}
        event: tokens  → {input_tokens, output_tokens, ...}
        │
        ▼
Frontend renders listings in real time as SSE events arrive
```

---

## 9. Configuration Reference

### Environment Variables (`.env`)

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API key for market analysis |
| `BEDROCK_API_KEY` | ✅ | AWS Bedrock API key |
| `BEDROCK_BASE_URL` | ✅ | Bedrock Mantle endpoint URL |
| `LLM_MODEL` | ✅ | Bedrock model ID (e.g. `google.gemma-3-4b-it`) |
| `Tavily_API` | ✅ | Tavily search API key (DDG fallback) |
| `PLAYWRIGHT_HEADLESS` | ⚪ | `false` (default) — `true` for headless mode |
| `PLAYWRIGHT_TIMEOUT_MS` | ⚪ | Page load timeout in ms (default `30000`) |

### Scraper Tuning Constants

| Constant | File | Default | Description |
|---|---|---|---|
| `MIN_EXTRACTABLE_TEXT` | `listing_extractor.py` | `200` | Min chars to pass to LLM |
| `MIN_TEXT_LENGTH` | `scraper/selector.py` | `200` | Min chars before Playwright fallback |
| `_SUBPROCESS_TIMEOUT` | `strategies/scrapy_strategy.py` | `40s` | Max Scrapy subprocess duration |
| `_PAGE_TIMEOUT_MS` | `strategies/playwright_strategy.py` | `30000ms` | Max Playwright page load time |
| `_MAX_SCROLL_ROUNDS` | `strategies/playwright_strategy.py` | `5` | Scroll iterations for lazy loading |
| `_TXT_KEEP_MAX` | `listing_extractor.py` | `10` | Max debug .txt files retained |
| `QUERY_DELAY_RANGE` | `listing_extractor.py` | `(0.5, 2.5)s` | Random jitter between DDG searches |
| `Semaphore(2)` | `listing_extractor.py` | `2` | Max concurrent URL extractions |

---

## 10. Dependency Graph

```
main.py
  ├── pipeline.py
  │     ├── utils.py           (parse_llm_json, extract_token_usage)
  │     ├── models.py
  │     ├── prompt.py
  │     └── listing_extractor  (lazy import — fetch_project_urls only)
  │
  └── listing_extractor.py
        ├── scraper/           (scrape_page — the new framework)
        │     ├── scraper/base.py
        │     ├── scraper/portals.py
        │     ├── scraper/text_cleaner.py
        │     ├── scraper/selector.py
        │     ├── scraper/manager.py
        │     ├── scraper/spider.py      (subprocess: no direct import at runtime)
        │     └── scraper/strategies/
        │           ├── scrapy_strategy.py
        │           └── playwright_strategy.py
        ├── utils.py           (parse_llm_json, extract_token_usage)
        └── models.py

utils.py
  └── models.py               (TokenUsage only)

models.py                     (no project-level imports — leaf node)
prompt.py                     (no project-level imports — leaf node)
```

> [!IMPORTANT]
> `utils.py` was created specifically to break the circular import between `pipeline.py` and `listing_extractor.py`. Neither file imports from the other at module level. `fetch_project_urls` is imported **lazily** inside `process_project()` in `pipeline.py` to ensure both modules are fully loaded before the import is attempted.

---

## 11. Error Handling Strategy

### Principle: No exception should crash the pipeline

| Layer | Error | Handling |
|---|---|---|
| **Scraper** | HTTP 403/406/429 from Scrapy | Auto-fallback to Playwright |
| **Scraper** | Bot-detection text in response | Auto-fallback to Playwright |
| **Scraper** | Playwright page timeout | Returns `ScrapeResult(success=False)` |
| **Scraper** | Scrapy subprocess timeout | Returns `ScrapeResult(success=False, failure_reason="timeout")` |
| **Extractor** | Page text < 200 chars | Skip URL, emit status SSE event |
| **Extractor** | No property keywords in page | Skip URL, emit status SSE event |
| **LLM Pass 1** | API error | Return `[], TokenUsage()` — URL skipped |
| **LLM Pass 2** | API error | Fall back to Pass 1 results (not empty!) |
| **LLM Pass 2** | Rejects all listings | Fall back to Pass 1 results (not empty!) |
| **URL Discovery** | DDG search fails | Automatic Tavily fallback |
| **URL Discovery** | Tavily also fails | Return empty list — project skipped |
| **Pipeline** | Project fetch_project_urls error | Logged, that project gets no portal_listings |

---

## 12. Performance & Scalability

### Current Architecture Limits

| Bottleneck | Current Setting | Impact |
|---|---|---|
| Concurrent URL extractions | `Semaphore(2)` | 2 URLs processed simultaneously |
| Playwright browser | 1 singleton | Thread-safe, but contexts serialise on the browser |
| Scrapy subprocess | 1 subprocess per URL | ~2-3s overhead for process startup |
| ThreadPoolExecutor | 4 workers for project URL fetch | Limits concurrent DDG search calls |

### Performance Characteristics

| Operation | Typical Duration |
|---|---|
| Scrapy scrape (static page, 200 OK) | 2–5 seconds |
| Playwright first URL (browser cold start) | 5–8 seconds |
| Playwright subsequent URLs (browser warm) | 2–4 seconds |
| LLM Pass 1 (Bedrock Gemma 4B) | 1–3 seconds |
| LLM Pass 2 (Bedrock Gemma 4B) | 1–2 seconds |
| Full listing extraction (5 URLs, 2 concurrent) | 15–40 seconds |

### Scalability Recommendations

1. **Horizontal scaling** — Run multiple Uvicorn workers (`--workers 4`). Each worker gets its own Playwright browser singleton.
2. **Playwright concurrency** — Add `PLAYWRIGHT_MAX_CONCURRENCY` env-var to cap browser contexts per process.
3. **Redis queue** — Move URL extraction to a background job queue (Celery + Redis) for large batches.
4. **Scrapy shared process** — For high-volume use, keep a persistent Scrapy `CrawlerRunner` in an asyncio-compatible background thread rather than spawning a subprocess per URL.
5. **LLM model upgrade** — Swap `LLM_MODEL` to a larger Bedrock model for better extraction accuracy on complex pages.

---

## 13. Extending the System

### Adding a New Scraping Strategy

1. Create `scraper/strategies/my_strategy.py`:

```python
from scraper.base import BaseScraper, ScrapeResult

class MyStrategy(BaseScraper):
    name = "mystrategy"

    def scrape(self, url: str) -> ScrapeResult:
        try:
            # ... fetch and extract text ...
            return ScrapeResult(success=True, text=text, strategy=self.name)
        except Exception as exc:
            return ScrapeResult(success=False, failure_reason=str(exc), strategy=self.name)
```

2. Register it in `scraper/manager.py`:

```python
from scraper.strategies.my_strategy import MyStrategy

class ScrapeManager:
    def __init__(self):
        self._scrapy = ScrapyScraper()
        self._playwright = PlaywrightScraper()
        self._my = MyStrategy()          # ← add
        self._selector = StrategySelector()
```

3. Update routing logic in `scraper/selector.py` if needed.

---

### Adding a New Portal to the Registry

`scraper/portals.py`:
```python
PLAYWRIGHT_PORTALS: frozenset[str] = frozenset({
    ...
    "newportal.com",  # ← add domain without www
})
```

---

### Adding a New Analysis Stage

1. Add prompt template to `prompt.py`
2. Add analysis function to `pipeline.py` following the existing pattern
3. Add Pydantic response model to `models.py`
4. Add FastAPI endpoint to `main.py`

---

## 14. Operational Guide

### Starting the Server

```powershell
# Backend
cd backend
.\venv\Scripts\activate
python -m uvicorn main:app --reload

# Frontend
cd frontend
npm run dev
```

### First-Time Setup

```powershell
pip install -r requirements.txt
playwright install chromium
```

### Checking Logs

All scraping events are logged with structured prefixes:

```
[StrategySelector] Selected Strategy: playwright → https://housing.com/...
[PlaywrightScraper] Launching Chromium (headless=False)…
[PlaywrightScraper] HTTP 200 → https://housing.com/...
[ScrapeManager] Characters Extracted: 6420 | Strategy Used: playwright | Elapsed Time: 3240ms
[ScrapeManager] Fallback Triggered → Playwright Started for https://99acres.com/...
Pass 1 extracted 2 listing(s) from https://floortap.com/...
Pass 2 kept 2/2 listing(s)
LLM extracted 2 valid listing(s) out of 2 from https://floortap.com/...
```

### Debug Files

After each extraction run, `.txt` files are written to `backend/`:

```
Nivaas_Business_Square_floortap.txt     ← page text sent to LLM
Kolte_Patil_Life_Republic_housing.txt
```

These files only exist when the page had ≥ 200 chars of usable text. `requirements.txt` is never deleted by the auto-cleanup.

### Shutting Down Playwright Gracefully

The Playwright browser is a persistent subprocess. It is cleaned up automatically when the Python process exits. For explicit cleanup (e.g. in tests):

```python
from scraper.strategies.playwright_strategy import PlaywrightScraper
PlaywrightScraper.shutdown()
```

---

*Documentation generated for Data Lake Market Research v2.0 — Scraping Framework redesign, July 2026.*
