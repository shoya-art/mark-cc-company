# 講義完了と `lecture_views` — 調査結果と修正内容（初心者向け）

## 結論（何が起きていたか）

会員サイトの **`lectures.html`** では、次の2種類の講義がありました。

| 講義タイプ（データ上） | 完了の操作 | 修正前の DB への書き込み |
|------------------------|------------|---------------------------|
| **`video`（動画）** | モーダル内の **「視聴完了 ✓」** | `lecture_views` に **upsert** されていた（`markViewed`） |
| **`work`（ワーク）** | **「ワークを提出する」** | **`work_answers` だけ**。`lecture_views` には **書いていなかった** |

そのため、**ワーク講義だけ完了しても `lecture_views` に INSERT が発生せず**、`lecture_views` 用 Database Webhook → LINE も動きませんでした。

動画講義については **もともと upsert はある**のですが、**エラーを確認しておらず**、失敗時もアラートが出ず「保存できたように見える」状態でした。

---

## ① どのファイルを開くか

1. エクスプローラ / Finder でプロジェクトを開く  
2. 次のファイルを開く（GitHub Pages 用の本番に近いのは `member-site` 側の場合があります）  
   - **`会員サイト作成/lectures.html`**（このリポジトリ内の会員サイト）  
   - または **`member-site/lectures.html`**（`mark-cc-company` リポジトリの `member-site` フォルダ）

---

## ② 探すコード（視聴完了の入口）

エディタで **検索（Ctrl+F / Cmd+F）** します。

| 検索ワード | 意味 |
|------------|------|
| `lecture_views` | このテーブルへの読み書き箇所が全部出る |
| `markViewed` | 動画講義の「視聴完了 ✓」から呼ばれる関数 |
| `submitWork` | ワーク提出の処理 |
| `openModal` | 講義カードをタップしたときにモーダルを組み立てる |

### 動画講義の流れ

1. `openModal(lecture, …)` の中で `lecture.type === 'video'` のとき HTML に  
   `onclick="markViewed('講義ID')"` のボタン **「視聴完了 ✓」** を出している  
2. ボタン押下 → **`markViewed(lectureId)`** が実行される  
3. そこで **`sb.from('lecture_views').upsert(...)`** が走る（修正後は共通関数 `upsertLectureViewRecord`）

### ワーク講義の流れ

1. `lecture.type === 'work'` のとき `buildWorkHTML` でフォームと **「ワークを提出する」** ボタン  
2. ボタン → **`submitWork(lectureId)`**  
3. 修正前は **`work_answers` の upsert だけ**で、`lecture_views` は触っていなかった  

---

## ③ 今回の修正（何をしたか）

### 追加した共通関数

**名前:** `upsertLectureViewRecord(lectureId)`

**やること:** 次の1行に相当するデータを **`lecture_views` に upsert**（初回は INSERT、2回目以降は UPDATE）。

- `user_id` … ログイン中の会員の ID（`currentUser.id`）
- `lecture_id` … 講義の ID（例: `1-1`, `3-3`）
- `viewed_at` … 完了した日時（ISO 文字列）

### 変更した箇所

1. **`markViewed`**  
   - 上記の共通関数を呼ぶ  
   - **`error` があれば `alert` して return**（失敗時にモーダルを閉めない）

2. **`submitWork`**（ワークの `work_answers` の保存が成功した直後）  
   - 同じ **`upsertLectureViewRecord(lectureId)`** を呼ぶ  
   - 失敗したらアラートし、ボタンを元に戻す（**ワークは保存済み**なので、メッセージで再試行を促す）

---

## ④ 何を保存するか（DBの意味）

| カラム | 内容 |
|--------|------|
| `user_id` | 誰が |
| `lecture_id` | どの講義を |
| `viewed_at` | いつ完了したか |

Supabase の **Database Webhook（`lecture_views` の INSERT）** は、この **INSERT が初めて入ったとき**に Edge Function を呼びます（2回目以降の upsert は UPDATE になるため、通知ロジックは「INSERT のみ」なら再通知されません。それは Edge Function 側の仕様です）。

---

## ⑤ ターミナルで何をするか（本番サイトに反映）

GitHub Pages で配信している場合:

1. 変更した **`lectures.html`** を **Git にコミットして push** する  
2. GitHub Pages のビルドが終わるまで **1〜2分待つ**  
3. ブラウザで **強制再読み込み**（Mac: `Cmd + Shift + R`）してから講義を試す  

Edge Function や Webhook は **HTML の push とは別**です。今回の不具合の主因は **フロントが `lecture_views` に書いていなかった（ワーク）** なので、**必ず `lectures.html` をデプロイ先に反映**してください。

---

## ⑥ まだ通知が来ないときの確認リスト

1. **Supabase Table Editor** で `lecture_views` を開き、操作直後に **行が増えているか**  
2. 増えない → ブラウザの **開発者ツール → Console** で `lecture_views` のエラー  
3. 増えるのに LINE が来ない → **Database Webhooks の配信ログ** と **Edge Functions の Logs**

---

## 参照: 修正を入れたファイル

- `会員サイト作成/lectures.html`  
- `_mark-cc-company-github/member-site/lectures.html`（同内容を同期）
