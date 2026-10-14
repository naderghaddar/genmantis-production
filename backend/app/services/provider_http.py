import time
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from threading import Event, Lock
from typing import Any, Callable

import httpx


class ProviderLogFilter(logging.Filter):
    """httpx logs request URLs at INFO; redact query credentials and contact emails."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(r"(?i)([?&](?:key|api_key|token|email)=)[^&\s\"']+", r"\1REDACTED", record.getMessage())
        record.args = ()
        return True


logging.getLogger("httpx").addFilter(ProviderLogFilter())


class ProviderError(Exception):
    """Safe reason codes only; never propagate URLs, credentials or response details."""
    def __init__(self, provider: str, reason: str, halt_provider: bool = False):
        self.reason = f"{provider}_{reason}"
        self.halt_provider = halt_provider
        super().__init__(self.reason)


class ProviderHTTP:
    def __init__(self, client: httpx.Client, provider: str, retries: int = 2,
                 interval: float = 0.25, sleep: Callable[[float], None] = time.sleep, cancel: Event | None = None):
        self.client, self.provider = client, provider
        self.retries, self.interval, self.sleep = retries, interval, sleep
        self._lock = Lock()
        self._next_call = 0.0
        self._disabled: ProviderError | None = None
        self.cancel = cancel

    def _wait(self, seconds: float) -> None:
        if self.cancel:
            if self.cancel.wait(seconds):
                raise ProviderError(self.provider, "pipeline_cancelled")
        else:
            self.sleep(seconds)

    def _pace(self) -> None:
        with self._lock:
            if self._disabled:
                raise self._disabled
            self._wait(max(0, self._next_call - time.monotonic()))
            self._next_call = time.monotonic() + self.interval

    def disable(self, error: ProviderError) -> None:
        with self._lock:
            self._disabled = error

    @staticmethod
    def retry_delay(response: httpx.Response | None, attempt: int) -> float:
        value = response.headers.get("Retry-After", "") if response else ""
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError):
                seconds = 2 ** attempt
        return max(0, seconds)

    def get(self, url: str, *, params: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            self._pace()
            response = None
            try:
                response = self.client.get(url, params=params, headers=headers)
            except httpx.TransportError:
                if attempt < self.retries:
                    self._wait(2 ** attempt)
                    continue
                raise ProviderError(self.provider, "network_error") from None
            try:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError
            except ValueError:
                payload = {}
            errors = payload.get("errors", [])
            if isinstance(errors, dict):
                errors = [errors]
            ids = {str(error.get("id", "")) for error in errors if isinstance(error, dict)} if isinstance(errors, list) else set()
            # Hunter documents 429 as usage exhaustion and 403 as rate limiting.
            quota = bool(ids & {"too_many_requests", "credits_exhausted", "insufficient_credits", "usage_limit_reached"})
            quota |= self.provider == "hunter" and response.status_code == 429 and not ids & {"rate_limit", "rate_limit_exceeded"}
            nb_status = payload.get("status")
            quota |= nb_status in {"insufficient_credit", "insufficient_credits"}
            message = str(payload.get("message", "")).casefold()
            quota |= self.provider == "neverbounce" and nb_status == "general_failure" and "credit" in message and any(word in message for word in ("insufficient", "exhausted", "not enough"))
            auth = response.status_code == 401 or nb_status in {"auth_failure", "invalid_api_key"}
            privacy = response.status_code == 451 or bool(ids & {"privacy_denial", "privacy_suppression"})
            transient = response.status_code >= 500 or response.status_code == 429 or nb_status in {"temp_unavail", "throttle_triggered"}
            transient |= self.provider == "hunter" and response.status_code == 403 and (not ids or bool(ids & {"rate_limit", "rate_limit_exceeded"}))
            if quota or auth:
                error = ProviderError(self.provider, "quota_exhausted" if quota else "authentication_error", True)
                self.disable(error)
                raise error
            if privacy:
                raise ProviderError(self.provider, "privacy_suppressed")
            if transient:
                if attempt < self.retries:
                    delay = self.retry_delay(response, attempt)
                    # A long cooldown is recorded rather than retried too early or holding workers indefinitely.
                    if delay > 30:
                        error = ProviderError(self.provider, "rate_limit_cooldown", True)
                        self.disable(error)
                        raise error
                    with self._lock:
                        self._next_call = max(self._next_call, time.monotonic() + delay)
                    self._wait(delay)
                    continue
                raise ProviderError(self.provider, "temporarily_unavailable")
            if self.provider == "neverbounce" and nb_status != "success":
                error = ProviderError(self.provider, "permission_error" if nb_status == "bad_referrer" else "request_error", nb_status == "bad_referrer")
                if error.halt_provider:
                    self.disable(error)
                raise error
            if not response.is_success or errors:
                known = ids & {"pagination_error", "wrong_params", "invalid_domain", "no_domain_search_access", "invalid_type"}
                reason = next(iter(sorted(known)), "permission_error" if response.status_code == 403 else "request_error")
                raise ProviderError(self.provider, reason)
            if not payload:
                raise ProviderError(self.provider, "invalid_response")
            return payload
        raise ProviderError(self.provider, "request_error")
