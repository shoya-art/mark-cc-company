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


def generate_post(time_slot: str, repo_root: str = ".") -> tuple:
    """Claude APIで投稿文を生成。(投稿文, スコア, ヘッダー型)を返す"""
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
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text

    post_text = ""
    if "---POST_START---" in text and "---POST_END---" in text:
        start = text.index("---POST_START---") + len("---POST_START---")
        end = text.index("---POST_END---")
        post_text = text[start:end].strip()

    score = 7.5
    if "---SCORE---" in text and "---SCORE_END---" in text:
        start = text.index("---SCORE---") + len("---SCORE---")
        end = text.index("---SCORE_END---")
        try:
            score = float(text[start:end].strip())
        except ValueError:
            pass

    header_type = "不明"
    if "---HEADER_TYPE---" in text and "---HEADER_TYPE_END---" in text:
        start = text.index("---HEADER_TYPE---") + len("---HEADER_TYPE---")
        end = text.index("---HEADER_TYPE_END---")
        header_type = text[start:end].strip()

    if not post_text:
        raise ValueError(f"投稿文の抽出に失敗しました。レスポンス: {text[:500]}")

    return post_text, score, header_type


def post_to_threads(text: str, user_id: str, token: str) -> str:
    """Threads APIに投稿する。投稿IDを返す。"""
    # Step 1: メディアコンテナ作成
    data = urllib.parse.urlencode({
        "media_type": "TEXT",
        "text": text,
        "access_token": token
    }).encode()

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


def append_to_log(post_text: str, score: float, header_type: str,
                  post_id: str, time_slot: str, repo_root: str = "."):
    """threads-log.mdに追記する"""
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


if __name__ == "__main__":
    time_slot = sys.argv[1] if len(sys.argv) > 1 else "morning"
    repo_root = sys.argv[2] if len(sys.argv) > 2 else "."

    print(f"=== Threads自動投稿 [{time_slot}] ===")
    print(f"実行時刻: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")

    try:
        print("\nThreads認証を確認中...")
        threads_user_id, threads_token = validate_threads_credentials()

        print("\n投稿文を生成中...")
        post_text, score, header_type = generate_post(time_slot, repo_root)
        print(f"\n【生成した投稿文】（スコア: {score:.1f}、ヘッダー型: {header_type}）")
        print("-" * 40)
        print(post_text)
        print("-" * 40)

        print("\nThreadsに投稿中...")
        post_id = post_to_threads(post_text, threads_user_id, threads_token)
        print(f"POST_ID: {post_id}")
        print("✅ 投稿成功！")

        append_to_log(post_text, score, header_type, post_id, time_slot, repo_root)

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
