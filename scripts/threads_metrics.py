#!/usr/bin/env python3
"""Collect Threads post insights and persist cumulative snapshots in Supabase."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from threads_data import SupabaseClient, SupabaseError, safe_isoformat
except ModuleNotFoundError:
    from scripts.threads_data import SupabaseClient, SupabaseError, safe_isoformat


THREADS_API_BASE = "https://graph.threads.net/v1.0"
METRICS = ("views", "likes", "replies", "reposts", "quotes", "shares")
WINDOWS = (
    ("24h", 24, 48),
    ("72h", 72, 96),
    ("7d", 168, 216),
)


class InsightsError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise InsightsError(f"{name} が未設定です。")
    return value


def threads_get(path: str, params: dict) -> dict:
    url = f"{THREADS_API_BASE}/{path.lstrip('/')}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "ziro-threads-analytics/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise InsightsError(f"Threads API error (HTTP {exc.code}): {body[:500]}") from None
    except urllib.error.URLError as exc:
        raise InsightsError(f"Threads APIに接続できません: {exc.reason}") from None


def fetch_post_details(post_id: str, token: str) -> dict:
    return threads_get(post_id, {
        "fields": "id,text,timestamp,permalink,username,media_type",
        "access_token": token,
    })


def fetch_insights(post_id: str, token: str) -> tuple[dict[str, int], dict]:
    requested = list(METRICS)
    try:
        response = threads_get(f"{post_id}/insights", {
            "metric": ",".join(requested),
            "access_token": token,
        })
    except InsightsError as exc:
        # Some API versions/accounts do not return shares for every media type.
        if "shares" not in str(exc).lower():
            raise
        requested.remove("shares")
        response = threads_get(f"{post_id}/insights", {
            "metric": ",".join(requested),
            "access_token": token,
        })

    values = {metric: 0 for metric in METRICS}
    for item in response.get("data", []):
        name = item.get("name")
        if name not in values:
            continue
        value = item.get("value")
        if value is None and item.get("values"):
            value = item["values"][0].get("value")
        if isinstance(value, dict):
            value = value.get("value", 0)
        values[name] = int(value or 0)
    return values, response


def parse_timestamp(value: str) -> datetime:
    normalized = safe_isoformat(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def due_windows(age_hours: float, existing: set[str]) -> list[str]:
    due = []
    for name, minimum, maximum in WINDOWS:
        if name not in existing and minimum <= age_hours < maximum:
            due.append(name)
    return due


def collect() -> int:
    token = require_env("THREADS_ACCESS_TOKEN")
    client = SupabaseClient.from_env(required=True)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=9)).isoformat()
    posts = client.select(
        "threads_posts",
        columns="id,threads_post_id,published_at,permalink",
        filters={"published_at": f"gte.{cutoff}"},
        order="published_at.asc",
    )

    updated = 0
    failures = 0
    for post in posts:
        post_id = post["threads_post_id"]
        try:
            published_at = parse_timestamp(post["published_at"])
            age_hours = max(0.0, (now - published_at).total_seconds() / 3600)
            snapshots = client.select(
                "threads_metric_snapshots",
                columns="measurement_window",
                filters={"post_id": f"eq.{post['id']}"},
            )
            existing = {row["measurement_window"] for row in snapshots}
            metrics, raw = fetch_insights(post_id, token)
            collected_at = now.isoformat()
            rows = [{
                "post_id": post["id"],
                "measurement_window": "latest",
                "collected_at": collected_at,
                **metrics,
                "raw_response": raw,
            }]
            rows.extend({
                "post_id": post["id"],
                "measurement_window": window,
                "collected_at": collected_at,
                **metrics,
                "raw_response": raw,
            } for window in due_windows(age_hours, existing))
            client.upsert(
                "threads_metric_snapshots",
                rows,
                on_conflict="post_id,measurement_window",
            )

            if not post.get("permalink"):
                details = fetch_post_details(post_id, token)
                patch = {
                    "permalink": details.get("permalink"),
                    "username": details.get("username"),
                    "media_type": details.get("media_type") or "TEXT",
                }
                client.update(
                    "threads_posts",
                    {key: value for key, value in patch.items() if value is not None},
                    filters={"id": f"eq.{post['id']}"},
                )
            updated += 1
            print(f"Insights更新: {post_id} ({age_hours:.1f}h)")
        except (InsightsError, SupabaseError, ValueError, KeyError) as exc:
            failures += 1
            print(f"::warning title=Threads Insights::{post_id}: {exc}")

    print(f"Insights収集完了: success={updated}, failed={failures}, total={len(posts)}")
    return 1 if posts and updated == 0 else 0


if __name__ == "__main__":
    try:
        sys.exit(collect())
    except (InsightsError, SupabaseError) as exc:
        print(f"::error title=Threads Insights::{exc}")
        sys.exit(1)
