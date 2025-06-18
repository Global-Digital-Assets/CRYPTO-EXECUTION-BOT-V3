"""Entry-only execution bot – FastAPI for health & APScheduler loop."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
import uvicorn

from order_flow import process_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = FastAPI(title="Binance Futures Execution Bot")


@app.get("/health")
async def health():
    return {"status": "ok"}


scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
    scheduler.add_job(process_signals, "interval", minutes=15, next_run_time=None)
    scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=9000, reload=False)
