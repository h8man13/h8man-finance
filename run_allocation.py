import sys
import asyncio
sys.path.append('services/telegram_router')
from app.handlers.portfolio import PortfolioHandler
from app.services.portfolio_service import allocation_table_pages, portfolio_pages_with_fallback
from app.services.formatting_service import FormattingService
from app.ui.loader import load_ui

class DummySession:
    def create_session(self,*args,**kwargs):
        pass
    def clear(self,*args,**kwargs):
        pass
    def get(self,*args,**kwargs):
        return None
    def get_sticky_commands(self):
        return []
    def is_sticky(self,name):
        return False
    def should_clear_session(self,spec,existing):
        return False

class DummyDispatcher:
    async def dispatch(self,*args,**kwargs):
        return {}

async def main():
    ui = load_ui('services/telegram_router/config/ui.yml')
    fmt = FormattingService()
    session = DummySession()
    dispatcher = DummyDispatcher()
    settings = type('S', (), {})()
    snapshot_builder = lambda *args, **kwargs: []
    allocation_builder = lambda ui, *entries: allocation_table_pages(ui, fmt, *entries)
    handler = PortfolioHandler(ui, session, dispatcher, settings,
                               snapshot_builder=snapshot_builder,
                               allocation_builder=allocation_builder,
                               formatting_service=fmt)
    sample_resp = {'data': {
        'current': {'stock_pct': 60, 'etf_pct': 30, 'crypto_pct': 10},
        'target': {'stock_pct': 55, 'etf_pct': 35, 'crypto_pct': 10}
    }}
    result = await handler.handle_allocation_view(resp=sample_resp)
    for page in result:
        print(page.encode('unicode_escape').decode())

asyncio.run(main())
