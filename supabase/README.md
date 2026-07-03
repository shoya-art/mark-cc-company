# Threads Analytics Database

## Initial setup

Run `threads-analytics-schema.sql` in the Supabase SQL Editor as the `postgres`
role. The migration is idempotent and can be run again when verifying a new
project.

## GitHub Secrets

The workflows require these repository secrets:

- `THREADS_SUPABASE_URL`
- `THREADS_SUPABASE_SECRET_KEY` (`sb_secret_...`)
- `THREADS_ACCESS_TOKEN`
- `ANTHROPIC_API_KEY`
- `THREADS_LINE_NOTIFY_URL`
- `THREADS_LINE_NOTIFY_SECRET`

Never put a Supabase secret key in source control, logs, screenshots, or chat.

## Data flow

1. `threads-auto-post.yml` publishes a post and immediately upserts its text,
   metadata, hypothesis, post ID, timestamp, and permalink.
2. `threads-insights.yml` first imports historical repository logs in batches of
   25 and records their current lifetime metrics as seed evidence. It then runs
   every six hours and stores the latest Insights, preserving comparable
   snapshots at 24 hours, 72 hours, and 7 days.
3. `threads-learning.yml` runs daily and compares 72-hour results. Patterns need
   at least five samples before they become knowledge candidates.
4. New post generation reads evidence-backed knowledge from Supabase. About 70%
   of posts exploit known winners and 30% explore one new variable.
5. The daily learning workflow sends the latest contrast, chain continuation,
   problem hypothesis, and next test to the configured LINE user.

LINE credentials remain in the existing member-site Supabase project. The
`notify-threads-analysis` Edge Function relays messages after validating the
shared `THREADS_NOTIFY_SECRET`; LINE credentials are not duplicated in GitHub.

## Safety boundaries

- Only the Supabase secret key can access these tables through the Data API.
- RLS is enabled and `anon` and `authenticated` have no table access.
- Historical top-vs-bottom differences become provisional seed knowledge
  immediately, but remain marked as requiring revalidation.
- One post never becomes a verified reusable rule.
- A rule becomes active automatically only after at least ten comparable posts
  and a material performance difference.
- Core brand, empathy, safety, and non-guarantee rules remain in the skills and
  cannot be replaced by performance optimization.

## Manual checks

Run `Threads Insights収集` manually after the first DB-backed post. Then open
Table Editor and verify:

- `threads_posts` contains the post.
- `threads_metric_snapshots` contains a `latest` row.
- `threads_post_performance` shows the combined result.

The access token must include `threads_manage_insights` for metric collection.
