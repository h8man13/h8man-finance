#!/usr/bin/env python3
"""
Basic test to verify the application works without pytest.
Run manually with: python check_basic.py
"""
import asyncio
import tempfile
import os
import sys

# Add the app to the path
sys.path.insert(0, os.path.dirname(__file__))

async def test_basic_functionality():
    """Test basic functionality without external dependencies."""
    print("Starting basic functionality test...")

    try:
        # Import key modules
        from app.db import init_db, open_db
        from app.models import UserContext
        from app.services.portfolio import PortfolioService
        from app.services.analytics import AnalyticsService
        print("✓ All imports successful")

        # Create temporary database
        fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)

        try:
            # Initialize database
            await init_db(db_path)
            print("✓ Database initialized")

            # Open database connection
            db = await open_db(db_path)
            print("✓ Database connection opened")

            # Create user context
            user = UserContext(
                user_id=12345,
                first_name="Test",
                last_name="User",
                username="testuser",
                language_code="en"
            )
            print("✓ User context created")

            # Create services
            portfolio_service = PortfolioService(db, user)
            analytics_service = AnalyticsService(db, user)
            print("✓ Services created")

            # Test basic portfolio operations
            portfolio = await portfolio_service.get_portfolio_snapshot()
            print(f"✓ Portfolio snapshot: {len(portfolio)} positions")

            cash_balance = await portfolio_service.get_cash_balance()
            print(f"✓ Cash balance: {cash_balance}")

            # Test analytics
            snapshot = await analytics_service.get_portfolio_snapshot("d")
            print(f"✓ Analytics snapshot: {list(snapshot.keys())}")

            # Close database
            await db.close()
            print("✓ Database closed")

        finally:
            # Clean up
            if os.path.exists(db_path):
                os.unlink(db_path)

        print("\n✅ All basic tests passed!")
        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    result = asyncio.run(test_basic_functionality())
    return 0 if result else 1

if __name__ == "__main__":
    sys.exit(main())