import json
import os
import logging
import requests
import random
from datetime import datetime
from bs4 import BeautifulSoup
from openai import OpenAI
from ddgs import DDGS
from typing import Tuple, List
import trafilatura
from concurrent.futures import ThreadPoolExecutor, as_completed
from models import PipelineResult, LocationIdentification, PropertyCategories, PropertyListing, TokenUsage, PortalListing
from prompt import STAGE1_PROMPT, STAGE2_PROMPT, STAGE3_PROMPT, STAGE4_PROMPT
import time
from utils import parse_llm_json, extract_token_usage  # shared utils — avoids circular import
from tavily import TavilyClient as _TavilyClient

try:
    _TAVILY_AVAILABLE = True
except ImportError:
    _TAVILY_AVAILABLE = False


def _tavily_search(query: str, max_results: int = 15) -> List[dict]:
    """Fallback search via Tavily. Returns results in the same {href, title, body} shape as DDGS."""
    if not _TAVILY_AVAILABLE:
        return []
    api_key = os.getenv("Tavily_API") or os.getenv("TAVILY_API_KEY") or os.getenv("TAVILY_API")
    if not api_key:
        return []
    try:
        client_t = _TavilyClient(api_key=api_key)
        response = client_t.search(query=query, max_results=max_results)
        results = []
        for r in response.get("results", []):
            results.append({
                "href": r.get("url", ""),
                "title": r.get("title", ""),
                "body": r.get("content", ""),
            })
        return results
    except Exception as e:
        logging.getLogger(__name__).warning(f"Tavily fallback failed: {e}")
        return []

def _bedrock_client():
    """Returns an OpenAI-compatible client pointed at the Bedrock Mantle endpoint."""
    return OpenAI(
        base_url=os.getenv("BEDROCK_BASE_URL", "https://bedrock-mantle.ap-south-1.api.aws/v1"),
        api_key=os.getenv("BEDROCK_API_KEY"),
        max_retries=0,
        timeout=30.0
    )

_BEDROCK_MODEL = os.getenv("LLM_MODEL")

# Set up logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("backend.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Ensure you have your API keys loaded via dotenv in main.py
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



