#!/usr/bin/env python3
"""Create and send one decision-ready report for each new 24-hour post snapshot."""

from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

import anthropic

try:
    from threads_data import SupabaseClient, SupabaseError
    from threads_notify_line import (
        LineNotificationError,
        require_env,
        send_relay_message,
    )
except ModuleNotFoundError:
    from scripts.threads_data import SupabaseClient, SupabaseError
    from scripts.threads_notify_line import (
        LineNotificationError,
        require_env,
        send_relay_message,
    )


MODEL = "claude-sonnet-4-6"
JST = timezone(timedelta(hours=9))
ROOT_KINDS = {"single", "parent"}
METRIC_LABELS = (
    ("views", "表示"),
    ("likes", "いいね"),
    ("replies", "返信"),
    ("reposts", "再投稿"),
    ("quotes", "引用"),
    ("shares", "シェア"),
)
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "result_summary": {"type": "string"},
        "reason_hypothesis": {"type": "string"},
        "keep": {"type": "string"},
        "change": {"type": "string"},
        "next_post_plan": {"type": "string"},
    },
    "required": [
        "result_summary",
        "reason_hypothesis",
        "keep",
        "change",
        "next_post_plan",
    ],
    "additionalProperties": False,
}


def _json_list(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            return _json_list(json.loads(value))
        except json.JSONDecodeError:
            return []
    return []


def load_24h_roots(client: SupabaseClient) -> list[dict]:
    rows = client.select(
        "threads_metric_snapshots",
        columns=(
            "post_id,collected_at,views,likes,replies,reposts,quotes,shares,"
            "threads_posts(id,threads_post_id,chain_id,post_kind,body,published_at,"
            "permalink,time_slot,topic,hook_type,cut_type,psychology_type,cta_type)"
        ),
        filters={"measurement_window": "eq.24h"},
        order="collected_at.asc",
    )
    records = []
    for row in rows:
        post = row.pop("threads_posts", None)
        if not post or post.get("post_kind") not in ROOT_KINDS:
            continue
        records.append({**post, **row})
    return records


def reported_post_ids(client: SupabaseClient) -> set[str]:
    rows = client.select(
        "threads_analysis_runs",
        columns="facts",
        filters={"analysis_type": "eq.manual"},
        order="created_at.desc",
        limit=2000,
    )
    result = set()
    for row in rows:
        for fact in _json_list(row.get("facts")):
            if fact.get("metric") == "post_24h_report" and fact.get("post_id"):
                result.add(str(fact["post_id"]))
    return result


def metric_medians(records: list[dict]) -> dict[str, float]:
    return {
        metric: float(statistics.median([int(row.get(metric) or 0) for row in records]))
        for metric, _ in METRIC_LABELS
    } if records else {}


def select_baseline(records: list[dict], current: dict) -> list[dict]:
    """Compare like with like when enough historical examples exist."""
    published_at = str(current.get("published_at") or "")
    previous = [
        row for row in records
        if str(row.get("published_at") or "") < published_at
        and row["id"] != current["id"]
    ]
    same_kind_slot = [
        row for row in previous
        if row.get("post_kind") == current.get("post_kind")
        and row.get("time_slot") == current.get("time_slot")
    ]
    if len(same_kind_slot) >= 5:
        return same_kind_slot[-30:]
    same_kind = [
        row for row in previous
        if row.get("post_kind") == current.get("post_kind")
    ]
    if len(same_kind) >= 5:
        return same_kind[-30:]
    return previous[-30:]


def performance_label(views: int, baseline_views: float | None) -> tuple[str, float | None]:
    if baseline_views is None or baseline_views <= 0:
        return "比較データ不足", None
    ratio = views / baseline_views
    if ratio >= 1.25:
        return "伸びた", ratio
    if ratio <= 0.75:
        return "伸びていない", ratio
    return "平均的", ratio


def comparison_rows(current: dict, baseline: dict[str, float]) -> list[str]:
    rows = []
    for metric, label in METRIC_LABELS:
        value = int(current.get(metric) or 0)
        median = baseline.get(metric)
        if median is None:
            rows.append(f"{label}：{value:,}（比較データ不足）")
            continue
        delta = value - median
        sign = "+" if delta >= 0 else ""
        rows.append(f"{label}：{value:,}（過去中央値 {median:,.0f}／{sign}{delta:,.0f}）")
    return rows


def generate_plan(current: dict, baseline: dict[str, float], label: str) -> dict:
    api_key = require_env("ANTHROPIC_API_KEY")
    payload = {
        "post": {
            "body": current.get("body"),
            "topic": current.get("topic"),
            "hook_type": current.get("hook_type"),
            "cut_type": current.get("cut_type"),
            "psychology_type": current.get("psychology_type"),
            "cta_type": current.get("cta_type"),
        },
        "metrics_24h": {
            metric: int(current.get(metric) or 0) for metric, _ in METRIC_LABELS
        },
        "past_24h_medians": baseline,
        "performance_label": label,
    }
    prompt = f"""あなたはジローのThreads投稿改善担当です。
次の1投稿について、24時間実績と過去投稿中央値を比較してください。

{json.dumps(payload, ensure_ascii=False, indent=2)}

制約:
- 数値で確認できる結果と、原因の仮説を区別する
- 読者への共感、彼の心理説明、希望、区切り、読みやすさ、CTAを見る
- 次回は一度に1要素だけ変える
- 投稿の丸写し、復縁保証、読者否定は禁止
- 抽象語ではなく、次に書く投稿が想像できる具体案にする
- next_post_planには「扱う悩み・切り口・冒頭2行の案」を含める
- 各項目は日本語で120文字以内
"""
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        tools=[{
            "name": "submit_post_report",
            "description": "24時間投稿分析を構造化して提出する",
            "input_schema": REPORT_SCHEMA,
        }],
        tool_choice={"type": "tool", "name": "submit_post_report"},
        messages=[{"role": "user", "content": prompt}],
    )
    for block in response.content:
        if getattr(block, "type", "") == "tool_use":
            data = getattr(block, "input", None)
            if isinstance(data, dict):
                return data
    raise RuntimeError("Anthropicから構造化された投稿分析が返りませんでした。")


