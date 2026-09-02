import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection
from pymongo.errors import (
    ConnectionFailure,
    ExecutionTimeout,
    NetworkTimeout,
    PyMongoError,
    WriteConcernError,
    WTimeoutError,
)

from app.config import settings

logger = logging.getLogger("tribunal.db")

T = TypeVar("T")

# Transient conditions only: a retry can plausibly succeed. Everything else
# (bad query, auth failure, duplicate key) is permanent and fails immediately.
# ConnectionFailure covers AutoReconnect and ServerSelectionTimeoutError.
_TRANSIENT = (
    ConnectionFailure,
    NetworkTimeout,
    ExecutionTimeout,
    WriteConcernError,
    WTimeoutError,
)

DB_UNAVAILABLE_MESSAGE = (
    "The case archive is temporarily unreachable. Please try again in a moment."
)

_client: AsyncIOMotorClient | None = None


class DatabaseUnavailable(Exception):
    """Raised when an operation still fails after exhausting its retries."""

    def __init__(self, operation: str, detail: str):
        self.operation = operation
        self.detail = detail
        self.message = DB_UNAVAILABLE_MESSAGE
        super().__init__(f"{operation}: {detail}")


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            settings.mongo_uri,
            # Without this the driver hangs on its 30s default before it will
            # admit the server is unreachable, stalling the whole request.
            serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
        )
    return _client


def get_collection() -> AsyncIOMotorCollection:
    return get_client()[settings.mongo_db_name]["trials"]


async def with_retry(
    operation: str,
    fn: Callable[[], Awaitable[T]],
    attempts: int | None = None,
) -> T:
    """Run a Mongo operation with bounded retries on transient failures."""
    total = attempts if attempts is not None else settings.mongo_max_attempts
    for attempt in range(1, total + 1):
        try:
            return await fn()
        except _TRANSIENT as e:
            logger.warning(
                "mongo %s attempt %d/%d failed: %s: %s",
                operation, attempt, total, type(e).__name__, e,
            )
            if attempt == total:
                raise DatabaseUnavailable(operation, f"{type(e).__name__}: {e}") from e
            delay = min(
                settings.retry_base_delay_seconds * (2 ** (attempt - 1)),
                settings.retry_max_delay_seconds,
            )
            await asyncio.sleep(delay)
        except PyMongoError as e:
            # Permanent: retrying an identical bad operation cannot help.
            logger.error("mongo %s failed permanently: %s: %s", operation, type(e).__name__, e)
            raise DatabaseUnavailable(operation, f"{type(e).__name__}: {e}") from e

    raise DatabaseUnavailable(operation, "retry loop exhausted")


async def find_one(query: dict) -> Any:
    return await with_retry("find_one", lambda: get_collection().find_one(query))


async def insert_one(doc: dict) -> Any:
    return await with_retry("insert_one", lambda: get_collection().insert_one(doc))


async def update_one(query: dict, update: dict) -> Any:
    return await with_retry("update_one", lambda: get_collection().update_one(query, update))
