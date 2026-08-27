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


class VerdictEntry(BaseModel):
    role: str
    persona: str
    model: str
    status: Literal["ok", "failed"]
    verdict: Literal["guilty", "not_guilty"] | None = None
    reasoning: str | None = None
    usage: Usage | None = None


class Trial(BaseModel):
    id: str
    charge_sheet: str
    created_at: datetime
    status: Literal["pending", "running", "completed"]
    model_mode: Literal["same", "distinct"]
    speeches: list[SpeechEntry] = []
    verdicts: list[VerdictEntry] = []


class TrialSummary(BaseModel):
    id: str
    charge_sheet_excerpt: str
    created_at: datetime
    status: Literal["pending", "running", "completed"]
    verdict_summary: list[str] = []
