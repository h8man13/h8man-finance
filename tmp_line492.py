from pathlib import Path
lines = Path('services/telegram_router/app/app.py').read_text(encoding='utf-8').splitlines()
print(f"Line 492: {lines[491]!r}")
print(f"Codes: {[ord(c) for c in lines[491][:5]]}")
