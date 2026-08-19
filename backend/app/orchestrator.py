import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator, Literal

from bson import ObjectId

from app.agents.judge import run_judge_verdict
from app.agents.lawyer import run_lawyer_speech
from app.agents.personas import JUDGES, LAWYERS
from app.config import settings
from app.db import get_collection
from app.models.trial import SpeechEntry, VerdictEntry


def _speech_event(entry: SpeechEntry) -> dict:
    if entry.status == "ok":
        return {
            "type": "speech",
            "role": entry.role,
            "content": entry.content,
            "model": entry.model,
            "usage": entry.usage.model_dump() if entry.usage else None,
        }
    return {"type": "error", "role": entry.role, "message": "speech generation failed"}


def _verdict_event(entry: VerdictEntry) -> dict:
    if entry.status == "ok":
        return {
            "type": "verdict",
            "role": entry.role,
            "verdict": entry.verdict,
            "reasoning": entry.reasoning,
            "model": entry.model,
            "usage": entry.usage.model_dump() if entry.usage else None,
        }
    return {"type": "error", "role": entry.role, "message": "verdict generation failed"}


async def run_trial(
    trial_id: str, charge_sheet: str, model_mode: Literal["same", "distinct"]
) -> AsyncGenerator[dict, None]:
    collection = get_collection()
    oid = ObjectId(trial_id)
    await collection.update_one({"_id": oid}, {"$set": {"status": "running"}})

    speeches: list[SpeechEntry] = []
    for persona in LAWYERS:
        model = settings.model_for_role(persona.role, model_mode)
        entry = await run_lawyer_speech(charge_sheet, persona, model)
        speeches.append(entry)
        yield _speech_event(entry)

    verdicts: list[VerdictEntry] = []
    tasks = {
        asyncio.create_task(
            run_judge_verdict(
                charge_sheet, speeches, persona, settings.model_for_role(persona.role, model_mode)
            )
        ): persona
        for persona in JUDGES
    }
    pending = set(tasks.keys())
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            entry = task.result()
            verdicts.append(entry)
            yield _verdict_event(entry)

    await collection.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "completed",
                "speeches": [s.model_dump() for s in speeches],
                "verdicts": [v.model_dump() for v in verdicts],
                "completed_at": datetime.now(timezone.utc),
            }
        },
    )

    yield {"type": "done", "trial_id": trial_id}
