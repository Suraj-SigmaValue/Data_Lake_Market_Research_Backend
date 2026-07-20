import os
import time
import logging
import hashlib
import json
import random
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
from openai import OpenAI
from ddgs import DDGS
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup
from models import TokenUsage
from utils import parse_llm_json, extract_token_usage  # shared utils — avoids circular import

try:
    from tavily import TavilyClient as _TavilyClientLE
    _TAVILY_LE_AVAILABLE = True
except ImportError:
    _TAVILY_LE_AVAILABLE = False

# ---------------------------------------------------------------------------
# Scraping layer — delegated to the modular scraper package
# ---------------------------------------------------------------------------
from scraper import scrape_page as scrape_listing_page  # noqa: E402


def _tavily_search_le(query: str, max_results: int = 30) -> List[Dict]:
    """Fallback: search via Tavily, returns results in the same {href, title, body} shape as DDGS."""
    logger_le = logging.getLogger(__name__)
    if not _TAVILY_LE_AVAILABLE:
        return []
    api_key = os.getenv("Tavily_API") or os.getenv("TAVILY_API_KEY") or os.getenv("TAVILY_API")
    if not api_key:
        logger_le.warning("Tavily API key not set. Skipping Tavily fallback.")
        return []
    try:
        client_t = _TavilyClientLE(api_key=api_key)
        response = client_t.search(query=query, max_results=max_results)
        results = []
        for r in response.get("results", []):
            results.append({
                "href": r.get("url", ""),
                "title": r.get("title", ""),
                "body": r.get("content", ""),
            })
        logger_le.info(f"Tavily returned {len(results)} results for '{query}'.")
        return results
    except Exception as e:
        logger_le.warning(f"Tavily fallback failed for '{query}': {e}")
        return []

logger = logging.getLogger(__name__)

_openai_client: Optional[OpenAI] = None

def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client


# Global requests Session (still used by fetch_project_urls URL discovery)
_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)

def _rich_useragent() -> str:
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

MIN_EXTRACTABLE_TEXT = 200


# ---------------------------------------------------------------------------
# Listing fingerprint for deduplication
# ---------------------------------------------------------------------------

