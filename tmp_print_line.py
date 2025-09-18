from pathlib import Path
lines = Path('services/telegram_router/app/app.py').read_text(encoding='utf-8').splitlines()
for idx, line in enumerate(lines):
    if 'footnotes_common_str' in line and 'text =' in line:
        print(f"Line {idx+1}: {line!r}")
