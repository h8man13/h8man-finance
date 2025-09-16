# Telegram Integration Fixes

## 🔍 Problem Analysis

The Telegram commands were returning "✅ Done" (generic success fallback) instead of proper responses, indicating communication issues between telegram_router and portfolio_core services.

## 🐛 Issues Found and Fixed

### 1. **Endpoint Path Mismatches**

#### Issue
- `commands.json` was mapping `/buy` → `/tx/buy`
- `commands.json` was mapping `/sell` → `/tx/sell`
- But portfolio_core has endpoints at `/buy` and `/sell`

#### Fix
- **File**: `services/telegram_router/config/commands.json`
- Changed `/tx/buy` → `/buy`
- Changed `/tx/sell` → `/sell`

#### Code Changes
```json
// Before
"path": "/tx/buy"
"path": "/tx/sell"

// After
"path": "/buy"
"path": "/sell"
```

### 2. **Portfolio Core Connector Path Issues**

#### Issue
- `PortfolioCoreClient` was using hardcoded old paths `/tx/buy` and `/tx/sell`

#### Fix
- **File**: `services/telegram_router/app/connectors/portfolio_core.py`
- Updated URLs to match actual endpoints

#### Code Changes
```python
# Before
url = f"{self.base}/tx/buy"
url = f"{self.base}/tx/sell"

# After
url = f"{self.base}/buy"
url = f"{self.base}/sell"
```

### 3. **Dispatcher Path Hardcoding**

#### Issue
- `Dispatcher` had hardcoded path checks for `/tx/buy` and `/tx/sell`

#### Fix
- **File**: `services/telegram_router/app/core/dispatcher.py`
- Updated path matching logic

#### Code Changes
```python
# Before
if path == "/tx/buy" and method == "POST":
if path == "/tx/sell" and method == "POST":

# After
if path == "/buy" and method == "POST":
if path == "/sell" and method == "POST":
```

### 4. **Parameter Name Mismatch**

#### Issue
- `/tx` command was sending parameter `n` but portfolio_core expects `limit`

#### Fix
- **File**: `services/telegram_router/config/commands.json`
- Updated args_map to use correct parameter name

#### Code Changes
```json
// Before
"args_map": {"n": "n"}

// After
"args_map": {"n": "limit"}
```

### 5. **Allocation Edit Parameter Structure**

#### Issue
- `/allocation_edit` was sending `weights` array but portfolio_core expects individual parameters `etf_pct`, `stock_pct`, `crypto_pct`

#### Fix
- **File**: `services/telegram_router/config/commands.json`
- Changed from array-based to individual parameter approach

#### Code Changes
```json
// Before
"args_schema": [
  {"name": "weights", "type": "percent", "required": true, "many": true, "min_items": 1, "max_items": 3}
],
"args_map": {"weights": "weights"}

// After
"args_schema": [
  {"name": "etf_pct", "type": "integer", "required": true, "min": 0, "max": 100},
  {"name": "stock_pct", "type": "integer", "required": true, "min": 0, "max": 100},
  {"name": "crypto_pct", "type": "integer", "required": true, "min": 0, "max": 100}
],
"args_map": {"etf_pct": "etf_pct", "stock_pct": "stock_pct", "crypto_pct": "crypto_pct"}
```

### 6. **Missing User Context**

#### Issue
- User context (user_id, first_name, last_name, username, language_code) was not being passed to portfolio_core
- portfolio_core endpoints require user context for authentication and user identification

#### Fix
- **Multiple Files**:
  - `services/telegram_router/app/models.py` - Extended TelegramUser model
  - `services/telegram_router/app/app.py` - Extract user context from Telegram messages
  - `services/telegram_router/app/core/dispatcher.py` - Pass user context to portfolio_core

#### Code Changes
```python
# models.py - Extended TelegramUser
class TelegramUser(BaseModel):
    id: int
    is_bot: Optional[bool] = False
    first_name: Optional[str] = None      # Added
    last_name: Optional[str] = None       # Added
    username: Optional[str] = None
    language_code: Optional[str] = None   # Added

# app.py - Extract user context
user_context = {
    "user_id": msg.from_.id,
    "first_name": getattr(msg.from_, 'first_name', ''),
    "last_name": getattr(msg.from_, 'last_name', ''),
    "username": msg.from_.username,
    "language_code": getattr(msg.from_, 'language_code', 'en')
}

# dispatcher.py - Add user context to portfolio_core calls
if service == "portfolio_core" and user_context:
    payload.update(user_context)
```

### 7. **UI Configuration Updates**

#### Issue
- Help text and prompts referenced old parameter formats

#### Fix
- **File**: `services/telegram_router/config/ui.yml`
- Updated help text and prompts to match new parameter structure

#### Code Changes
```yaml
# Before
- "/allocation_edit [etf|stocks|crypto] - adjust target allocations"
allocation_edit_prompt:
  blocks:
    - header: "Use: [etf,stocks,crypto]"

# After
- "/allocation_edit [etf_pct] [stock_pct] [crypto_pct] - adjust target allocations"
allocation_edit_prompt:
  blocks:
    - header: "Use: [etf_pct] [stock_pct] [crypto_pct]"
```

## 📋 Files Modified

### Telegram Router
1. `config/commands.json` - Fixed endpoint paths and parameter mappings
2. `config/ui.yml` - Updated help text and prompts
3. `app/models.py` - Extended TelegramUser model
4. `app/app.py` - Added user context extraction and passing
5. `app/core/dispatcher.py` - Added user context handling
6. `app/connectors/portfolio_core.py` - Fixed endpoint URLs

### Portfolio Core
7. `tests/test_telegram_integration.py` - Added integration tests

## ✅ Validation

Created comprehensive integration tests to verify:
- ✅ All endpoints use correct paths (`/buy`, `/sell`, not `/tx/buy`, `/tx/sell`)
- ✅ Parameter mappings work correctly (`limit` not `n`)
- ✅ User context is properly passed and processed
- ✅ Allocation edit uses individual parameters
- ✅ Full workflow simulation succeeds

## 🚀 Expected Result

After these fixes, Telegram commands should now:
1. ✅ Return proper portfolio data instead of "✅ Done"
2. ✅ Correctly identify users and maintain per-user portfolios
3. ✅ Process all parameters correctly
4. ✅ Execute buy/sell transactions properly
5. ✅ Handle allocation management correctly

## 🔧 Deployment Notes

1. **Restart both services** after applying changes
2. **Verify configuration** is properly loaded
3. **Test with actual Telegram commands** to confirm resolution
4. **Monitor logs** for any remaining communication issues

## 🧪 Test Commands

Try these Telegram commands to verify the fixes:
```
/portfolio
/cash
/allocation
/buy 1 AAPL.US 150
/tx 5
/allocation_edit 60 30 10
```

All commands should now return proper formatted responses instead of the generic "✅ Done" message.