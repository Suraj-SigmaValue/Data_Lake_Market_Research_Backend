import sys
import os

# Ensure the backend directory is on sys.path
_backend_dir = os.path.dirname(os.path.abspath(__file__))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from core.config import *  # loads .env & environment
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import analyze_router, listings_router, places_router

app = FastAPI(title="Data Lake Market Research API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(analyze_router)
app.include_router(listings_router)
app.include_router(places_router)

@app.get("/")
def read_root():
    return {"message": "Data Lake Market Research API (FastAPI) is running."}
