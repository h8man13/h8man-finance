"""
CORS middleware configuration.
"""
from typing import Optional, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def add_cors(app: FastAPI, settings) -> None:
    """Add CORS middleware to the app."""
    origins = settings.cors_origin_list()
    
    if not origins:
        return
        
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=["*"],
    )