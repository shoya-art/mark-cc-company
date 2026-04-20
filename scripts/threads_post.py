#!/usr/bin/env python3
"""Threads自動投稿スクリプト - 復縁アドバイザー・ジロー"""

import anthropic
import urllib.request
import urllib.parse
import json
import sys
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))


def read_file_safe(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def generate_post(time_slot: str, repo_root: str = ".") -> tuple:
    """Claude APIで投稿文を生成。(投稿文, スコア, ヘッダー型)を返す"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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


def post_to_threads(text: str) -> str:
    """Threads APIに投稿する。投稿IDを返す。"""
    user_id = os.environ.get("THREADS_USER_ID", "26439768865674129")
    token = os.environ["THREADS_ACCESS_TOKEN"]

    # Step 1: メディアコンテナ作成
    data = urllib.parse.urlencode({
        "media_type": "TEXT",
        "text": text,
        "access_token": token
    }).encode()

    req = urllib.request.Request(
        f"https://graph.threads.net/v1.0/{user_id}/threads",
        data=data, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise ValueError(f"コンテナ作成エラー {e.code}: {e.read().decode()}")

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

    req2 = urllib.request.Request(
        f"https://graph.threads.net/v1.0/{user_id}/threads_publish",
        data=data2, method="POST"
    )
    try:
        with urllib.request.urlopen(req2) as r2:
            resp2 = json.loads(r2.read())
    except urllib.error.HTTPError as e:
        raise ValueError(f"公開エラー {e.code}: {e.read().decode()}")

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
        print("\n投稿文を生成中...")
        post_text, score, header_type = generate_post(time_slot, repo_root)
        print(f"\n【生成した投稿文】（スコア: {score:.1f}、ヘッダー型: {header_type}）")
        print("-" * 40)
        print(post_text)
        print("-" * 40)

        print("\nThreadsに投稿中...")
        post_id = post_to_threads(post_text)
        print(f"POST_ID: {post_id}")
        print("✅ 投稿成功！")

        append_to_log(post_text, score, header_type, post_id, time_slot, repo_root)

    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
