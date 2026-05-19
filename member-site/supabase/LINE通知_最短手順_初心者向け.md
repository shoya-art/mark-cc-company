# LINE通知（notify-instructor）最短手順 — 初心者向け

会員が講義・ワーク・チェックイン・日報・日記・質問メモをしたときに、**あなたのLINEへ通知**するまでの手順です。  
上から順にやれば完了します（所要目安: 初回30〜60分）。

---

## 全体像（3ステップだけ覚える）

1. **Supabase に秘密情報を登録する**（トークンなど）
2. **プログラム（Edge Function）を Supabase に載せる**（デプロイ）
3. **「DBが変わったらそのプログラムを呼ぶ」設定をする**（Database Webhooks）

---

## 事前チェック（これだけ揃っていればOK）

- [ ] LINE の **Messaging API** 用 **チャネルアクセストークン（長期）**
- [ ] 通知を受け取る **あなたの LINE ユーザー ID**（`LINE_TO_USER_ID`）
- [ ] Supabase の **Project URL**（例: `https://xxxx.supabase.co`）
- [ ] Supabase の **service_role** キー（Settings → API → `service_role` **秘密**）
- [ ] このPCに **ターミナル** が使える（Mac の「ターミナル」でOK）

> **注意:** `service_role` は絶対に公開しないでください（GitHubに載せない・会員サイトのHTMLに書かない）。

---

## 手順1: Supabase に Secrets を入れる（5〜10分）

