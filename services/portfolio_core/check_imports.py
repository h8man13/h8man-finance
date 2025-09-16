#!/usr/bin/env python3
"""
Import validation script - renamed to avoid pytest collection.
Run manually with: python check_imports.py
"""
import sys
import os

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(__file__))

# Test each module individually
modules_to_test = [
    "app.settings",
    "app.models",
    "app.db",
    "app.cors",
    "app.services.portfolio",
    "app.services.analytics",
    "app.services.data_service",
    "app.adapters.fx_client",
    "app.adapters.market_data_client",
    "app.adapters",
    "app.api",
    "app.main"
]

def main():
    errors = []

    for module_name in modules_to_test:
        try:
            __import__(module_name)
            print(f"✓ {module_name}")
        except Exception as e:
            print(f"✗ {module_name}: {e}")
            errors.append((module_name, str(e)))

    if errors:
        print(f"\nFound {len(errors)} import errors:")
        for module, error in errors:
            print(f"  {module}: {error}")
        return 1
    else:
        print(f"\nAll {len(modules_to_test)} modules imported successfully!")
        return 0

if __name__ == "__main__":
    sys.exit(main())