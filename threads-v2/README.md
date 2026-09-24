# ジロー Threads v2

2026-09-24: Cloudflare本番へ配備済み。**AI生成・公開投稿は停止中、有料API未実行**。
旧Python版を壊さず、Cloudflare Workers + D1 で独立運用する。
Threads再認証、D1、暗号化トークン保存、自動更新、LINE通知、OpenAIキー登録まで設定済み。
開始には有料AI生成の許可、生成結果の確認、公開フラグの順次有効化が必要。

本番URL: https://jiro-threads-v2.jiro-threads-v2.workers.dev

## 確定仕様

- 毎日JST 06/07/20/21/22時、親投稿5本。各親に子2本を順に返信。合計15件/日。
- 親: 未完フック。子①: `実は、5つあるんです！！`（4/6も可）、空行、丸数字と理由。
- 子②: 何個当てはまったか→希望→状況で行動が変わる→相談CTA→固定LP。
- LP: https://jiro-hukuen-lp-179.sss1127.chatgpt.site
- 1ブロック最大3行、1行最大34文字。親最大60文字、子①440、子②本文400。
- 個別心理・復縁結果を保証せず、根拠不明の「成功率が1番」は「今の2人に合った方法」に変更。
- 23:10 JSTに1時間データをまとめて分析、23:15以降に翌日の5組をSolで生成。
- 投稿時点でAIを呼ばない。原稿不足は通知、15分以上遅れた枠を後追い投稿しない。
- 投稿・計測処理は5分ごとに起動。公開後60〜75分の親のviews/likes/repostsを記録する。
  正確な60分値ではなく取得時の累積値。実際の経過分を必ず保存。API反映の遅れはあり得る。
- 6/24/72時間・7日も保存。1時間を逃した場合、後の値で埋めない。
- 表示数を主指標、いいね率・再投稿率を補助。同じ時刻の過去30日が5件未満なら比較保留。
- タップ・滞在・相談・売上は未計測。推測した数字をレポートに出さない。
- D1はv2専用。旧Supabase履歴はそのまま残るが、自動移行はしない。初期は比較保留になる。

## 課金制御

Solのみ使用、固定単価は入力$4/M・出力$20/M。価格変更時はsrc/content.jsも更新が必要。
1回の呼び出し前にUTF-8バイト数（保守的な入力上限）と最大出力から予算を予約。
推論トークンを含むAPI利用量で精算する。キャッシュ割引は保守的に無視。
エラーで利用量不明の場合は予約額を保持し、自動再送しない。
通常は生成1回+分析1回/日。回数だけでは料金は決まらず、文章量・推論量に依存する。
月$16警告、$20で新規AI処理を抑止。月はJST。円建て保証ではなく為替・税・他用途の課金は別。
予算停止後も作成済み原稿の投稿と数値取得は続く。

## 再構築手順（お金の支払い操作は含めない）

Node 22以降。CLIは検証済みバージョンに固定する。

```bash
npx wrangler@4.137.0 login
npx wrangler@4.137.0 whoami
npx wrangler@4.137.0 d1 create jiro-threads-v2
```

返されたdatabase_idをwrangler.tomlへ設定し、D1 migrationを適用する。

```bash
npx wrangler@4.137.0 d1 migrations apply jiro-threads-v2 --remote
```

以下を `npx wrangler@4.137.0 secret put 名前` の対話入力で登録する。
キーをチャット・コミット・コマンド引数に貼らない。

| Secret | 用途 |
|---|---|
| OPENAI_API_KEY | 課金済みAPIプロジェクトのキー。Codex契約とは別 |
| THREADS_ACCESS_TOKEN | 新しく交換した長期トークン（既存の期限切れは不可） |
| TOKEN_ENCRYPTION_KEY | ランダム32バイトのbase64。D1保存トークンをAES-GCM暗号化 |
| ADMIN_TOKEN | ランダム32文字以上。管理API専用 |
| THREADS_LINE_NOTIFY_URL | 既存のLINE通知中継URL |
| THREADS_LINE_NOTIFY_SECRET | 既存の通知中継Secret |

