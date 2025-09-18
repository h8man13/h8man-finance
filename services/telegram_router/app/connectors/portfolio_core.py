from __future__ import annotations

from ..settings import get_settings
from .http import HTTPClient


class PortfolioCoreClient:
    def __init__(self, http: HTTPClient):
        self.http = http
        self.base = get_settings().PORTFOLIO_CORE_URL.rstrip("/")