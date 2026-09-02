import json
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from app.db import DatabaseUnavailable, find_one, get_collection, insert_one, with_retry
from app.models.trial import ChargeSheetIn, VerdictEntry, tally_final_verdict
from app.orchestrator import run_trial

router = APIRouter(prefix="/trials", tags=["trials"])


def _unavailable(e: DatabaseUnavailable) -> HTTPException:
    return HTTPException(status_code=503, detail=e.message)


def _final_verdict(doc: dict) -> dict | None:
    """Stored tally, or one computed on the fly for trials written before it existed."""
    stored = doc.get("final_verdict")
    if stored is not None:
        return stored
    verdicts = doc.get("verdicts") or []
    if not verdicts:
        return None
    return tally_final_verdict([VerdictEntry(**v) for v in verdicts]).model_dump()


def _serialize_trial(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    doc["final_verdict"] = _final_verdict(doc)
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
    try:
        result = await insert_one(doc)
    except DatabaseUnavailable as e:
        raise _unavailable(e)
    return {"id": str(result.inserted_id)}


@router.get("/{trial_id}/stream")
async def stream_trial(trial_id: str):
    oid = _get_oid(trial_id)
    try:
        doc = await find_one({"_id": oid})
    except DatabaseUnavailable as e:
        raise _unavailable(e)
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
    async def fetch() -> list[dict]:
        cursor = get_collection().find().sort("created_at", -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    try:
        docs = await with_retry("list_trials", fetch)
    except DatabaseUnavailable as e:
        raise _unavailable(e)

    results = []
    for doc in docs:
        verdicts = doc.get("verdicts", [])
        results.append(
            {
                "id": str(doc["_id"]),
                "charge_sheet_excerpt": doc["charge_sheet"][:150],
                "created_at": doc["created_at"],
                "status": doc["status"],
                "model_mode": doc.get("model_mode"),
                "verdict_summary": [v.get("verdict") or v.get("status") for v in verdicts],
                "final_verdict": _final_verdict(doc),
            }
        )
    return results


@router.get("/{trial_id}")
async def get_trial(trial_id: str):
    oid = _get_oid(trial_id)
    try:
        doc = await find_one({"_id": oid})
    except DatabaseUnavailable as e:
        raise _unavailable(e)
    if doc is None:
        raise HTTPException(status_code=404, detail="trial not found")
    return _serialize_trial(doc)