`THREADS_TOKEN_EXPIRES_AT` は秘密情報ではないため、交換レスポンスから計算したISO UTC日時を
`wrangler.toml` の通常変数として設定する。

Threadsの初回交換は `python3 setup_threads.py` で実施できる。
短期トークンとApp Secretを非表示入力し、長期交換・本人ID確認後に
Cloudflare Secretへstdin経由で登録する。トークンは表示しない。チャットに貼らない。
`threads_basic`、`threads_content_publish`、`threads_manage_insights` が必要。

全ENABLEフラグfalseで配備し、ADMIN_TOKENで認証してPOST /bootstrapを1回呼ぶ。
アカウントIDと有効期限を検証し、D1へ暗号化して登録する。
以降はD1内の最新トークンを使用。起動のたびに古いSecretで上書きしない。

```bash
npx wrangler@4.137.0 deploy
```

管理API:
- GET /health: 認証必須。最終起動、モード、期限、キュー件数、警告。トークンを返さない。
- POST /bootstrap: 登録済みSecretから初期トークン登録。再認証時も使用。
- POST /prepare: `{"date":"翌日のYYYY-MM-DD"}`。ENABLE_AI=trueのときのみ**有料生成**。

## 現在地と起動順

1. 完了: D1・管理認証・Threads長期トークン・LINE通知を本番設定。
2. 完了: `/bootstrap`、5分heartbeat、未認証401、認証済み200、LINEテスト通知を確認。
3. 維持: `ENABLE_REFRESH=true`、`ENABLE_AI=false`、`ENABLE_PUBLISH=false`。
4. 完了: 1年期限・生成リクエスト限定のOpenAI APIキーをCloudflare Secretへ登録。
5. 課金許可後: `ENABLE_AI=true`、`ENABLE_PUBLISH=false`で翌日5組だけ生成する。
6. D1 `jobs.payload` の改行・文言・リンクを人が確認してから `ENABLE_PUBLISH=true` にする。
7. 初回実投稿後、親ID・子ID・1h snapshot・レポート・利用額を確認する。

OpenAIキーの有効期限は2027-09-24。期限前に新しいキーへ手動ローテーションする。

古いThreads GitHubワークフローはdisabledのまま維持し、二重起動させない。

## 失敗・復旧

- APIキー未設定/残高不足/予算超過: キューは空のまま。原稿を捏造しない。
- トークン期限は毎日03:05 JSTにD1内の保存値だけを確認し、残り14日以下のときだけMetaへ更新を要求する。期限切れ・連携解除は再認証が必要。
- 更新は本人IDを確認後にtokenとexpiryを同一トランザクションで保存。
- 投稿APIの応答が不明ならneeds_review。保存したcontainer_idと実際のThreadsを照合し、
  公開済みIDを確定してから管理者が状態を修復する。自動再送・二重投稿を避ける。
- pendingのai_runsは請求済みの可能性あり。再生成は使用額確認後、新しい管理された実行IDで行う。
- 通知失敗はD1 alertsに残して再試行。通知レスポンス消失時には重複通知の可能性がある。
- cron自体が止まると同じWorkerからは通知できない。/healthのheartbeatを別の監視サービスで
  15分間隔で見る運用は追加接続が必要。現時点で外部死活監視は未接続。
- Cloudflare無料枠のCPU/D1上限は実運用で検証する。無料枠を超える場合は停止・間隔調整を優先し、
  有料プランへ自動変更しない。厳密な定刻・無停止の保証はない。

## 検証

```bash
npm test
npm run check
npx wrangler@4.137.0 d1 migrations apply jiro-threads-v2 --local
npx wrangler@4.137.0 deploy --dry-run
```

有料APIや実投稿を行わず、SQLiteと模擬APIで予算停止、部分失敗、重複防止、改行、
JST時刻、計測窓、認証を確認。実APIでの生成品質・実配信は課金/認証復旧後に確認が必要。
