#!/usr/bin/env python3
"""
Quick syntax check for the application.
Run manually with: python check_syntax.py
"""
import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

def main():
    try:
        # Try to import key modules
        print("Testing imports...")

        from app.settings import settings
        print("✓ settings imported")

        from app.models import UserContext
        print("✓ models imported")

        from app.db import init_db, open_db
        print("✓ db imported")

        from app.services.portfolio import PortfolioService
        print("✓ portfolio service imported")

        from app.services.analytics import AnalyticsService
        print("✓ analytics service imported")

        from app.services.data_service import DataService
        print("✓ data service imported")

        from app.adapters import fx_client, market_data_client
        print("✓ adapters imported")

        from app.api import router
        print("✓ api router imported")

        from app.main import app
        print("✓ main app imported")

        print("\nAll imports successful! ✓")
        return 0

    except Exception as e:
        print(f"\nImport error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())