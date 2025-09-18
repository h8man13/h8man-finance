from pathlib import Path
path = Path('services/telegram_router/app/app.py')
text = path.read_text(encoding='utf-8')
old = "        base = (values.get(\"base\", \"\") or \"\").upper()\n        quote = (values.get(\"quote\", \"\") or \"\").upper()\n        # Invert if user requested EUR/USD but upstream pair is USD_EUR\n"
new = "        base = (values.get(\"base\", \"\") or data.get(\"base\") or \"\").upper()\n        quote = (values.get(\"quote\", \"\") or data.get(\"quote\") or \"\").upper()\n        if (not base or not quote) and pair:\n            parts = pair.replace(\"-\", \"_\").split(\"_\")\n            if len(parts) == 2:\n                base = base or parts[0]\n                quote = quote or parts[1]\n        # Invert if user requested EUR/USD but upstream pair is USD_EUR\n"
if text.count(old) != 1:
    raise SystemExit('original fx snippet not found uniquely')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
