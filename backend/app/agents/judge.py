import json
import logging

from app.agents.base import (
    AgentCallError,
    ChatResult,
    FailureClass,
    RetryNotifier,
    call_openrouter,
)
from app.agents.personas import PersonaConfig
from app.config import settings
from app.models.trial import SpeechEntry, Usage, VerdictEntry

logger = logging.getLogger("tribunal.judge")

_VALID_VERDICTS = {"guilty", "not_guilty"}


def _parse_verdict(raw: str) -> tuple[str, str] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    # Still structured JSON parsing, not regex-over-prose: some models wrap
    # the object in a single-element list despite response_format json_object.
    if isinstance(data, list):
        if len(data) != 1 or not isinstance(data[0], dict):
            return None
        data = data[0]

    if not isinstance(data, dict):
        return None

    verdict = str(data.get("verdict", "")).strip().lower()
    reasoning = data.get("reasoning")
    if verdict not in _VALID_VERDICTS or not isinstance(reasoning, str):
        return None
    return verdict, reasoning


def _validate_verdict(result: ChatResult) -> tuple[str, str]:
    """Content-level validation, run inside the shared attempt budget.

    Raising here makes an unparseable verdict cost exactly one attempt, the
    same as an HTTP failure — the parse layer never doubles the call count.
    """
    parsed = _parse_verdict(result.content)
    if parsed is None:
        raise AgentCallError(
            FailureClass.INVALID_VERDICT,
            f"unparseable verdict: {result.content[:300]!r}",
        )
    return parsed


def _build_user_prompt(charge_sheet: str, speeches: list[SpeechEntry]) -> str:
    parts = [f"Charge sheet:\n{charge_sheet}\n"]
    for s in speeches:
        if s.status == "ok":
            parts.append(f"--- {s.role} ---\n{s.content}\n")
        else:
            parts.append(f"--- {s.role} ---\n[this speech failed and is unavailable]\n")
    parts.append(
        'Render your verdict now. Respond ONLY with JSON: '
        '{"verdict": "guilty" or "not_guilty", "reasoning": "..."}'
    )
    return "\n".join(parts)


async def run_judge_verdict(
    charge_sheet: str,
    speeches: list[SpeechEntry],
    persona: PersonaConfig,
    model: str,
    on_retry: RetryNotifier | None = None,
) -> VerdictEntry:
    user_prompt = _build_user_prompt(charge_sheet, speeches)

    try:
        result = await call_openrouter(
            model=model,
            system_prompt=persona.system_prompt,
            user_prompt=user_prompt,
            max_tokens=settings.agent_max_tokens,
            json_mode=True,
            validate=_validate_verdict,
            on_retry=on_retry,
        )
    except AgentCallError as e:
        logger.warning(
            "judge %s (%s) failed after %d attempt(s): %s",
            persona.role, model, e.attempts, e.detail,
        )
        return VerdictEntry(
            role=persona.role,
            persona=persona.system_prompt,
            model=model,
            status="failed",
            attempts=e.attempts,
            error_reason=e.message,
            error_code=e.failure_class,
        )

    verdict, reasoning = result.parsed
    return VerdictEntry(
        role=persona.role,
        persona=persona.system_prompt,
        model=model,
        status="ok",
        verdict=verdict,
        reasoning=reasoning,
        attempts=result.attempts,
        usage=Usage(
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost=result.cost,
        ),
    )
