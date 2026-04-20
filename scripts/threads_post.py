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
    winning_patterns = read_file_safe(f"{base}/winning-patterns.md")
    hypotheses = read_file_safe(f"{base}/hypotheses.md")

    slot_config = {
        "morning": {
            "time": "朝の通勤時間帯（7:50 JST）",
            "header_priority": "反転断言型または女性讃歌型を優先（朝は保存・拡散向きが伸びる）",
        },
        "lunch": {
            "time": "昼休み（12:20 JST）",
            "header_priority": "罪悪感反転型を優先（昼はコンサル導線に最適）",
        },
        "evening": {
            "time": "夜のリラックスタイム（21:30 JST）",
            "header_priority": "問いかけ＋段階解説型を優先（夜はコメント誘導が効果的）",
        },
    }
    config = slot_config.get(time_slot, slot_config["morning"])

    prompt = f"""あなたは復縁アドバイザー・ジロー（@ziro_fukuen_pro）のThreads投稿を自動生成するエージェントです。

【今日の投稿時間帯】{config["time"]}
【コンセプト】「復縁は自己肯定感が9割」
【ターゲット】自己肯定感が低く復縁を望む女性（20〜35歳）
- 「彼が悪い」より「自分が変わりたい」と思っている
- すでに「これやってるけどダメだよね」と自己否定している行動を持っている

【優先ヘッダー型】{config["header_priority"]}

=== 勝ちパターン（必ず参照） ===
{winning_patterns if winning_patterns else "（ファイルなし）"}

=== 現在検証中の仮説 ===
{hypotheses if hypotheses else "（ファイルなし）"}

【4構造フォーマット（この順番を守る）】
① 共感フック（1〜2文）: ヘッダー型でターゲットの状況を言語化
② 違和感・反転（1〜2文）: 「でも実は」「やめなくていい」「間違いじゃない」
③ 本質（2〜3文）: 「復縁は自己肯定感が9割」から核心を伝える
④ 行動・コメント誘導: 最後に「コメントで教えてください。個別にアドバイスします。」を含める

【原則】
- 1文を短く。1〜2行で改行。スマホで読みやすく
- 「相談者さん」「サポート生」を使ってアドバイザー目線
- NG: 「頑張れば復縁できます」「まずは自分磨きから」「今すぐDM」「LINE登録で〜」

以下の手順で実行してください:
1. 投稿文を生成する（200〜400文字）
2. 以下7項目を10点満点で採点する:
   自然さ、具体性、感情移入しやすさ、ペルソナ一致度、テンポ感、体験語り感、業者臭さのなさ
3. 平均7.0未満の場合は再生成（最大3回）

最終出力を以下の形式で返してください:
---POST_START---
（投稿テキストのみ）
---POST_END---
---SCORE---
（平均スコア数値のみ、例: 8.2）
---SCORE_END---
---HEADER_TYPE---
（使用したヘッダー型名のみ、例: 罪悪感反転型）
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
