from pathlib import Path
content = Path('services/telegram_router/app/app.py').read_bytes()
pos = content.find(b'if spec.name == "/fx":')
print(content[pos:pos+60])
