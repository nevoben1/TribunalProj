import json
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from app.db import get_collection
from app.models.trial import ChargeSheetIn
from app.orchestrator import run_trial

router = APIRouter(prefix="/trials", tags=["trials"])


def _serialize_trial(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def _get_oid(trial_id: str) -> ObjectId:
    try:
        return ObjectId(trial_id)
    except InvalidId:
        raise HTTPException(status_code=404, detail="trial not found")


@router.post("")
async def create_trial(body: ChargeSheetIn):
    doc = {
        "charge_sheet": body.charge_sheet,
        "created_at": datetime.now(timezone.utc),
        "status": "pending",
        "model_mode": body.model_mode,
        "speeches": [],
        "verdicts": [],
    }
    result = await get_collection().insert_one(doc)
    return {"id": str(result.inserted_id)}


@router.get("/{trial_id}/stream")
async def stream_trial(trial_id: str):
    oid = _get_oid(trial_id)
    collection = get_collection()
    doc = await collection.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="trial not found")

    if doc["status"] != "pending":
        async def replay_generator():
            yield {"event": "done", "data": '{"trial_id": "%s", "already_completed": true}' % trial_id}

        return EventSourceResponse(replay_generator())

    async def event_generator():
        async for event in run_trial(trial_id, doc["charge_sheet"], doc["model_mode"]):
            yield {"event": event["type"], "data": json.dumps(event)}

    return EventSourceResponse(event_generator())


@router.get("")
async def list_trials(skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    collection = get_collection()
    cursor = collection.find().sort("created_at", -1).skip(skip).limit(limit)
    results = []
    async for doc in cursor:
        verdicts = doc.get("verdicts", [])
        results.append(
            {
                "id": str(doc["_id"]),
                "charge_sheet_excerpt": doc["charge_sheet"][:150],
                "created_at": doc["created_at"],
                "status": doc["status"],
                "model_mode": doc.get("model_mode"),
                "verdict_summary": [v.get("verdict") or v.get("status") for v in verdicts],
            }
        )
    return results


@router.get("/{trial_id}")
async def get_trial(trial_id: str):
    oid = _get_oid(trial_id)
    doc = await get_collection().find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="trial not found")
    return _serialize_trial(doc)
