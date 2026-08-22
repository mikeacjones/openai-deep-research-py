"""Combined HTTP API, browser UI, and Temporal worker runtime."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import time
import uuid
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote

from aiohttp import web
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from config import TemporalSettings, temporal_client
from worker import create_worker
from workflows.deep_research_workflow import DeepResearchWorkflow

LOGGER = logging.getLogger(__name__)
WORKFLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")


class ApiError(Exception):
    """A user-facing HTTP error."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class HourlyRateLimiter:
    """Small per-user guardrail for paid research starts."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._starts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        starts = self._starts[key]
        while starts and starts[0] <= now - 3600:
            starts.popleft()
        if len(starts) >= self.limit:
            return False
        starts.append(now)
        return True


def temporal_ui_url(settings: TemporalSettings, workflow_id: str) -> str:
    namespace = quote(settings.namespace, safe="")
    workflow = quote(workflow_id, safe="")
    if "localhost" in settings.address or "127.0.0.1" in settings.address:
        return f"http://localhost:8233/namespaces/{namespace}/workflows/{workflow}"
    return f"https://cloud.temporal.io/namespaces/{namespace}/workflows/{workflow}"


def _workflow_id(request: web.Request) -> str:
    workflow_id = request.match_info["workflow_id"]
    if not WORKFLOW_ID_PATTERN.fullmatch(workflow_id):
        raise ApiError(400, "workflow_id contains invalid characters")
    return workflow_id


def _status_name(status: WorkflowExecutionStatus | None) -> str:
    if status in {
        WorkflowExecutionStatus.RUNNING,
        WorkflowExecutionStatus.CONTINUED_AS_NEW,
        None,
    }:
        return "researching"
    if status == WorkflowExecutionStatus.COMPLETED:
        return "completed"
    if status == WorkflowExecutionStatus.CANCELED:
        return "cancelled"
    return status.name.lower() if status else "researching"


@web.middleware
async def error_middleware(
    request: web.Request, handler: web.RequestHandler
) -> web.StreamResponse:
    try:
        return await handler(request)
    except ApiError as error:
        return web.json_response({"detail": error.detail}, status=error.status)
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return web.json_response(
                {"detail": "Research workflow was not found"}, status=404
            )
        LOGGER.exception("Temporal RPC failed")
        return web.json_response(
            {"detail": "Temporal is temporarily unavailable"}, status=503
        )
    except web.HTTPException:
        raise
    except Exception:
        LOGGER.exception("Unhandled API request failure")
        return web.json_response(
            {"detail": "The request could not be completed"}, status=500
        )


def create_web_app(
    client: Client,
    settings: TemporalSettings,
    *,
    ui_root: Path | None = None,
    starts_per_hour: int | None = None,
) -> web.Application:
    """Create the HTTP surface without starting network listeners."""

    root = ui_root or Path(__file__).with_name("ui")
    configured_limit = (
        starts_per_hour
        if starts_per_hour is not None
        else int(os.environ.get("RESEARCH_STARTS_PER_HOUR", "5"))
    )
    if configured_limit < 1:
        raise ValueError("RESEARCH_STARTS_PER_HOUR must be a positive integer")
    limiter = HourlyRateLimiter(configured_limit)

    async def index(_request: web.Request) -> web.StreamResponse:
        return web.FileResponse(root / "index.html")

    async def health(_request: web.Request) -> web.StreamResponse:
        return web.json_response(
            {
                "status": "healthy",
                "temporal_address": settings.address,
                "temporal_namespace": settings.namespace,
                "task_queue": settings.task_queue,
            }
        )

    async def ready(_request: web.Request) -> web.StreamResponse:
        try:
            connected = await client.service_client.check_health(
                timeout=timedelta(seconds=3)
            )
        except (RPCError, OSError, asyncio.TimeoutError) as error:
            return web.json_response(
                {
                    "status": "not_ready",
                    "temporal": "unavailable",
                    "detail": str(error),
                },
                status=503,
            )
        if not connected:
            return web.json_response(
                {"status": "not_ready", "temporal": "unavailable"}, status=503
            )
        return web.json_response({"status": "ready", "temporal": "connected"})

    async def start_research(request: web.Request) -> web.StreamResponse:
        try:
            body = await request.json()
        except Exception as error:
            raise ApiError(400, "Request body must be valid JSON") from error
        query = body.get("query") if isinstance(body, dict) else None
        if not isinstance(query, str) or not query.strip():
            raise ApiError(400, "query must be a non-empty string")
        query = query.strip()
        if len(query) > 4000:
            raise ApiError(400, "query must be 4000 characters or fewer")

        rate_key = (
            request.headers.get("X-Temporal-Auth-Email") or request.remote or "unknown"
        ).lower()
        if not limiter.check(rate_key):
            raise ApiError(429, "Too many research requests. Try again later.")

        workflow_id = f"deep-research-{uuid.uuid4().hex[:12]}"
        await client.start_workflow(
            DeepResearchWorkflow.run,
            query,
            id=workflow_id,
            task_queue=settings.task_queue,
        )
        return web.json_response(
            {
                "workflow_id": workflow_id,
                "status": "researching",
                "temporal_ui_url": temporal_ui_url(settings, workflow_id),
            },
            status=201,
        )

    async def research_status(request: web.Request) -> web.StreamResponse:
        workflow_id = _workflow_id(request)
        handle = client.get_workflow_handle(workflow_id, result_type=str)
        description = await handle.describe()
        return web.json_response(
            {
                "workflow_id": workflow_id,
                "status": _status_name(description.status),
                "temporal_ui_url": temporal_ui_url(settings, workflow_id),
            }
        )

    async def research_result(request: web.Request) -> web.StreamResponse:
        workflow_id = _workflow_id(request)
        handle = client.get_workflow_handle(workflow_id, result_type=str)
        description = await handle.describe()
        if description.status != WorkflowExecutionStatus.COMPLETED:
            raise ApiError(409, "Research result is not available yet")
        result = await handle.result()
        return web.json_response(
            {
                "workflow_id": workflow_id,
                "status": "completed",
                "report": result,
            }
        )

    async def cancel_research(request: web.Request) -> web.StreamResponse:
        workflow_id = _workflow_id(request)
        handle = client.get_workflow_handle(workflow_id)
        await handle.cancel()
        return web.json_response(
            {"workflow_id": workflow_id, "status": "cancellation_requested"},
            status=202,
        )

    app = web.Application(middlewares=[error_middleware], client_max_size=1_048_576)
    app.router.add_get("/", index)
    app.router.add_get("/api/health", health)
    app.router.add_get("/api/ready", ready)
    app.router.add_post("/api/start-research", start_research)
    app.router.add_get("/api/status/{workflow_id}", research_status)
    app.router.add_get("/api/result/{workflow_id}", research_result)
    app.router.add_post("/api/cancel/{workflow_id}", cancel_research)
    return app


async def run_application() -> None:
    settings = TemporalSettings.from_env()
    client = await temporal_client(settings)
    worker = create_worker(client, settings)
    app = create_web_app(client, settings)
    runner = web.AppRunner(app, access_log=LOGGER)
    await runner.setup()

    host = os.environ.get("HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("PORT", "8234"))
    except ValueError as error:
        raise ValueError("PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")

    site = web.TCPSite(runner, host, port)
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signal_name, stop_requested.set)
            installed_signals.append(signal_name)
        except NotImplementedError:
            pass

    worker_task = asyncio.create_task(worker.run(), name="temporal-worker")
    stop_task = asyncio.create_task(stop_requested.wait(), name="shutdown-request")
    try:
        await site.start()
        print(
            f"Deep Research app listening on http://{host}:{port}; "
            f"polling '{settings.task_queue}' in '{settings.namespace}'"
        )
        done, _ = await asyncio.wait(
            {worker_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if worker_task in done:
            await worker_task
        else:
            await worker.shutdown()
            await worker_task
    finally:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        await runner.cleanup()
        for signal_name in installed_signals:
            loop.remove_signal_handler(signal_name)


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run_application())
