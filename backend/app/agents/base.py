import asyncio
import logging
from typing import Any, Awaitable, Callable

import httpx

from app.config import settings

logger = logging.getLogger("tribunal.agents")

# Called before each retry with (retry_number, max_retries, user_facing_reason).
RetryNotifier = Callable[[int, int, str], Awaitable[None]]


class FailureClass:
    """Failure taxonomy shared by the HTTP layer and the judge parse layer."""

    TIMEOUT = "timeout"
    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    PROVIDER_ERROR = "provider_error"
    EMPTY_CONTENT = "empty_content"
    MALFORMED_RESPONSE = "malformed_response"
    INVALID_VERDICT = "invalid_verdict"
    AUTH = "auth"
    PAYMENT = "payment"
    MODEL_UNAVAILABLE = "model_unavailable"
    BAD_REQUEST = "bad_request"
    UNKNOWN = "unknown"


# Only these are worth spending an attempt on again. Everything else is a
# permanent condition (bad key, bad model id, malformed body) that a second
# identical request cannot fix, so we fail fast instead of burning the budget.
_RETRYABLE = {
    FailureClass.TIMEOUT,
    FailureClass.NETWORK,
    FailureClass.RATE_LIMIT,
    FailureClass.PROVIDER_ERROR,
    FailureClass.EMPTY_CONTENT,
    FailureClass.MALFORMED_RESPONSE,
    FailureClass.INVALID_VERDICT,
}

# User-facing prose. Deliberately free of status codes, exception names and
# provider payloads — the raw detail goes to the log, never to the courtroom.
_REASONS = {
    FailureClass.TIMEOUT: "the model took too long to answer",
    FailureClass.NETWORK: "we could not reach the model provider",
    FailureClass.RATE_LIMIT: "the model provider is rate-limiting our requests",
    FailureClass.PROVIDER_ERROR: "the model provider hit an internal error",
    FailureClass.EMPTY_CONTENT: "the model replied with no usable text",
    FailureClass.MALFORMED_RESPONSE: "the model provider sent a reply we could not read",
    FailureClass.INVALID_VERDICT: "the judge did not return a verdict in the required format",
    FailureClass.AUTH: "our access to the model provider was refused",
    FailureClass.PAYMENT: "this model is not available on the current account credits",
    FailureClass.MODEL_UNAVAILABLE: "the configured model is not available at the provider",
    FailureClass.BAD_REQUEST: "the model provider rejected the request as invalid",
    FailureClass.UNKNOWN: "the model call failed for an unexpected reason",
}

_SENTENCES = {
    FailureClass.TIMEOUT: (
        "The model took too long to answer and did not respond within the time limit."
    ),
    FailureClass.NETWORK: (
        "We could not reach the model provider — the connection failed."
    ),
    FailureClass.RATE_LIMIT: (
        "The model provider is rate-limiting our requests and kept refusing this one."
    ),
    FailureClass.PROVIDER_ERROR: (
        "The model provider had an internal error and could not complete this request."
    ),
    FailureClass.EMPTY_CONTENT: (
        "The model answered but produced no usable text."
    ),
    FailureClass.MALFORMED_RESPONSE: (
        "The model provider sent back a reply we could not read."
    ),
    FailureClass.INVALID_VERDICT: (
        "The judge never returned a verdict in the required format, and we do not "
        "guess a verdict from unstructured text."
    ),
    FailureClass.AUTH: (
        "Our access to the model provider was refused, so this call could not be made."
    ),
    FailureClass.PAYMENT: (
        "This model could not be used with the account's current credits."
    ),
    FailureClass.MODEL_UNAVAILABLE: (
        "The model configured for this participant is not available at the provider."
    ),
    FailureClass.BAD_REQUEST: (
        "The model provider rejected this request as invalid."
    ),
    FailureClass.UNKNOWN: (
        "The model call failed for an unexpected reason."
    ),
}


def reason_sentence(failure_class: str) -> str:
    """Full user-facing sentence for a terminal failure."""
    return _SENTENCES.get(failure_class, _SENTENCES[FailureClass.UNKNOWN])


def reason_phrase(failure_class: str) -> str:
    """Short user-facing phrase, used inside retry notices."""
    return _REASONS.get(failure_class, _REASONS[FailureClass.UNKNOWN])


class AgentCallError(Exception):
    def __init__(self, failure_class: str, detail: str, attempts: int = 1):
        self.failure_class = failure_class
        self.detail = detail
        self.attempts = attempts
        self.message = reason_sentence(failure_class)
        super().__init__(f"{failure_class}: {detail}")


