#!/usr/bin/env python3
"""
Validation script for portfolio_core tests and architecture.
"""
import os
import sys
import traceback

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(__file__))

def validate_imports():
    """Test that all modules can be imported successfully."""
    print("🔍 Validating imports...")

    modules_to_test = [
        ("app.settings", "Settings configuration"),
        ("app.models", "Data models"),
        ("app.db", "Database layer"),
        ("app.cors", "CORS middleware"),
        ("app.services.portfolio", "Portfolio service"),
        ("app.services.analytics", "Analytics service"),
        ("app.services.data_service", "Data service"),
        ("app.adapters.fx_client", "FX adapter"),
        ("app.adapters.market_data_client", "Market data adapter"),
        ("app.adapters", "Adapters package"),
        ("app.api", "API routes"),
        ("app.main", "Main application")
    ]

    success_count = 0
    for module_name, description in modules_to_test:
        try:
            __import__(module_name)
            print(f"  ✅ {module_name} - {description}")
            success_count += 1
        except Exception as e:
            print(f"  ❌ {module_name} - {description}: {e}")

    print(f"\n📊 Import validation: {success_count}/{len(modules_to_test)} modules successful")
    return success_count == len(modules_to_test)


def validate_test_structure():
    """Validate test file structure and basic syntax."""
    print("\n🔍 Validating test structure...")

    test_files = [
        "tests/conftest.py",
        "tests/test_command_endpoints.py",
        "tests/test_analytics.py",
        "tests/test_api.py",
        "tests/test_adapters.py",
        "tests/test_data_service.py",
        "tests/test_admin_endpoints.py",
        "tests/test_integration.py"
    ]

    success_count = 0
    for test_file in test_files:
        file_path = os.path.join(os.path.dirname(__file__), test_file)
        try:
            if os.path.exists(file_path):
                # Try to compile the file to check for syntax errors
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    compile(content, file_path, 'exec')
                print(f"  ✅ {test_file} - syntax OK")
                success_count += 1
            else:
                print(f"  ⚠️  {test_file} - file not found")
        except SyntaxError as e:
            print(f"  ❌ {test_file} - syntax error: {e}")
        except Exception as e:
            print(f"  ❌ {test_file} - error: {e}")

    print(f"\n📊 Test structure validation: {success_count}/{len(test_files)} files valid")
    return success_count >= len(test_files) - 1  # Allow one missing file


def validate_architecture_components():
    """Validate that key architecture components are properly implemented."""
    print("\n🔍 Validating architecture components...")

    try:
        # Import and check key classes
        from app.adapters.fx_client import FxClient
        from app.adapters.market_data_client import MarketDataClient
        from app.services.data_service import DataService
        from app.services.analytics import AnalyticsService
        from app.services.portfolio import PortfolioService

        print("  ✅ FxClient adapter class")
        print("  ✅ MarketDataClient adapter class")
        print("  ✅ DataService class")
        print("  ✅ AnalyticsService class")
        print("  ✅ PortfolioService class")

        # Check for key methods
        fx_client = FxClient()
        md_client = MarketDataClient()

        # Check FX client methods
        assert hasattr(fx_client, 'get_rate'), "FxClient missing get_rate method"
        assert hasattr(fx_client, 'get_rates'), "FxClient missing get_rates method"
        assert hasattr(fx_client, 'health_check'), "FxClient missing health_check method"
        print("  ✅ FxClient has required methods")

        # Check market data client methods
        assert hasattr(md_client, 'get_quote'), "MarketDataClient missing get_quote method"
        assert hasattr(md_client, 'get_quotes'), "MarketDataClient missing get_quotes method"
        assert hasattr(md_client, 'get_symbol_meta'), "MarketDataClient missing get_symbol_meta method"
        assert hasattr(md_client, 'health_check'), "MarketDataClient missing health_check method"
        print("  ✅ MarketDataClient has required methods")

        # Check analytics service for admin endpoint method
        from app.models import UserContext
        user_context = UserContext(user_id=1, first_name="Test", last_name="User")

        # We can't fully instantiate without DB, but we can check method exists
        assert hasattr(AnalyticsService, 'run_daily_snapshot'), "AnalyticsService missing run_daily_snapshot method"
        print("  ✅ AnalyticsService has run_daily_snapshot method")

        print("\n📊 Architecture validation: All components present")
        return True

    except Exception as e:
        print(f"  ❌ Architecture validation failed: {e}")
        return False


