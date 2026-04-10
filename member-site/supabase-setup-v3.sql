-- 追加テーブル v3 (2026-04-02)
-- Supabase SQL Editor で実行してください

-- 1. ジローからのお知らせテーブル
CREATE TABLE IF NOT EXISTS notices (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  title text NOT NULL,
  body text NOT NULL,
  is_pinned boolean DEFAULT false,
  created_at timestamptz DEFAULT now()
);

ALTER TABLE notices ENABLE ROW LEVEL SECURITY;
-- 全員が読める
CREATE POLICY "all read notices" ON notices FOR SELECT USING (true);
-- 管理者のみ投稿・更新・削除
CREATE POLICY "admin manage notices" ON notices FOR ALL
  USING ((SELECT email FROM auth.users WHERE id = auth.uid()) = 'shoyaaaaaa1127@gmail.com');

-- 2. 復縁日記テーブル
CREATE TABLE IF NOT EXISTS diary_entries (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users NOT NULL,
  date date NOT NULL,
  content text NOT NULL,
  mood text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  UNIQUE(user_id, date)
);

ALTER TABLE diary_entries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own diary_entries" ON diary_entries FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "admin read diary_entries" ON diary_entries FOR SELECT
  USING ((SELECT email FROM auth.users WHERE id = auth.uid()) = 'shoyaaaaaa1127@gmail.com');

-- 3. 質問メモテーブル
CREATE TABLE IF NOT EXISTS question_memos (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users NOT NULL,
  lecture_id text NOT NULL,
  question text NOT NULL,
  is_answered boolean DEFAULT false,
  created_at timestamptz DEFAULT now()
);

ALTER TABLE question_memos ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own question_memos" ON question_memos FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "admin read question_memos" ON question_memos FOR SELECT
  USING ((SELECT email FROM auth.users WHERE id = auth.uid()) = 'shoyaaaaaa1127@gmail.com');
CREATE POLICY "admin update question_memos" ON question_memos FOR UPDATE
  USING ((SELECT email FROM auth.users WHERE id = auth.uid()) = 'shoyaaaaaa1127@gmail.com');
