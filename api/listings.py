from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from data.models import ExtractListingsRequest, ExtractListingsResponse
from orchestration.listing_flow import run_extract_listings, stream_extract_listings

router = APIRouter()

@router.post("/extract-listings", response_model=ExtractListingsResponse)
def extract_listings_endpoint(request: ExtractListingsRequest):
    valid_listings, token_usage = run_extract_listings(
        request.project_name, request.location, request.urls,
        request.provider, request.property_type, target_count=5
    )
    return ExtractListingsResponse(listings=valid_listings, token_usage=token_usage)

@router.post("/extract-listings-stream")
def extract_listings_stream_endpoint(request: ExtractListingsRequest):
    """
    Streaming version of /extract-listings.
    Returns a text/event-stream (SSE) response.
    """
    generator = stream_extract_listings(
        project_name=request.project_name,
        location=request.location,
        urls=request.urls,
        provider=request.provider,
        property_type=request.property_type,
        target_count=5,
    )
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
