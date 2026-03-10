"""
BiliMartMonitor — FastAPI application entry point.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env from the project root before anything else touches env vars
# ---------------------------------------------------------------------------
_SRC_ROOT_PATH = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _SRC_ROOT_PATH.parent
load_dotenv(_PROJECT_ROOT / ".env")

# Make src/ importable
_SRC_ROOT = str(_SRC_ROOT_PATH)
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

# ---------------------------------------------------------------------------
# Seed auth data on startup
# ---------------------------------------------------------------------------
from backend.auth import ensure_default_access_users  # noqa: E402
ensure_default_access_users()

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from backend.routers import auth, sessions, qr, market, settings, accounts  # noqa: E402
from backend.cron_runner import cron_loop  # noqa: E402
from bsm.telegrambot import bot_loop  # noqa: E402

log = logging.getLogger("bsm.main")
_MONITOR_INTERVAL_MULTIPLIER = 12.0
_MONITOR_INACTIVITY_SECONDS = 60.0

# ---------------------------------------------------------------------------
# Lifespan — start/stop background cron task
# ---------------------------------------------------------------------------
_cron_task: asyncio.Task | None = None
_bot_task: asyncio.Task | None = None
_monitor_task: asyncio.Task | None = None
_cron_task_lock = asyncio.Lock()


async def _stop_cron_task_locked() -> bool:
    global _cron_task

    task = _cron_task
    if task is None or task.done():
        _cron_task = None
        return False

    task.cancel()
    results = await asyncio.gather(task, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
            log.warning("Cron task stopped with error: %s", result)
    _cron_task = None
    return True


async def start_cron_task() -> bool:
    global _cron_task

    async with _cron_task_lock:
        if _cron_task is not None and not _cron_task.done():
            return False
        _cron_task = asyncio.create_task(cron_loop())
        return True


async def restart_cron_task() -> None:
    global _cron_task

    async with _cron_task_lock:
        await _stop_cron_task_locked()
        _cron_task = asyncio.create_task(cron_loop())


async def _send_monitor_tg_log(message: str) -> None:
    from bsm.notify import send_admin_telegram_alert

    await asyncio.to_thread(send_admin_telegram_alert, f"监控日志\n{message}")


async def _monitor_loop() -> None:
    from backend.cron_state import cron_state
    from bsm.settings import load_runtime_config

    started_at_monotonic = time.monotonic()
    cron_state.info("监控进程已启动")
    try:
        await _send_monitor_tg_log("监控进程已启动")
    except Exception as exc:
        cron_state.warn(f"监控进程启动 TG 日志发送失败: {exc}")

    while True:
        try:
            cfg = await asyncio.to_thread(load_runtime_config)
            raw_interval = float(cfg.get("interval", 20) or 20)
            if raw_interval <= 0:
                raw_interval = 20.0
            monitor_interval = max(1.0, raw_interval * _MONITOR_INTERVAL_MULTIPLIER)
            await asyncio.sleep(monitor_interval)

            idle_seconds = cron_state.seconds_since_activity()
            uptime_seconds = max(0, int(time.monotonic() - started_at_monotonic))
            idle_text = "N/A" if idle_seconds is None else str(int(idle_seconds))
            cron_state.info(
                f"监控心跳：uptime={uptime_seconds}s idle={idle_text}s check_interval={int(monitor_interval)}s"
            )
            if idle_seconds is None:
                continue

            if idle_seconds >= _MONITOR_INACTIVITY_SECONDS:
                cron_state.warn(
                    f"监控告警：Cron 超过 {int(_MONITOR_INACTIVITY_SECONDS)} 秒无活动（{int(idle_seconds)} 秒），准备重启"
                )
                await _send_monitor_tg_log(
                    f"Cron 超过 {int(_MONITOR_INACTIVITY_SECONDS)} 秒无活动（{int(idle_seconds)} 秒），开始重启"
                )
                await restart_cron_task()
                cron_state.info("监控处理：Cron 已重启")
                await _send_monitor_tg_log("Cron 已重启")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            cron_state.error(f"监控进程异常: {exc}")
            try:
                await _send_monitor_tg_log(f"监控进程异常: {exc}")
            except Exception:
                pass
            await asyncio.sleep(5)

    cron_state.info("监控进程已停止")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cron_task, _bot_task, _monitor_task
    from backend.cron_state import cron_state
    cron_state.load()
    await start_cron_task()
    _bot_task = asyncio.create_task(bot_loop())
    _monitor_task = asyncio.create_task(_monitor_loop())
    log.info("Cron, Telegram bot and monitor background tasks started")
    yield
    await _stop_cron_task_locked()
    tasks = [task for task in (_bot_task, _monitor_task) if task and not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                log.warning("Background task stopped with error: %s", result)
    log.info("Cron, Telegram bot and monitor background tasks stopped")


app = FastAPI(title="BiliMartMonitor API", version="0.9.5.2", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS — allow Next.js dev server
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(qr.router)
app.include_router(market.router)
app.include_router(settings.router)
app.include_router(accounts.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "BiliMartMonitor"}
