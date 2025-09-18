# Parameter Standardization Analysis
**Multi-LLM Microservices Architecture Parameter Inconsistencies**
**Date**: September 2025
**Status**: Comprehensive Analysis & Recommendations

## 🎯 Executive Summary

**Key Finding**: Significant parameter naming inconsistencies exist across services, confirming the hypothesis that different LLMs coding different services introduced varying conventions.

**Impact**: These inconsistencies create:
- Configuration complexity in `commands.json` parameter mapping
- Maintenance overhead and potential bugs
- Developer confusion and reduced code clarity
- Integration friction between services

**Recommendation**: Implement standardized parameter naming conventions across all services.

---

## 📊 **Service-by-Service Parameter Analysis**

### **1. fx Service**
**LLM Characteristics**: Simple, consistent, REST-like patterns

#### Parameters Used:
- **Currency Pairs**: `base`, `quote` (clean, standard)
- **Control**: `pair`, `force` (descriptive)
- **Cache**: `key` (generic)

#### Conventions:
- ✅ Uses standard REST parameter names
- ✅ Consistent uppercase/lowercase handling (`base.upper()`, `quote.upper()`)
- ✅ Clear business domain terminology
- ✅ Follows forex market conventions

#### Strengths:
- Business domain alignment (BASE_QUOTE standard)
- Clear, unambiguous parameter names
- Consistent case handling

---

### **2. market_data Service**
**LLM Characteristics**: Complex, feature-rich, slightly verbose

#### Parameters Used:
- **Symbols**: `symbols`, `symbol` (inconsistent singular/plural)
- **Time**: `period` (clear)
- **User Context**: `user_id`, `first_name`, `last_name`, `username`, `language_code` (verbose but complete)

#### Response Models:
- **Financial Data**: `price`, `price_eur`, `open`, `open_eur`, `currency`, `market`
- **Metadata**: `asset_class` (follows domain standards)
- **Error Handling**: `code`, `message`, `source`, `retriable`, `details`

#### Conventions:
- ✅ Comprehensive user context handling
- ✅ Multi-currency support (`_eur` suffix pattern)
- ⚠️ Inconsistent singular/plural (`symbol` vs `symbols`)
- ✅ Business domain terminology (`asset_class`, not `type`)

#### Strengths:
- Rich context information
- Multi-currency aware
- Comprehensive error details

#### Issues:
- `symbols` (plural) for batch requests vs `symbol` (singular) for single requests

---

### **3. portfolio_core Service**
**LLM Characteristics**: Financial domain expert, precise, business-focused

#### Parameters Used:
- **Financial Amounts**: `amount_eur`, `price_eur`, `fees_eur` (consistent EUR suffix)
- **Quantities**: `qty` (abbreviated)
- **Asset Classification**: `asset_class` (business standard)
- **User Context**: `user_id`, `first_name`, `last_name`, `username`, `language_code`
- **Operations**: `op_id` (operation tracking)
- **Time**: `period` (consistent with market_data)

#### Business Models:
- **Request Models**: `AddPositionRequest`, `CashMutationRequest`, `TradeRequest`
- **Error Codes**: `BAD_INPUT`, `NOT_FOUND`, `INSUFFICIENT`, `CONFLICT`, `INTERNAL`

#### Conventions:
- ✅ Consistent `_eur` suffix for all monetary values
- ✅ Business domain terminology (`asset_class`, `qty`)
- ✅ Operation tracking via `op_id`
- ✅ Financial precision using `Decimal` types
- ✅ Clear business error classifications

#### Strengths:
- Strong financial domain modeling
- Consistent monetary field naming
- Proper business validation

---

### **4. telegram_router Service**
**LLM Characteristics**: Integration-focused, mapping-heavy, UI-aware

#### Parameters Used:
- **Command Mapping**: Complex `args_map` transformations
- **User Context**: Telegram-specific fields (`chat_id`, `message_id`)
- **Mixed Conventions**: Inherits parameter names from target services

