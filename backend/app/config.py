from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    mongo_uri: str = ""
    mongo_db_name: str = "tribunal"
    cors_origins: str = "http://localhost:3000"
    # Output cap for every participant. Judges need one as much as lawyers do:
    # left unset, the request inherits the provider's own default
    # max_completion_tokens, which on some endpoints is small enough that the
    # reasoning phase consumes it and the verdict JSON comes back truncated
    # mid-string (or as a bare "{}") and fails to parse.
    agent_max_tokens: int = Field(
        default=800,
        validation_alias=AliasChoices("AGENT_MAX_TOKENS", "LAWYER_MAX_TOKENS"),
    )
    request_timeout_seconds: float = 30.0

    # Failure handling. The agent budget is per participant and shared between
    # HTTP failures and judge parse failures, so worst case is
    # 7 * agent_max_attempts model calls for a whole trial.
    agent_max_attempts: int = 3
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 8.0
    mongo_max_attempts: int = 3
    # Generous enough for a cold host's first Atlas connection (SRV lookup +
    # TLS + topology discovery), still far below the driver's 30s default.
    mongo_server_selection_timeout_ms: int = 10000

    # Model configuration: both pools are always configured server-side.
    # The user picks which pool to use ("same" or "distinct") per trial,
    # via a request field — no server restart needed to switch.
    same_model: str = "TODO_SET_SAME_MODEL"

    prosecutor_1_model: str = "TODO_SET_PROSECUTOR_1_MODEL"
    prosecutor_2_model: str = "TODO_SET_PROSECUTOR_2_MODEL"
    defender_1_model: str = "TODO_SET_DEFENDER_1_MODEL"
    defender_2_model: str = "TODO_SET_DEFENDER_2_MODEL"
    judge_1_model: str = "TODO_SET_JUDGE_1_MODEL"
    judge_2_model: str = "TODO_SET_JUDGE_2_MODEL"
    judge_3_model: str = "TODO_SET_JUDGE_3_MODEL"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def model_for_role(self, role: str, model_mode: Literal["same", "distinct"]) -> str:
        if model_mode == "same":
            return self.same_model
        return {
            "prosecutor_1": self.prosecutor_1_model,
            "prosecutor_2": self.prosecutor_2_model,
            "defender_1": self.defender_1_model,
            "defender_2": self.defender_2_model,
            "judge_1": self.judge_1_model,
            "judge_2": self.judge_2_model,
            "judge_3": self.judge_3_model,
        }[role]


settings = Settings()
