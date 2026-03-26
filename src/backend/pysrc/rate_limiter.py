from __future__ import annotations

from .web_types import Json
import functools
import threading
import time
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


class GraphQLThrottled(Exception):
    """Raised when Shopify signals rate limiting; carries optional Retry-After hint."""
    retry_after_seconds: float | None = None

    def __init__(self, retry_after_seconds: float | None = None) -> None:
        super().__init__()
        self.retry_after_seconds = retry_after_seconds


def is_graphql_throttled_payload(payload: Json.Value) -> bool:
    """True if the JSON body indicates GraphQL throttling (HTTP 200 with errors)."""
    if not isinstance(payload, dict):
        return False
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return False
    for e in errors:
        if not isinstance(e, dict):
            continue
        msg = str(e.get("message") or "").lower()
        if "throttl" in msg:
            return True
        ext = e.get("extensions")
        if isinstance(ext, dict):
            code = str(ext.get("code") or "").upper()
            if "THROTTLE" in code:
                return True
    return False


def graphql_rate_limit(
    *,
    min_interval_seconds: float = 0.15,
    throttle_cooldown_seconds: float = 0.65,
    max_throttle_retries: int = 12,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator: spaces out calls (min_interval_seconds) and retries on throttle.

    Retries when the wrapped function raises GraphQLThrottled (HTTP 429 or
    throttled GraphQL error payload).
    """
    lock = threading.Lock()
    last_start: list[float] = [0.0]

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            throttle_retries = 0
            while True:
                with lock:
                    now = time.monotonic()
                    wait = last_start[0] + min_interval_seconds - now
                    if wait > 0:
                        time.sleep(wait)
                    last_start[0] = time.monotonic()
                try:
                    result = fn(*args, **kwargs)
                except GraphQLThrottled as ex:
                    throttle_retries += 1
                    if throttle_retries > max_throttle_retries:
                        raise RuntimeError(
                            f"Shopify GraphQL throttled after {max_throttle_retries} retries"
                        ) from ex
                    delay = (
                        ex.retry_after_seconds
                        if ex.retry_after_seconds is not None
                        else throttle_cooldown_seconds
                    )
                    time.sleep(delay)
                    continue
                return result

        return wrapper

    return decorator