#### Command Configuration Examples:
```json
{
  "name": "/price",
  "args_map": {"symbols": "symbols"}  // Direct pass-through
},
{
  "name": "/fx",
  "args_map": {"base": "base", "quote": "quote"}  // Direct pass-through
},
{
  "name": "/add",
  "args_map": {"asset_class": "asset_class", "qty": "qty", "symbol": "symbol"}  // Fixed mapping
}
```

#### Conventions:
- ⚠️ **Inconsistent**: Inherits varying conventions from different services
- ⚠️ **Complex Mapping**: Requires configuration for each parameter mismatch
- ✅ **Flexible**: Can adapt to any backend service
- ⚠️ **Error-Prone**: Manual mapping creates opportunities for mistakes

#### Issues:
- Acts as a "translator" between inconsistent service APIs
- Requires maintenance when any service changes parameter names
- Configuration complexity scales with parameter inconsistencies

---

## 🚨 **Critical Parameter Inconsistencies Found**

### **1. Asset Classification**
- **portfolio_core**: `asset_class` ✅ (business standard)
- **market_data**: `asset_class` ✅ (matches portfolio_core)
- **Legacy/Router**: Sometimes `type` ❌ (generic, ambiguous)

**Impact**: Requires parameter mapping in router configuration
**Recommendation**: Standardize on `asset_class` everywhere

### **2. Currency Amount Naming**
- **portfolio_core**: `amount_eur`, `price_eur`, `fees_eur` ✅ (consistent EUR suffix)
- **market_data**: `price_eur` ✅ (matches portfolio_core for EUR values)
- **fx**: `rate` ❌ (no currency indication)

**Impact**: Unclear which currency amounts represent
**Recommendation**: Adopt `_eur` suffix pattern for all EUR amounts

### **3. Symbol Handling**
- **market_data**: `symbols` (plural) for batch, `symbol` (singular) for single
- **portfolio_core**: `symbol` (always singular)
- **fx**: `pair` (different concept but clear)

**Impact**: API consistency issues
**Recommendation**: Use `symbol` for single, `symbols` for batch consistently

### **4. User Context Fields**
- **portfolio_core**: Required `user_id: int`, optional other fields
- **market_data**: Optional `user_id: Optional[int]`, verbose context
- **telegram_router**: Telegram-specific fields mixed with user context

**Impact**: Different nullability requirements, integration complexity
**Recommendation**: Standardize user context model across services

### **5. Error Response Formats**
- **portfolio_core**: `ErrorCode` enum (`bad_input`, `not_found`, etc.)
- **market_data**: String codes (`BAD_INPUT`, `NOT_FOUND`, etc.)
- **fx**: Simple HTTP errors only

**Impact**: Inconsistent error handling, difficult error mapping
**Recommendation**: Adopt single error code format (prefer UPPER_CASE for API consistency)

---

## 📋 **Standardization Recommendations**

### **Phase 1: Critical Harmonization**

#### **1. Asset Classification Standard**
```json
// ✅ Adopt everywhere
"asset_class": "stock" | "etf" | "crypto"

// ❌ Eliminate
"type": "stock"
```

#### **2. Currency Amount Standard**
```json
// ✅ Adopt pattern for all EUR amounts
"amount_eur": "1500.00"
"price_eur": "150.75"
"fees_eur": "2.50"

// ❌ Avoid ambiguous currency
"amount": "1500.00"  // Which currency?
"price": "150.75"    // Which currency?
```

#### **3. Symbol Handling Standard**
```json
// ✅ Single symbol
"symbol": "AAPL.US"

// ✅ Multiple symbols
"symbols": ["AAPL.US", "MSFT.US", "GOOGL.US"]

// ❌ Avoid mixing
"symbols": "AAPL.US"  // String for single symbol
```

#### **4. User Context Standard**
```typescript
interface UserContext {
  user_id: number;           // Required, consistent type
  first_name?: string;       // Optional, consistent naming
  last_name?: string;        // Optional, consistent naming
  username?: string;         // Optional, consistent naming
  language_code?: string;    // Optional, consistent naming
}
```

