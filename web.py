"""
NodeScope - Local Node Inspection Interface
FastAPI backend with SSE progress and REST API
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routers.api import router as api_router
from routers.views import router as views_router

from contextlib import asynccontextmanager
from state import state
from core.local_access import LocalAccessMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    print("[Web] Shutting down, cleaning up resources...")
    state.is_running = False
    if state.task is not None and not state.task.done():
        await state.task
    await state.checker.stop()

app = FastAPI(title="NodeScope", version="0.1.0", lifespan=lifespan)
app.add_middleware(LocalAccessMiddleware)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    # Pydantic's default error details include input values, possibly YAML/keys.
    return JSONResponse({"detail": "请求格式无效，请检查字段和数据长度"}, status_code=422)

# Mount supporting static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Ensure exports directory
exports_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")
os.makedirs(exports_dir, exist_ok=True)
app.mount("/exports", StaticFiles(directory=exports_dir), name="exports")

# Include Routers
app.include_router(views_router)
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)
