import respx
from httpx import Response
with respx.mock:
    route = respx.get("http://example.com").mock(return_value=Response(200))
    import httpx
    httpx.get("http://example.com")
    print('calls before', list(route.calls))
    route.calls.reset()
    print('calls after reset', list(route.calls))
PY
