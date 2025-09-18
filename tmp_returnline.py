from pathlib import Path
lines = Path('services/telegram_router/app/app.py').read_text(encoding='utf-8').splitlines()
for idx, line in enumerate(lines):
    if line.strip() == 'return [text]':
        print(f"Return line index: {idx}, repr: {line!r}")
        break
