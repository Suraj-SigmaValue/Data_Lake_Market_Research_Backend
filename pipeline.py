import json
import os
import logging
import requests
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
from listing_extractor import fetch_project_urls
def extract_token_usage(response) -> TokenUsage:
    if hasattr(response, 'usage') and response.usage:
        return TokenUsage(
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
            total_tokens=response.usage.total_tokens or 0,
            call_count=1
        )
    return TokenUsage(call_count=1)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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

def get_search_context(location: str, target_category: str) -> str:
    """Uses DuckDuckGo to find real estate portals and scrapes the actual pages for maximum data for a specific category."""
    logger.info(f"Starting expanded DuckDuckGo search + deep scraping for location: {location}, category: {target_category}")
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
        
        context = ""
        for query in queries:
            results = list(DDGS().text(query))
            for i, r in enumerate(results):
                url = r.get('href', '')
                snippet = r.get('body', '')
                
                # Deep scrape the top 2 links of each category for massive data volume
                page_text = ""
                if i < 2 and url:
                    page_text = scrape_page(url)
                
                content_block = f"Source: {r.get('title')}\nURL: {url}\nSnippet: {snippet}\n"
                if page_text:
                    content_block += f"Page Content Extract:\n{page_text}\n"
                content_block += "\n"
                
                if url not in context:
                    context += content_block
                    
        logger.info(f"Successfully retrieved expanded search + scraped context for {location} (length: {len(context)})")
        return context
    except Exception as e:
        logger.error(f"Search error: {e}")
        return "No search data available."

def parse_llm_json(response_text: str) -> dict:
    """Helper to safely parse JSON from LLM string output."""
    try:
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        data = json.loads(response_text)
        return data
    except Exception as e:
        logger.error(f"JSON Parse Error: {e}\nResponse text was: {response_text}")
        return {}

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
    
    for p, category in projects_with_category:
        if p.project_name:
            try:
                import time
                time.sleep(1.5) # Prevent 429 Too Many Requests from DDGS
                urls, usage = fetch_project_urls(p.project_name, pipeline_result.location, category)
                if total_token_usage:
                    total_token_usage.input_tokens += usage.input_tokens
                    total_token_usage.output_tokens += usage.output_tokens
                    total_token_usage.total_tokens += usage.total_tokens
                    total_token_usage.call_count += usage.call_count
                p.portal_listings = [PortalListing(**item) for item in urls if isinstance(item, dict)]
            except Exception as exc:
                logger.error(f"{p.project_name} generated an exception: {exc}")
                
    return pipeline_result

def run_openai_analysis_single_category(latitude: str, longitude: str, location: str, category: str) -> Tuple[dict, TokenUsage]:
    logger.info(f"Starting OpenAI analysis for category: {category}")
    context = get_search_context(location, category)
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

def run_groq_analysis_single_category(latitude: str, longitude: str, location: str, category: str) -> Tuple[dict, TokenUsage]:
    logger.info(f"Starting Groq analysis for category: {category}")
    context = get_search_context(location, category)
    formatted_prompt = STAGE1_PROMPT.format(latitude=latitude, longitude=longitude, location=location, target_category=category)
    
    try:
        # Groq is compatible with the OpenAI SDK
        groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("Groq_API_Key")
        )
        
        logger.info("Calling Groq llama-3.3-70b-versatile")
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
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
        logger.error(f"Groq error for {category}: {e}")
        return {}, TokenUsage()

