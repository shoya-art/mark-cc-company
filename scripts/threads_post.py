#!/usr/bin/env python3
"""Threads自動投稿スクリプト - 復縁アドバイザー・ジロー"""

import anthropic
import hashlib
import urllib.error
import urllib.request
import urllib.parse
import json
import sys
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
THREADS_API_BASE = "https://graph.threads.net/v1.0"
THREADS_TEXT_LIMIT = 500
CHAIN_STATE_FILENAME = "threads-pending-chain.json"
CHAIN_PART_NAMES = ("親投稿", "追いコメント①", "追いコメント②", "最終コメント")


class ConfigurationError(RuntimeError):
    """Required runtime configuration is missing or inconsistent."""


class ThreadsAPIError(RuntimeError):
    """Threads API returned an actionable error."""


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(
            f"{name} が未設定です。GitHub Actions の Repository secret を確認してください。"
        )
    return value


def token_fingerprint(token: str) -> str:
    """Return a non-reversible identifier for comparing workflow runs."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def action_error(message: str) -> None:
    escaped = str(message).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::error title=Threads自動投稿::{escaped}")


def threads_api_request(url: str, data: bytes = None) -> dict:
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            payload = {}

        api_error = payload.get("error", {})
        code = api_error.get("code")
        subcode = api_error.get("error_subcode")
        message = api_error.get("message") or raw_body[:300] or "詳細なし"

        if code == 190 or subcode in {463, 467}:
            raise ThreadsAPIError(
                "THREADS_ACCESS_TOKEN が無効または期限切れです "
                f"(code={code}, subcode={subcode})。"
                f"Meta response: {message}。"
                "Meta for Developers で有効期限を確認し、Repository secret を更新してください。"
            ) from None

        raise ThreadsAPIError(
            f"Threads API error (HTTP {exc.code}, code={code}, subcode={subcode}): {message}"
        ) from None
    except urllib.error.URLError as exc:
        raise ThreadsAPIError(f"Threads API に接続できません: {exc.reason}") from None


def validate_threads_credentials() -> tuple:
    """Validate the exact token injected into this run before generating a post."""
    token = require_env("THREADS_ACCESS_TOKEN")
    configured_user_id = os.environ.get("THREADS_USER_ID", "26439768865674129").strip()
    fingerprint = token_fingerprint(token)
    event_name = os.environ.get("GITHUB_EVENT_NAME", "local")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")

    print(
        "Threads credential: "
        f"fingerprint={fingerprint}, event={event_name}, run_id={run_id}"
    )

    query = urllib.parse.urlencode({
        "fields": "id,username",
        "access_token": token,
    })
    profile = threads_api_request(f"{THREADS_API_BASE}/me?{query}")
    actual_user_id = str(profile.get("id", ""))

    if not actual_user_id:
        raise ThreadsAPIError(f"Threads ユーザー情報を取得できませんでした: {profile}")
    if configured_user_id and configured_user_id != actual_user_id:
        raise ConfigurationError(
            "THREADS_USER_ID がアクセストークンのユーザーと一致しません。"
            f"設定値={configured_user_id}, API値={actual_user_id}"
        )

    print(f"Threads authentication OK: @{profile.get('username', 'unknown')} ({actual_user_id})")
    return actual_user_id, token


def read_file_safe(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def read_recent_chain_log(repo_root: str, limit: int = 14) -> str:
    """直近のチェーン投稿履歴を返す。CTAと冒頭の連投を避けるために使う。"""
    log_path = f"{repo_root}/.company/marketing/content-plan/threads-chain-log.md"
    log_text = read_file_safe(log_path)
    if not log_text:
        return "（投稿履歴なし）"

    entries = log_text.split("\n## ")
    recent = entries[-limit:]
    return "\n## ".join(recent)


def read_generation_rules(repo_root: str) -> str:
    """完全版、各パーツ、品質検査のスキルを生成プロンプト用に読み込む。"""
    skill_dirs = (
        "create-ziro-threads-chain",
        "write-threads-parent-post",
        "write-threads-reply-one",
        "write-threads-reply-two",
        "write-threads-final-reply",
        "check-threads-reply-chain",
    )
    sections = []
    for skill_name in skill_dirs:
        skill_dir = Path(repo_root) / ".claude-plugin" / "skills" / skill_name
        files = [skill_dir / "SKILL.md"]
        references_dir = skill_dir / "references"
        if references_dir.exists():
            files.extend(sorted(references_dir.glob("*.md")))

        for path in files:
            content = read_file_safe(str(path))
            if content:
                relative_path = path.relative_to(repo_root)
                sections.append(f"### {relative_path}\n{content}")

    if not sections:
        raise ConfigurationError(
            "Threads投稿スキルを読み込めません。.claude-plugin/skills を確認してください。"
        )
    return "\n\n".join(sections)


def extract_section(text: str, name: str) -> str:
    start_markers = (f"---{name}_START---", f"---{name}---")
    end_marker = f"---{name}_END---"
    start_marker = next((marker for marker in start_markers if marker in text), "")
    if not start_marker or end_marker not in text:
        return ""
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    return text[start:end].strip()


def validate_chain_texts(texts: list) -> None:
    if len(texts) != len(CHAIN_PART_NAMES):
        raise ValueError(f"投稿チェーンは4件必要です。取得件数={len(texts)}")

    for part_name, text in zip(CHAIN_PART_NAMES, texts):
        if not text.strip():
            raise ValueError(f"{part_name}が空です。")
        if len(text) > THREADS_TEXT_LIMIT:
            raise ValueError(
                f"{part_name}がThreadsの上限を超えています。"
                f"{len(text)} / {THREADS_TEXT_LIMIT}文字"
            )


def validate_chain_structure(texts: list) -> None:
    """自動判定できる最低限の区切り構造を検査する。"""
    validate_chain_texts(texts)
    for index in range(3):
        if not texts[index].rstrip().endswith("↓"):
            raise ValueError(f"{CHAIN_PART_NAMES[index]}が未完の「↓」で終わっていません。")
    if texts[3].rstrip().endswith("↓"):
        raise ValueError("最終コメントが未完のまま終わっています。")


def validate_quality_gate(status: str, score: float) -> None:
    normalized_status = status.strip().upper()
    if normalized_status != "PASS":
        raise ValueError(
            "品質チェックがPASSではないため投稿を停止しました。"
            f"判定={normalized_status or '未出力'}"
        )
    if score < 8.5:
        raise ValueError(
            "品質スコアが公開基準の8.5点未満のため投稿を停止しました。"
            f"スコア={score:.1f}"
        )


def parse_score_and_header(text: str) -> tuple:
    score = 7.5
    score_text = extract_section(text, "SCORE")
    if score_text:
        try:
            score = float(score_text)
        except ValueError:
            pass

    header_type = extract_section(text, "HEADER_TYPE") or "不明"
    return score, header_type


def generate_legacy_post(time_slot: str, repo_root: str = ".") -> tuple:
    """従来ルールの単体投稿を生成する。"""
    client = anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))
    base = f"{repo_root}/.company/marketing/content-plan/threads-learning"
    source_posts = read_file_safe(f"{base}/source-posts.md")

    slot_config = {
        "morning": {
            "time": "朝の通勤時間帯（7:50 JST）",
            "tier_hint": "Tier1・Tier2を優先（保存・拡散向き）",
        },
        "lunch": {
            "time": "昼休み（12:20 JST）",
            "tier_hint": "Tier3・Tier4を優先（共感・コメント誘導向き）",
        },
        "evening": {
            "time": "夜のリラックスタイム（21:30 JST）",
            "tier_hint": "コメント誘導型を優先（A2・E1・E2系）",
        },
    }
    config = slot_config.get(time_slot, slot_config["morning"])

    prompt = f"""復縁アドバイザー・ジロー（@ziro_fukuen_pro）のThreads投稿を1本書いてください。