class _Failure:
    def __init__(self, failure_class: str, detail: str, retry_after: float | None = None):
        self.failure_class = failure_class
        self.detail = detail
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.failure_class in _RETRYABLE


class ChatResult:
    def __init__(
        self,
        content: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float | None = None,
        parsed: Any = None,
        attempts: int = 1,
    ):
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.cost = cost
        self.parsed = parsed
        # How many calls this participant actually consumed to succeed.
        self.attempts = attempts


_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.openrouter_base_url,
            timeout=httpx.Timeout(settings.request_timeout_seconds),
        )
    return _client


def _classify_status(status_code: int) -> str:
    if status_code == 429:
        return FailureClass.RATE_LIMIT
    if status_code in (401, 403):
        return FailureClass.AUTH
    if status_code == 402:
        return FailureClass.PAYMENT
    if status_code == 404:
        return FailureClass.MODEL_UNAVAILABLE
    if status_code in (400, 422):
        return FailureClass.BAD_REQUEST
    if status_code >= 500:
        return FailureClass.PROVIDER_ERROR
    if status_code in (408, 409, 425):
        return FailureClass.TIMEOUT
    return FailureClass.UNKNOWN


def _parse_retry_after(resp: httpx.Response) -> float | None:
    raw = resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        # Only the delta-seconds form is honored; an HTTP-date is rare here and
        # not worth the parsing surface — we fall back to our own backoff.
        return max(0.0, float(raw.strip()))
    except ValueError:
        return None


def _backoff_delay(retry_number: int, failure: _Failure) -> float:
    if failure.retry_after is not None:
        return min(failure.retry_after, settings.retry_max_delay_seconds)
    delay = settings.retry_base_delay_seconds * (2 ** (retry_number - 1))
    return min(delay, settings.retry_max_delay_seconds)


async def _attempt_call(body: dict, headers: dict) -> ChatResult | _Failure:
    client = get_http_client()
    try:
        resp = await client.post("/chat/completions", json=body, headers=headers)
    except httpx.TimeoutException as e:
        return _Failure(FailureClass.TIMEOUT, f"httpx timeout: {e}")
    except httpx.HTTPError as e:
        return _Failure(FailureClass.NETWORK, f"httpx error: {e}")

    if resp.status_code != 200:
        return _Failure(
            _classify_status(resp.status_code),
            f"HTTP {resp.status_code}: {resp.text[:300]}",
            retry_after=_parse_retry_after(resp),
        )

    try:
        data = resp.json()
        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        usage = data.get("usage") or {}
    except (ValueError, KeyError, IndexError, AttributeError, TypeError) as e:
        return _Failure(FailureClass.MALFORMED_RESPONSE, f"{type(e).__name__}: {e}")

    if not content:
        return _Failure(FailureClass.EMPTY_CONTENT, f"empty content: {resp.text[:300]}")

    return ChatResult(
        content=content,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        cost=usage.get("cost"),
    )


async def call_openrouter(
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None = None,
    json_mode: bool = False,
    validate: Callable[[ChatResult], Any] | None = None,
    on_retry: RetryNotifier | None = None,
    attempts: int | None = None,
) -> ChatResult:
    """One call per participant, with a single shared attempt budget.

    `validate` lets a caller (the judge) reject a syntactically fine response
    whose *content* is unusable, by raising AgentCallError. That rejection
    consumes an attempt from the same budget as an HTTP failure, so the two
    layers never multiply into 2x the calls.
    """
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

    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
    total = attempts if attempts is not None else settings.agent_max_attempts
    max_retries = max(total - 1, 0)

    for attempt in range(1, total + 1):
        outcome = await _attempt_call(body, headers)

        if isinstance(outcome, ChatResult) and validate is not None:
            try:
                outcome.parsed = validate(outcome)
            except AgentCallError as e:
                outcome = _Failure(e.failure_class, e.detail)

        if isinstance(outcome, ChatResult):
            outcome.attempts = attempt
            return outcome

        logger.warning(
            "model %s attempt %d/%d failed (%s): %s",
            model, attempt, total, outcome.failure_class, outcome.detail,
        )

        if not outcome.retryable or attempt == total:
            raise AgentCallError(outcome.failure_class, outcome.detail, attempts=attempt)

        if on_retry is not None:
            await on_retry(attempt, max_retries, reason_phrase(outcome.failure_class))
        await asyncio.sleep(_backoff_delay(attempt, outcome))

    # Unreachable: the loop either returns or raises.
    raise AgentCallError(FailureClass.UNKNOWN, "retry loop exhausted", attempts=total)
