/* One record per member per Japan calendar day. No credentials or answers logged. */
(function (root) {
  'use strict';
  const dayKey = (date = new Date()) => new Date(+date + 9 * 3600000).toISOString().slice(0, 10);
  const shiftDay = (key, days) => new Date(Date.parse(key + 'T00:00:00Z') + days * 86400000).toISOString().slice(0, 10);
  const average = rows => rows.length ? rows.reduce((sum, r) => sum + (Number(r.mood) + Number(r.action) + Number(r.state)) / 3, 0) / rows.length : null;
  function summary(rows, today = dayKey()) {
    const days = Array.from({ length: 14 }, (_, i) => shiftDay(today, -i));
    const recent = rows.filter(r => days.slice(0, 7).includes(r.date));
    const prior = rows.filter(r => days.slice(7).includes(r.date));
    const current = rows.find(r => r.date === today);
    const yesterday = rows.find(r => r.date === shiftDay(today, -1));
    const avg = average(recent), prev = average(prior);
    return { current, yesterday, recentCount: recent.length, priorCount: prior.length, avg,
      delta: avg === null || prev === null ? null : avg - prev,
      moodDelta: current && yesterday ? Number(current.mood) - Number(yesterday.mood) : null };
  }
  const signed = n => (n > 0 ? '+' : '') + n.toFixed(1);
  function summaryText(rows, today = dayKey()) {
    const s = summary(rows, today);
    return [s.current ? `今日：気分${s.current.mood}・行動${s.current.action}・前向きさ${s.current.state}` : '今日は未記録',
      s.moodDelta === null ? '気分の前日差：比較できる記録なし' : `気分の前日差：${signed(s.moodDelta)}`,
      s.avg === null ? '直近7日：未記録' : `直近7日平均：${s.avg.toFixed(1)}（${s.recentCount}日記録）`,
      s.delta === null ? '前の7日との比較：記録不足' : `前の7日との差：${signed(s.delta)}（比較元${s.priorCount}日記録）`].join(' ／ ');
  }
  async function loadToday(client, userId, date = dayKey()) {
    const { data, error } = await client.from('checkins').select('*').eq('user_id', userId).eq('date', date).maybeSingle();
    if (error) throw error;
    return data;
  }
  async function save(client, record) {
    if (!record.user_id || !/^\d{4}-\d{2}-\d{2}$/.test(record.date) ||
        !['mood', 'action', 'state'].every(k => Number.isInteger(record[k]) && record[k] >= 1 && record[k] <= 5)) throw new Error('Invalid check-in');
    const { data, error } = await client.from('checkins').upsert(record, { onConflict: 'user_id,date' }).select('date').single();
    if (error) throw error;
    if (!data || data.date !== record.date) throw new Error('Check-in save not confirmed');
    return data;
  }
  // Bound the admin read to 14 days and paginate; never silently truncate at the API row cap.
  async function loadRecent(client, today = dayKey()) {
    const rows = [];
    for (let offset = 0; offset < 20000; offset += 500) {
      const { data, error } = await client.from('checkins').select('*')
        .gte('date', shiftDay(today, -13)).lte('date', today)
        .order('date', { ascending: false }).order('user_id').range(offset, offset + 499);
      if (error) throw error;
      if (!Array.isArray(data)) throw new Error('Missing check-in response');
      rows.push(...data);
      if (data.length < 500) return { data: rows, error: null };
    }
    throw new Error('Check-in result exceeds safe read limit');
  }
  function promptKey(userId, date) { return `daily-checkin-prompt:${userId}:${date}`; }
  function showPrompt(userId, today, existing) {
    if (existing) return;
    const key = promptKey(userId, today);
    try { if (root.sessionStorage.getItem(key)) return; } catch (_) { /* Storage is optional. */ }
    const dialog = document.getElementById('daily-checkin-prompt');
    if (!dialog?.showModal) return; // The permanent card remains accessible.
    const dismiss = () => { try { root.sessionStorage.setItem(key, 'shown'); } catch (_) {} };
    dialog.querySelector('form').addEventListener('submit', dismiss, { once: true });
    dialog.addEventListener('cancel', dismiss, { once: true });
    dialog.addEventListener('close', dismiss, { once: true });
    dialog.showModal();
  }
  // Recheck on return/BFCache and at midnight, without continuously polling the DB.
  function onNewDay(callback) {
    let last = dayKey();
    const check = () => { const next = dayKey(); if (next !== last) { last = next; callback(); } };
    document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
    root.addEventListener('pageshow', check);
    root.setInterval(() => { if (!document.hidden) check(); }, 60000);
    return check;
  }
  root.DailyCheckin = { dayKey, shiftDay, summary, summaryText, loadToday, save, loadRecent, promptKey, showPrompt, onNewDay };
})(typeof window === 'undefined' ? globalThis : window);