【時間帯】{config["time"]}
【今回の優先元ネタ】{config["tier_hint"]}

---

以下は実際にThreadsで伸びた投稿のリストです。
この中から1つ選び、ジローの口調でリライトしてください。

{source_posts if source_posts else "（ファイルなし）"}

---

【リライトのルール】

1. 元ネタの「構造・フレーム」だけを借りる。フレーズの丸コピ禁止
2. ジローはアドバイザー視点で話す（「復縁サポートしてきた経験から」「相談者さんから聞いた話」など）
3. 文体ルール（絶対守る）:
   - です・ます禁止。「だ」「だよ」「から」「よ」で終わる
   - ——（ダッシュ）禁止
   - 概念語禁止（「土台」「本質」「自己肯定感の向上」など説明っぽい言葉）
   - 1文を短く。改行多め
   - 100〜200文字以内（短いほど良い）
4. コメント誘導する場合: 「〜教えてください」「コメントで教えて」をラフに入れる
5. NG: 「頑張れば」「まずは自分磨き」「〜なのです」「業者っぽい表現」

---

以下の形式だけで返してください（説明・前置き不要）:
---POST_START---
（投稿テキストのみ）
---POST_END---
---SCORE---
（ラフさ・人間味の採点、10点満点で数値のみ）
---SCORE_END---
---HEADER_TYPE---
（参照した元ネタのID、例: B1）
---HEADER_TYPE_END---"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.content[0].text
    post_text = extract_section(text, "POST")
    score, header_type = parse_score_and_header(text)

    if not post_text:
        raise ValueError(f"従来投稿の抽出に失敗しました。レスポンス: {text[:500]}")
    if len(post_text) > THREADS_TEXT_LIMIT:
        raise ValueError(
            f"従来投稿がThreadsの上限を超えています。"
            f"{len(post_text)} / {THREADS_TEXT_LIMIT}文字"
        )
    return post_text, score, header_type


