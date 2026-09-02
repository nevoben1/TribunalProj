from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChargeSheetIn(BaseModel):
    charge_sheet: str = Field(min_length=20, max_length=4000)
    model_mode: Literal["same", "distinct"] = "same"


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None


class SpeechEntry(BaseModel):
    role: str
    persona: str
    model: str
    status: Literal["ok", "failed"]
    content: str | None = None
    usage: Usage | None = None
    attempts: int = 1
    # Plain-language explanation shown to the user; never a raw provider payload.
    error_reason: str | None = None
    error_code: str | None = None


class VerdictEntry(BaseModel):
    role: str
    persona: str
    model: str
    status: Literal["ok", "failed"]
    verdict: Literal["guilty", "not_guilty"] | None = None
    reasoning: str | None = None
    usage: Usage | None = None
    attempts: int = 1
    error_reason: str | None = None
    error_code: str | None = None


class FinalVerdict(BaseModel):
    # None means the whole bench failed and never ruled.
    verdict: Literal["guilty", "not_guilty"] | None = None
    guilty_votes: int = 0
    not_guilty_votes: int = 0
    failed_votes: int = 0
    # A 1-1 split, resolved for the defendant rather than reported as a decision.
    tie_break: bool = False
    unanimous: bool = False


def tally_final_verdict(verdicts: list[VerdictEntry]) -> FinalVerdict:
    """Majority of the judges that actually ruled. Deterministic, no model call.

    A tie goes to the defendant, mirroring a bench with no majority to convict.
    Judges that failed are excluded from the tally, not counted as acquittals.
    """
    votes = [v.verdict for v in verdicts if v.status == "ok" and v.verdict]
    guilty = votes.count("guilty")
    not_guilty = votes.count("not_guilty")
    failed = len(verdicts) - len(votes)

    if not votes:
        return FinalVerdict(failed_votes=failed)

    return FinalVerdict(
        verdict="guilty" if guilty > not_guilty else "not_guilty",
        guilty_votes=guilty,
        not_guilty_votes=not_guilty,
        failed_votes=failed,
        tie_break=guilty == not_guilty,
        unanimous=guilty == 0 or not_guilty == 0,
    )


class Trial(BaseModel):
    id: str
    charge_sheet: str
    created_at: datetime
    status: Literal["pending", "running", "completed"]
    model_mode: Literal["same", "distinct"]
    speeches: list[SpeechEntry] = []
    verdicts: list[VerdictEntry] = []
    final_verdict: FinalVerdict | None = None


class TrialSummary(BaseModel):
    id: str
    charge_sheet_excerpt: str
    created_at: datetime
    status: Literal["pending", "running", "completed"]
    verdict_summary: list[str] = []
    final_verdict: FinalVerdict | None = None
