import json
import logging

from app.agents.base import AgentCallError, call_openrouter
from app.agents.personas import PersonaConfig
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
    charge_sheet: str, speeches: list[SpeechEntry], persona: PersonaConfig, model: str
) -> VerdictEntry:
    user_prompt = _build_user_prompt(charge_sheet, speeches)

    # Parse-layer retry (distinct from base.py's HTTP-layer retry): a full
    # second call is only made if the first response fails to parse as a
    # valid verdict, never for HTTP/timeout reasons (base.py owns those).
    for parse_attempt in range(2):
        try:
            result = await call_openrouter(
                model=model,
                system_prompt=persona.system_prompt,
                user_prompt=user_prompt,
                json_mode=True,
            )
        except AgentCallError as e:
            logger.warning("judge %s (%s) call failed: %s", persona.role, model, e.message)
            return VerdictEntry(
                role=persona.role,
                persona=persona.system_prompt,
                model=model,
                status="failed",
            )

        parsed = _parse_verdict(result.content)
        if parsed is not None:
            verdict, reasoning = parsed
            return VerdictEntry(
                role=persona.role,
                persona=persona.system_prompt,
                model=model,
                status="ok",
                verdict=verdict,
                reasoning=reasoning,
                usage=Usage(
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    cost=result.cost,
                ),
            )
        logger.warning(
            "judge %s (%s) parse attempt %d failed, raw content: %r",
            persona.role, model, parse_attempt, result.content,
        )
        # parse failed, loop retries once more if parse_attempt == 0

    return VerdictEntry(
        role=persona.role,
        persona=persona.system_prompt,
        model=model,
        status="failed",
    )