def validate_configuration():
    """Validate configuration and requirements."""
    print("\n🔍 Validating configuration...")

    try:
        from app.settings import settings

        # Check key settings exist
        required_settings = [
            'APP_NAME', 'ENV', 'HOST', 'PORT',
            'MARKET_DATA_BASE_URL', 'FX_BASE_URL',
            'ADAPTER_TIMEOUT_SEC', 'ADAPTER_RETRY_COUNT',
            'FX_CACHE_TTL_SEC', 'QUOTES_CACHE_TTL_SEC'
        ]

        for setting in required_settings:
            assert hasattr(settings, setting), f"Missing setting: {setting}"

        print("  ✅ All required settings present")

        # Check requirements.txt
        req_file = os.path.join(os.path.dirname(__file__), 'requirements.txt')
        if os.path.exists(req_file):
            with open(req_file, 'r') as f:
                requirements = f.read()

            required_packages = [
                'fastapi', 'uvicorn', 'httpx', 'aiosqlite',
                'pydantic', 'pytest', 'pytest-asyncio'
            ]

            for package in required_packages:
                assert package in requirements, f"Missing package: {package}"

            print("  ✅ All required packages in requirements.txt")

        print("\n📊 Configuration validation: Complete")
        return True

    except Exception as e:
        print(f"  ❌ Configuration validation failed: {e}")
        return False


def validate_admin_endpoints():
    """Validate admin endpoints exist and are properly structured."""
    print("\n🔍 Validating admin endpoints...")

    try:
        from app.api import router
        from fastapi.routing import APIRoute

        # Get all routes
        routes = [route for route in router.routes if isinstance(route, APIRoute)]
        route_paths = [route.path for route in routes]

        # Check admin endpoints exist
        admin_endpoints = [
            '/admin/snapshots/run',
            '/admin/snapshots/status',
            '/admin/snapshots/cleanup',
            '/admin/health'
        ]

        for endpoint in admin_endpoints:
            assert endpoint in route_paths, f"Missing admin endpoint: {endpoint}"
            print(f"  ✅ {endpoint}")

        print("\n📊 Admin endpoints validation: All endpoints present")
        return True

    except Exception as e:
        print(f"  ❌ Admin endpoints validation failed: {e}")
        return False


def main():
    """Run all validations."""
    print("🚀 Portfolio Core Test Validation")
    print("=" * 50)

    validations = [
        validate_imports,
        validate_test_structure,
        validate_architecture_components,
        validate_configuration,
        validate_admin_endpoints
    ]

    results = []
    for validation in validations:
        try:
            result = validation()
            results.append(result)
        except Exception as e:
            print(f"❌ Validation failed with exception: {e}")
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 50)
    print("📋 VALIDATION SUMMARY")
    print("=" * 50)

    validation_names = [
        "Import validation",
        "Test structure validation",
        "Architecture components validation",
        "Configuration validation",
        "Admin endpoints validation"
    ]

    passed = sum(results)
    total = len(results)

    for i, (name, result) in enumerate(zip(validation_names, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{i+1}. {name}: {status}")

    print(f"\n🎯 Overall Result: {passed}/{total} validations passed")

    if passed == total:
        print("\n🎉 SUCCESS: All validations passed!")
        print("The portfolio_core service is ready for testing.")
        return True
    else:
        print(f"\n⚠️  WARNING: {total - passed} validations failed.")
        print("Some issues need to be resolved before full testing.")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)