#!/usr/bin/env python3
"""Send the latest Threads analysis result through LINE Messaging API."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:
    from threads_data import SupabaseClient, SupabaseError
except ModuleNotFoundError:
    from scripts.threads_data import SupabaseClient, SupabaseError


LINE_TEXT_LIMIT = 5000
JST = timezone(timedelta(hours=9))


class LineNotificationError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LineNotificationError(f"{name} が未設定です。GitHub Secretsを確認してください。")
    return value


def _list(value: object) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return _list(parsed)
    return []


def _first_text(items: list[dict], *keys: str) -> str:
    for item in items:
        for key in keys:
            value = str(item.get(key) or "").strip()
            if value:
                return value
    return ""


def _metric(facts: list[dict], name: str) -> dict | None:
    return next((fact for fact in facts if fact.get("metric") == name), None)


def _percent(value: object) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except (TypeError, ValueError):
        return "-"


def format_analysis_message(run: dict) -> str:
    facts = _list(run.get("facts"))
    problems = _list(run.get("problems"))
    hypotheses = _list(run.get("hypotheses"))
    next_tests = _list(run.get("next_tests"))
    created_at = str(run.get("created_at") or "")
    try:
        date_label = datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        ).astimezone(JST).strftime("%m/%d")
    except ValueError:
        date_label = "最新"

    lines = [
        f"【Threads日次分析 {date_label}】",
        f"対象：{int(run.get('posts_analyzed') or 0)}投稿",
        "",
        str(run.get("summary") or "分析が完了しました。").strip(),
    ]

    contrast = _metric(facts, "top_bottom_views_contrast")
    if contrast:
        ratio = contrast.get("ratio")
        ratio_label = f"{float(ratio):.1f}倍" if ratio is not None else "算出不可"
        lines.extend([
            "",
            "■ 上位・下位の差",
            f"上位中央値：{int(float(contrast.get('top_median_views') or 0)):,}表示",
            f"下位中央値：{int(float(contrast.get('bottom_median_views') or 0)):,}表示",
            f"差：{ratio_label}",
        ])

    chain_metrics = (
        ("reply_1_view_ratio", "親→追いコメント①"),
        ("reply_2_view_ratio_from_reply_1", "①→②"),
        ("final_reply_view_ratio_from_reply_2", "②→最終"),
    )
    chain_lines = []
    for metric_name, label in chain_metrics:
        fact = _metric(facts, metric_name)
        if fact:
            chain_lines.append(f"{label}：{_percent(fact.get('value'))}")
    if chain_lines:
        lines.extend(["", "■ チェーン継続率", *chain_lines])

    problem = _first_text(problems, "problem", "observation")
    hypothesis = _first_text(hypotheses, "hypothesis")
    if problem:
        lines.extend(["", "■ 問題候補", problem])
    if hypothesis:
        lines.extend(["", "■ 原因仮説", hypothesis])

    if next_tests:
        test = next_tests[0]
        variable = str(test.get("variable") or "").strip()
        description = str(test.get("test") or "").strip()
        target = str(test.get("target_metric") or "").strip()
        lines.extend(["", "■ 次回の検証"])
        if variable:
            lines.append(f"変更するもの：{variable}")
        if description:
            lines.append(description)
        if target:
            lines.append(f"確認指標：{target}")

    lines.extend(["", "※高低差は事実、原因は検証中の仮説です。"])
    return "\n".join(lines)[:LINE_TEXT_LIMIT]


def load_latest_analysis(client: SupabaseClient) -> dict:
    rows = client.select(
        "threads_analysis_runs",
        columns=(
            "id,created_at,posts_analyzed,summary,facts,problems,hypotheses,next_tests"
        ),
        order="created_at.desc",
        limit=1,
    )
    if not rows:
        raise LineNotificationError("通知できるThreads分析結果がまだありません。")
    return rows[0]


def send_relay_message(message: str, relay_url: str, relay_secret: str) -> None:
    payload = json.dumps({"message": message}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        relay_url,
        data=payload,
        method="POST",
        headers={
            "x-threads-notify-secret": relay_secret,
            "Content-Type": "application/json",
            "User-Agent": "ziro-threads-analytics/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in {200, 201, 202}:
                raise LineNotificationError(f"LINE通知中継に失敗しました (HTTP {response.status})")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LineNotificationError(
            f"LINE通知中継 error (HTTP {exc.code}): {body[:300]}"
        ) from None
    except urllib.error.URLError as exc:
        raise LineNotificationError(f"LINE通知中継に接続できません: {exc.reason}") from None


def notify() -> int:
    relay_url = require_env("THREADS_LINE_NOTIFY_URL")
    relay_secret = require_env("THREADS_LINE_NOTIFY_SECRET")
    client = SupabaseClient.from_env(required=True)
    run = load_latest_analysis(client)
    send_relay_message(format_analysis_message(run), relay_url, relay_secret)
    print(f"LINE通知完了: analysis_run_id={run['id']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(notify())
    except (LineNotificationError, SupabaseError) as exc:
        print(f"::error title=Threads LINE通知::{exc}")
        sys.exit(1)
