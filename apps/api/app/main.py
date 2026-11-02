import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import campaigns, demo, kobo, review, simulation
from app.api.routes import router
from app.config import settings
from app.voice import phone_sim, recovery, speech
from app.voice.calls import router as voice_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    simulation.fail_interrupted_runs()
    recovery.close_interrupted_calls()
    scheduler = asyncio.create_task(campaigns.run_scheduler()) if settings.scheduler else None
    yield
    if scheduler:
        scheduler.cancel()


app = FastAPI(title="Voice survey platform", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
app.include_router(router)
app.include_router(voice_router)
app.include_router(speech.router)
app.include_router(review.router)
app.include_router(campaigns.router)
app.include_router(kobo.router)
app.include_router(simulation.router)
app.include_router(phone_sim.router)
app.include_router(demo.router)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")


@app.middleware("http")
async def demo_only_guard(request: Request, call_next):
    # A tunnelled demo server must not expose forms, interviews or settings.
    if settings.demo_only and not demo.is_public(request.url.path):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"ok": True}
