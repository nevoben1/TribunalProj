import logging

from app.agents.base import AgentCallError, call_openrouter
from app.agents.personas import PersonaConfig
from app.config import settings
from app.models.trial import SpeechEntry, Usage

logger = logging.getLogger("tribunal.lawyer")


async def run_lawyer_speech(charge_sheet: str, persona: PersonaConfig, model: str) -> SpeechEntry:
    user_prompt = (
        f"Charge sheet:\n{charge_sheet}\n\n"
        "Deliver your speech in 120-150 words — this is a hard limit, not a "
        "suggestion. Plan your argument to fit that budget from the first sentence: "
        "make your strongest points only, then conclude. You must finish with a "
        "complete final sentence; never let your speech cut off mid-thought."
    )
    try:
        result = await call_openrouter(
            model=model,
            system_prompt=persona.system_prompt,
            user_prompt=user_prompt,
            max_tokens=settings.lawyer_max_tokens,
        )
        return SpeechEntry(
            role=persona.role,
            persona=persona.system_prompt,
            model=model,
            status="ok",
            content=result.content,
            usage=Usage(
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cost=result.cost,
            ),
        )
    except AgentCallError as e:
        logger.warning("lawyer %s (%s) call failed: %s", persona.role, model, e.message)
        return SpeechEntry(
            role=persona.role,
            persona=persona.system_prompt,
            model=model,
            status="failed",
        )
