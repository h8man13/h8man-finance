import respx
from httpx import Response
with respx.mock:
    route = respx.get("http://example.com").mock(return_value=Response(200))
    import httpx
    httpx.get("http://example.com")
    print('call_count first', route.call_count)
    route.calls.reset()
    print('call_count after reset', route.call_count)
    print('route.called after reset', route.called)