def generate_chain_post(time_slot: str, repo_root: str = ".") -> tuple:
    """Claude APIで親投稿と3つの追いコメントを生成する。"""
    client = anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))

    base = f"{repo_root}/.company/marketing/content-plan/threads-learning"
    source_posts = read_file_safe(f"{base}/source-posts.md")
    generation_rules = read_generation_rules(repo_root)
    recent_log = read_recent_chain_log(repo_root)

    slot_config = {
        "morning": {
            "time": "朝の投稿時間帯（7:00 JST）",
            "tier_hint": "Tier1・Tier2を優先（保存・拡散向き）",
        },
        "lunch": {
            "time": "昼休み（12:00 JST）",
            "tier_hint": "Tier3・Tier4を優先（共感・コメント誘導向き）",
        },
        "evening": {
            "time": "夜のリラックスタイム（21:00 JST）",
            "tier_hint": "コメント誘導型を優先（A2・E1・E2系）",
        },
    }
    config = slot_config.get(time_slot, slot_config["morning"])

    prompt = f"""復縁アドバイザー・ジロー（@ziro_fukuen_pro）のThreads投稿チェーンを1組書いてください。
投稿チェーンは「親投稿 → 追いコメント① → 追いコメント② → 最終コメント」の4件です。

【時間帯】{config["time"]}
【今回の優先元ネタ】{config["tier_hint"]}

---

以下は実際にThreadsで伸びた投稿の元ネタです。
この中から1つの悩みを選び、フレーズではなく構造だけを参考にしてください。

{source_posts if source_posts else "（ファイルなし）"}

【投稿スキル／必須ルール】

{generation_rules}

---

【直近14投稿の履歴】
冒頭、テーマ、CTAの重複を避けてください。固定投稿・プロフィールへの直接誘導は、直近履歴を見て全体の20〜30%に収まる場合だけ選んでください。

{recent_log}

---

【全体の必須条件】

1. 4件が同じ悩みを扱い、直前の「…↓」を次の一文目で必ず回収する
2. 親投稿では答えを出さない
3. 追いコメント①は希望を明言し、男性心理を分かりやすく説明する
4. 追いコメント②はNG行動を即回収し、彼の受け取り方と変化までつなぐ
5. 最終コメントは②を回収し、彼に見える変化と前向きな期待を描いて完結させる
6. 各1件を{THREADS_TEXT_LIMIT}文字以内にする
7. 復縁を保証しない。彼の心情を事実のように断定しない
8. ジローは読者を否定せず、希望を残して一緒に進む立場で話す
9. 誰かの投稿のフレーズを複製しない

---

以下の形式だけで返してください（説明・前置き不要）:
---PARENT_START---
（親投稿のみ）
---PARENT_END---
---REPLY_ONE_START---
（追いコメント①のみ）
---REPLY_ONE_END---
---REPLY_TWO_START---
（追いコメント②のみ）
---REPLY_TWO_END---
---FINAL_REPLY_START---
（最終コメントのみ）
---FINAL_REPLY_END---
---QUALITY_STATUS---
（品質チェックスキルの最終判定。PASSのみ）
---QUALITY_STATUS_END---
---SCORE---
（4件全体の共感・分かりやすさ・つながりの採点、10点満点で数値のみ）
---SCORE_END---
---HEADER_TYPE---
（参照した元ネタのID、例: B1）
---HEADER_TYPE_END---"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=5000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text

    chain_texts = [
        extract_section(text, "PARENT"),
        extract_section(text, "REPLY_ONE"),
        extract_section(text, "REPLY_TWO"),
        extract_section(text, "FINAL_REPLY"),
    ]

    score, header_type = parse_score_and_header(text)

    try:
        validate_chain_structure(chain_texts)
    except ValueError as exc:
        raise ValueError(f"{exc} Claude response: {text[:800]}") from exc

    validate_quality_gate(extract_section(text, "QUALITY_STATUS"), score)

    return chain_texts, score, header_type


def post_to_threads(text: str, user_id: str, token: str, reply_to_id: str = None) -> str:
    """Threads APIに投稿する。投稿IDを返す。"""
    # Step 1: メディアコンテナ作成
    payload = {
        "media_type": "TEXT",
        "text": text,
        "access_token": token
    }
    if reply_to_id:
        payload["reply_to_id"] = reply_to_id
    data = urllib.parse.urlencode(payload).encode()

    resp = threads_api_request(f"{THREADS_API_BASE}/{user_id}/threads", data)

    if "id" not in resp:
        raise ValueError(f"コンテナ作成失敗: {resp}")

    creation_id = resp["id"]
    print(f"Container ID: {creation_id}")
    time.sleep(2)

    # Step 2: 公開
    data2 = urllib.parse.urlencode({
        "creation_id": creation_id,
        "access_token": token
    }).encode()

    resp2 = threads_api_request(f"{THREADS_API_BASE}/{user_id}/threads_publish", data2)

    if "id" not in resp2:
        raise ValueError(f"公開失敗: {resp2}")

    return resp2["id"]


def chain_state_path(repo_root: str) -> Path:
    return Path(repo_root) / ".company" / "marketing" / "content-plan" / CHAIN_STATE_FILENAME


def save_chain_state(state: dict, repo_root: str = ".") -> None:
    """公開済みIDを保存する。トークンは含めない。"""
    path = chain_state_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def load_chain_state(repo_root: str = ".") -> dict:
    path = chain_state_path(repo_root)
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigurationError(f"未完了チェーンの状態ファイルが壊れています: {exc}") from exc

    texts = state.get("texts", [])
    published_ids = state.get("published_ids", [])
    validate_chain_texts(texts)
    if state.get("mode", "chain") != "chain":
        raise ConfigurationError("未完了チェーンのモードが不正です。")
    if len(published_ids) > len(texts):
        raise ConfigurationError("未完了チェーンの投稿ID数が不正です。")
    return state


def create_chain_state(texts: list, score: float, header_type: str, time_slot: str) -> dict:
    return {
        "schema_version": 1,
        "mode": "chain",
        "created_at": datetime.now(JST).isoformat(),
        "time_slot": time_slot,
        "texts": texts,
        "score": score,
        "header_type": header_type,
        "published_ids": [],
    }


def publish_chain(state: dict, user_id: str, token: str, repo_root: str = ".") -> list:
    """未公開の先頭要素から順に投稿し、各成功後に状態を保存する。"""
    texts = state["texts"]
    published_ids = state.setdefault("published_ids", [])

    for index in range(len(published_ids), len(texts)):
        reply_to_id = published_ids[-1] if published_ids else None
        part_name = CHAIN_PART_NAMES[index]
        print(f"\n{part_name}をThreadsに投稿中...")
        post_id = post_to_threads(texts[index], user_id, token, reply_to_id=reply_to_id)
        published_ids.append(post_id)
        save_chain_state(state, repo_root)
        print(f"{part_name} POST_ID: {post_id}")

    return published_ids


def append_chain_to_log(chain_texts: list, score: float, header_type: str,
                        post_ids: list, time_slot: str, repo_root: str = "."):
    """threads-chain-log.mdにチェーン投稿を追記する。"""
    log_path = f"{repo_root}/.company/marketing/content-plan/threads-chain-log.md"
    now = datetime.now(JST)

    entry = f"""