1. ブラウザで [Supabase](https://supabase.com/dashboard) を開き、対象プロジェクトを選ぶ  
2. 左メニュー **Project Settings**（歯車）→ **Edge Functions** → **Secrets**  
3. **Add new secret** で、次を **名前どおり** 追加する  

| Name（名前） | Value（値）の中身 |
|--------------|-------------------|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE のチャネルアクセストークン（長期） |
| `LINE_TO_USER_ID` | あなたの LINE ユーザー ID |
| `SUPABASE_URL` | プロジェクトの URL（`https://....supabase.co`）※未設定なら後でCLIでも可 |
| `SERVICE_ROLE_KEY` | Supabase の `service_role` キー（**service_role** の方） |

**最初はこれで十分です。**  
`WEBHOOK_SECRET` は「セキュリティを上げたいとき」だけ後から足せばOKです。

---

## 手順2: Supabase CLI を入れてログイン（10分・初回だけ）

ターミナルを開いて、次を **そのまま** 順に実行します。

### 2-1. CLI のインストール（Homebrew があるMac向け）

```bash
brew install supabase/tap/supabase
```

Homebrew が無い場合は、公式のインストール方法に従ってください:  
https://supabase.com/docs/guides/cli/getting-started

### 2-2. ログイン

```bash
supabase login
```

ブラウザが開くので、指示どおり許可します。

### 2-3. このプロジェクトのフォルダへ移動

```bash
cd "/Users/hanadashoya/Desktop/curosr/mark-cc-company/会員サイト作成"
```

（フォルダの場所が違う場合は、自分のPC上の `会員サイト作成` まで `cd` してください。）

### 2-4. Supabase プロジェクトと紐づける（link）

```bash
supabase link
```

- **Project ref** を聞かれたら、ダッシュボードの URL `https://app.supabase.com/project/ここがref` の **ref** を貼る  
- **DB password** を聞かれたら、プロジェクト作成時の DB パスワードを入れる  

※すでに `supabase/` 以下に `config.toml` で `project_id` が書いてある場合は、状況により `link` がスキップされることもあります。

---

## 手順3: Edge Function をデプロイ（2〜5分）

`会員サイト作成` フォルダにいる状態で:

```bash
supabase functions deploy notify-instructor --no-verify-jwt
```

成功すると、ターミナルに完了メッセージが出ます。

> `config.toml` に `[functions.notify-instructor] verify_jwt = false` があるので、Database Webhook から呼べるようになっています。

---

## 手順4: 呼び出しURLをコピーする（1分）

1. Supabase ダッシュボード → **Edge Functions**  
2. **`notify-instructor`** を開く  
3. 表示されている **URL** をコピーする  

形はだいたい次のどちらかです。

- `https://＜project-ref＞.supabase.co/functions/v1/notify-instructor`

このURLを、次の「Webhook」で使います。

---

## 手順5: Database Webhooks を作る（10〜20分）

左メニュー **Database** → **Webhooks** → **Create a new hook**（または Enable）。

**同じ Function URL** を使い、**テーブルとイベント**だけ変えて **複数本** 作ります。

### 共通の設定（各Webhookで同じ）

- **Type**: `HTTP Request`（HTTPでEdge Functionを叩く方式でOK）  
- **URL**: 手順4でコピーした `.../functions/v1/notify-instructor`  
- **HTTP Method**: `POST`  
- **HTTP Headers**（必要な場合のみ）  
  - `WEBHOOK_SECRET` を Secrets に入れたなら:  
    - Name: `x-webhook-secret`  
    - Value: その秘密文字列  
  - もし **401** などで失敗する場合は、次も試す（プロジェクトの **anon public** キー）:  
    - Name: `Authorization`  
    - Value: `Bearer ＜anonキー＞`  
    - 追加で Name: `apikey` / Value: `＜anonキー＞`  

※UIの名称は Supabase のバージョンで少し違うことがあります。「Headers を追加できる場所」に入れればOKです。

### テーブル別（ここが違う）

| # | Webhookの名前（分かりやすければ何でもOK） | Table（スキーマは通常 `public`） | 有効にするイベント |
|---|------------------------------------------|-----------------------------------|---------------------|
| 1 | `line_lecture_views` | `lecture_views` | **Insert** のみ |
| 2 | `line_work_answers` | `work_answers` | **Insert** と **Update** |
| 3 | `line_checkins` | `checkins` | **Insert** のみ（※） |
| 4 | `line_daily_reports` | `daily_reports` | **Insert** のみ（※） |
| 5 | `line_diary_entries` | `diary_entries` | **Insert** のみ（※） |
| 6 | `line_question_memos` | `question_memos` | **Insert** のみ |

（※）「会員が**更新**したときも通知したい」場合だけ、Supabase の Secrets に次を足してから、同じテーブルで **Update** もオンにします。

- チェックイン更新も通知: `CHECKIN_NOTIFY_ON_UPDATE` = `true`  
- 日報の更新も通知: `DAILY_REPORT_NOTIFY_ON_UPDATE` = `true`  
- 日記の更新も通知: `DIARY_NOTIFY_ON_UPDATE` = `true`  

---

## 手順6: 動作確認（3分）

1. 会員サイトに **別アカウント（テスト会員）** でログインする  
2. 次のどれか1つを実際に操作する  
   - 講義を完了する  
   - ワークを保存する  
   - チェックインを送る  
3. **あなたのLINE** に通知が来るか確認する  

---

## うまくいかないとき（最短トラブルシュート）

| 症状 | まず確認すること |
|------|------------------|
| デプロイでエラー | `cd` が `会員サイト作成` になっているか、`supabase functions list` でログインできているか |
| Webhookは成功するがLINEが来ない | Secrets の `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO_USER_ID` の打ち間違い、LINE公式のチャネル状態 |
| Webhookが 401 | `WEBHOOK_SECRET` を付けたなら Header の `x-webhook-secret` が一致しているか。または `Authorization: Bearer anon` を試す |
| Webhookが 404 | Function URL のスペルミス、`notify-instructor` がデプロイ済みか |
| 講義完了なのに来ない | `lecture_views` は **初回INSERTだけ**通知です（2回目以降のupsertはUPDATE扱いで送りません） |

Webhookの失敗ログは **Database → Webhooks** から該当フックを開き、**Delivery / Logs**（名称は環境により異なる）で確認できます。

---

## 参照コードの場所

- 関数本体: `会員サイト作成/supabase/functions/notify-instructor/index.ts`  
- 詳細README: `会員サイト作成/supabase/functions/notify-instructor/README.md`  

---

## セキュリティのおすすめ（余裕が出たら）

- `WEBHOOK_SECRET` を設定し、Webhook側の Header `x-webhook-secret` と揃える（勝手にURLを叩かれにくくなる）  
- `service_role` は **Secretsにだけ**置く（リポジトリ・チャット・スクリーンショットに載せない）  

以上で完了です。