def format_report(
    current: dict,
    baseline: dict[str, float],
    baseline_count: int,
    label: str,
    ratio: float | None,
    plan: dict,
) -> str:
    body = str(current.get("body") or "").strip()
    published = str(current.get("published_at") or "")
    try:
        date_label = datetime.fromisoformat(
            published.replace("Z", "+00:00")
        ).astimezone(JST).strftime("%m/%d %H:%M")
    except ValueError:
        date_label = "日時不明"
    ratio_text = f"（過去中央値の{ratio:.2f}倍）" if ratio is not None else ""
    try:
        measured_hours = (
            datetime.fromisoformat(str(current.get("collected_at")).replace("Z", "+00:00"))
            - datetime.fromisoformat(published.replace("Z", "+00:00"))
        ).total_seconds() / 3600
        measured_label = f"計測時点：投稿から{measured_hours:.1f}時間"
    except (TypeError, ValueError):
        measured_label = "計測時点：投稿から約24時間"
    lines = [
        f"【Threads 24時間レポート｜{date_label}】",
        "",
        "■ 投稿した内容",
        body,
    ]
    if current.get("permalink"):
        lines.append(str(current["permalink"]))
    lines.extend([
        "",
        "■ 投稿から24時間後のデータ",
        measured_label,
        *[f"{label_name}：{int(current.get(metric) or 0):,}" for metric, label_name in METRIC_LABELS],
        "保存：Threads APIでは取得対象外",
        "",
        f"■ 過去{baseline_count}投稿との比較",
        *comparison_rows(current, baseline),
        f"総合判定：{label}{ratio_text}",
        "",
        "■ 今回の見立て",
        str(plan.get("result_summary") or "").strip(),
        f"原因仮説：{str(plan.get('reason_hypothesis') or '').strip()}",
        "",
        "■ 次の投稿方針",
        f"残す：{str(plan.get('keep') or '').strip()}",
        f"変える：{str(plan.get('change') or '').strip()}",
        f"次に出す投稿：{str(plan.get('next_post_plan') or '').strip()}",
        "",
        "※原因は仮説です。次回は1要素だけ変えて検証します。",
    ])
    return "\n".join(lines)[:4500]


def save_report(
    client: SupabaseClient,
    current: dict,
    label: str,
    ratio: float | None,
    plan: dict,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    client.insert("threads_analysis_runs", {
        "analysis_type": "manual",
        "period_start": current.get("published_at") or now,
        "period_end": current.get("collected_at") or now,
        "posts_analyzed": 1,
        "summary": str(plan.get("result_summary") or label),
        "facts": [{
            "metric": "post_24h_report",
            "post_id": current["id"],
            "threads_post_id": current["threads_post_id"],
            "performance_label": label,
            "views_ratio": ratio,
        }],
        "problems": [],
        "hypotheses": [{"hypothesis": plan.get("reason_hypothesis")}],
        "next_tests": [{
            "variable": plan.get("change"),
            "test": plan.get("next_post_plan"),
            "target_metric": "views_24h",
        }],
        "model_name": MODEL,
        "prompt_version": "threads-post-report-v1",
    })


def run() -> int:
    relay_url = require_env("THREADS_LINE_NOTIFY_URL")
    relay_secret = require_env("THREADS_LINE_NOTIFY_SECRET")
    client = SupabaseClient.from_env(required=True)
    records = load_24h_roots(client)
    already_reported = reported_post_ids(client)
    pending = [row for row in records if str(row["id"]) not in already_reported]
    if not pending:
        print("新しい24時間投稿レポートはありません。")
        return 0

    sent = 0
    for current in pending:
        baseline_records = select_baseline(records, current)
        baseline = metric_medians(baseline_records)
        label, ratio = performance_label(
            int(current.get("views") or 0),
            baseline.get("views"),
        )
        plan = generate_plan(current, baseline, label)
        message = format_report(
            current,
            baseline,
            len(baseline_records),
            label,
            ratio,
            plan,
        )
        send_relay_message(message, relay_url, relay_secret)
        save_report(client, current, label, ratio, plan)
        sent += 1
        print(f"24時間レポート通知完了: {current['threads_post_id']}")
    print(f"24時間レポート完了: sent={sent}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except (
        anthropic.APIError,
        LineNotificationError,
        RuntimeError,
        SupabaseError,
        ValueError,
    ) as exc:
        print(f"::error title=Threads 24時間レポート::{exc}")
        sys.exit(1)
