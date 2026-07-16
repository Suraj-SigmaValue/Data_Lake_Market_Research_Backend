import sys
import os

# Ensure the backend directory is always on sys.path so local modules
# (pipeline, listing_extractor, models, prompt) are found even when
# uvicorn's --reload spawns a child subprocess with a different cwd.
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from dotenv import load_dotenv
load_dotenv()  # Load from the current backend/.env


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from models import AnalyzeRequest, AnalyzeResponse, TrendResponse, AppreciationResponse, FinalAnalysisRequest, FinalAnalysisResponse, ExtractListingsRequest, ExtractListingsResponse
from pipeline import run_openai_analysis, run_bedrock_analysis, run_openai_trend_analysis, run_bedrock_trend_analysis, run_openai_appreciation_analysis, run_bedrock_appreciation_analysis, run_openai_final_analysis, run_bedrock_final_analysis
from listing_extractor import run_extract_listings, stream_extract_listings

app = FastAPI(title="Data Lake Market Research API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import asyncio

@app.get("/")
def read_root():
    return {"message": "Data Lake Market Research API (FastAPI) is running."}

@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_location(request: AnalyzeRequest):
    (openai_res, openai_tok), (bedrock_res, bedrock_tok) = await asyncio.gather(
        asyncio.to_thread(run_openai_analysis, request.latitude, request.longitude, request.location),
        asyncio.to_thread(run_bedrock_analysis, request.latitude, request.longitude, request.location)
    )
    
    return AnalyzeResponse(
        location=request.location,
        openai_result=openai_res,
        bedrock_result=bedrock_res,
        openai_tokens=openai_tok,
        bedrock_tokens=bedrock_tok
    )

@app.post("/trend", response_model=TrendResponse)
async def analyze_trend(request: AnalyzeRequest):
    (openai_res, openai_tok), (bedrock_res, bedrock_tok) = await asyncio.gather(
        asyncio.to_thread(run_openai_trend_analysis, request.latitude, request.longitude, request.location),
        asyncio.to_thread(run_bedrock_trend_analysis, request.latitude, request.longitude, request.location)
    )
    
    return TrendResponse(
        location=request.location,
        openai_trend=openai_res,
        bedrock_trend=bedrock_res,
        openai_tokens=openai_tok,
        bedrock_tokens=bedrock_tok
    )

@app.post("/appreciation", response_model=AppreciationResponse)
async def analyze_appreciation(request: AnalyzeRequest):
    (openai_res, openai_tok), (bedrock_res, bedrock_tok) = await asyncio.gather(
        asyncio.to_thread(run_openai_appreciation_analysis, request.latitude, request.longitude, request.location),
        asyncio.to_thread(run_bedrock_appreciation_analysis, request.latitude, request.longitude, request.location)
    )
    
    return AppreciationResponse(
        location=request.location,
        openai_appreciation=openai_res,
        bedrock_appreciation=bedrock_res,
        openai_tokens=openai_tok,
        bedrock_tokens=bedrock_tok
    )

@app.post("/final-analysis", response_model=FinalAnalysisResponse)
async def final_analysis(request: FinalAnalysisRequest):
    (openai_res, openai_tok), (bedrock_res, bedrock_tok) = await asyncio.gather(
        asyncio.to_thread(
            run_openai_final_analysis,
            request.latitude, request.longitude, request.location,
            request.price_point_data, request.trend_data, request.appreciation_data
        ),
        asyncio.to_thread(
            run_bedrock_final_analysis,
            request.latitude, request.longitude, request.location,
            request.price_point_data, request.trend_data, request.appreciation_data
        )
    )
    
    return FinalAnalysisResponse(
        location=request.location,
        openai_analysis=openai_res,
        bedrock_analysis=bedrock_res,
        openai_tokens=openai_tok,
        bedrock_tokens=bedrock_tok
    )

@app.post("/extract-listings", response_model=ExtractListingsResponse)
def extract_listings_endpoint(request: ExtractListingsRequest):
    valid_listings, token_usage = run_extract_listings(
        request.project_name, request.location, request.urls,
        request.provider, request.property_type, target_count=5
    )
    return ExtractListingsResponse(listings=valid_listings, token_usage=token_usage)


@app.post("/extract-listings-stream")
def extract_listings_stream_endpoint(request: ExtractListingsRequest):
    """
    Streaming version of /extract-listings.
    Returns a text/event-stream (SSE) response.
    Events: status | listing | tokens | error | done
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
            "X-Accel-Buffering": "no",   # disables Nginx buffering if behind a proxy
        },
    )
