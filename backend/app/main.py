import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    account_actions,
    associations,
    deletions,
    evidence,
    exports,
    identity,
    papers,
    read_models,
    research,
    workflow,
)
from app.core.errors import DomainError
from app.db.session import SessionLocal
from app.responses import ErrorEnvelope, HealthPublic

logger = logging.getLogger("researchos")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
app = FastAPI(
    title="ResearchOS API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    responses={
        status: {"model": ErrorEnvelope, "description": "ResearchOS machine-readable error"}
        for status in (400, 401, 403, 404, 405, 409, 413, 415, 422, 429, 500, 503)
    },
)


@app.middleware("http")
async def request_metadata(request: Request, call_next):
    request.state.request_id = str(uuid4())
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        logger.error(
            json.dumps(
                {
                    "event": "request_failed",
                    "request_id": request.state.request_id,
                    "exception_type": type(error).__name__,
                }
            )
        )
        response = JSONResponse(
            status_code=500,
            content={
                "error": {"code": "INTERNAL_ERROR", "message": "服务暂时无法处理，请稍后重试"},
                "request_id": request.state.request_id,
            },
        )
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    route = request.scope.get("route")
    logger.info(
        json.dumps(
            {
                "event": "request_completed",
                "request_id": request.state.request_id,
                "method": request.method,
                "route": getattr(route, "path", "unknown"),
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            }
        )
    )
    return response


@app.exception_handler(DomainError)
async def domain_error(request, error):
    return JSONResponse(
        status_code=error.status,
        headers={"Retry-After": str(error.details["retry_after_seconds"])}
        if error.code == "RATE_LIMITED"
        else None,
        content={
            "error": {"code": error.code, "message": error.message, "details": error.details},
            "request_id": request.state.request_id,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    # Do not echo raw input (passwords, unpublished text) from Pydantic errors.
    fields = [
        {"field": ".".join(str(value) for value in row["loc"]), "message": row["msg"]}
        for row in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {"code": "VALIDATION_ERROR", "message": "请求字段无效", "details": fields},
            "request_id": request.state.request_id,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request, error):
    code, message = {
        404: ("NOT_FOUND", "请求路径不存在"),
        405: ("METHOD_NOT_ALLOWED", "请求方法不支持"),
    }.get(error.status_code, ("HTTP_ERROR", "请求无法完成"))
    return JSONResponse(
        status_code=error.status_code,
        headers=error.headers,
        content={
            "error": {"code": code, "message": message, "details": None},
            "request_id": request.state.request_id,
        },
    )


@app.exception_handler(IntegrityError)
async def integrity_error(request, error):
    # Driver exceptions may contain SQL parameters/private research text: never log them.
    return JSONResponse(
        status_code=409,
        content={
            "error": {"code": "STATE_CONFLICT", "message": "资料关系或状态发生冲突，请刷新后重试"},
            "request_id": request.state.request_id,
        },
    )


@app.get("/api/health", response_model=HealthPublic)
async def health():
    async with SessionLocal() as db:
        await db.execute(text("SELECT 1"))
    return {"status": "ready", "service": "ResearchOS", "version": app.version}


app.include_router(identity.router, prefix="/api/v1", tags=["identity"])
app.include_router(research.router, prefix="/api/v1", tags=["research"])
app.include_router(workflow.router, prefix="/api/v1", tags=["workflow"])
app.include_router(read_models.router, prefix="/api/v1", tags=["read-models"])
app.include_router(papers.router, prefix="/api/v1", tags=["papers"])
app.include_router(evidence.router, prefix="/api/v1", tags=["evidence"])
app.include_router(exports.router, prefix="/api/v1", tags=["exports"])
app.include_router(associations.router, prefix="/api/v1", tags=["associations"])
app.include_router(deletions.router, prefix="/api/v1", tags=["deletions"])
app.include_router(account_actions.router, prefix="/api/v1", tags=["account-actions"])
