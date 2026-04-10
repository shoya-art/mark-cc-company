-- 追加テーブル v2 (2026-04-01)
-- Supabase SQL Editor で実行してください

-- 1. checkinsテーブルにtagsカラム追加
ALTER TABLE checkins ADD COLUMN IF NOT EXISTS tags text[];

-- 2. ワーク回答テーブル
CREATE TABLE IF NOT EXISTS work_answers (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users NOT NULL,
  lecture_id text NOT NULL,
  answer text NOT NULL,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  UNIQUE(user_id, lecture_id)
);

ALTER TABLE work_answers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own work_answers" ON work_answers FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "admin read work_answers" ON work_answers FOR SELECT
  USING ((SELECT email FROM auth.users WHERE id = auth.uid()) = 'shoyaaaaaa1127@gmail.com');

-- 3. 講義視聴記録テーブル
CREATE TABLE IF NOT EXISTS lecture_views (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users NOT NULL,
  lecture_id text NOT NULL,
  viewed_at timestamptz DEFAULT now(),
  UNIQUE(user_id, lecture_id)
);

ALTER TABLE lecture_views ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own lecture_views" ON lecture_views FOR ALL USING (auth.uid() = user_id);

-- 4. 日報テーブル
CREATE TABLE IF NOT EXISTS daily_reports (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id uuid REFERENCES auth.users NOT NULL,
  date date NOT NULL,
  -- 毎日
  good1 text,
  good2 text,
  good3 text,
  self_praise text,
  action_toward text,
  growth text,
  -- 週1
  self_esteem_score int CHECK (self_esteem_score BETWEEN 1 AND 10),
  positive_score int CHECK (positive_score BETWEEN 1 AND 10),
  -- 2週に1回
  give_up_moment text,
  weak_point text,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  UNIQUE(user_id, date)
);

ALTER TABLE daily_reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own daily_reports" ON daily_reports FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "admin read daily_reports" ON daily_reports FOR SELECT
  USING ((SELECT email FROM auth.users WHERE id = auth.uid()) = 'shoyaaaaaa1127@gmail.com');

-- 5. profilesテーブルにenrollment_dateカラム追加
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS enrollment_date date;

-- 既存ユーザーのenrollment_dateをcreated_atから設定
UPDATE profiles SET enrollment_date = created_at::date WHERE enrollment_date IS NULL;
