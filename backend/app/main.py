from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import DatabaseUnavailable, get_client, with_retry
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
    try:
        await with_retry("ping", lambda: get_client().admin.command("ping"))
    except DatabaseUnavailable as e:
        raise HTTPException(status_code=503, detail=e.message)
    return {"status": "ok"}
