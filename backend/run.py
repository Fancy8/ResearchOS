"""Cross-platform ASGI launcher with a psycopg-compatible Windows event loop."""
import asyncio
import sys
import uvicorn


if __name__ == "__main__":
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=58000, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    if sys.platform == "win32":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())
