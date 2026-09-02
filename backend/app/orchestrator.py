import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncGenerator, Awaitable, Callable, Literal

from bson import ObjectId

from app.agents.judge import run_judge_verdict
from app.agents.lawyer import run_lawyer_speech
from app.agents.personas import JUDGES, LAWYERS
from app.config import settings
from app.db import DatabaseUnavailable, update_one
from app.models.trial import SpeechEntry, VerdictEntry, tally_final_verdict

logger = logging.getLogger("tribunal.orchestrator")

PERSIST_FAILED_MESSAGE = (
    "The trial finished, but the verdict could not be written to the case archive. "
    "The results below are complete, yet they will not appear in the case history."
)
INTERNAL_ERROR_MESSAGE = (
    "The trial was interrupted by an unexpected problem on our side and could not "
    "be completed."
)


def _speech_event(entry: SpeechEntry) -> dict:
    if entry.status == "ok":
        return {
            "type": "speech",
            "role": entry.role,
            "content": entry.content,
            "model": entry.model,
            "usage": entry.usage.model_dump() if entry.usage else None,
        }
    return _error_event(entry.role, entry.error_reason, entry.error_code)


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
    return _error_event(entry.role, entry.error_reason, entry.error_code)


def _error_event(role: str, message: str | None, code: str | None) -> dict:
    return {
        "type": "error",
        "role": role,
        "message": message or INTERNAL_ERROR_MESSAGE,
        "reason_code": code or "unknown",
    }


def _retry_notifier(queue: asyncio.Queue, role: str) -> Callable[[int, int, str], Awaitable[None]]:
    async def notify(retry: int, max_retries: int, reason: str) -> None:
        await queue.put(
            {
                "type": "retry",
                "role": role,
                "retry": retry,
                "max_retries": max_retries,
                "reason": reason,
            }
        )

    return notify


async def _drain(queue: asyncio.Queue, task: asyncio.Task) -> AsyncGenerator[dict, None]:
    """Yield queued retry notices while `task` runs, so they reach the client live."""
    while not task.done():
        getter = asyncio.ensure_future(queue.get())
        done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
        if getter in done:
            yield getter.result()
        else:
            # Cancelling a pending Queue.get leaves the item in the queue; the
            # trailing drain below picks up anything that landed in the gap.
            getter.cancel()
    while not queue.empty():
        yield queue.get_nowait()


async def _run_trial(
    trial_id: str, charge_sheet: str, model_mode: Literal["same", "distinct"]
) -> AsyncGenerator[dict, None]:
    oid = ObjectId(trial_id)
    queue: asyncio.Queue = asyncio.Queue()

    try:
        await update_one({"_id": oid}, {"$set": {"status": "running"}})
    except DatabaseUnavailable as e:
        # Best effort: a status flag is not worth discarding a trial over. The
        # final persist is the write that actually matters.
        logger.warning("could not mark trial %s running: %s", trial_id, e.detail)

    speeches: list[SpeechEntry] = []
    for persona in LAWYERS:
        model = settings.model_for_role(persona.role, model_mode)
        task = asyncio.ensure_future(
            run_lawyer_speech(charge_sheet, persona, model, _retry_notifier(queue, persona.role))
        )
        async for event in _drain(queue, task):
            yield event
        entry = await task
        speeches.append(entry)
        yield _speech_event(entry)

    verdicts: list[VerdictEntry] = []
    tasks = []
    for i, persona in enumerate(JUDGES):
        if i > 0:
            # Stagger judge calls: free-tier models often cap concurrent
            # requests at 1, so firing all 3 judges at once (they can share
            # SAME_MODEL in "same" mode) causes rate-limit failures on the
            # later requests.
            await asyncio.sleep(1.5)
        tasks.append(
            asyncio.ensure_future(
                run_judge_verdict(
                    charge_sheet,
                    speeches,
                    persona,
                    settings.model_for_role(persona.role, model_mode),
                    _retry_notifier(queue, persona.role),
                )
            )
        )

    pending = set(tasks)
    while pending:
        getter = asyncio.ensure_future(queue.get())
        done, _ = await asyncio.wait({getter, *pending}, return_when=asyncio.FIRST_COMPLETED)
        if getter in done:
            yield getter.result()
        else:
            getter.cancel()
        for task in [t for t in pending if t.done()]:
            pending.discard(task)
            entry = await task
            verdicts.append(entry)
            yield _verdict_event(entry)
    while not queue.empty():
        yield queue.get_nowait()

    # Majority of the judges that ruled — a plain tally over verdicts we already
    # have, never an extra model call.
    final_verdict = tally_final_verdict(verdicts)
    yield {"type": "final_verdict", **final_verdict.model_dump()}

    try:
        await update_one(
            {"_id": oid},
            {
                "$set": {
                    "status": "completed",
                    "speeches": [s.model_dump() for s in speeches],
                    "verdicts": [v.model_dump() for v in verdicts],
                    "final_verdict": final_verdict.model_dump(),
                    "completed_at": datetime.now(timezone.utc),
                }
            },
        )
    except DatabaseUnavailable as e:
        # Every model call is already paid for and already on the user's
        # screen: report the loss, then still close the stream cleanly so the
        # client keeps what it received instead of hanging on an open socket.
        logger.error("failed to persist trial %s: %s", trial_id, e.detail)
        yield _error_event("system", PERSIST_FAILED_MESSAGE, "persist_failed")


async def run_trial(
    trial_id: str, charge_sheet: str, model_mode: Literal["same", "distinct"]
) -> AsyncGenerator[dict, None]:
    """Wrapper guaranteeing the stream always terminates with a `done` event."""
    try:
        async for event in _run_trial(trial_id, charge_sheet, model_mode):
            yield event
    except asyncio.CancelledError:
        # Client disconnected mid-trial; nothing to report to a gone socket.
        raise
    except Exception:
        logger.exception("trial %s aborted unexpectedly", trial_id)
        yield _error_event("system", INTERNAL_ERROR_MESSAGE, "internal")

    yield {"type": "done", "trial_id": trial_id}
