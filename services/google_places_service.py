import math
import logging
import requests
from typing import List, Dict, Any, Tuple
from core.config import GOOGLE_PLACE_API_KEY

logger = logging.getLogger(__name__)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the geodesic distance between two points in kilometers using the Haversine formula."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def reverse_geocode_google(lat: float, lng: float) -> Dict[str, Any]:
    """
    Use Google Reverse Geocoding API to accurately resolve formatted address, locality,
    sublocality (micromarket), city, state, and country from coordinates.
    """
    if not GOOGLE_PLACE_API_KEY:
        logger.warning("GOOGLE_PLACE_API_KEY not found.")
        return {}

    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "latlng": f"{lat},{lng}",
        "key": GOOGLE_PLACE_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") == "OK" and data.get("results"):
            top = data["results"][0]
            components = top.get("address_components", [])

            locality = ""
            sublocality = ""
            city = ""
            state = ""
            country = ""

            for comp in components:
                types = comp.get("types", [])
                if "sublocality_level_1" in types or "sublocality" in types:
                    sublocality = comp.get("long_name", "")
                elif "locality" in types:
                    locality = comp.get("long_name", "")
                elif "administrative_area_level_2" in types:
                    city = comp.get("long_name", "")
                elif "administrative_area_level_1" in types:
                    state = comp.get("long_name", "")
                elif "country" in types:
                    country = comp.get("long_name", "")

            return {
                "formatted_address": top.get("formatted_address", ""),
                "sublocality": sublocality,
                "locality": locality,
                "city": city or locality,
                "state": state,
                "country": country,
                "place_id": top.get("place_id", ""),
            }
    except Exception as e:
        logger.error(f"Reverse geocode error: {e}")

    return {}

def fetch_nearby_projects_google(lat: float, lng: float, min_count: int = 5) -> Dict[str, Any]:
    """
    Query Google Places Nearby Search for real estate projects within 2.0 km radius.
    If fewer than `min_count` projects are found within 2.0 km, automatically fallback to 4.0 km radius.
    Filter using Haversine distance for 100% distance precision.
    """
    if not GOOGLE_PLACE_API_KEY:
        logger.warning("GOOGLE_PLACE_API_KEY missing.")
        return {"projects": [], "radius_used_km": 2.0, "total_found": 0}

    def _query_nearby(radius_m: int) -> List[Dict[str, Any]]:
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        keywords = "residential project|apartment complex|office building|commercial complex|housing society"
        params = {
            "location": f"{lat},{lng}",
            "radius": radius_m,
            "keyword": keywords,
            "key": GOOGLE_PLACE_API_KEY,
        }
        try:
            resp = requests.get(url, params=params, timeout=12)
            data = resp.json()
            if data.get("status") in ("OK", "ZERO_RESULTS"):
                return data.get("results", [])
        except Exception as e:
            logger.error(f"Google Places Nearby search error: {e}")
        return []

    # Step 1: Search within 2.0 km (2000 meters)
    raw_2km = _query_nearby(2000)
    projects_2km = []
    seen_names = set()

    for item in raw_2km:
        loc = item.get("geometry", {}).get("location", {})
        plat = loc.get("lat")
        plng = loc.get("lng")
        if plat is None or plng is None:
            continue

        dist_km = round(haversine_distance(lat, lng, plat, plng), 2)
        name = item.get("name", "").strip()

        if dist_km <= 2.0 and name and name.lower() not in seen_names:
            seen_names.add(name.lower())
            projects_2km.append({
                "project_name": name,
                "vicinity": item.get("vicinity", ""),
                "distance_km": dist_km,
                "distance_str": f"{dist_km} km",
                "latitude": str(plat),
                "longitude": str(plng),
                "place_id": item.get("place_id", ""),
            })

    # Sort by distance ascending
    projects_2km.sort(key=lambda x: x["distance_km"])

    if len(projects_2km) >= min_count:
        return {
            "projects": projects_2km,
            "radius_used_km": 2.0,
            "total_found": len(projects_2km),
        }

    # Step 2: Fallback to 4.0 km (4000 meters) if < min_count found in 2 km
    logger.info(f"Only {len(projects_2km)} projects found within 2.0 km. Expanding to 4.0 km fallback radius...")
    raw_4km = _query_nearby(4000)
    projects_4km = []
    seen_names.clear()

    for item in raw_4km:
        loc = item.get("geometry", {}).get("location", {})
        plat = loc.get("lat")
        plng = loc.get("lng")
        if plat is None or plng is None:
            continue

        dist_km = round(haversine_distance(lat, lng, plat, plng), 2)
        name = item.get("name", "").strip()

        if dist_km <= 4.0 and name and name.lower() not in seen_names:
            seen_names.add(name.lower())
            projects_4km.append({
                "project_name": name,
                "vicinity": item.get("vicinity", ""),
                "distance_km": dist_km,
                "distance_str": f"{dist_km} km",
                "latitude": str(plat),
                "longitude": str(plng),
                "place_id": item.get("place_id", ""),
            })

    projects_4km.sort(key=lambda x: x["distance_km"])

    return {
        "projects": projects_4km,
        "radius_used_km": 4.0,
        "total_found": len(projects_4km),
    }

def fetch_nearby_landmarks_google(lat: float, lng: float) -> str:
    """
    Fetch nearby IT Parks, Metro Stations, Highways, Schools, Hospitals, Malls
    via Google Places API with exact Haversine distances for Stage 3 Appreciation analysis.
    """
    if not GOOGLE_PLACE_API_KEY:
        return ""

    categories = [
        ("Employment & Job Hubs", "IT park|tech park|business hub|office park"),
        ("Transit & Connectivity", "metro station|railway station|highway|expressway"),
        ("Social & Commercial Infrastructure", "hospital|school|college|shopping mall|supermarket"),
    ]

    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    result_str = "VERIFIED GOOGLE NEARBY DEMAND DRIVERS & INFRASTRUCTURE (EXACT DISTANCES):\n"

    for category_name, keyword in categories:
        try:
            params = {
                "location": f"{lat},{lng}",
                "radius": 5000,
                "keyword": keyword,
                "key": GOOGLE_PLACE_API_KEY,
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if data.get("status") in ("OK", "ZERO_RESULTS"):
                items = data.get("results", [])[:4]
                if items:
                    result_str += f"- {category_name}:\n"
                    for item in items:
                        loc = item.get("geometry", {}).get("location", {})
                        plat, plng = loc.get("lat"), loc.get("lng")
                        if plat and plng:
                            dist_km = round(haversine_distance(lat, lng, plat, plng), 2)
                            dist_m = int(dist_km * 1000)
                            result_str += f"  • {item.get('name')}: {dist_km} km ({dist_m} meters) | Vicinity: {item.get('vicinity', '')}\n"
        except Exception as e:
            logger.warning(f"Error fetching landmarks for {category_name}: {e}")

    return result_str