def run_groq_analysis(latitude: str, longitude: str, location: str) -> Tuple[PipelineResult, TokenUsage]:
    logger.info("Starting Groq analysis pipeline (Concurrent)")
    categories = ["residential", "office", "retail", "land"]
    
    all_parsed_data = {}
    total_token_usage = TokenUsage()
    
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_category = {
            executor.submit(run_groq_analysis_single_category, latitude, longitude, location, cat): cat
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
    
    logger.info("Successfully parsed concurrent Groq response and fetched URLs")
    return result, total_token_usage

def get_trend_search_context(location: str) -> str:
    """Uses DuckDuckGo to search for price trends over the last 3 years."""
    logger.info(f"Starting DuckDuckGo search for trend analysis: {location}")
    try:
        categories = ["flat", "shop", "office", "land"]
        queries = [f"property price trend last 3 years in {location}"]
        for cat in categories:
            queries.append(f"real estate rate trend {location} {cat}")
            
        context = ""
        import time
        for query in queries:
            results = []
            for attempt in range(3):
                try:
                    results = list(DDGS().text(query))
                    if results:
                        break
                except Exception as e:
                    logger.warning(f"DDGS attempt {attempt+1} failed for trend query: {e}")
                    time.sleep(1 + attempt)
                    
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
                if url not in context:
                    context += content_block
        return context
    except Exception as e:
        logger.error(f"Search error for trend: {e}")
        return "No search data available."

def run_openai_trend_analysis(latitude: str, longitude: str, location: str) -> Tuple[str, TokenUsage]:
    logger.info("Starting OpenAI trend analysis pipeline")
    context = get_trend_search_context(location)
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

def run_groq_trend_analysis(latitude: str, longitude: str, location: str) -> Tuple[str, TokenUsage]:
    logger.info("Starting Groq trend analysis pipeline")
    context = get_trend_search_context(location)
    formatted_prompt = STAGE2_PROMPT.format(latitude=latitude, longitude=longitude, location=location)
    
    try:
        groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("Groq_API_Key")
        )
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
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
        logger.error(f"Groq trend error: {e}")
        return f"Error fetching trend analysis from Groq: {e}", TokenUsage()

def get_appreciation_search_context(location: str) -> str:
    """Uses DuckDuckGo to search for infrastructure, employment hubs, and appreciation drivers."""
    logger.info(f"Starting DuckDuckGo search for appreciation analysis: {location}")
    try:
        queries = [
            f"upcoming infrastructure projects metro highways in {location}",
            f"employment hubs IT parks job growth in {location}",
            f"real estate demand supply property appreciation potential {location}"
        ]
        context = ""
        for query in queries:
            results = list(DDGS().text(query))
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
                if url not in context:
                    context += content_block
        return context
    except Exception as e:
        logger.error(f"Search error for appreciation: {e}")
        return "No search data available."

def run_openai_appreciation_analysis(latitude: str, longitude: str, location: str) -> Tuple[str, TokenUsage]:
    logger.info("Starting OpenAI appreciation analysis pipeline")
    context = get_appreciation_search_context(location)
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

def run_groq_appreciation_analysis(latitude: str, longitude: str, location: str) -> Tuple[str, TokenUsage]:
    logger.info("Starting Groq appreciation analysis pipeline")
    context = get_appreciation_search_context(location)
    formatted_prompt = STAGE3_PROMPT.format(latitude=latitude, longitude=longitude, location=location)
    
    try:
        groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("Groq_API_Key")
        )
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
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
        logger.error(f"Groq appreciation error: {e}")
        return f"Error fetching appreciation analysis from Groq: {e}", TokenUsage()

def run_openai_final_analysis(location: str, latitude: str, longitude: str, price_data: dict, trend_data: dict, appreciation_data: dict) -> Tuple[str, TokenUsage]:
    logger.info("Starting OpenAI final analysis pipeline")
    formatted_prompt = STAGE4_PROMPT.format(
        location=location,
        latitude=latitude,
        longitude=longitude,
        price_point_data=json.dumps(price_data),
        trend_data=json.dumps(trend_data),
        appreciation_data=json.dumps(appreciation_data)
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

def run_groq_final_analysis(location: str, latitude: str, longitude: str, price_data: dict, trend_data: dict, appreciation_data: dict) -> Tuple[str, TokenUsage]:
    logger.info("Starting Groq final analysis pipeline")
    formatted_prompt = STAGE4_PROMPT.format(
        location=location,
        latitude=latitude,
        longitude=longitude,
        price_point_data=json.dumps(price_data),
        trend_data=json.dumps(trend_data),
        appreciation_data=json.dumps(appreciation_data)
    )
    
    try:
        groq_client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("Groq_API_Key")
        )
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
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
        logger.error(f"Groq final analysis error: {e}")
        return f"Error fetching final analysis from Groq: {e}", TokenUsage()
