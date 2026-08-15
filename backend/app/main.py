from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import get_client
from app.routes.trials import router as trials_router

app = FastAPI(title="AI Tribunal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(trials_router)


@app.get("/health")
async def health():
    await get_client().admin.command("ping")
    return {"status": "ok"}
