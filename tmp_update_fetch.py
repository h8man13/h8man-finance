from pathlib import Path
path = Path('services/portfolio_core/app/clients.py')
lines = path.read_text(encoding='utf-8').splitlines()
for idx, line in enumerate(lines):
    if line.strip() == 'quote = Quote(symbol, price_eur, currency, market, freshness)':
        indent = line[:len(line) - len(line.lstrip())]
        entry_line = f"{indent}entry = QuoteCacheEntry(quote=quote, expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._quotes_ttl))"
        cache_line = f"{indent}self._quote_cache[symbol] = entry"
        quote_line = f"{indent}quotes[symbol] = quote"
        extra_lines = [
            f"{indent}for req in symbols:",
            f"{indent}    req_norm = req.upper()",
            f"{indent}    if req_norm != symbol and req_norm.startswith(f\"{symbol}.\"):",
            f"{indent}        self._quote_cache[req_norm] = entry",
            f"{indent}        quotes[req_norm] = quote",
        ]
        lines[idx] = f"{indent}quote = Quote(symbol, price_eur, currency, market, freshness)"
        lines[idx + 1:idx + 3] = [entry_line, cache_line, quote_line, *extra_lines]
        break
else:
    raise SystemExit('target line not found')
path.write_text('\\n'.join(lines) + '\\n', encoding='utf-8')