def scrape_page(url: str) -> str:
    """Safely fetch and extract text from a webpage using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            result = trafilatura.extract(
                                         downloaded, 
                                         include_tables=True, 
                                         include_links=False
                                         )
            if result:
                return result[:8000] # Cap to 8000 chars per page to avoid overloading
        
        # Fallback to BeautifulSoup if trafilatura fails
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for script in soup(["script", "style", "nav", "footer", "aside"]):
                script.extract()
            text = soup.get_text(separator=' ', strip=True)
            return text[:8000]
        else:
            logger.warning(f"requests got status {resp.status_code} for {url}. Skipping.")
            return ""
    except Exception as e:
        logger.warning(f"Scrape failed for {url}: {e}")
        return ""

from services.google_places_service import reverse_geocode_google, fetch_nearby_projects_google, fetch_nearby_landmarks_google

def get_search_context(location: str, target_category: str, latitude: str = "", longitude: str = "") -> str:
    """Uses Google Places API for reverse geocoding & 2km/4km nearby projects, plus DuckDuckGo/Tavily for portal deep scraping."""
    logger.info(f"Starting expanded search for location: {location}, category: {target_category}, coords: ({latitude}, {longitude})")
    
    google_context = ""
    if latitude and longitude:
        try:
            lat_f = float(latitude)
            lng_f = float(longitude)

            # 1. Reverse Geocode via Google Places
            geo_info = reverse_geocode_google(lat_f, lng_f)
            if geo_info.get("formatted_address"):
                google_context += f"VERIFIED GOOGLE REVERSE GEOLOCATION:\n"
                google_context += f"- Formatted Address: {geo_info.get('formatted_address')}\n"
                google_context += f"- Micromarket / Sublocality: {geo_info.get('sublocality') or geo_info.get('locality')}\n"
                google_context += f"- City: {geo_info.get('city')}, State: {geo_info.get('state')}, Country: {geo_info.get('country')}\n\n"

            # 2. Strict 2 km / 4 km Nearby Projects via Google Places
            nearby_info = fetch_nearby_projects_google(lat_f, lng_f, min_count=5)
            if nearby_info.get("projects"):
                google_context += f"VERIFIED REAL ESTATE PROJECTS NEARBY (Radius: {nearby_info['radius_used_km']} km):\n"
                for p in nearby_info["projects"]:
                    google_context += f"• Project: {p['project_name']} | Distance: {p['distance_str']} | Vicinity: {p['vicinity']}\n"
                google_context += "\n"
        except Exception as g_err:
            logger.warning(f"Google Places Context extraction failed: {g_err}")

    try:
        if target_category == "residential":
            queries = [f"1 BHK 2 BHK 3 BHK flats apartment for sale in {location} price"]
        elif target_category == "office":
            queries = [f"commercial office space properties for sale in {location} price"]
        elif target_category == "retail":
            queries = [f"commercial shops retail showrooms for sale in {location} price"]
        elif target_category == "land":
            queries = [f"residential plots land for sale in {location} price"]
        else:
            queries = [f"properties for sale in {location} price"]
        
        web_context = ""
        for query in queries:
            results = []
            try:
                results = list(DDGS().text(query, backend="google,duckduckgo,yandex"))
            except Exception as ddg_err:
                logger.warning(f"DDG failed for query '{query}': {ddg_err}. Falling back to Tavily.")

            if not results:
                logger.info(f"DDG returned no results for '{query}'. Trying Tavily...")
                results = _tavily_search(query)
                if results:
                    logger.info(f"Tavily returned {len(results)} results for '{query}'.")

            for i, r in enumerate(results):
                url = r.get('href', '')
                snippet = r.get('body', '')
                
                page_text = ""
                if i < 2 and url:
                    page_text = scrape_page(url)
                
                content_block = f"Source: {r.get('title')}\nURL: {url}\nSnippet: {snippet}\n"
                if page_text:
                    content_block += f"Page Content Extract:\n{page_text}\n"
                content_block += "\n"
                
                if url not in web_context:
                    web_context += content_block
                    
        full_context = google_context + web_context
        logger.info(f"Successfully retrieved context for {location} (length: {len(full_context)})")
        return full_context
    except Exception as e:
        logger.error(f"Search error: {e}")
        return google_context or "No search data available."


# parse_llm_json and extract_token_usage are imported from utils.py (see top of file)

def build_pipeline_result(location: str, parsed_data: dict) -> PipelineResult:
    loc_id_data = parsed_data.get("location_identification", {})
    categories_data = parsed_data.get("property_categories", {})
    
    loc_id = LocationIdentification(**loc_id_data)
    
    def parse_listings(cat_key: str):
        raw_list = categories_data.get(cat_key, [])
        if not isinstance(raw_list, list):
            return []
        return [PropertyListing(**item) for item in raw_list if isinstance(item, dict)]
        
    cats = PropertyCategories(
        residential=parse_listings("residential"),
        office=parse_listings("office"),
        retail=parse_listings("retail"),
        land=parse_listings("land")
    )
    
    return PipelineResult(location=location, location_identification=loc_id, property_categories=cats)

import concurrent.futures

def populate_project_urls(pipeline_result: PipelineResult, total_token_usage: TokenUsage = None) -> PipelineResult:
    projects_with_category = []
    for p in pipeline_result.property_categories.residential:
        projects_with_category.append((p, "residential flat apartment"))
    for p in pipeline_result.property_categories.office:
        projects_with_category.append((p, "commercial office space"))
    for p in pipeline_result.property_categories.retail:
        projects_with_category.append((p, "commercial retail shop showroom"))
    for p in pipeline_result.property_categories.land:
        projects_with_category.append((p, "residential plot land"))
    
    def process_project(p, category):
        if not p.project_name:
            return None
        try:
            import time
            from listing_extractor import fetch_project_urls  # lazy import — avoids circular import at module level
            time.sleep(random.uniform(0.5, 2.5)) # Jitter to prevent 429 Too Many Requests from DDGS
            urls, usage = fetch_project_urls(p.project_name, pipeline_result.location, category, max_urls=15)
            p.portal_listings = [PortalListing(**item) for item in urls if isinstance(item, dict)]
            return usage
        except Exception as exc:
            logger.error(f"{p.project_name} generated an exception: {exc}")
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_project, p, cat): (p, cat) for p, cat in projects_with_category}
        for future in concurrent.futures.as_completed(futures):
            usage = future.result()
            if usage and total_token_usage:
                total_token_usage.input_tokens += usage.input_tokens
                total_token_usage.output_tokens += usage.output_tokens
                total_token_usage.total_tokens += usage.total_tokens
                total_token_usage.call_count += usage.call_count
                
    return pipeline_result

def run_openai_analysis_single_category(latitude: str, longitude: str, location: str, category: str) -> Tuple[dict, TokenUsage]:
    logger.info(f"Starting OpenAI analysis for category: {category}")
    context = get_search_context(location, category, latitude=latitude, longitude=longitude)
    formatted_prompt = STAGE1_PROMPT.format(latitude=latitude, longitude=longitude, location=location, target_category=category)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a Real Estate Extraction AI. Output ONLY JSON. Do not include markdown blocks."},
                {"role": "user", "content": formatted_prompt + "\n\nSearch Context:\n" + context}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        parsed_data = parse_llm_json(content)
        return parsed_data, extract_token_usage(response)
    except Exception as e:
        logger.error(f"OpenAI error for {category}: {e}")
        return {}, TokenUsage()

def run_openai_analysis(latitude: str, longitude: str, location: str) -> Tuple[PipelineResult, TokenUsage]:
    logger.info("Starting OpenAI analysis pipeline (Concurrent)")
    categories = ["residential", "office", "retail", "land"]
    
    all_parsed_data = {}
    total_token_usage = TokenUsage()
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_category = {
            executor.submit(run_openai_analysis_single_category, latitude, longitude, location, cat): cat
            for cat in categories
        }
        
        for future in as_completed(future_to_category):
            cat = future_to_category[future]
            try:
                parsed_data, usage = future.result()
                
                # Merge location_identification from the first successful response
                if not all_parsed_data.get("location_identification") and parsed_data.get("location_identification"):
                    all_parsed_data["location_identification"] = parsed_data.get("location_identification")
                
                # Merge property_categories
                if "property_categories" not in all_parsed_data:
                    all_parsed_data["property_categories"] = {}
                
                if parsed_data.get("property_categories", {}).get(cat):
                    all_parsed_data["property_categories"][cat] = parsed_data["property_categories"][cat]
                else:
                    if cat not in all_parsed_data["property_categories"]:
                        all_parsed_data["property_categories"][cat] = []
                        
                total_token_usage.input_tokens += usage.input_tokens
                total_token_usage.output_tokens += usage.output_tokens
                total_token_usage.total_tokens += usage.total_tokens
                total_token_usage.call_count += usage.call_count
                
            except Exception as exc:
                logger.error(f"Category {cat} generated an exception: {exc}")
    
    result = build_pipeline_result(location, all_parsed_data)
    result = populate_project_urls(result, total_token_usage)
    
    logger.info("Successfully parsed concurrent OpenAI response and fetched URLs")
    return result, total_token_usage

# def run_bedrock_analysis(latitude: str, longitude: str, location: str) -> PipelineResult:
#     logger.info("Starting Bedrock analysis pipeline")
#     context = get_search_context(location)
#     
#     formatted_prompt = PROMPT_TEMPLATE.format(latitude=latitude, longitude=longitude, location=location)
#     
#     try:
#         model_id = os.getenv("LLM_MODEL", "mistral.ministral-3-14b-instruct")
#         logger.info(f"Initializing Bedrock client with model: {model_id}")
#         
#         bedrock = boto3.client(
#             service_name='bedrock-runtime', 
#             region_name=os.getenv("AWS_DEFAULT_REGION", "ap-south-1")
#         )
#         
#         logger.info("Calling Bedrock converse API")
#         response = bedrock.converse(
#             modelId=model_id,
#             messages=[{
#                 "role": "user",
#                 "content": [{"text": formatted_prompt + "\n\nSearch Context:\n" + context}]
#             }],
#             inferenceConfig={
#                 "maxTokens": 2048,
#                 "temperature": 0.1
#             }
#         )
#         
#         content = response['output']['message']['content'][0]['text']
#         logger.info("Successfully received response from Bedrock")
#         
#         parsed_data = parse_llm_json(content)
#         result = build_pipeline_result(location, parsed_data)
#         
#         logger.info("Successfully parsed Bedrock response")
#         return result
#     except Exception as e:
#         logger.error(f"Bedrock error: {e}")
#         return PipelineResult(location=location, location_identification=LocationIdentification(), property_categories=PropertyCategories(), error_message=f"Error fetching from Bedrock: {e}")

def run_bedrock_analysis_single_category(latitude: str, longitude: str, location: str, category: str) -> Tuple[dict, TokenUsage]:
    logger.info(f"Starting Bedrock analysis for category: {category}")
    context = get_search_context(location, category, latitude=latitude, longitude=longitude)
    formatted_prompt = STAGE1_PROMPT.format(latitude=latitude, longitude=longitude, location=location, target_category=category)
    
    try:
        bedrock_client = _bedrock_client()
        
        logger.info(f"Calling Bedrock model: {_BEDROCK_MODEL}")
        response = bedrock_client.chat.completions.create(
            model=_BEDROCK_MODEL,
            messages=[
                {"role": "system", "content": "You are a Real Estate Extraction AI. Output ONLY valid JSON."},
                {"role": "user", "content": formatted_prompt + "\n\nSearch Context:\n" + context}
            ],
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        parsed_data = parse_llm_json(content)
        return parsed_data, extract_token_usage(response)
    except Exception as e:
        logger.error(f"Bedrock error for {category}: {e}")
        return {}, TokenUsage()

def run_bedrock_analysis(latitude: str, longitude: str, location: str) -> Tuple[PipelineResult, TokenUsage]:
    logger.info("Starting Bedrock analysis pipeline (Concurrent)")
    categories = ["residential", "office", "retail", "land"]
    
    all_parsed_data = {}
    total_token_usage = TokenUsage()
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_category = {
            executor.submit(run_bedrock_analysis_single_category, latitude, longitude, location, cat): cat
            for cat in categories
        }
        
        for future in as_completed(future_to_category):
            cat = future_to_category[future]
            try:
                parsed_data, usage = future.result()
                
                # Merge location_identification
                if not all_parsed_data.get("location_identification") and parsed_data.get("location_identification"):
                    all_parsed_data["location_identification"] = parsed_data.get("location_identification")
                
                # Merge property_categories
                if "property_categories" not in all_parsed_data:
                    all_parsed_data["property_categories"] = {}
                
                if parsed_data.get("property_categories", {}).get(cat):
                    all_parsed_data["property_categories"][cat] = parsed_data["property_categories"][cat]
                else:
                    if cat not in all_parsed_data["property_categories"]:
                        all_parsed_data["property_categories"][cat] = []
                        
                total_token_usage.input_tokens += usage.input_tokens
                total_token_usage.output_tokens += usage.output_tokens
                total_token_usage.total_tokens += usage.total_tokens
                total_token_usage.call_count += usage.call_count
                
            except Exception as exc:
                logger.error(f"Category {cat} generated an exception: {exc}")
    
    result = build_pipeline_result(location, all_parsed_data)
    result = populate_project_urls(result, total_token_usage)
    
    logger.info("Successfully parsed concurrent Bedrock response and fetched URLs")
    return result, total_token_usage

def get_trend_search_context(location: str, latitude: str = "", longitude: str = "") -> str:
    """Uses Google Places reverse geocoding + DuckDuckGo/Tavily for 3-year micromarket trend analysis."""
    logger.info(f"Starting search for trend analysis: {location}, coords: ({latitude}, {longitude})")
    
    google_context = ""
    if latitude and longitude:
        try:
            geo_info = reverse_geocode_google(float(latitude), float(longitude))
            if geo_info.get("formatted_address"):
                google_context += f"VERIFIED GOOGLE MICROMARKET LOCATION CONTEXT:\n"
                google_context += f"- Identified Micromarket / Sublocality: {geo_info.get('sublocality') or geo_info.get('locality')}\n"
                google_context += f"- Full Formatted Address: {geo_info.get('formatted_address')}\n"
                google_context += f"- City / State: {geo_info.get('city')}, {geo_info.get('state')}\n\n"
        except Exception as e:
            logger.warning(f"Google trend geocoding failed: {e}")

    try:
        categories = ["flat", "shop", "office", "land"]
        queries = [f"property price trend last 3 years in {location}"]
        for cat in categories:
            queries.append(f"real estate rate trend {location} {cat}")
            
        web_context = ""
        import time
        for query in queries:
            results = []
            for attempt in range(3):
                try:
                    results = list(DDGS().text(query, backend="google,duckduckgo,yandex"))
                    if results:
                        break
                except Exception as e:
                    logger.warning(f"DDGS attempt {attempt+1} failed for trend query '{query}': {e}")
                    time.sleep(1 + attempt)

            if not results:
                logger.info(f"DDG returned no results for trend query '{query}'. Trying Tavily...")
                results = _tavily_search(query)

            for i, r in enumerate(results):
                url = r.get('href', '')
                snippet = r.get('body', '')
                page_text = ""
                if i < 2 and url:
                    page_text = scrape_page(url)
                content_block = f"Source: {r.get('title')}\nURL: {url}\nSnippet: {snippet}\n"
                if page_text:
                    content_block += f"Page Content Extract:\n{page_text[:10000]}\n"
                content_block += "\n"
                if url not in web_context:
                    web_context += content_block
        return google_context + web_context
    except Exception as e:
        logger.error(f"Search error for trend: {e}")
        return google_context or "No search data available."

def run_openai_trend_analysis(latitude: str, longitude: str, location: str) -> Tuple[str, TokenUsage]:
    logger.info("Starting OpenAI trend analysis pipeline")
    context = get_trend_search_context(location, latitude=latitude, longitude=longitude)
    formatted_prompt = STAGE2_PROMPT.format(latitude=latitude, longitude=longitude, location=location)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a Real Estate Trend Analysis AI. Output ONLY HTML. Do not output JSON or Markdown."},
                {"role": "user", "content": formatted_prompt + "\n\nSearch Context:\n" + context}
            ]
        )
        content = response.choices[0].message.content
        if "```html" in content:
            content = content.split("```html")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return content, extract_token_usage(response)
    except Exception as e:
        logger.error(f"OpenAI trend error: {e}")
        return f"Error fetching trend analysis from OpenAI: {e}", TokenUsage()

def run_bedrock_trend_analysis(latitude: str, longitude: str, location: str) -> Tuple[str, TokenUsage]:
    logger.info("Starting Bedrock trend analysis pipeline")
    context = get_trend_search_context(location, latitude=latitude, longitude=longitude)
    formatted_prompt = STAGE2_PROMPT.format(latitude=latitude, longitude=longitude, location=location)
    
    try:
        bedrock_client = _bedrock_client()
        response = bedrock_client.chat.completions.create(
            model=_BEDROCK_MODEL,
            messages=[
                {"role": "system", "content": "You are a Real Estate Trend Analysis AI. Output ONLY HTML. Do not output JSON or Markdown."},
                {"role": "user", "content": formatted_prompt + "\n\nSearch Context:\n" + context}
            ]
        )
        content = response.choices[0].message.content
        if "```html" in content:
            content = content.split("```html")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return content, extract_token_usage(response)
    except Exception as e:
        logger.error(f"Bedrock trend error: {e}")
        return f"Error fetching trend analysis from Bedrock: {e}", TokenUsage()

def get_appreciation_search_context(location: str, latitude: str = "", longitude: str = "") -> str:
    """Uses Google Places Nearby Search for IT Parks, Metro, Highways, Hospitals, Malls + DuckDuckGo/Tavily."""
    logger.info(f"Starting search for appreciation analysis: {location}, coords: ({latitude}, {longitude})")
    
    google_context = ""
    if latitude and longitude:
        try:
            lat_f = float(latitude)
            lng_f = float(longitude)
            geo_info = reverse_geocode_google(lat_f, lng_f)
            if geo_info.get("formatted_address"):
                google_context += f"VERIFIED GOOGLE GEOLOCATION CONTEXT:\n"
                google_context += f"- Formatted Address: {geo_info.get('formatted_address')}\n"
                google_context += f"- Micromarket / Sublocality: {geo_info.get('sublocality') or geo_info.get('locality')}\n\n"

            landmarks_info = fetch_nearby_landmarks_google(lat_f, lng_f)
            if landmarks_info:
                google_context += landmarks_info + "\n"
        except Exception as e:
            logger.warning(f"Google appreciation landmarks extraction failed: {e}")

    try:
        queries = [
            f"upcoming infrastructure projects metro highways in {location}",
            f"employment hubs IT parks job growth in {location}",
            f"real estate demand supply property appreciation potential {location}"
        ]
        web_context = ""
        for query in queries:
            results = []
            try:
                results = list(DDGS().text(query, backend="google,duckduckgo,yandex"))
            except Exception as ddg_err:
                logger.warning(f"DDG failed for appreciation query '{query}': {ddg_err}. Falling back to Tavily.")

            if not results:
                logger.info(f"DDG returned no results for appreciation query '{query}'. Trying Tavily...")
                results = _tavily_search(query)

            for i, r in enumerate(results):
                url = r.get('href', '')
                snippet = r.get('body', '')
                page_text = ""
                if i < 2 and url:
                    page_text = scrape_page(url)
                content_block = f"Source: {r.get('title')}\nURL: {url}\nSnippet: {snippet}\n"
                if page_text:
                    content_block += f"Page Content Extract:\n{page_text[:4000]}\n"
                content_block += "\n"
                if url not in web_context:
                    web_context += content_block
        return google_context + web_context
    except Exception as e:
        logger.error(f"Search error for appreciation: {e}")
        return google_context or "No search data available."

def run_openai_appreciation_analysis(latitude: str, longitude: str, location: str) -> Tuple[str, TokenUsage]:
    logger.info("Starting OpenAI appreciation analysis pipeline")
    context = get_appreciation_search_context(location, latitude=latitude, longitude=longitude)
    formatted_prompt = STAGE3_PROMPT.format(latitude=latitude, longitude=longitude, location=location)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a Real Estate Appreciation Analysis AI. Output ONLY HTML. Do not output JSON or Markdown."},
                {"role": "user", "content": formatted_prompt + "\n\nSearch Context:\n" + context}
            ]
        )
        content = response.choices[0].message.content
        if "```html" in content:
            content = content.split("```html")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return content, extract_token_usage(response)
    except Exception as e:
        logger.error(f"OpenAI appreciation error: {e}")
        return f"Error fetching appreciation analysis from OpenAI: {e}", TokenUsage()

def run_bedrock_appreciation_analysis(latitude: str, longitude: str, location: str) -> Tuple[str, TokenUsage]:
    logger.info("Starting Bedrock appreciation analysis pipeline")
    context = get_appreciation_search_context(location, latitude=latitude, longitude=longitude)
    formatted_prompt = STAGE3_PROMPT.format(latitude=latitude, longitude=longitude, location=location)
    
    try:
        bedrock_client = _bedrock_client()
        response = bedrock_client.chat.completions.create(
            model=_BEDROCK_MODEL,
            messages=[
                {"role": "system", "content": "You are a Real Estate Appreciation Analysis AI. Output ONLY HTML. Do not output JSON or Markdown."},
                {"role": "user", "content": formatted_prompt + "\n\nSearch Context:\n" + context}
            ]
        )
        content = response.choices[0].message.content
        if "```html" in content:
            content = content.split("```html")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return content, extract_token_usage(response)
    except Exception as e:
        logger.error(f"Bedrock appreciation error: {e}")
        return f"Error fetching appreciation analysis from Bedrock: {e}", TokenUsage()

def run_openai_final_analysis(location: str, latitude: str, longitude: str, price_data: dict, trend_data: dict, appreciation_data: dict) -> Tuple[str, TokenUsage]:
    logger.info("Starting OpenAI final analysis pipeline")
    from datetime import date
    formatted_prompt = STAGE4_PROMPT.format(
        location=location,
        latitude=latitude,
        longitude=longitude,
        price_point_data=json.dumps(price_data),
        trend_data=json.dumps(trend_data),
        appreciation_data=json.dumps(appreciation_data),
        current_year=date.today().year
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a Master Real Estate Analyst AI. Output ONLY HTML. Do not output JSON or Markdown."},
                {"role": "user", "content": formatted_prompt}
            ]
        )
        content = response.choices[0].message.content
        if "```html" in content:
            content = content.split("```html")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return content, extract_token_usage(response)
    except Exception as e:
        logger.error(f"OpenAI final analysis error: {e}")
        return f"Error fetching final analysis from OpenAI: {e}", TokenUsage()

def run_bedrock_final_analysis(location: str, latitude: str, longitude: str, price_data: dict, trend_data: dict, appreciation_data: dict) -> Tuple[str, TokenUsage]:
    logger.info("Starting Bedrock final analysis pipeline")
    from datetime import date
    formatted_prompt = STAGE4_PROMPT.format(
        location=location,
        latitude=latitude,
        longitude=longitude,
        price_point_data=json.dumps(price_data),
        trend_data=json.dumps(trend_data),
        appreciation_data=json.dumps(appreciation_data),
        current_year=date.today().year
    )
    
    try:
        bedrock_client = _bedrock_client()
        response = bedrock_client.chat.completions.create(
            model=_BEDROCK_MODEL,
            messages=[
                {"role": "system", "content": "You are a Master Real Estate Analyst AI. Output ONLY HTML. Do not output JSON or Markdown."},
                {"role": "user", "content": formatted_prompt}
            ]
        )
        content = response.choices[0].message.content
        if "```html" in content:
            content = content.split("```html")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return content, extract_token_usage(response)
    except Exception as e:
        logger.error(f"Bedrock final analysis error: {e}")
        return f"Error fetching final analysis from Bedrock: {e}", TokenUsage()