def _listing_fingerprint(item: dict) -> str:
    """Creates a stable hash from (title, price, area) to detect duplicates."""
    title = str(item.get('title') or '').lower().strip()
    price = str(item.get('price') or '').lower().strip()
    area = str(item.get('area') or '').lower().strip()
    key = f"{title}|{price}|{area}"
    return hashlib.md5(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

def _build_llm_client(provider: str):
    # User requested to ALWAYS use bedrock for listing extraction to save OpenAI costs
    return OpenAI(
        base_url=os.getenv("BEDROCK_BASE_URL", "https://bedrock-mantle.ap-south-1.api.aws/v1"),
        api_key=os.getenv("BEDROCK_API_KEY"),
    ), os.getenv("LLM_MODEL")



def _validate_extracted_listings(listings: List[dict], requested_project: str, requested_category: str, provider: str) -> Tuple[List[dict], TokenUsage]:
    """
    Pass 2 Semantic Validation Layer.
    Uses the LLM to semantically verify that each extracted listing matches the requested category and project.
    """
    if not listings:
        from models import TokenUsage
        return [], TokenUsage()
        

    
    validation_prompt = f"""You are a strict Real Estate Semantic Validation AI.
Your ONLY job is to verify if each extracted property listing truly belongs to the requested category and the requested project.

REQUESTED PROJECT: "{requested_project}"
REQUESTED CATEGORY: "{requested_category}"

You MUST evaluate the semantics of each listing (title, project_name, price, area, area_type).
1. PROJECT MATCH: If the listing's project name is completely different from "{requested_project}" (e.g. it is a "Similar Property" or "Promoted Project"), you MUST reject it.
2. CATEGORY MATCH: If the listing is for a different category (e.g., Office when requested is Retail, or Apartment when requested is Land), you MUST reject it.
CRITICAL RULE: If the REQUESTED CATEGORY is Commercial, Office, or Retail, you MUST strictly reject ANY listing that mentions "BHK", "Bedroom", or "Flat". Commercial spaces are never BHKs.
If the listing is ambiguous but semantically plausible, you may accept it.
NEVER modify the listings. Just return a boolean 'is_valid' for each.

LISTINGS TO VALIDATE:
{json.dumps(listings, indent=2)}

OUTPUT FORMAT:
Return ONLY valid JSON mapping the listing index to its validity.
{{
  "validation": [
    {{"index": 0, "is_valid": true}},
    {{"index": 1, "is_valid": false}}
  ]
}}
"""
    try:
        llm_client, model_name = _build_llm_client(provider)
        response = llm_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a validation AI. Output ONLY JSON."},
                {"role": "user", "content": validation_prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        data = parse_llm_json(content)
        validation_results = data.get("validation", [])
        
        if not validation_results:
            # Validation LLM returned nothing useful — trust Pass 1 results
            logger.warning("Pass 2 validation returned empty results — trusting Pass 1 output.")
            return listings, extract_token_usage(response)

        valid_indices = {item["index"] for item in validation_results if item.get("is_valid")}
        filtered_listings = [listing for i, listing in enumerate(listings) if i in valid_indices]
        
        if not filtered_listings and listings:
            logger.warning(f"Pass 2 correctly rejected ALL {len(listings)} listing(s) due to category mismatch.")
        
        return filtered_listings, extract_token_usage(response)
    except Exception as e:
        logger.error(f"Semantic validation error: {e} — trusting Pass 1 output.")
        # If validation fails, fall back to Pass 1 results rather than silently dropping everything
        return listings, TokenUsage()


def extract_listings_from_text(
    page_text: str,
    project_name: str,
    location: str,
    portal_name: str,
    url: str,
    provider: str = "openai",
    property_type: str = "residential",
    max_listings: int = 10,
) -> Tuple[List[dict], TokenUsage]:
    """
    Calls the LLM to extract property listings from raw page text.
    Returns up to `max_listings` items with portal and url already injected.
    """
    from pipeline import parse_llm_json, extract_token_usage

    if not page_text or len(page_text) < MIN_EXTRACTABLE_TEXT:
        return [], TokenUsage()

    # ── Dynamic example generation ─────────────────────────────────────────
    # Build project-name match examples from the actual runtime project_name.
    # This avoids hardcoding any specific project names inside the prompt.
    pn_words = project_name.strip().split()
    # Variant 1: last 2 significant words (e.g. "Life Republic" from "Kolte Patil Life Republic")
    variant_short = " ".join(pn_words[-2:]) if len(pn_words) >= 2 else project_name
    # Variant 2: the very last word, because portals often drop the developer name (e.g. "Minerva" for "Lokhandwala Minerva")
    variant_shortest = pn_words[-1] if pn_words else project_name
    # Variant 3: project name embedded in a description phrase (as portals write it)
    variant_in    = f"in {project_name}"
    variant_by    = f"{project_name} by"
    variant_soc   = f"{project_name} society"

    # Title type example — driven entirely by the requested category
    cat = property_type.lower().strip()
    if cat in ("office", "commercial"):
        example_title    = "Commercial Office Space"
        example_area     = "850"
        example_area_type = "sq.ft. Carpet Area"
        example_price    = "1.25 Cr"
    elif cat == "retail":
        example_title    = "Retail Shop"
        example_area     = "620"
        example_area_type = "sq.ft. Carpet Area"
        example_price    = "85 Lacs"
    elif cat == "land":
        example_title    = "Residential Plot"
        example_area     = "2400"
        example_area_type = "sq.ft. Plot Area"
        example_price    = "45 Lacs"
    else:  # residential / default
        example_title    = f"Apartment in {project_name}"
        example_area     = "1142"
        example_area_type = "sq.ft. Carpet Area"
        example_price    = "1.25 Cr"

    # Separator hint — what portal search pages use to split listing blocks
    listing_separators = (
        '"Contact Agent", "Get Phone No", "Request Callback", '
        '"Enquire Now", "Photos", "Posted:", or a new unit-type heading'
    )

    prompt = f"""
    You are a highly accurate Real Estate Listing Extraction AI.

Extract ONLY valid property listings from the provided webpage text.

──────────────────────────────
INPUT
──────────────────────────────
PROJECT NAME: "{project_name}"
LOCATION: "{location}"
PROPERTY CATEGORY: "{property_type}"

WEBPAGE CONTENT:
{page_text[:12000]}

──────────────────────────────
EXTRACTION RULES
──────────────────────────────
1. Extract listings ONLY when ALL of the following match:
   - Project Name (exact match or highly similar)
   - Location (same location)
   - Requested Property Category

2. CRITICAL HALLUCINATION PREVENTION:
   - Extract the EXACT project name and location as written in the webpage text.
   - DO NOT blindly copy the requested PROJECT NAME. If the text says "Zen Business Center", the "project_name" field MUST be "Zen Business Center".

3. Ignore listings from Recommended, Similar, Nearby, Related, or any clearly different projects.
   WARNING: Real estate websites aggressively inject "Promoted" or "Similar Properties" from completely different cities at the bottom of the page (e.g., showing a Mumbai property on a Dubai page). You MUST verify the city/region of every single listing. If a listing belongs to a different city than the requested location, you MUST ignore it.
4. Preserve the ORIGINAL price exactly as shown on the webpage.
   - Do NOT convert currencies.
   - Keep the original currency symbol or code (₹, $, AED, €, £, SGD, etc.).
   - Extract only the main property price (ignore EMI, loan offers, savings, discounts, rent etc.).
   - in Price section, Only Price should be come along with the Currency

5. Currency must match the extracted price.
   Examples:
   - "₹ 2.5 Cr" → "₹"
   - "$450,000" → "$"
   - "AED 1.2M" → "AED"

6. Area must contain ONLY the numeric value with its unit exactly as shown.
   Examples:
   - "1,277 sqft"
   - "118 sq.m."
   - "240 sqm"
   - "150 sq yd"
   Do NOT include labels like Carpet Area or Built-up Area in this field.

7. Area Type should contain ONLY the area label if explicitly mentioned.
   Examples:
   - "Carpet Area"
   - "Built-up Area"
   - "Super Built-up Area"
   - "Saleable Area"
   Otherwise return an empty string.

8. If the requested property category is Office, Commercial, Retail or Shop, then only should come Office, Commercial, Retail or Shop, otherwise reject listing..

9. Webpages may have broken layouts or merged text. Pair the correct Price and Area by reading nearby lines before and after the current line.

10. If you are not reasonably confident that the project, location, and category refer to the requested property, skip the listing.

──────────────────────────────
OUTPUT
──────────────────────────────
Return ONLY valid JSON.

{{
  "listings": [
    {{
      "project_name": "...",
      "category": "...",
      "title": "...",
      "price": "...",
      "currency": "...",
      "area": "...",
      "area_type": "...",
      "location": "..."
    }}
  ]
}}

If no valid listing is found, return:

{{"listings":[]}}
"""


    try:
        llm_client, model_name = _build_llm_client(provider)
        response = llm_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a structured data extractor. Output ONLY valid JSON."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        data = parse_llm_json(content)
        extracted = data.get("listings", [])

        pass1_usage = extract_token_usage(response)
        logger.info(f"Pass 1 extracted {len(extracted)} listing(s) from {url}")
        
        # Pass 2: Semantic Validation
        validated_extracted, pass2_usage = _validate_extracted_listings(extracted, project_name, property_type, provider)
        
        if len(validated_extracted) < len(extracted):
            logger.info(f"Pass 2 kept {len(validated_extracted)}/{len(extracted)} listing(s) from {url}")
        
        # Combine token usage
        total_usage = TokenUsage()
        total_usage.input_tokens = pass1_usage.input_tokens + pass2_usage.input_tokens
        total_usage.output_tokens = pass1_usage.output_tokens + pass2_usage.output_tokens
        total_usage.total_tokens = pass1_usage.total_tokens + pass2_usage.total_tokens
        total_usage.call_count = pass1_usage.call_count + pass2_usage.call_count

        # Inject portal metadata
        for item in validated_extracted:
            item["portal"] = portal_name
            item["url"] = url

        logger.info(f"LLM extracted {len(validated_extracted)} valid listing(s) out of {len(extracted)} from {url}")
        return validated_extracted, total_usage
    except Exception as e:
        logger.error(f"LLM extraction error for {url} ({provider}): {e}")
        return [], TokenUsage()


import asyncio

async def _async_scrape_and_extract(
    url_idx: int,
    url_obj: dict,
    project_name: str,
    location: str,
    provider: str,
    property_type: str,
    target_count: int,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Wrapper to run blocking scraping and LLM extraction in a thread pool."""
    href = url_obj.get("url", "")
    portal = url_obj.get("portal", "Website")
    result = {
        "url_idx": url_idx,
        "url_obj": url_obj,
        "href": href,
        "portal": portal,
        "extracted": [],
        "usage": TokenUsage(),
        "status_messages": [],
        "error": None
    }

    if not href:
        return result

    async with semaphore:
        result["status_messages"].append({"type": "status", "msg": f"Scraping {portal}\u2026"})
        try:
            page_text = await asyncio.to_thread(scrape_listing_page, href)
        except Exception as exc:
            result["error"] = f"Scraping error on {portal}: {exc}"
            return result

        if not page_text or len(page_text) < MIN_EXTRACTABLE_TEXT:
            result["status_messages"].append({"type": "status", "msg": f"No readable content on {portal} \u2014 skipping"})
            return result

        # Save the text to a .txt file named after the portal for debugging/records
        # (Only saved when content is actually usable by the LLM)
        # Auto-cleanup: keep only the 5 most recent .txt files in the backend dir.
        _TXT_KEEP_MAX = 10

        def _save_file():
            import glob
            import re
            # Sanitize project name to be filename-safe
            safe_project = re.sub(r'[^a-zA-Z0-9_]', '', project_name.replace(' ', '_'))
            filename = f"{safe_project}_{portal}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(page_text)

            # Collect all .txt files in the same directory, sorted oldest-first (excluding requirements.txt)
            txt_files = sorted(
                [f for f in glob.glob("*.txt") if os.path.basename(f) != "requirements.txt"],
                key=lambda p: os.path.getmtime(p),
            )
            # Delete oldest files beyond the cap
            for old_file in txt_files[:-_TXT_KEEP_MAX]:
                try:
                    os.remove(old_file)
                    logger.info(f"Auto-deleted old debug file: {old_file}")
                except Exception as del_err:
                    logger.warning(f"Could not delete {old_file}: {del_err}")

        await asyncio.to_thread(_save_file)

        # Pre-filter: Valid HTML must contain real estate keywords
        page_text_lower = page_text.lower()
        property_keywords = [
            "bhk", "price", "sqft", "sq ft", "floor plan", "listing", "for sale", 
            "carpet area", "crore", "lakh", "commercial", "office", "retail", "shop", "plot", "land"
        ]
        
        if not any(kw in page_text_lower for kw in property_keywords):
            result["status_messages"].append({"type": "status", "msg": f"No property keywords found on {portal} \u2014 skipping"})
            return result

        result["status_messages"].append({"type": "status", "msg": f"Extracting listings from {portal} with LLM\u2026"})
        try:
            extracted, usage = await asyncio.to_thread(
                extract_listings_from_text,
                page_text=page_text,
                project_name=project_name,
                location=location,
                portal_name=portal,
                url=href,
                provider=provider,
                property_type=property_type,
                max_listings=target_count,
            )
            result["extracted"] = extracted
            result["usage"] = usage
        except Exception as exc:
            result["error"] = f"LLM error on {portal}: {exc}"
            
    return result


async def run_extract_listings(
    project_name: str,
    location: str,
    urls: List[dict],
    provider: str = "openai",
    property_type: str = "residential",
    target_count: int = 5,
) -> Tuple[List[dict], TokenUsage]:
    """
    Concurrent version of run_extract_listings.
    """
    valid_listings: List[dict] = []
    seen_fingerprints: set = set()
    total_usage = TokenUsage()
    
    semaphore = asyncio.Semaphore(2)
    tasks = [
        asyncio.create_task(
            _async_scrape_and_extract(
                url_idx, url_obj, project_name, location, provider, property_type, target_count, semaphore
            )
        )
        for url_idx, url_obj in enumerate(urls)
    ]

    for task in asyncio.as_completed(tasks):
        if len(valid_listings) >= target_count:
            break
            
        result = await task
        
        if result["error"]:
            logger.error(result["error"])
            continue

        usage = result["usage"]
        if usage:
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            total_usage.total_tokens += usage.total_tokens
            total_usage.call_count += usage.call_count

        for item in result["extracted"]:
            title_val = item.get("title") or item.get("Unit") or ""
            if title_val:
                item["title"] = title_val

            if not (item.get("title") and item.get("price")):
                continue

            fp = _listing_fingerprint(item)
            if fp in seen_fingerprints:
                continue

            seen_fingerprints.add(fp)
            valid_listings.append(item)
            logger.info(f"  ✓ [{result['portal']}] {item.get('title')} — {item.get('price')}")

            if len(valid_listings) >= target_count:
                break
                
    for t in tasks:
        if not t.done():
            t.cancel()

    return valid_listings[:target_count], total_usage


# ---------------------------------------------------------------------------
# Streaming API: stream_extract_listings  (Server-Sent Events generator)
# ---------------------------------------------------------------------------

import json as _json

def _sse(event: str, data: dict) -> str:
    """Formats a single Server-Sent Event frame."""
    return f"event: {event}\ndata: {_json.dumps(data)}\n\n"

async def stream_extract_listings(
    project_name: str,
    location: str,
    urls: List[dict],
    provider: str = "openai",
    property_type: str = "residential",
    target_count: int = 5,
):
    """
    Async Generator that yields SSE-formatted strings in real time.
    Processes URLs concurrently with a concurrency limit.
    """
    valid_listings: List[dict] = []
    seen_fingerprints: set = set()
    total_usage = TokenUsage()
    total_urls = len(urls)

    semaphore = asyncio.Semaphore(2)
    tasks = [
        asyncio.create_task(
            _async_scrape_and_extract(
                url_idx, url_obj, project_name, location, provider, property_type, target_count, semaphore
            )
        )
        for url_idx, url_obj in enumerate(urls)
    ]

    for completed_task in asyncio.as_completed(tasks):
        if len(valid_listings) >= target_count:
            break

        result = await completed_task
        
        # Emit all queued status messages for this URL
        for msg_obj in result["status_messages"]:
            yield _sse(msg_obj["type"], {
                "message": msg_obj["msg"],
                "portal": result["portal"],
                "url": result["href"],
                "url_index": result["url_idx"] + 1,
                "total_urls": total_urls,
                "found_so_far": len(valid_listings),
                "target": target_count,
            })

        if result["error"]:
            yield _sse("error", {"message": result["error"]})
            continue

        usage = result["usage"]
        if usage and usage.call_count > 0:
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            total_usage.total_tokens += usage.total_tokens
            total_usage.call_count += usage.call_count
            yield _sse("tokens", {
                "input_tokens": total_usage.input_tokens,
                "output_tokens": total_usage.output_tokens,
                "total_tokens": total_usage.total_tokens,
                "call_count": total_usage.call_count,
            })

        for item in result["extracted"]:
            title_val = item.get("title") or item.get("Unit") or ""
            if title_val:
                item["title"] = title_val
            if not (item.get("title") and item.get("price")):
                continue
                
            # Process area_type for the new column
            area_val = str(item.get("area", "")).strip()
            area_type = str(item.get("area_type", "")).strip()
            type_lower = area_type.lower()
            
            ignore_types = ["sqft", "sq ft", "sq.ft", "sq.ft.", "sqm", "sq.m", "sq meters", "square feet", "square meters", "sq. yards", "sq yards"]
            
            if not area_type:
                item["area_type"] = "NA"
            elif type_lower in ignore_types:
                # It's just a unit (e.g. "sq ft"). Append it to area if it's missing.
                if type_lower not in area_val.lower():
                    item["area"] = f"{area_val} {area_type}".strip()
                item["area_type"] = "NA"
            else:
                item["area_type"] = area_type

            fp = _listing_fingerprint(item)
            if fp in seen_fingerprints:
                continue
            seen_fingerprints.add(fp)
            valid_listings.append(item)

            yield _sse("listing", {
                "listing": item,
                "found_so_far": len(valid_listings),
                "target": target_count,
            })

            if len(valid_listings) >= target_count:
                break
                
    # Cancel remaining tasks if we exited early
    for t in tasks:
        if not t.done():
            t.cancel()

    yield _sse("done", {
        "total_found": len(valid_listings),
        "message": (
            f"Found {len(valid_listings)} listing(s) for '{project_name}'."
            if valid_listings
            else f"No listings found for '{project_name}' across {total_urls} portal(s)."
        ),
        "token_usage": {
            "input_tokens": total_usage.input_tokens,
            "output_tokens": total_usage.output_tokens,
            "total_tokens": total_usage.total_tokens,
            "call_count": total_usage.call_count,
        },
    })


# ---------------------------------------------------------------------------
# URL discovery: fetch_project_urls
# ---------------------------------------------------------------------------

def _extract_portal_name(url: str) -> str:
    try:
        domain = urlparse(url).netloc.lower().replace("www.", "")
        if "99acres" in domain: return "99acres"
        if "magicbricks" in domain: return "MagicBricks"
        if "housing.com" in domain: return "Housing.com"
        if "nobroker" in domain: return "NoBroker"
        if "squareyards" in domain: return "Square Yards"
        if "makaan" in domain: return "Makaan"
        if "proptiger" in domain: return "PropTiger"
        if "commonfloor" in domain: return "CommonFloor"
        if "propertywala" in domain: return "PropertyWala"
        if "nestoria" in domain: return "Nestoria"
        if "homes247" in domain: return "Homes247"
        if "olx" in domain: return "OLX"
        if "starestate" in domain: return "StarEstate"
        if "realestateindia" in domain: return "RealEstateIndia"
        return domain
    except Exception:
        return "Website"


_BLOCKED_DOMAINS = {
    "google", "youtube", "facebook", "instagram", "twitter",
    "wikipedia", "justdial", "linkedin", "reddit", "quora",
    "indiamart", "sulekha", "urbanclap", "amazon",
}
import random
import time
from typing import List, Dict, Tuple, Set
from ddgs import DDGS
# Assume TokenUsage and logger are defined elsewhere

# Universal junk patterns (short, cross‑regional)
UNIVERSAL_JUNK = {"news", "blog", "video", "youtube", "facebook", "twitter", 
                  "instagram", "linkedin", "wikipedia", "forum", "pdf", "map"}

# Category → search term synonyms (generic, can be extended)
CATEGORY_TERMS = {
    "residential": ["apartments", "flats", "villas", "residential", "housing"],
    "office": ["office", "commercial office", "office complex", "business space", "workspace"],
    "retail": ["retail", "shop", "showroom", "commercial space"],
    "land": ["plot", "land", "residential plot", "commercial plot"],
}

# Positive keywords that indicate a listing page (universal)
LISTING_INDICATORS = {"sale", "rent", "listing", "available", "property", "real estate", "for sale", "to rent"}

def _is_project_relevant(project_name: str, location: str, title: str, snippet: str, url: str) -> bool:
    """
    Returns True if the result is about the given project and (optionally) location.
    This is the core relevance filter – no domain assumptions.
    """
    # Normalise
    project_lower = project_name.lower()
    location_lower = location.lower() if location else ""
    title_lower = title.lower()
    snippet_lower = snippet.lower()
    url_lower = url.lower()
    combined = f"{title_lower} {snippet_lower} {url_lower}"

    # Must contain the project name (or its significant parts)
    # Split project name into words and require at least 50% match if multi‑word
    project_parts = project_lower.split()
    if len(project_parts) == 1:
        # For single‑word projects, ensure it appears at least twice to reduce false positives
        if combined.count(project_parts[0]) < 2:
            return False
    else:
        matched = sum(1 for part in project_parts if part in combined)
        if matched < len(project_parts) * 0.5:  # at least half the words match
            return False

    # Optionally require location (if provided) – improves precision
    if location_lower:
        # Check if location appears as a whole or as separate words
        location_words = location_lower.split()
        if not any(loc in combined for loc in location_words):
            # If location is "New York", we accept if "new" and "york" appear
            if len(location_words) > 1:
                if not all(w in combined for w in location_words):
                    return False
            else:
                return False

    # Check for at least one positive listing indicator
    if not any(ind in combined for ind in LISTING_INDICATORS):
        return False

    # Exclude universal junk
    if any(junk in url_lower or junk in title_lower for junk in UNIVERSAL_JUNK):
        return False

    return True



def fetch_project_urls(
    project_name: str,
    location: str,
    category: str = "property",
    max_urls: int = 15,
) -> Tuple[List[Dict], TokenUsage]:
    """
    Discover relevant project listing URLs using DuckDuckGo.

    ------------------------------------------------------------------------
    USAGE / CUSTOMIZATION
    ------------------------------------------------------------------------
    This function intentionally preserves the existing public interface.

    Optional internal guardrails (safe to customize):

    - MAX_RETRIES
        Number of DDGS retries per query.

    - SEARCH_DELAY_RANGE
        Delay before each DDGS request.

    - QUERY_DELAY_RANGE
        Delay between search queries.

    - CUSTOM_DDGS_CLIENT
        Replace with a mock or injected DDGS client for testing.

        Example:
            CUSTOM_DDGS_CLIENT = MyMockDDGS()

    ------------------------------------------------------------------------
    Assumptions preserved:

    • Returns <= max_urls unique URLs.
    • Uses CATEGORY_TERMS lookup.
    • Uses _is_project_relevant() exactly as before.
    • Portal name is derived from URL domain.
    • No portal-specific filtering.
    • No hardcoded website logic.
    ------------------------------------------------------------------------
    """

    # ------------------------------------------------------------------
    # Optional Guardrails
    # ------------------------------------------------------------------

    MAX_RETRIES = 3

    SEARCH_DELAY_RANGE = (0.5, 1.0)

    QUERY_DELAY_RANGE = (1.0, 2.0)

    CUSTOM_DDGS_CLIENT = None  # Optional injection for testing

    # ------------------------------------------------------------------
    # Input Validation
    # ------------------------------------------------------------------

    if not isinstance(project_name, str) or not project_name.strip():
        logger.warning("fetch_project_urls(): empty project name")
        return [], TokenUsage()

    if not isinstance(location, str):
        logger.warning("fetch_project_urls(): invalid location")
        return [], TokenUsage()

    try:
        max_urls = max(1, int(max_urls))
    except Exception:
        logger.warning("Invalid max_urls supplied. Falling back to 15.")
        max_urls = 15

    project_name = project_name.strip()
    location = location.strip()
    category = (category or "property").strip().lower()

    logger.info(
        "Searching URLs | Project='%s' | Location='%s' | Category='%s'",
        project_name,
        location,
        category,
    )

    # ------------------------------------------------------------------
    # Category Terms
    # ------------------------------------------------------------------

    terms: List[str] = CATEGORY_TERMS.get(
        category,
        CATEGORY_TERMS.get("property", ["property", "real estate", "listings", "for sale"]),
    )

    # ------------------------------------------------------------------
    # Query Construction
    # ------------------------------------------------------------------

    def build_queries() -> List[str]:
        """
        Build a single search query.
        """

        return [
            f'"{project_name}" {location} {terms[0]} real estate property sales listings'
        ]

    queries = build_queries()

    # ------------------------------------------------------------------
    # DDGS Search
    # ------------------------------------------------------------------

    def execute_query(query: str) -> List[Dict]:
        """
        Execute one DDGS query with adaptive retry logic.

        Handles:
        - 429 Too Many Requests
        - ConnectTimeout
        - Connection Refused
        - 5xx Server Errors
        - Temporary DDGS failures
        """

        ddgs_client = CUSTOM_DDGS_CLIENT or DDGS()

        MAX_BACKOFF = 90

        for attempt in range(MAX_RETRIES):

            try:

                time.sleep(
                    random.uniform(*SEARCH_DELAY_RANGE)
                )

                logger.info(
                    f"[Search {attempt+1}/{MAX_RETRIES}] {query}"
                )

                results = list(
                    ddgs_client.text(
                        query,
                        max_results=30,
                    )
                )

                if results:

                    logger.info(
                        f"Found {len(results)} results."
                    )

                    return results

                logger.warning(
                    "No search results returned."
                )

            except Exception as exc:

                error = str(exc).lower()

                # -----------------------------
                # 429 Too Many Requests
                # -----------------------------
                if "429" in error:

                    wait = min(
                        20 * (attempt + 1),
                        MAX_BACKOFF,
                    )

                    logger.warning(
                        f"429 detected. Waiting {wait}s..."
                    )

                    time.sleep(wait)

                    continue

                # -----------------------------
                # Connection Timeout
                # -----------------------------
                if "timeout" in error:

                    wait = min(
                        5 * (attempt + 1),
                        MAX_BACKOFF,
                    )

                    logger.warning(
                        f"Timeout. Waiting {wait}s..."
                    )

                    time.sleep(wait)

                    continue

                # -----------------------------
                # Connection Refused
                # -----------------------------
                if "10061" in error:

                    wait = min(
                        8 * (attempt + 1),
                        MAX_BACKOFF,
                    )

                    logger.warning(
                        f"Connection refused. Waiting {wait}s..."
                    )

                    time.sleep(wait)

                    continue

                # -----------------------------
                # 502 / 503 / 504
                # -----------------------------
                if any(
                    code in error
                    for code in (
                        "502",
                        "503",
                        "504",
                    )
                ):

                    wait = min(
                        10 * (attempt + 1),
                        MAX_BACKOFF,
                    )

                    logger.warning(
                        f"Server unavailable. Waiting {wait}s..."
                    )

                    time.sleep(wait)

                    continue

                # -----------------------------
                # Unknown error
                # -----------------------------
                wait = min(
                    (2 ** attempt) + random.uniform(2, 5),
                    MAX_BACKOFF,
                )

                logger.warning(
                    f"Unexpected search error: {exc}"
                )

                logger.warning(
                    f"Retrying in {wait:.1f}s"
                )

                time.sleep(wait)

        logger.error(
            f"Search failed after {MAX_RETRIES} attempts: {query}"
        )

        # --- Fallback: Tavily ---
        logger.info(f"Attempting Tavily fallback for query: {query}")
        tavily_results = _tavily_search_le(query)
        if tavily_results:
            logger.info(f"Tavily returned {len(tavily_results)} results for '{query}'.")
            return tavily_results
        else:
            logger.warning(f"Tavily also returned no results for '{query}'.")

        return []

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    seen_urls: Set[str] = set()

    portal_listings: List[Dict] = []

    # ------------------------------------------------------------------
    # Search Loop
    # ------------------------------------------------------------------

    for query in queries:

        if len(portal_listings) >= max_urls:
            break

        logger.info("Executing query: %s", query)

        results = execute_query(query)

        if not results:
            continue

        for result in results:

            if len(portal_listings) >= max_urls:
                break

            href: str = result.get("href", "").strip()

            if not href:
                continue

            if href in seen_urls:
                continue

            title: str = result.get("title", "")
            snippet: str = result.get("body", "")

            try:

                if not _is_project_relevant(
                    project_name,
                    location,
                    title,
                    snippet,
                    href,
                ):
                    continue

            except Exception as exc:

                logger.exception(
                    "Relevance filter failed for '%s': %s",
                    href,
                    exc,
                )

                continue

            try:

                parsed = urlparse(href)

                domain = parsed.netloc.replace("www.", "")

                portal = (
                    domain.split(".")[0]
                    if domain
                    else "unknown"
                )

            except Exception:

                portal = "unknown"

            seen_urls.add(href)

            portal_listings.append(
                {
                    "portal": portal,
                    "url": href,
                }
            )

            logger.debug(
                "Accepted URL (%d/%d): %s",
                len(portal_listings),
                max_urls,
                href,
            )

        time.sleep(
            random.uniform(*QUERY_DELAY_RANGE)
        )

    logger.info(
        "Completed URL discovery | Project='%s' | URLs=%d",
        project_name,
        len(portal_listings),
    )

    return portal_listings, TokenUsage()