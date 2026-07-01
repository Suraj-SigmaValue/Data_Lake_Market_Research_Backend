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

class Transaction(BaseModel):
    total_price: Any = ""
    area: Any = ""
    area_unit: Any = ""
    area_basis: Any = ""
    calculated_rate: Any = ""
    normalized_net_carpet_rate: Any = ""
    url: Any = ""
    portal: Any = ""

class PropertyListing(BaseModel):
    project_name: Any = ""
    property_type: Any = ""
    listing_type: Any = ""
    average_project_rate: Any = ""
    total_price: Any = ""
    area: Any = ""
    area_unit: Any = ""
    area_basis: Any = ""
    calculated_rate: Any = ""
    rate_unit: Any = ""
    portal: Any = ""
    url: Any = ""
    distance_from_coordinate: Any = ""
    transactions: List[Transaction] = []

class PropertyCategories(BaseModel):
    residential: List[PropertyListing] = []
    office: List[PropertyListing] = []
    retail: List[PropertyListing] = []
    land: List[PropertyListing] = []

class PipelineResult(BaseModel):
    location: str
    location_identification: LocationIdentification
    property_categories: PropertyCategories

class AnalyzeResponse(BaseModel):
    location: str
    openai_result: PipelineResult
    groq_result: PipelineResult

class TrendResponse(BaseModel):
    location: str
    openai_trend: str
    groq_trend: str

class AppreciationResponse(BaseModel):
    location: str
    openai_appreciation: str
    groq_appreciation: str

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
    groq_analysis: str
