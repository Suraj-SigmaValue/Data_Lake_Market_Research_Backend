import asyncio
from fastapi import APIRouter
from data.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    TrendResponse,
    AppreciationResponse,
    FinalAnalysisRequest,
    FinalAnalysisResponse,
)
from orchestration.analysis_flow import (
    run_openai_analysis,
    run_bedrock_analysis,
    run_openai_trend_analysis,
    run_bedrock_trend_analysis,
    run_openai_appreciation_analysis,
    run_bedrock_appreciation_analysis,
    run_openai_final_analysis,
    run_bedrock_final_analysis,
)

router = APIRouter()

@router.post("/analyze", response_model=AnalyzeResponse)
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

@router.post("/trend", response_model=TrendResponse)
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

@router.post("/appreciation", response_model=AppreciationResponse)
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

@router.post("/final-analysis", response_model=FinalAnalysisResponse)
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
