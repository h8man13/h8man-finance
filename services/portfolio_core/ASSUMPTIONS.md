# Portfolio Core - Assumptions and Open Questions

## Current Implementation Assumptions

### Service Boundaries
- **ASSUMPTION**: Portfolio_core should NOT directly call market_data or fx services
- **RATIONALE**: Maintains clean service boundaries as specified
- **IMPACT**: Telegram_router must provide pre-converted EUR amounts and metadata

### Database Schema
- **ASSUMPTION**: Positions table uses (user_id, symbol) as PRIMARY KEY instead of auto-increment ID
- **RATIONALE**: Matches the specification exactly
- **IMPACT**: Simplified position lookups but requires schema migration

### Currency Handling
- **ASSUMPTION**: All stored values are in EUR equivalents calculated at transaction time
- **RATIONALE**: Avoids need for real-time FX conversion in portfolio calculations
- **IMPACT**: Historical FX rates are "frozen" at transaction time

### Time-Weighted Return Calculation
- **ASSUMPTION**: Using Europe/Berlin timezone for all date calculations
- **RATIONALE**: Specified in requirements
- **IMPACT**: All bucket boundaries and daily cutoffs use Berlin time

### Market Data Dependencies
- **ASSUMPTION**: Portfolio_core uses stored position costs as fallback for current values
- **RATIONALE**: Removed direct market_data dependencies
- **IMPACT**: Portfolio snapshots may not reflect real-time market values

### Benchmarks
- **ASSUMPTION**: Benchmarks (S&P 500, Gold) should be provided by telegram_router
- **RATIONALE**: Portfolio_core should not fetch external data
- **IMPACT**: Portfolio analytics may not include benchmark data

## Open Questions

### 1. Real-time vs Stored Values
**QUESTION**: Should portfolio snapshots use real-time market prices or stored position costs?
- **CURRENT**: Using stored average costs as fallback
- **IMPLICATIONS**: Snapshots may not reflect current market value
- **RECOMMENDATION**: Telegram_router should provide current prices when calling portfolio_core

### 2. Transaction Flow Dependencies
**QUESTION**: How should buy/sell transactions get current market prices?
- **CURRENT**: Hardcoded FX rate fallback (0.9 USD->EUR)
- **IMPLICATIONS**: Inaccurate currency conversion
- **RECOMMENDATION**: Telegram_router should fetch price and FX rate, then call portfolio_core with EUR amounts

### 3. Snapshot Maintenance
**QUESTION**: How should the daily snapshot maintenance be triggered?
- **CURRENT**: `/snapshots/run` endpoint exists but no scheduler
- **IMPLICATIONS**: No automated daily snapshots for TWR calculation
- **RECOMMENDATION**: External cron job or n8n workflow to call endpoint daily

### 4. Symbol Metadata
**QUESTION**: How should portfolio_core get symbol metadata (market, asset_class, currency)?
- **CURRENT**: Using hardcoded defaults in portfolio.py:166-170
- **IMPLICATIONS**: Incorrect market/asset_class assignments
- **RECOMMENDATION**: Telegram_router should call market_data `/meta` endpoint and provide to portfolio_core

### 5. Error Handling
**QUESTION**: How should portfolio_core handle missing external data?
- **CURRENT**: Using fallback values and continuing
- **IMPLICATIONS**: Silent failures may cause incorrect calculations
- **RECOMMENDATION**: Return specific error codes for missing data requirements

### 6. Performance Analytics
**QUESTION**: Should portfolio_core calculate performance without real-time prices?
- **CURRENT**: Limited analytics using stored costs
- **IMPLICATIONS**: Performance calculations may be inaccurate
- **RECOMMENDATION**: Portfolio analytics should be fed by telegram_router with fresh market data

### 7. Multi-User Support
**QUESTION**: How should portfolio_core handle user authentication?
- **CURRENT**: Accepts user_id parameter but no validation
- **IMPLICATIONS**: No security validation of user access
- **RECOMMENDATION**: Use shared secret or JWT tokens for service-to-service auth

### 8. Database Migration
**QUESTION**: How should existing data be migrated to new schema?
- **CURRENT**: Migration logic in db.py:110-155 but may fail
- **IMPLICATIONS**: Data loss if migration fails
- **RECOMMENDATION**: Test migration thoroughly with production data backup

## Required Clarifications

### Immediate Actions Needed:

1. **Service Communication Pattern**: Confirm that telegram_router should provide all external data (prices, FX rates, metadata) to portfolio_core

2. **Snapshot Schedule**: Define how daily snapshots should be triggered for TWR calculations

3. **Real-time Data**: Clarify whether portfolio views should use real-time or stored position costs

4. **Error Boundaries**: Define error handling when telegram_router doesn't provide required data

5. **Testing Strategy**: Confirm test approach for service integration without external dependencies

### Architecture Decisions Required:

1. **Data Flow**: `telegram_router -> [market_data + fx] -> portfolio_core` vs other patterns

2. **State Management**: Should portfolio_core store any external data (quotes, FX rates) or only portfolio state?

3. **Caching Strategy**: Should portfolio_core cache any computed values or recalculate on each request?

4. **Batch Operations**: Should portfolio_core support bulk position updates for better performance?

## Recommendations for Next Steps

1. **Clarify service communication patterns** before proceeding with telegram_router integration
2. **Define error handling contracts** between services
3. **Implement proper authentication** between services
4. **Set up snapshot maintenance scheduling**
5. **Test integration flows** with mock data to validate assumptions