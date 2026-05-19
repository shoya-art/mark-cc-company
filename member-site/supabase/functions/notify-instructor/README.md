# notify-instructor（LINE push）

会員の DB 更新を [Database Webhooks](https://supabase.com/docs/guides/database/webhooks) から受け取り、**LINE Messaging API の push** であなたの LINE に通知します。

## 1. Secrets（Supabase ダッシュボード）

Edge Function の Secrets に次を設定します。

| 名前 | 内容 |
|------|------|
| `LINE_CHANNEL_ACCESS_TOKEN` | チャネルアクセストークン（long-lived） |
| `LINE_TO_USER_ID` | 通知先のユーザー ID（あなたの ID） |
| `SUPABASE_URL` | プロジェクト URL（通常は自動で入る） |
| `SERVICE_ROLE_KEY` または `SUPABASE_SERVICE_ROLE_KEY` | service_role（profiles の名前取得用） |

任意:

| 名前 | 内容 |
|------|------|
| `WEBHOOK_SECRET` | 設定したら、Webhook の HTTP ヘッダー `x-webhook-secret` に同じ文字列を付ける |
| `CHECKIN_NOTIFY_ON_UPDATE` | `true` のとき、チェックインの **更新** でも通知（未設定は **新規のみ**） |
| `DAILY_REPORT_NOTIFY_ON_UPDATE` | `true` のとき、日報の **更新** でも通知（未設定は **新規のみ**） |
| `DIARY_NOTIFY_ON_UPDATE` | `true` のとき、日記の **更新** でも通知（未設定は **新規のみ**） |

## 2. デプロイ

プロジェクトルートで（`supabase` があるディレクトリ）:

```bash
supabase functions deploy notify-instructor --no-verify-jwt
```

`config.toml` に `[functions.notify-instructor] verify_jwt = false` があるので、CLI バージョンによっては `--no-verify-jwt` が不要な場合があります。

## 3. Database Webhooks

Supabase → **Database → Webhooks** で、次のテーブルごとに **同じ Function URL** を指定します。

対応テーブル:

- `lecture_views` … **INSERT のみ**（upsert の初回完了。再 upsert の UPDATE は通知しない）
- `work_answers` … INSERT / UPDATE
- `checkins` … INSERT（UPDATE は環境変数で有効化）
- `daily_reports` … INSERT（UPDATE は環境変数で有効化）
- `diary_entries` … INSERT（UPDATE は環境変数で有効化）
- `question_memos` … **INSERT のみ**（新規の質問メモ）

各 Webhook の **HTTP Parameters → Headers** に、`WEBHOOK_SECRET` を設定している場合:

- `x-webhook-secret`: （Secrets と同じ値）

## 4. ローカル（VS Code / Deno）の補足

Deno がプロジェクトとして認識されないと `Deno` や `npm:` に赤波線が出ます。拡張機能 **Deno** を入れ、当該フォルダで「Initialize Workspace Configuration」すると解消しやすいです。
