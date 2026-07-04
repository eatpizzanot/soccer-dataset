"""Minimal, polite API-Football (api-sports.io) client.

Handles auth, retries, rate-limit backoff, and the standard response envelope. Reused by
league discovery and the missing-league ingest. Never logs the API key.
"""
from __future__ import annotations

import time
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from pipeline import config as c


class ApiFootballError(RuntimeError):
    pass


class ApiFootball:
    def __init__(self, min_interval: float = 0.15) -> None:
        self._session = requests.Session()
        self._session.headers[c.APIFOOTBALL_HEADER] = c.apifootball_key()
        self._min_interval = min_interval  # ~6-7 req/s max; well under Mega per-min limits
        self._last = 0.0
        self.request_count = 0

    def _throttle(self) -> None:
        dt = time.time() - self._last
        if dt < self._min_interval:
            time.sleep(self._min_interval - dt)
        self._last = time.time()

    @retry(
        retry=retry_if_exception_type((requests.RequestException, ApiFootballError)),
        wait=wait_exponential(multiplier=2, min=2, max=60),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _raw(self, endpoint: str, params: dict[str, Any] | None) -> dict:
        self._throttle()
        r = self._session.get(f"{c.APIFOOTBALL_BASE}/{endpoint}", params=params or {}, timeout=40)
        self.request_count += 1
        if r.status_code == 429:
            raise ApiFootballError("rate limited (429)")
        r.raise_for_status()
        return r.json()

    def get(self, endpoint: str, params: dict[str, Any] | None = None) -> list[dict]:
        """Return the ``response`` list for a single call, raising on API-level errors."""
        j = self._raw(endpoint, params)
        errors = j.get("errors")
        if errors and (errors if isinstance(errors, list) else True):
            # API-Football returns {} or [] when no errors; a non-empty dict/list is an error
            if (isinstance(errors, dict) and errors) or (isinstance(errors, list) and errors):
                raise ApiFootballError(f"{endpoint} errors: {errors}")
        return j.get("response", []) or []

    def get_paged(self, endpoint: str, params: dict[str, Any] | None = None, max_pages: int = 100) -> list[dict]:
        """Fetch every page of a paginated endpoint (e.g. fixtures)."""
        params = dict(params or {})
        out: list[dict] = []
        page = 1
        while page <= max_pages:
            params["page"] = page
            j = self._raw(endpoint, params)
            errors = j.get("errors")
            if (isinstance(errors, dict) and errors) or (isinstance(errors, list) and errors):
                raise ApiFootballError(f"{endpoint} errors: {errors}")
            out.extend(j.get("response", []) or [])
            paging = j.get("paging", {}) or {}
            total = int(paging.get("total", 1) or 1)
            if page >= total:
                break
            page += 1
        return out
