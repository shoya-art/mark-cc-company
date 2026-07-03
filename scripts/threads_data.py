#!/usr/bin/env python3
"""Shared Supabase REST client for Threads automation."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class SupabaseError(RuntimeError):
    """Supabase Data API returned an actionable error."""


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SupabaseError(f"{name} が未設定です。GitHub Secretsを確認してください。")
    return value


class SupabaseClient:
    """Minimal PostgREST client that supports Supabase secret API keys."""

    def __init__(self, base_url: str, secret_key: str):
        self.base_url = base_url.rstrip("/")
        self.secret_key = secret_key

    @classmethod
    def from_env(cls, required: bool = True) -> "SupabaseClient | None":
        base_url = os.environ.get("THREADS_SUPABASE_URL", "").strip()
        secret_key = os.environ.get("THREADS_SUPABASE_SECRET_KEY", "").strip()
        if not base_url and not secret_key and not required:
            return None
        if not base_url:
            base_url = _required_env("THREADS_SUPABASE_URL")
        if not secret_key:
            secret_key = _required_env("THREADS_SUPABASE_SECRET_KEY")
        return cls(base_url, secret_key)

    def _headers(self, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.secret_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ziro-threads-analytics/1.0",
        }
        # Legacy service_role keys are JWTs and may be sent as Bearer tokens.
        # New sb_secret_ keys must be sent through the apikey header only.
        if not self.secret_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self.secret_key}"
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def request(
        self,
        method: str,
        resource: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any = None,
        prefer: str | None = None,
        retries: int = 3,
    ) -> Any:
        query = urllib.parse.urlencode(params or {}, doseq=True, safe="(),.*:")
        url = f"{self.base_url}/rest/v1/{resource.lstrip('/')}"
        if query:
            url = f"{url}?{query}"
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()

        for attempt in range(1, retries + 1):
            request = urllib.request.Request(
                url,
                data=body,
                method=method,
                headers=self._headers(prefer),
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                if exc.code >= 500 and attempt < retries:
                    time.sleep(attempt * 2)
                    continue
                raise SupabaseError(
                    f"Supabase API error (HTTP {exc.code}): {raw[:500]}"
                ) from None
            except urllib.error.URLError as exc:
                if attempt < retries:
                    time.sleep(attempt * 2)
                    continue
                raise SupabaseError(f"Supabaseに接続できません: {exc.reason}") from None

        raise SupabaseError("Supabase API request failed")

    def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"select": columns}
        params.update(filters or {})
        if order:
            params["order"] = order
        if limit is not None:
            params["limit"] = limit
        return self.request("GET", table, params=params) or []

    def upsert(
        self,
        table: str,
        rows: dict[str, Any] | list[dict[str, Any]],
        *,
        on_conflict: str,
    ) -> list[dict[str, Any]]:
        result = self.request(
            "POST",
            table,
            params={"on_conflict": on_conflict},
            payload=rows,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return result or []

    def insert(
        self,
        table: str,
        rows: dict[str, Any] | list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = self.request(
            "POST",
            table,
            payload=rows,
            prefer="return=representation",
        )
        return result or []

    def update(
        self,
        table: str,
        values: dict[str, Any],
        *,
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        result = self.request(
            "PATCH",
            table,
            params=filters,
            payload=values,
            prefer="return=representation",
        )
        return result or []


def safe_isoformat(value: str) -> str:
    """Normalize a Meta timestamp for PostgreSQL without changing its instant."""
    return value.replace("+0000", "+00:00") if value else value
