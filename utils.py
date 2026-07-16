"""
utils.py - shared utility functions used by both pipeline.py and listing_extractor.py.

Kept in a separate module to avoid the circular import:
    pipeline.py  ->  listing_extractor.py  ->  pipeline.py
"""

import json
import logging
from models import TokenUsage

logger = logging.getLogger(__name__)


def extract_token_usage(response) -> TokenUsage:
    """Extract token counts from an OpenAI-compatible API response."""
    if hasattr(response, "usage") and response.usage:
        return TokenUsage(
            input_tokens=response.usage.prompt_tokens or 0,
            output_tokens=response.usage.completion_tokens or 0,
            total_tokens=response.usage.total_tokens or 0,
            call_count=1,
        )
    return TokenUsage(call_count=1)


def parse_llm_json(response_text: str) -> dict:
    """Safely parse JSON from LLM string output (strips markdown fences if present)."""
    try:
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"JSON Parse Error: {e}\nResponse text was: {response_text}")
        return {}
