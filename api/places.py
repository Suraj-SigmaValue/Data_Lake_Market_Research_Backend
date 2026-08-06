import logging
import requests
from fastapi import APIRouter, Query
from core.config import GOOGLE_PLACE_API_KEY
from services.google_places_service import reverse_geocode_google, fetch_nearby_projects_google

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/places/search")
def search_places(query: str = Query(..., min_length=2)):
    """
    Search for property, building name, or address via Google Places API (Text Search).
    Returns list of matching places with place_id, name, formatted_address, latitude, and longitude.
    """
    if not GOOGLE_PLACE_API_KEY:
        logger.warning("GOOGLE_PLACE_API_KEY is not set in environment.")
        return {"places": [], "error": "Google Places API key is missing."}

    try:
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": query,
            "key": GOOGLE_PLACE_API_KEY,
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        status = data.get("status")
        if status != "OK":
            logger.warning(f"Google Places API returned status: {status}, error_message: {data.get('error_message')}")
            return {"places": [], "status": status}

        results = []
        for item in data.get("results", []):
            loc = item.get("geometry", {}).get("location", {})
            results.append({
                "place_id": item.get("place_id", ""),
                "name": item.get("name", ""),
                "formatted_address": item.get("formatted_address", ""),
                "latitude": str(loc.get("lat", "")),
                "longitude": str(loc.get("lng", "")),
            })

        return {"places": results, "status": "OK"}
    except Exception as e:
        logger.error(f"Error calling Google Places API: {e}")
        return {"places": [], "error": str(e)}

@router.get("/places/reverse-geocode")
def reverse_geocode(latitude: float, longitude: float):
    """
    Accurately resolve location details (formatted_address, sublocality, locality, city, state, country) from lat/lng.
    """
    info = reverse_geocode_google(latitude, longitude)
    return {"location_info": info}

@router.get("/places/nearby")
def nearby_projects(latitude: float, longitude: float, min_count: int = 5):
    """
    Fetch real estate projects strictly within 2.0 km radius (with 4.0 km automatic fallback).
    """
    res = fetch_nearby_projects_google(latitude, longitude, min_count=min_count)
    return res
