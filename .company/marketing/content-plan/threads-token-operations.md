# Threadsアクセストークン更新手順

`Generate Threads Access Token` の出力は、そのままGitHub Secretへ登録しない。
必ず短期トークンを長期トークンへ交換し、`expires_in` を確認してから登録する。

## 交換と登録

```bash
python scripts/exchange_threads_token.py
```

対話入力する値:

1. Generate Threads Access Tokenで取得した短期アクセストークン
2. Meta App DashboardのThreads App Secret

スクリプトは次を自動実行する。

1. `grant_type=th_exchange_token` で長期トークンへ交換
2. `expires_in` が50日以上あることを検証
3. `/v1.0/me` で対象Threadsアカウントを検証
4. `gh secret set` でRepository Secretを更新

トークン本体とApp Secretは画面やログへ出力しない。
交換成功時は次の形式で安全な確認情報だけ表示する。

```text
access_token: <redacted:12桁の指紋>
expires_in: 5184000 seconds
expires_at: 有効期限のUTC日時
```

`expires_in` が50日未満の場合は短期トークンと判断し、GitHub Secretを更新せず終了する。

## 更新後の確認

GitHub Actionsの`workflow_dispatch`で一度実行する。ログの以下を確認する。

- `Threads authentication OK`
- `fingerprint=...`
- 投稿が成功すること

同じ`fingerprint`がschedule実行でも表示されれば、同じRepository Secretを使用している。
