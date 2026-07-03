#!/usr/bin/env python3
"""Import historical repository logs and current lifetime metrics into Supabase."""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from threads_data import SupabaseClient, SupabaseError
    from threads_metrics import InsightsError, fetch_insights, fetch_post_details
except ModuleNotFoundError:
    from scripts.threads_data import SupabaseClient, SupabaseError
    from scripts.threads_metrics import InsightsError, fetch_insights, fetch_post_details


JST = timezone(timedelta(hours=9))
FIELD_PATTERN = r"\*\*{label}:\*\*\s*(.*?)(?=\n\*\*[^\n]+:\*\*|\n---|\Z)"


def field(entry: str, label: str) -> str:
    match = re.search(FIELD_PATTERN.format(label=re.escape(label)), entry, re.S)
    return match.group(1).strip() if match else ""


def split_entries(text: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(r"(?m)^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$", text))
    entries = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        entries.append((match.group(1), text[match.end():end]))
    return entries


def parse_score(value: str) -> float | None:
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", value)
    return float(match.group(1)) if match else None


def parse_tags(value: str) -> tuple[str | None, str | None]:
    tags = re.findall(r"#([^\s#]+)", value)
    source = tags[0] if tags else None
    slot = tags[1] if len(tags) > 1 and tags[1] in {"morning", "lunch", "evening"} else None
    return source, slot


def published_at(value: str) -> str:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=JST).isoformat()


def parse_legacy_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for date_text, entry in split_entries(path.read_text(encoding="utf-8")):
        post_id = field(entry, "投稿ID")
        body = field(entry, "投稿内容")
        if not post_id or not body:
            continue
        source, slot = parse_tags(field(entry, "タグ"))
        records.append({
            "threads_post_id": post_id,
            "post_kind": "single",
            "body": body,
            "published_at": published_at(date_text),
            "posting_mode": "legacy",
            "time_slot": slot,
            "quality_score": parse_score(field(entry, "品質スコア")),
            "generation_metadata": {
                "historical_import": True,
                "source_post_id": source,
            },
        })
    return records


def parse_chain_log(path: Path) -> list[list[dict]]:
    if not path.exists():
        return []
    chains = []
    labels = (
        ("親投稿", "親投稿ID", "parent"),
        ("追いコメント①", "追いコメント① ID", "reply_1"),
        ("追いコメント②", "追いコメント② ID", "reply_2"),
        ("最終コメント", "最終コメントID", "final_reply"),
    )
    for date_text, entry in split_entries(path.read_text(encoding="utf-8")):
        source, slot = parse_tags(field(entry, "タグ"))
        score = parse_score(field(entry, "品質スコア"))
        parent_id = field(entry, "親投稿ID")
        if not parent_id:
            continue
        chain_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"threads-chain:{parent_id}"))
        records = []
        for body_label, id_label, post_kind in labels:
            post_id = field(entry, id_label)
            body = field(entry, body_label)
            if not post_id or not body:
                continue
            records.append({
                "threads_post_id": post_id,
                "chain_id": chain_id,
                "post_kind": post_kind,
                "body": body,
                "published_at": published_at(date_text),
                "posting_mode": "chain",
                "time_slot": slot,
                "quality_score": score,
                "generation_metadata": {
                    "historical_import": True,
                    "source_post_id": source,
                },
            })
        if records:
            chains.append(records)
    return chains


def enrich_record(record: dict, token: str) -> tuple[dict, dict, dict]:
    details = fetch_post_details(record["threads_post_id"], token)
    metrics, raw = fetch_insights(record["threads_post_id"], token)
    enriched = {
        **record,
        "body": details.get("text") or record["body"],
        "published_at": details.get("timestamp") or record["published_at"],
        "permalink": details.get("permalink"),
        "username": details.get("username"),
        "media_type": details.get("media_type") or "TEXT",
    }
    return enriched, metrics, raw


def store_record(
    client: SupabaseClient,
    record: dict,
    metrics: dict,
    raw: dict,
    parent_db_id: str | None = None,
) -> str:
    payload = {**record, "parent_post_id": parent_db_id}
    saved = client.upsert("threads_posts", payload, on_conflict="threads_post_id")
    db_id = saved[0]["id"]
    client.upsert("threads_metric_snapshots", {
        "post_id": db_id,
        "measurement_window": "latest",
        **metrics,
        "raw_response": raw,
    }, on_conflict="post_id,measurement_window")
    return db_id


def backfill(repo_root: Path, limit: int) -> int:
    import os

    token = os.environ.get("THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        raise InsightsError("THREADS_ACCESS_TOKEN が未設定です。")
    client = SupabaseClient.from_env(required=True)
    legacy = parse_legacy_log(
        repo_root / ".company/marketing/content-plan/threads-log.md"
    )
    chains = parse_chain_log(
        repo_root / ".company/marketing/content-plan/threads-chain-log.md"
    )
    units = [("legacy", [record]) for record in legacy]
    units.extend(("chain", records) for records in chains)
    units.sort(key=lambda item: item[1][0]["published_at"], reverse=True)
    existing_ids = {
        row["threads_post_id"]
        for row in client.select(
            "threads_posts",
            columns="threads_post_id",
            limit=10000,
        )
    }

    imported = 0
    skipped = 0
    failed = 0
    for _, records in units:
        if imported >= limit:
            break
        ids = [record["threads_post_id"] for record in records]
        if all(post_id in existing_ids for post_id in ids):
            skipped += len(ids)
            continue

        root_db_id = None
        try:
            for record in records:
                enriched, metrics, raw = enrich_record(record, token)
                db_id = store_record(
                    client,
                    enriched,
                    metrics,
                    raw,
                    root_db_id if record["post_kind"] not in {"parent", "single"} else None,
                )
                if record["post_kind"] in {"parent", "single"}:
                    root_db_id = db_id
                imported += 1
                existing_ids.add(record["threads_post_id"])
                print(f"履歴取込: {record['threads_post_id']}")
        except (InsightsError, SupabaseError, KeyError) as exc:
            failed += len(records)
            print(f"::warning title=Threads Backfill::{ids[0]}: {exc}")

    print(f"履歴取込完了: imported={imported}, skipped={skipped}, failed={failed}")
    return 1 if units and imported == 0 and skipped == 0 else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--limit", type=int, default=25)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        sys.exit(backfill(Path(args.repo_root), max(1, args.limit)))
    except (InsightsError, SupabaseError) as exc:
        print(f"::error title=Threads Backfill::{exc}")
        sys.exit(1)
