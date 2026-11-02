import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import campaigns, kobo, review, simulation
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


@app.get("/api/health")
def health():
    return {"ok": True}
