import os
import time
import logging
from typing import Tuple, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from openai import OpenAI
from ddgs import DDGS
import requests
from bs4 import BeautifulSoup
from models import TokenUsage

logger = logging.getLogger(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def scrape_listing_page(url: str) -> str:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for script in soup(["script", "style", "nav", "footer", "aside", "header", "noscript"]):
                script.extract()
            text = soup.get_text(separator=' ', strip=True)
            return text[:4000]
        return ""
    except Exception as e:
        logger.warning(f"Scrape failed for {url}: {e}")
        return ""

def extract_multiple_listings_from_url(url: str, project_name: str, location: str, portal_name: str, provider: str = "openai") -> Tuple[List[dict], TokenUsage]:
    from pipeline import parse_llm_json, extract_token_usage
    
    page_text = scrape_listing_page(url)
    if not page_text or len(page_text) < 50:
        return [], TokenUsage()
        
    prompt = f"""
    Extract property listing details from the following webpage text for the project '{project_name}' in '{location}'.
    There might be MULTIPLE listings on this single page. Extract up to 5 valid listings for this project.
    
    CRITICAL RULES:
    1. ONLY extract properties that are EXPLICITLY part of the project '{project_name}'.
    2. DO NOT extract "Similar Properties", "Nearby Properties", or properties that are simply "near {project_name}".
    3. If a listing belongs to a DIFFERENT project name (e.g., extracting 'Regent Plaza Mall' when looking for 'Magnolia Business Center'), you MUST IGNORE IT completely.
    4. If no listings strictly match the project '{project_name}', return an empty array [].
    
    Return ONLY a JSON object with the following schema:
    {{
      "listings": [
        {{
          "project_name": "String (e.g., EXACTLY '{project_name}')",
          "title": "String (e.g., '2 BHK Apartment' or 'Shop', this represents the Unit type)",
          "price": "String (e.g., '92 L' or '1.5 Cr', do not include currency symbol)",
          "currency": "String (e.g., '₹' or 'INR')",
          "area": "String (e.g., '1040 sqft')",
          "area_type": "String (e.g., 'Carpet area' or 'Built-up area')",
          "location": "String (e.g., '{location}')"
        }}
      ]
    }}
    If you cannot find a specific field, leave it as an empty string "".
    
    Webpage Text:
    {page_text[:5000]}
    """
    
    try:
        if provider == "groq":
            llm_client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.getenv("Groq_API_Key"))
            model_name = "llama-3.3-70b-versatile"
        else:
            llm_client = client
            model_name = "gpt-4o-mini"
            
        response = llm_client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "You are a fast structured data extractor. Output ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        data = parse_llm_json(content)
        
        extracted = data.get("listings", [])
        for item in extracted:
            item['portal'] = portal_name
            item['url'] = url
            
        return extracted, extract_token_usage(response)
    except Exception as e:
        logger.error(f"Error extracting listing details from {url} using {provider}: {e}")
        return [], TokenUsage()

def run_extract_listings(project_name: str, location: str, urls: List[dict], provider: str = "openai") -> Tuple[List[dict], TokenUsage]:
    valid_listings = []
    total_usage = TokenUsage()
    
    # Process sequentially instead of spamming 150 LLM calls!
    for url_obj in urls:
        href = url_obj.get("url")
        portal = url_obj.get("portal", "Website")
        if not href:
            continue
            
        logger.info(f"Extracting listings from {href} for {project_name} using {provider}")
        extracted, usage = extract_multiple_listings_from_url(href, project_name, location, portal, provider)
        
        if usage:
            total_usage.input_tokens += usage.input_tokens
            total_usage.output_tokens += usage.output_tokens
            total_usage.total_tokens += usage.total_tokens
            total_usage.call_count += usage.call_count
            
        if extracted:
            for item in extracted:
                # Handle the case where the LLM might have used 'Unit' instead of 'title' due to previous prompt cache
                title_val = item.get('title') or item.get('Unit')
                if title_val:
                    item['title'] = title_val
                    
                if item.get('title') and item.get('price'):
                    valid_listings.append(item)
                    
        # Stop completely if we found 5 listings (even if it was all from the very first URL!)
        if len(valid_listings) >= 5:
            valid_listings = valid_listings[:5]
            break
            
    return valid_listings, total_usage

def fetch_project_urls(project_name: str, location: str, category: str = "property") -> Tuple[List[dict], TokenUsage]:
    if not project_name:
        return [], TokenUsage()
    logger.info(f"Fetching URLs for {project_name} in {location} ({category})")
    try:
        query = f"{project_name}, {location} {category} for sale listing"
        
        results = []
        for attempt in range(3):
            try:
                results = list(DDGS().text(query, max_results=10)) # limit to 10 results!
                if results:
                    break
            except Exception as e:
                logger.warning(f"DDGS attempt {attempt+1} failed for {project_name}: {e}")
                time.sleep(1 + attempt)
                
        if not results:
            logger.warning(f"No DDGS results found for {project_name}")
            return []
            
        portal_listings = []
        
        from urllib.parse import urlparse
        def extract_portal_name(url: str) -> str:
            try:
                domain = urlparse(url).netloc.lower()
                domain = domain.replace('www.', '')
                if '99acres' in domain: return '99acres'
                if 'magicbricks' in domain: return 'MagicBricks'
                if 'housing.com' in domain: return 'Housing.com'
                if 'nobroker' in domain: return 'NoBroker'
                if 'squareyards' in domain: return 'Square Yards'
                if 'makaan' in domain: return 'Makaan'
                if 'proptiger' in domain: return 'PropTiger'
                if 'commonfloor' in domain: return 'CommonFloor'
                if 'propertywala' in domain: return 'PropertyWala'
                return domain
            except:
                return "Website"
        
        for r in results:
            href = r.get('href')
            if href:
                portal = extract_portal_name(href)
                if not any(x in portal for x in ['google', 'youtube', 'facebook', 'instagram', 'twitter', 'wikipedia', 'justdial', 'linkedin']):
                    portal_listings.append({"portal": portal, "url": href})
                    if len(portal_listings) >= 10: # Only return top 10 URLs
                        break
                        
        return portal_listings, TokenUsage()
    except Exception as e:
        logger.error(f"Error fetching URLs for {project_name}: {e}")
        return [], TokenUsage()
