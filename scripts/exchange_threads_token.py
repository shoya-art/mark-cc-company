#!/usr/bin/env python3
"""Exchange a Threads short-lived token and store the verified long-lived token."""

import argparse
import getpass
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


EXCHANGE_URL = "https://graph.threads.net/access_token"
PROFILE_URL = "https://graph.threads.net/v1.0/me"
MIN_LONG_LIVED_SECONDS = 50 * 24 * 60 * 60


def fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def read_secret(env_name: str, prompt: str) -> str:
    value = os.environ.get(env_name, "").strip() or getpass.getpass(prompt).strip()
    if not value:
        raise ValueError(f"{env_name} is required")
    return value


def get_json(url: str, secrets=()) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        for secret in secrets:
            if secret:
                body = body.replace(secret, "***")
        raise RuntimeError(f"Meta API error (HTTP {exc.code}): {body[:500]}") from None


def exchange_token(short_token: str, app_secret: str) -> tuple:
    query = urllib.parse.urlencode({
        "grant_type": "th_exchange_token",
        "client_secret": app_secret,
        "access_token": short_token,
    })
    result = get_json(
        f"{EXCHANGE_URL}?{query}",
        secrets=(short_token, app_secret),
    )
    long_token = str(result.get("access_token", "")).strip()
    expires_in = int(result.get("expires_in", 0))

    if not long_token:
        raise RuntimeError(f"Meta did not return access_token: {result}")
    if expires_in < MIN_LONG_LIVED_SECONDS:
        raise RuntimeError(
            "Token exchange did not return a long-lived token: "
            f"expires_in={expires_in} seconds"
        )

    return long_token, expires_in


def validate_profile(token: str) -> dict:
    query = urllib.parse.urlencode({
        "fields": "id,username",
        "access_token": token,
    })
    profile = get_json(f"{PROFILE_URL}?{query}", secrets=(token,))
    if not profile.get("id"):
        raise RuntimeError(f"Unable to validate Threads profile: {profile}")
    return profile


def save_repository_secret(token: str, repo: str) -> None:
    subprocess.run(
        ["gh", "secret", "set", "THREADS_ACCESS_TOKEN", "--repo", repo],
        input=token + "\n",
        text=True,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exchange and verify a Threads long-lived access token."
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", "shoya-art/mark-cc-company"),
        help="GitHub repository that owns THREADS_ACCESS_TOKEN",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Validate the exchange without updating GitHub Secret",
    )
    args = parser.parse_args()

    short_token = read_secret(
        "THREADS_SHORT_LIVED_TOKEN", "Threads short-lived access token: "
    )
    app_secret = read_secret("THREADS_APP_SECRET", "Threads App Secret: ")

    long_token, expires_in = exchange_token(short_token, app_secret)
    profile = validate_profile(long_token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    print("Verified long-lived Threads token")
    print(f"  account: @{profile.get('username', 'unknown')} ({profile['id']})")
    print(f"  access_token: <redacted:{fingerprint(long_token)}>")
    print(f"  expires_in: {expires_in} seconds")
    print(f"  expires_at: {expires_at.isoformat()}")

    if not args.no_save:
        save_repository_secret(long_token, args.repo)
        print(f"Updated {args.repo} Repository Secret: THREADS_ACCESS_TOKEN")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
