import os
from dotenv import load_dotenv
load_dotenv() # Load from the current backend/.env

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from models import AnalyzeRequest, AnalyzeResponse, TrendResponse, AppreciationResponse, FinalAnalysisRequest, FinalAnalysisResponse, ExtractListingsRequest, ExtractListingsResponse
from pipeline import run_openai_analysis, run_groq_analysis, run_openai_trend_analysis, run_groq_trend_analysis, run_openai_appreciation_analysis, run_groq_appreciation_analysis, run_openai_final_analysis, run_groq_final_analysis
from listing_extractor import run_extract_listings

app = FastAPI(title="Data Lake Market Research API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Data Lake Market Research API (FastAPI) is running."}

@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_location(request: AnalyzeRequest):
    # Run pipelines concurrently or sequentially
    # For MVP, running sequentially
    openai_res, openai_tok = run_openai_analysis(request.latitude, request.longitude, request.location)
    groq_res, groq_tok = run_groq_analysis(request.latitude, request.longitude, request.location)
    
    return AnalyzeResponse(
        location=request.location,
        openai_result=openai_res,
        groq_result=groq_res,
        openai_tokens=openai_tok,
        groq_tokens=groq_tok
    )

@app.post("/trend", response_model=TrendResponse)
def analyze_trend(request: AnalyzeRequest):
    openai_res, openai_tok = run_openai_trend_analysis(request.latitude, request.longitude, request.location)
    groq_res, groq_tok = run_groq_trend_analysis(request.latitude, request.longitude, request.location)
    
    return TrendResponse(
        location=request.location,
        openai_trend=openai_res,
        groq_trend=groq_res,
        openai_tokens=openai_tok,
        groq_tokens=groq_tok
    )

@app.post("/appreciation", response_model=AppreciationResponse)
def analyze_appreciation(request: AnalyzeRequest):
    openai_res, openai_tok = run_openai_appreciation_analysis(request.latitude, request.longitude, request.location)
    groq_res, groq_tok = run_groq_appreciation_analysis(request.latitude, request.longitude, request.location)
    
    return AppreciationResponse(
        location=request.location,
        openai_appreciation=openai_res,
        groq_appreciation=groq_res,
        openai_tokens=openai_tok,
        groq_tokens=groq_tok
    )

@app.post("/final-analysis", response_model=FinalAnalysisResponse)
def final_analysis(request: FinalAnalysisRequest):
    openai_res, openai_tok = run_openai_final_analysis(
        request.latitude, request.longitude, request.location,
        request.price_point_data, request.trend_data, request.appreciation_data
    )
    groq_res, groq_tok = run_groq_final_analysis(
        request.latitude, request.longitude, request.location,
        request.price_point_data, request.trend_data, request.appreciation_data
    )
    
    return FinalAnalysisResponse(
        location=request.location,
        openai_analysis=openai_res,
        groq_analysis=groq_res,
        openai_tokens=openai_tok,
        groq_tokens=groq_tok
    )

@app.post("/extract-listings", response_model=ExtractListingsResponse)
def extract_listings_endpoint(request: ExtractListingsRequest):
    valid_listings, token_usage = run_extract_listings(request.project_name, request.location, request.urls, request.provider)
    return ExtractListingsResponse(
        listings=valid_listings,
        token_usage=token_usage
    )
