from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    mongo_uri: str = ""
    mongo_db_name: str = "tribunal"
    cors_origins: str = "http://localhost:3000"
    lawyer_max_tokens: int = 800
    request_timeout_seconds: float = 30.0

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
