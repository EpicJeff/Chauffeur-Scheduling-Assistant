import asyncio
from fastapi import Request
from main import dashboard, config

async def test():
    req = Request(scope={'type': 'http', 'method': 'GET', 'path': '/dashboard', 'headers': []})
    try:
        res = dashboard(req)
        print('Success:', res)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(test())
