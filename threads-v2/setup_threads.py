#!/usr/bin/env python3
"""One-time Threads reconnect. Secrets are passed through stdin, never printed."""
import getpass
import importlib.util
import os
from pathlib import Path
import subprocess
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "exchange", ROOT.parent / "scripts" / "exchange_threads_token.py"
)
exchange = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exchange)


def main():
    short = getpass.getpass("新しいThreads短期トークン（非表示）: ").strip()
    secret = getpass.getpass("Threads App Secret（非表示）: ").strip()
    if not short or not secret:
        raise ValueError("入力が空です")
    token, seconds = exchange.exchange_token(short, secret)
    profile = exchange.validate_profile(token)
    expected = os.environ.get("THREADS_USER_ID", "26439768865674129")
    if str(profile.get("id")) != expected:
        raise ValueError("Threadsアカウントが設定と一致しません")
    expires = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()
    for name, value in (
        ("THREADS_ACCESS_TOKEN", token),
        ("THREADS_TOKEN_EXPIRES_AT", expires),
    ):
        subprocess.run(
            ["npx", "--yes", "wrangler@4.137.0", "secret", "put", name],
            input=value + "\n", text=True, check=True, cwd=ROOT,
        )
    print("長期トークンと期限をCloudflareへ登録しました。期限:", expires)
    print("次に認証付き POST /bootstrap を実行してください。投稿は開始しません。")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Do not print exception payloads which may contain credentials.
        raise SystemExit("登録が完了しませんでした。アカウント・権限・入力を確認してください。")
