import json
import os
import logging
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from openai import OpenAI
from ddgs import DDGS
from typing import Tuple
import trafilatura
from models import PipelineResult, LocationIdentification, PropertyCategories, PropertyListing, TokenUsage
from prompt import STAGE1_PROMPT, STAGE2_PROMPT, STAGE3_PROMPT, STAGE4_PROMPT

def extract_token_usage(response) -> TokenUsage:
    if hasattr(response, 'usage') and response.usage:
        return TokenUsage(
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
            total_tokens=response.usage.total_tokens or 0
        )
    return TokenUsage()

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
            result = trafilatura.extract(downloaded, include_tables=True, include_links=False)
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
        return ""
    except Exception as e:
        logger.error(f"Scrape error for {url}: {e}")
        return ""

def get_search_context(location: str) -> str:
    """Uses DuckDuckGo to find real estate portals and scrapes the actual pages for maximum data."""
    logger.info(f"Starting expanded DuckDuckGo search + deep scraping for location: {location}")
    try:
        queries = [
            f"1 BHK 2 BHK 3 BHK flats for sale in {location} price",
            f"commercial office space properties for sale in {location} price",
            f"commercial shops retail showrooms for sale in {location} price",
            f"residential plots land for sale in {location} price"
        ]
        
        context = ""
        for query in queries:
            results = list(DDGS().text(query, max_results=10))
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

def run_openai_analysis(latitude: str, longitude: str, location: str) -> Tuple[PipelineResult, TokenUsage]:
    logger.info("Starting OpenAI analysis pipeline")
    context = get_search_context(location)
    
    formatted_prompt = STAGE1_PROMPT.format(latitude=latitude, longitude=longitude, location=location)
    
    try:
        logger.info("Calling OpenAI gpt-4o")
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a Real Estate Extraction AI. Output ONLY JSON. Do not include markdown blocks."},
                {"role": "user", "content": formatted_prompt + "\n\nSearch Context:\n" + context}
            ],
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        logger.info("Successfully received response from OpenAI")
        
        parsed_data = parse_llm_json(content)
        result = build_pipeline_result(location, parsed_data)
        
        logger.info("Successfully parsed OpenAI response")
        return result, extract_token_usage(response)
    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return PipelineResult(location=location, location_identification=LocationIdentification(), property_categories=PropertyCategories(), error_message=f"Error fetching from OpenAI: {e}"), TokenUsage()

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

def run_groq_analysis(latitude: str, longitude: str, location: str) -> Tuple[PipelineResult, TokenUsage]:
    logger.info("Starting Groq analysis pipeline")
    context = get_search_context(location)
    
    formatted_prompt = STAGE1_PROMPT.format(latitude=latitude, longitude=longitude, location=location)
    
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
        logger.info("Successfully received response from Groq")
        
        parsed_data = parse_llm_json(content)
        result = build_pipeline_result(location, parsed_data)
        
        logger.info("Successfully parsed Groq response")
        return result, extract_token_usage(response)
    except Exception as e:
        logger.error(f"Groq error: {e}")
        return PipelineResult(location=location, location_identification=LocationIdentification(), property_categories=PropertyCategories(), error_message=f"Error fetching from Groq: {e}"), TokenUsage()

def get_trend_search_context(location: str) -> str:
    """Uses DuckDuckGo to search for price trends over the last 3 years."""
    logger.info(f"Starting DuckDuckGo search for trend analysis: {location}")
    try:
        queries = [
            f"property price trend last 3 years in {location}",
            f"real estate rate trend {location} flat shop office land"
        ]
        context = ""
        for query in queries:
            results = list(DDGS().text(query, max_results=10))
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
            results = list(DDGS().text(query, max_results=7))
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
