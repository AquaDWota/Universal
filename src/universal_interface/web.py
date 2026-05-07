"""Web dashboard — FastAPI + packaged static UI."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from universal_interface.app_context import AppContext
from universal_interface.config import EnvSettings
from universal_interface.orchestrator import handle_turn
from universal_interface.workflow_runner import run_workflow

STATIC_DIR = Path(__file__).resolve().parent / "static"
_WORKFLOW_LOG = logging.getLogger("uai.workflow")


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000)


def _parse_crontab(expr: str) -> CronTrigger | None:
    parts = expr.strip().split()
    if len(parts) != 5:
        return None
    minute, hour, day, month, dow = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=dow,
        timezone=ZoneInfo("UTC"),
    )


async def _run_workflow_job(app: FastAPI, wf_name: str) -> None:
    ctx = app.state.ctx
    text = await run_workflow(ctx, wf_name)
    _WORKFLOW_LOG.info("workflow '%s' finished (%d chars)", wf_name, len(text))


def _workflow_job_sync(app: FastAPI, wf_name: str) -> None:
    loop = app.state.main_loop
    fut = asyncio.run_coroutine_threadsafe(_run_workflow_job(app, wf_name), loop)
    try:
        fut.result(timeout=300)
    except Exception:
        _WORKFLOW_LOG.exception("workflow '%s' crashed", wf_name)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        env = EnvSettings()
        app.state.ctx = await AppContext.create(env=env)
        app.state.main_loop = asyncio.get_running_loop()
        app.state.scheduler = None

        sched = BackgroundScheduler()
        for wf_name, wf in app.state.ctx.config.workflows.items():
            if not wf.enabled:
                continue
            cron_expr = str(wf.schedule or "").strip()
            if not cron_expr:
                continue
            trig = _parse_crontab(cron_expr)
            if trig is None:
                _WORKFLOW_LOG.warning(
                    "Skipping workflow '%s': invalid cron expression %r",
                    wf_name,
                    wf.schedule,
                )
                continue
            sched.add_job(
                _workflow_job_sync,
                trigger=trig,
                args=[app, wf_name],
                id=f"workflow:{wf_name}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        if sched.get_jobs():
            sched.start()
            app.state.scheduler = sched

        yield

        if getattr(app.state, "scheduler", None):
            app.state.scheduler.shutdown(wait=False)
        await app.state.ctx.shutdown()

    application = FastAPI(title="Universal AI Interface", lifespan=lifespan)

    @application.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        ctx: AppContext = request.app.state.ctx
        return {"ok": True, "inference": ctx.config.ai.inference}

    @application.get("/api/status")
    async def api_status(request: Request) -> dict[str, Any]:
        ctx: AppContext = request.app.state.ctx
        privacy = ctx.config.privacy or {}
        local_mode = privacy.get("local_mode", True)
        sched_on = getattr(request.app.state, "scheduler", None) is not None
        return {
            "ok": True,
            "inference": ctx.config.ai.inference,
            "local_model": ctx.config.ai.local_model,
            "cloud_model": ctx.config.ai.cloud_model,
            "privacy_local_mode": bool(local_mode),
            "vector_store_active": ctx.vector_store is not None,
            "connector_count": len(ctx.registry.all()),
            "workflow_scheduler_active": sched_on,
        }

    @application.get("/api/connectors")
    async def api_connectors(request: Request) -> dict[str, Any]:
        ctx: AppContext = request.app.state.ctx
        connectors: list[dict[str, Any]] = []
        for c in ctx.registry.all():
            entry = ctx.config.connectors.get(c.name)
            enabled = entry.enabled if entry else True
            connectors.append(
                {
                    "name": c.name,
                    "category": c.category,
                    "description": c.description,
                    "version": getattr(c, "version", "0.1.0"),
                    "auth_type": c.auth_type.value,
                    "enabled": enabled,
                    "capabilities": [
                        {
                            "action_id": cap.action_id,
                            "name": cap.name,
                            "description": cap.description,
                            "requires_confirmation": cap.requires_confirmation,
                        }
                        for cap in c.capabilities
                    ],
                }
            )
        return {"connectors": connectors}

    @application.post("/api/chat")
    async def api_chat(request: Request, body: ChatBody) -> dict[str, str]:
        ctx: AppContext = request.app.state.ctx
        reply = await handle_turn(ctx, body.message.strip())
        return {"reply": reply}

    @application.get("/", response_model=None)
    async def root() -> FileResponse | HTMLResponse:
        index = STATIC_DIR / "index.html"
        if not index.is_file():
            return HTMLResponse(
                "<p>Web UI assets missing. Reinstall the package.</p>",
                status_code=500,
            )
        return FileResponse(index)

    application.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    return application


app = create_app()