## {now.strftime('%Y-%m-%d %H:%M')}

**親投稿:**
{chain_texts[0]}

**追いコメント①:**
{chain_texts[1]}

**追いコメント②:**
{chain_texts[2]}

**最終コメント:**
{chain_texts[3]}

**タグ:** #{header_type} #{time_slot}
**品質スコア:** {score:.1f} / 10
**親投稿ID:** {post_ids[0]}
**追いコメント① ID:** {post_ids[1]}
**追いコメント② ID:** {post_ids[2]}
**最終コメントID:** {post_ids[3]}
**メトリクス（取得時）:** いいね 0 / 返信 0 / 再投稿 0 / 表示 0
**分類:** 未判定（24時間後にanalyzeで更新）
**検証仮説:** なし

---
"""

    log_file = Path(log_path)
    if not log_file.exists():
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("# Threads投稿チェーンログ\n", encoding="utf-8")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)

    print(f"ログ追記: {log_path}")


def append_legacy_to_log(post_text: str, score: float, header_type: str,
                         post_id: str, time_slot: str, repo_root: str = "."):
    """既存のthreads-log.mdへ従来投稿を追記する。"""
    log_path = f"{repo_root}/.company/marketing/content-plan/threads-log.md"
    now = datetime.now(JST)
    entry = f"""
