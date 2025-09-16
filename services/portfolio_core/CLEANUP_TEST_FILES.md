# Test Files Cleanup

## Files Renamed to Avoid Pytest Collection:
- `test_imports.py` → `check_imports.py`
- `test_syntax.py` → `check_syntax.py`
- `test_basic.py` → `check_basic.py`

## Reason:
These were standalone import/validation scripts that called `sys.exit()` which terminated pytest.
Pytest was treating them as test files because they started with `test_`.

## To Run Manually:
```bash
python check_imports.py   # Check module imports
python check_syntax.py    # Check syntax and imports
python check_basic.py     # Run basic functionality test
```

## For Pytest:
Now only proper test files in `tests/` directory will be collected by pytest.