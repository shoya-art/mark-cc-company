-- =============================================
-- 会員サイト データベース設定
-- Supabaseのダッシュボード > SQL Editor で実行する
-- =============================================

-- 1. プロフィールテーブル（会員情報）
create table if not exists profiles (
  id uuid references auth.users on delete cascade primary key,
  email text,
  name text,
  goal text check (goal in ('reconnect', 'next_love', 'closure')),
  created_at timestamptz default now()
);

alter table profiles enable row level security;

create policy "自分のプロフィールを見られる" on profiles
  for select using (auth.uid() = id);

create policy "自分のプロフィールを作成できる" on profiles
  for insert with check (auth.uid() = id);

create policy "自分のプロフィールを更新できる" on profiles
  for update using (auth.uid() = id);

-- 2. 毎日のチェックインテーブル
create table if not exists checkins (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references auth.users on delete cascade not null,
  date date not null default current_date,
  mood integer check (mood between 1 and 5) not null,
  action integer check (action between 1 and 5) not null,
  state integer check (state between 1 and 5) not null,
  note text,
  created_at timestamptz default now(),
  unique (user_id, date)
);

alter table checkins enable row level security;

create policy "自分のチェックインを管理できる" on checkins
  for all using (auth.uid() = user_id);

-- 管理者（ジロー）は全員のチェックインを見られる
create policy "管理者は全チェックインを見られる" on checkins
  for select using (
    (select email from auth.users where id = auth.uid()) = 'shoyaaaaaa1127@gmail.com'
  );

-- 管理者は全プロフィールを見られる
create policy "管理者は全プロフィールを見られる" on profiles
  for select using (
    (select email from auth.users where id = auth.uid()) = 'shoyaaaaaa1127@gmail.com'
  );

-- 3. 管理者用：全ユーザー一覧を取得するビュー
create or replace view member_overview as
select
  p.id,
  p.email,
  p.name,
  p.goal,
  p.created_at,
  count(c.id) as checkin_count,
  max(c.date) as last_checkin,
  round(avg(c.mood), 1) as avg_mood,
  round(avg(c.action), 1) as avg_action,
  round(avg(c.state), 1) as avg_state
from profiles p
left join checkins c on c.user_id = p.id
group by p.id, p.email, p.name, p.goal, p.created_at;