## {now.strftime('%Y-%m-%d %H:%M')}

**投稿内容:**
{post_text}

**タグ:** #{header_type} #{time_slot}
**品質スコア:** {score:.1f} / 10
**投稿ID:** {post_id}
**メトリクス（取得時）:** いいね 0 / 返信 0 / 再投稿 0 / 表示 0
**分類:** 未判定（24時間後にanalyzeで更新）
**検証仮説:** なし

---
"""
    log_file = Path(log_path)
    if not log_file.exists():
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text("# Threads投稿ログ\n", encoding="utf-8")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)
    print(f"ログ追記: {log_path}")


def parse_cli_args(args: list) -> tuple:
    """新形式(mode slot root)と旧形式(slot root)の両方を受け付ける。"""
    valid_modes = {"legacy", "chain"}
    valid_slots = {"morning", "lunch", "evening"}
    if args and args[0] in valid_modes:
        mode = args[0]
        time_slot = args[1] if len(args) > 1 else "morning"
        repo_root = args[2] if len(args) > 2 else "."
    else:
        mode = "legacy"
        time_slot = args[0] if args else "morning"
        repo_root = args[1] if len(args) > 1 else "."

    if time_slot not in valid_slots:
        raise ConfigurationError(f"不明な投稿時間帯です: {time_slot}")
    return mode, time_slot, repo_root


def run_legacy(time_slot: str, repo_root: str, user_id: str, token: str) -> None:
    print("\n従来投稿を生成中...")
    post_text, score, header_type = generate_legacy_post(time_slot, repo_root)
    print(f"\n【生成した従来投稿】（スコア: {score:.1f}、型: {header_type}）")
    print(post_text)
    print("\n従来投稿をThreadsに投稿中...")
    post_id = post_to_threads(post_text, user_id, token)
    append_legacy_to_log(post_text, score, header_type, post_id, time_slot, repo_root)
    print(f"\n✅ 従来投稿の公開に成功しました！ POST_ID: {post_id}")


def run_chain(time_slot: str, repo_root: str, user_id: str, token: str) -> None:
    state = load_chain_state(repo_root)
    if state:
        print(
            "\n未完了の投稿チェーンを検出しました。"
            f"{len(state['published_ids'])} / {len(state['texts'])} 件公開済み。続きから再開します。"
        )
    else:
        print("\n新しい投稿チェーンを生成中...")
        chain_texts, score, header_type = generate_chain_post(time_slot, repo_root)
        state = create_chain_state(chain_texts, score, header_type, time_slot)
        save_chain_state(state, repo_root)

        print(
            f"\n【生成した投稿チェーン】"
            f"（スコア: {score:.1f}、ヘッダー型: {header_type}）"
        )
        for part_name, text in zip(CHAIN_PART_NAMES, chain_texts):
            print(f"\n--- {part_name} ({len(text)}文字) ---")
            print(text)

    post_ids = publish_chain(state, user_id, token, repo_root)
    append_chain_to_log(
        state["texts"],
        float(state.get("score", 7.5)),
        state.get("header_type", "不明"),
        post_ids,
        state.get("time_slot", time_slot),
        repo_root,
    )
    chain_state_path(repo_root).unlink(missing_ok=True)
    print("\n✅ 親投稿と3つの追いコメントの公開に成功しました！")


if __name__ == "__main__":
    try:
        post_mode, time_slot, repo_root = parse_cli_args(sys.argv[1:])
    except ConfigurationError as e:
        action_error(str(e))
        print(f"❌ エラー: {e}")
        sys.exit(1)

    print(f"=== Threads自動投稿 [{post_mode}/{time_slot}] ===")
    print(f"実行時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")

    try:
        print("\nThreads認証を確認中...")
        threads_user_id, threads_token = validate_threads_credentials()

        if post_mode == "legacy":
            run_legacy(time_slot, repo_root, threads_user_id, threads_token)
        else:
            run_chain(time_slot, repo_root, threads_user_id, threads_token)

    except (ConfigurationError, ThreadsAPIError) as e:
        action_error(str(e))
        print(f"❌ エラー: {e}")
        sys.exit(1)
    except Exception as e:
        action_error(f"予期しないエラー: {type(e).__name__}: {e}")
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
