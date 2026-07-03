#!/usr/bin/env python3
"""Analyze Threads performance and accumulate evidence-backed knowledge."""

from __future__ import annotations

import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import anthropic

try:
    from threads_data import SupabaseClient, SupabaseError
except ModuleNotFoundError:
    from scripts.threads_data import SupabaseClient, SupabaseError


MODEL = "claude-sonnet-4-6"
MIN_SAMPLE_SIZE = 5
ACTIVE_SAMPLE_SIZE = 10
ACTIVE_LIFT = 1.25
DIMENSIONS = (
    ("topic", "topic"),
    ("hook", "hook_type"),
    ("cut", "cut_type"),
    ("psychology", "psychology_type"),
    ("cta", "cta_type"),
    ("timing", "time_slot"),
)


def median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def load_records(client: SupabaseClient, measurement_window: str) -> list[dict]:
    rows = client.select(
        "threads_metric_snapshots",
        columns=(
            "post_id,measurement_window,views,likes,replies,reposts,quotes,shares,"
            "threads_posts(id,threads_post_id,chain_id,post_kind,body,published_at,"
            "permalink,time_slot,topic,hook_type,cut_type,psychology_type,cta_type,"
            "hypothesis,variable_changed,quality_score,generation_metadata)"
        ),
        filters={"measurement_window": f"eq.{measurement_window}"},
        order="views.desc",
    )
    records = []
    for row in rows:
        post = row.pop("threads_posts", None)
        if not post:
            continue
        total = sum(int(row.get(key) or 0) for key in (
            "likes", "replies", "reposts", "quotes", "shares"
        ))
        views = int(row.get("views") or 0)
        records.append({
            **post,
            **row,
            "total_engagements": total,
            "engagement_rate": (total / views) if views else 0.0,
        })
    return records


def chain_facts(records: list[dict]) -> list[dict]:
    chains: dict[str, dict[str, int]] = defaultdict(dict)
    for row in records:
        if row.get("chain_id"):
            chains[row["chain_id"]][row["post_kind"]] = int(row["views"])

    first_ratios = []
    second_ratios = []
    final_step_ratios = []
    final_parent_ratios = []
    for parts in chains.values():
        parent = parts.get("parent", 0)
        if not parent:
            continue
        if "reply_1" in parts:
            first_ratios.append(parts["reply_1"] / parent)
        reply_1 = parts.get("reply_1", 0)
        reply_2 = parts.get("reply_2", 0)
        final_reply = parts.get("final_reply", 0)
        if reply_1 and reply_2:
            second_ratios.append(reply_2 / reply_1)
        if reply_2 and final_reply:
            final_step_ratios.append(final_reply / reply_2)
        if final_reply:
            final_parent_ratios.append(final_reply / parent)

    facts = []
    if first_ratios:
        facts.append({
            "metric": "reply_1_view_ratio",
            "value": round(median(first_ratios), 4),
            "sample_size": len(first_ratios),
        })
    if second_ratios:
        facts.append({
            "metric": "reply_2_view_ratio_from_reply_1",
            "value": round(median(second_ratios), 4),
            "sample_size": len(second_ratios),
        })
    if final_step_ratios:
        facts.append({
            "metric": "final_reply_view_ratio_from_reply_2",
            "value": round(median(final_step_ratios), 4),
            "sample_size": len(final_step_ratios),
        })
    if final_parent_ratios:
        facts.append({
            "metric": "final_reply_view_ratio_from_parent",
            "value": round(median(final_parent_ratios), 4),
            "sample_size": len(final_parent_ratios),
        })
    return facts


