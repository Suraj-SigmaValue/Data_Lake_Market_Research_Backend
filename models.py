from pydantic import BaseModel
from typing import List, Optional, Any

class AnalyzeRequest(BaseModel):
    latitude: str
    longitude: str
    location: str

class LocationIdentification(BaseModel):
    latitude: Any = ""
    longitude: Any = ""
    identified_location: Any = ""
    nearest_locality: Any = ""
    sector_or_area: Any = ""
    micro_market: Any = ""
    city: Any = ""
    state: Any = ""
    country: Any = ""

class PortalListing(BaseModel):
    portal: str
    url: str
    project_name: Optional[str] = ""
    title: Optional[str] = ""
    price: Optional[str] = ""
    currency: Optional[str] = ""
    area: Optional[str] = ""
    area_type: Optional[str] = ""
    location: Optional[str] = ""

class PropertyListing(BaseModel):
    project_name: Any = ""
    property_type: Any = ""
    distance_from_coordinate: Any = ""
    portal_listings: List[PortalListing] = []

class PropertyCategories(BaseModel):
    residential: List[PropertyListing] = []
    office: List[PropertyListing] = []
    retail: List[PropertyListing] = []
    land: List[PropertyListing] = []

class PipelineResult(BaseModel):
    location: str
    location_identification: LocationIdentification
    property_categories: PropertyCategories
    error_message: Optional[str] = None

class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0

class AnalyzeResponse(BaseModel):
    location: str
    openai_result: PipelineResult
    bedrock_result: PipelineResult
    openai_tokens: TokenUsage
    bedrock_tokens: TokenUsage


class TrendResponse(BaseModel):
    location: str
    openai_trend: str
    bedrock_trend: str
    openai_tokens: TokenUsage
    bedrock_tokens: TokenUsage

class AppreciationResponse(BaseModel):
    location: str
    openai_appreciation: str
    bedrock_appreciation: str
    openai_tokens: TokenUsage
    bedrock_tokens: TokenUsage

class FinalAnalysisRequest(BaseModel):
    location: str
    latitude: str
    longitude: str
    price_point_data: dict
    trend_data: dict
    appreciation_data: dict

class FinalAnalysisResponse(BaseModel):
    location: str
    openai_analysis: str
    bedrock_analysis: str
    openai_tokens: TokenUsage
    bedrock_tokens: TokenUsage

class ExtractListingsRequest(BaseModel):
    project_name: str
    location: str
    urls: List[dict]
    provider: str = "bedrock"
    property_type: str

class ExtractListingsResponse(BaseModel):
    listings: List[PortalListing]
    token_usage: TokenUsage
