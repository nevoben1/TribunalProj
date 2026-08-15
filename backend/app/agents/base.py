import httpx

from app.config import settings


class AgentCallError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ChatResult:
    def __init__(self, content: str, prompt_tokens: int, completion_tokens: int):
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            timeout=httpx.Timeout(settings.request_timeout_seconds),
        )
    return _client


async def call_openrouter(
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> ChatResult:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        # Some free models are reasoning-capable and, left unchecked, will
        # spend a large share of max_tokens on a hidden "reasoning" phase
        # before emitting any visible content (observed producing fully
        # empty content on real free-tier calls). A handful of models
        # require reasoning and reject an outright disable, so we ask for
        # the minimum effort rather than turning it off entirely.
        "reasoning": {"effort": "low"},
    }
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    client = get_http_client()
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}

    last_error = ""
    for attempt in range(2):
        try:
            resp = await client.post("/chat/completions", json=body, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                choice = data["choices"][0]["message"]["content"]
                if choice:
                    usage = data.get("usage", {})
                    return ChatResult(
                        content=choice,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                    )
                last_error = "model returned empty content"
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.TimeoutException:
            last_error = "timeout"
        except httpx.HTTPError as e:
            last_error = f"http error: {e}"

    raise AgentCallError(f"call to model '{model}' failed after retry: {last_error}")