def performance_contrast_facts(root_records: list[dict]) -> list[dict]:
    """Persist the observed winner/loser gap before explaining its cause."""
    ranked = sorted(
        root_records,
        key=lambda row: (int(row.get("views") or 0), row.get("engagement_rate") or 0),
        reverse=True,
    )
    if len(ranked) < 2:
        return []
    sample_size = min(5, max(1, len(ranked) // 4))
    top = ranked[:sample_size]
    bottom = ranked[-sample_size:]
    top_median = median([row["views"] for row in top])
    bottom_median = median([row["views"] for row in bottom])
    return [{
        "metric": "top_bottom_views_contrast",
        "top_median_views": round(top_median, 2),
        "bottom_median_views": round(bottom_median, 2),
        "ratio": round(top_median / bottom_median, 4) if bottom_median else None,
        "sample_size_per_group": sample_size,
        "top_post_ids": [row["id"] for row in top],
        "bottom_post_ids": [row["id"] for row in bottom],
    }]


def dimension_findings(root_records: list[dict]) -> list[dict]:
    overall = median([row["views"] for row in root_records])
    if overall <= 0:
        return []
    findings = []
    for category, field in DIMENSIONS:
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in root_records:
            value = (row.get(field) or "").strip()
            if value and value.lower() != "none":
                groups[value].append(row)
        for value, rows in groups.items():
            if len(rows) < MIN_SAMPLE_SIZE:
                continue
            group_median = median([row["views"] for row in rows])
            lift = group_median / overall
            if lift >= 1.15 or lift <= 0.85:
                findings.append({
                    "category": category,
                    "field": field,
                    "value": value,
                    "sample_size": len(rows),
                    "median_views": round(group_median, 2),
                    "overall_median_views": round(overall, 2),
                    "lift": round(lift, 4),
                    "post_ids": [row["id"] for row in rows],
                })
    return findings


def save_knowledge(client: SupabaseClient, finding: dict) -> None:
    positive = finding["lift"] >= 1
    direction = "伸びる傾向" if positive else "伸びにくい傾向"
    rule = (
        f"{finding['field']}が「{finding['value']}」の投稿は、"
        f"72時間表示数が基準より{direction}にある。次回も単独変数として検証する。"
    )
    confidence = min(
        0.95,
        0.50 + min(finding["sample_size"], 20) / 50
        + min(abs(finding["lift"] - 1), 0.25),
    )
    status = (
        "active"
        if finding["sample_size"] >= ACTIVE_SAMPLE_SIZE
        and (finding["lift"] >= ACTIVE_LIFT or finding["lift"] <= 1 / ACTIVE_LIFT)
        else "candidate"
    )
    evidence = (
        f"n={finding['sample_size']}、中央値={finding['median_views']}、"
        f"全体中央値={finding['overall_median_views']}、倍率={finding['lift']}"
    )
    existing = client.select(
        "threads_knowledge",
        columns="id",
        filters={"rule_text": f"eq.{rule}"},
        limit=1,
    )
    values = {
        "category": finding["category"],
        "rule_text": rule,
        "evidence_summary": evidence,
        "evidence_post_ids": finding["post_ids"],
        "sample_size": finding["sample_size"],
        "confidence": round(confidence, 4),
        "status": status,
        "last_validated_at": datetime.now(timezone.utc).isoformat(),
        "applicable_conditions": {"metric": "views", "window": "72h"},
    }
    if existing:
        client.update(
            "threads_knowledge",
            values,
            filters={"id": f"eq.{existing[0]['id']}"},
        )
    else:
        client.insert("threads_knowledge", values)


def language_review(root_records: list[dict], seed_mode: bool = False) -> dict:
    if len(root_records) < MIN_SAMPLE_SIZE or not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "facts": [],
            "problems": [],
            "hypotheses": [],
            "next_tests": [],
            "knowledge_candidates": [],
            "summary": "言語分析に必要な投稿数またはAPIキーが不足しています。",
        }

    ranked = sorted(root_records, key=lambda row: (row["views"], row["engagement_rate"]), reverse=True)
    sample_size = min(5, max(2, len(ranked) // 4))
    selected = ranked[:sample_size] + ranked[-sample_size:]
    payload = [{
        "group": "top" if index < sample_size else "bottom",
        "post_id": row["id"],
        "body": row["body"],
        "views": row["views"],
        "engagement_rate": round(row["engagement_rate"], 4),
        "topic": row.get("topic"),
        "hook_type": row.get("hook_type"),
        "cut_type": row.get("cut_type"),
        "cta_type": row.get("cta_type"),
    } for index, row in enumerate(selected)]

    evidence_label = (
        "既存投稿の成熟後累積値。初期仮説として使い、72時間比較で再検証する"
        if seed_mode else "72時間後の比較可能な数値"
    )
    prompt = f"""あなたはThreads投稿の分析担当です。
以下は上位投稿と下位投稿です。
データの性質: {evidence_label}

{json.dumps(payload, ensure_ascii=False, indent=2)}

ルール:
- 数値から確認できる事実と、原因の仮説を混同しない
- 口調、文言、共感、男性心理、希望、区切り、CTA、読みやすさを比較する
- 1投稿だけを根拠に一般化しない
- 次回テストでは変更要素を1つにする
- 復縁保証や読者否定につながる改善案は禁止

次のJSONだけを返してください。
{{
  "summary": "短い要約",
  "facts": [{{"observation": "数値で確認できること", "post_ids": []}}],
  "problems": [{{"problem": "問題候補", "evidence": "根拠", "confidence": 0.0}}],
  "hypotheses": [{{"hypothesis": "原因仮説", "confidence": 0.0}}],
  "next_tests": [{{"variable": "変える要素1つ", "test": "具体的なテスト", "target_metric": "views等"}}],
  "knowledge_candidates": [{{
    "category": "topic|hook|cut|psychology|tone|readability|cta|timing|other",
    "rule_text": "上位と下位の差から得た再利用可能な仮説",
    "evidence": "上位と下位の具体的な差",
    "post_ids": ["根拠にしたDB投稿ID"],
    "confidence": 0.0
  }}]
}}"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "summary": "言語分析のJSON解析に失敗しました。",
            "facts": [],
            "problems": [],
            "hypotheses": [],
            "next_tests": [],
            "knowledge_candidates": [],
            "raw": text[:2000],
        }


def save_language_knowledge(
    client: SupabaseClient,
    candidates: list[dict],
    *,
    seed_mode: bool,
) -> int:
    allowed_categories = {
        "topic", "hook", "cut", "psychology", "tone",
        "readability", "cta", "timing", "other",
    }
    saved_count = 0
    for candidate in candidates[:10]:
        rule = str(candidate.get("rule_text") or "").strip()
        evidence = str(candidate.get("evidence") or "").strip()
        post_ids = list(dict.fromkeys(candidate.get("post_ids") or []))
        if not rule or not evidence or len(post_ids) < 2:
            continue
        category = candidate.get("category")
        if category not in allowed_categories:
            category = "other"
        confidence = max(0.0, min(float(candidate.get("confidence") or 0), 0.65 if seed_mode else 0.80))
        values = {
            "category": category,
            "rule_text": rule,
            "evidence_summary": evidence,
            "evidence_post_ids": post_ids,
            "sample_size": len(post_ids),
            "confidence": round(confidence, 4),
            "status": "candidate",
            "last_validated_at": datetime.now(timezone.utc).isoformat(),
            "applicable_conditions": {
                "source": "historical_seed" if seed_mode else "72h_language_comparison",
                "requires_revalidation": True,
            },
        }
        existing = client.select(
            "threads_knowledge",
            columns="id",
            filters={"rule_text": f"eq.{rule}"},
            limit=1,
        )
        if existing:
            client.update(
                "threads_knowledge",
                values,
                filters={"id": f"eq.{existing[0]['id']}"},
            )
        else:
            client.insert("threads_knowledge", values)
        saved_count += 1
    return saved_count


def analyze() -> int:
    client = SupabaseClient.from_env(required=True)
    now = datetime.now(timezone.utc)
    standard_records = load_records(client, "72h")
    standard_roots = [
        row for row in standard_records if row["post_kind"] in {"single", "parent"}
    ]
    seed_mode = len(standard_roots) < MIN_SAMPLE_SIZE
    if seed_mode:
        cutoff = now - timedelta(days=7)
        seed_records = [
            row for row in load_records(client, "latest")
            if datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")) <= cutoff
        ]
        analysis_records = seed_records
        root_records = [
            row for row in seed_records if row["post_kind"] in {"single", "parent"}
        ]
    else:
        analysis_records = standard_records
        root_records = standard_roots

    if not root_records:
        print("比較可能な投稿データがまだないため、分析をスキップします。")
        return 0

    findings = dimension_findings(standard_roots) if not seed_mode else []
    for finding in findings:
        save_knowledge(client, finding)

    review = language_review(root_records, seed_mode=seed_mode)
    language_knowledge_count = save_language_knowledge(
        client,
        review.get("knowledge_candidates", []),
        seed_mode=seed_mode,
    )
    facts = [{
        "metric": "median_views_historical" if seed_mode else "median_views_72h",
        "value": round(median([row["views"] for row in root_records]), 2),
        "sample_size": len(root_records),
        "evidence_type": "provisional_seed" if seed_mode else "standardized_72h",
    }, *performance_contrast_facts(root_records), *chain_facts(analysis_records),
        *review.get("facts", [])]

    oldest = min(datetime.fromisoformat(row["published_at"].replace("Z", "+00:00")) for row in root_records)
    client.insert("threads_analysis_runs", {
        "analysis_type": "daily",
        "period_start": oldest.isoformat(),
        "period_end": now.isoformat(),
        "posts_analyzed": len(root_records),
        "summary": review.get("summary") or f"{len(root_records)}件を分析しました。",
        "facts": facts,
        "problems": review.get("problems", []),
        "hypotheses": review.get("hypotheses", []),
        "next_tests": review.get("next_tests", []),
        "model_name": MODEL if os.environ.get("ANTHROPIC_API_KEY") else None,
        "prompt_version": "threads-analysis-v1",
    })
    print(
        f"分析完了: posts={len(root_records)}, seed_mode={seed_mode}, "
        f"findings={len(findings)}, language_knowledge={language_knowledge_count}, "
        f"next_tests={len(review.get('next_tests', []))}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(analyze())
    except (SupabaseError, anthropic.APIError, ValueError) as exc:
        print(f"::error title=Threads Analytics::{exc}")
        sys.exit(1)