#### **5. Error Code Standard**
```json
// ✅ Adopt UPPER_CASE pattern everywhere
{
  "code": "BAD_INPUT" | "NOT_FOUND" | "INSUFFICIENT" | "CONFLICT" | "INTERNAL" | "UPSTREAM_ERROR",
  "message": "Human readable description",
  "source": "service_name",
  "retriable": boolean,
  "details": object | null
}
```

### **Phase 2: Advanced Standardization**

#### **6. Time Period Standard**
```json
// ✅ Consistent across services
"period": "d" | "w" | "m" | "y"
```

#### **7. Quantity Standard**
```json
// ✅ Clear abbreviated form
"qty": "10.5"

// ❌ Avoid verbose
"quantity": "10.5"
```

#### **8. Operation Tracking Standard**
```json
// ✅ Idempotency support
"op_id": "unique-operation-identifier"
```

---

## 🔧 **Implementation Strategy**

### **Phase 1: Backend Service Updates (2-3 weeks)**

#### **Week 1: portfolio_core Alignment**
- [ ] Update error codes to UPPER_CASE format
- [ ] Ensure consistent `asset_class` usage
- [ ] Validate all EUR amounts use `_eur` suffix

#### **Week 2: market_data Alignment**
- [ ] Standardize error codes to UPPER_CASE
- [ ] Fix symbol/symbols parameter consistency
- [ ] Align user context model with portfolio_core

#### **Week 3: fx Service Alignment**
- [ ] Add structured error responses
- [ ] Consider currency indication in rate responses
- [ ] Align with standard error envelope format

### **Phase 2: Integration Layer Updates (1 week)**

#### **telegram_router Simplification**
- [ ] Update `commands.json` with standardized parameter names
- [ ] Simplify parameter mappings (many should become direct pass-through)
- [ ] Remove workaround mappings for legacy parameter names

### **Phase 3: Documentation & Validation (1 week)**

#### **API Documentation**
- [ ] Create unified parameter naming guide
- [ ] Document standard error response formats
- [ ] Update integration examples

#### **Validation**
- [ ] Test all command flows with standardized parameters
- [ ] Verify error handling consistency
- [ ] Validate no breaking changes for existing functionality

---

## 🎯 **Benefits of Standardization**

### **Development Benefits**
- **Reduced Cognitive Load**: Developers know parameter patterns across services
- **Faster Integration**: Less time spent mapping between different conventions
- **Fewer Bugs**: Consistent naming reduces configuration errors
- **Better Maintainability**: Changes in one service predictably affect others

### **Operational Benefits**
- **Clearer Monitoring**: Consistent error codes enable better alerting
- **Easier Debugging**: Standard parameter names across logs
- **Configuration Simplification**: Fewer parameter mappings in router
- **API Consistency**: External consumers see uniform interface

### **Business Benefits**
- **Faster Feature Development**: Less time spent on integration plumbing
- **Higher Code Quality**: Clear, consistent domain modeling
- **Reduced Training Time**: New developers learn patterns once
- **Better Documentation**: Consistent terminology across services

---

## 📝 **Conclusion**

The multi-LLM microservices architecture has indeed introduced parameter naming inconsistencies, as suspected. Each service shows characteristics of different LLM "personalities":

- **fx**: Simple, REST-focused LLM
- **market_data**: Feature-rich, comprehensive LLM
- **portfolio_core**: Business domain expert LLM
- **telegram_router**: Integration-focused LLM

**Primary Issues**:
1. **Asset Classification**: `type` vs `asset_class` confusion
2. **Currency Ambiguity**: Missing `_eur` suffixes in some services
3. **Error Code Formats**: Mixed case conventions
4. **Symbol Handling**: Inconsistent singular/plural usage

**Impact**: Medium-High - Creates integration complexity and maintenance overhead

**Solution**: Systematic parameter standardization following the recommended naming conventions will eliminate these inconsistencies and create a more maintainable architecture.

**Timeline**: 4-5 weeks for complete standardization across all services

**Priority**: High - Should be addressed before Phase 2 development to avoid compounding the technical debt.