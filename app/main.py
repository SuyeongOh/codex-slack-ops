from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from redis.asyncio import Redis

from .config import get_settings
from .db import Database
from .exceptions import ApprovalError, ApprovalNotFound, InvalidApprovalTransition
from .locks import MemoryLockManager, RedisLockManager
from .schemas import ApprovalCreateRequest, ApprovalResponse, ExecutionUpdateRequest
from .services.approval_service import ApprovalService
from .services.slack_service import SlackService
from .slack_app import build_slack_app, build_slack_handler, build_socket_mode_handler


logger = logging.getLogger(__name__)
settings = get_settings()


async def _run_expiration_sweeper(app: FastAPI, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            expired_approvals = await app.state.approval_service.expire_pending_requests()
            if expired_approvals:
                logger.info("expired %s stale approvals", len(expired_approvals))
        except Exception:
            logger.exception("expiration sweeper failed")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.expiration_sweep_seconds)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.socket_mode_enabled and not settings.has_socket_mode_token:
        raise RuntimeError("SLACK_APP_TOKEN is required when SLACK_USE_SOCKET_MODE=true")

    if not settings.socket_mode_enabled and settings.has_placeholder_signing_secret:
        logger.warning(
            "SLACK_SIGNING_SECRET is not configured with a real value. "
            "Posting messages will work, but Slack button callbacks will fail verification."
        )

    database = Database(settings.database_url)
    await database.create_schema()

    redis = None
    if settings.redis_url == "memory://":
        lock_manager = MemoryLockManager()
    else:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        lock_manager = RedisLockManager(redis=redis, default_ttl=settings.redis_lock_ttl_seconds)

    slack_service = SlackService(bot_token=settings.slack_bot_token)
    approval_service = ApprovalService(
        settings=settings,
        database=database,
        slack_service=slack_service,
        lock_manager=lock_manager,
    )

    app.state.database = database
    app.state.redis = redis
    app.state.approval_service = approval_service
    app.state.stop_event = asyncio.Event()
    app.state.sweeper_task = asyncio.create_task(_run_expiration_sweeper(app, app.state.stop_event))
    app.state.slack_app = build_slack_app(
        bot_token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
        approval_service=approval_service,
        socket_mode=settings.socket_mode_enabled,
    )
    app.state.slack_handler = None
    app.state.socket_mode_handler = None
    if settings.socket_mode_enabled:
        app.state.socket_mode_handler = build_socket_mode_handler(
            slack_app=app.state.slack_app,
            app_token=settings.slack_app_token,
        )
        await app.state.socket_mode_handler.connect_async()
        logger.info("Slack Socket Mode connected")
    else:
        app.state.slack_handler = build_slack_handler(slack_app=app.state.slack_app)

    yield

    app.state.stop_event.set()
    app.state.sweeper_task.cancel()
    try:
        await app.state.sweeper_task
    except asyncio.CancelledError:
        pass
    if app.state.socket_mode_handler is not None:
        await app.state.socket_mode_handler.close_async()
    if redis is not None:
        await redis.aclose()
    await database.close()


app = FastAPI(title="Codex Slack Approvals", lifespan=lifespan)


def _check_internal_token(x_internal_token: str) -> None:
    if x_internal_token != settings.internal_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


def _require_http_slack_handler() -> None:
    if app.state.slack_handler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Slack HTTP callbacks are disabled while Socket Mode is enabled",
        )


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/approvals", response_model=ApprovalResponse)
async def create_approval(
    payload: ApprovalCreateRequest,
    x_internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> ApprovalResponse:
    _check_internal_token(x_internal_token)
    try:
        approval = await app.state.approval_service.create_request(payload)
    except ApprovalError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return ApprovalResponse.model_validate(approval)


@app.get("/api/v1/approvals/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    x_internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> ApprovalResponse:
    _check_internal_token(x_internal_token)
    try:
        approval = await app.state.approval_service.get_request(approval_id)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ApprovalResponse.model_validate(approval)


@app.post("/api/v1/approvals/{approval_id}/execution", response_model=ApprovalResponse)
async def update_execution_status(
    approval_id: str,
    payload: ExecutionUpdateRequest,
    x_internal_token: str = Header(default="", alias="X-Internal-Token"),
) -> ApprovalResponse:
    _check_internal_token(x_internal_token)
    try:
        approval = await app.state.approval_service.record_execution_update(approval_id, payload)
    except ApprovalNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidApprovalTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ApprovalResponse.model_validate(approval)


@app.post("/slack/events")
async def slack_events(request: Request) -> Response:
    _require_http_slack_handler()
    return await app.state.slack_handler.handle(request)


@app.post("/slack/interactions")
async def slack_interactions(request: Request) -> Response:
    _require_http_slack_handler()
    return await app.state.slack_handler.handle(request)
