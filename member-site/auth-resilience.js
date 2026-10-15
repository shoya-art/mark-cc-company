/* Shared, fail-closed authentication handling. No credentials or answers are logged. */
(function (root) {
  'use strict';
  const TIMEOUT = 15000;
  const transientMessage = '現在、認証・データ保存サービスとの通信が不安定です。IDやパスワードの間違いとは限りません。再登録やパスワード変更はせず、少し時間をおいてお試しください。';
  function kind(error) {
    if (!error) return 'unknown';
    if (Number(error.status) >= 500 || ['request_timeout', 'unexpected_failure'].includes(error.code) || ['AbortError', 'TimeoutError', 'AuthRetryableFetchError', 'TypeError'].includes(error.name)) return 'service';
    if (Number(error.status) === 429 || /^over_.*limit$/.test(error.code || '')) return 'rate';
    if (error.code === 'invalid_credentials') return 'credentials';
    if (['session_not_found', 'refresh_token_not_found', 'refresh_token_already_used', 'bad_jwt', 'jwt_expired'].includes(error.code) || error.name === 'AuthSessionMissingError') return 'session';
    return 'unknown';
  }
  function message(error) {
    if (kind(error) === 'credentials') return 'IDまたはパスワードが正しくありません。入力をご確認ください。';
    if (kind(error) === 'rate') return '操作が集中しています。繰り返し押さず、しばらく時間をおいてお試しください。';
    if (error?.code === 'email_not_confirmed') return 'アカウントの確認が必要です。ジローへお問い合わせください。';
    return transientMessage;
  }
  async function boundedFetch(input, init = {}) {
    const controller = new AbortController();
    const originalSignal = init.signal || input?.signal;
    const abort = () => controller.abort();
    if (originalSignal?.aborted) abort();
    else originalSignal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, TIMEOUT);
    try { return await root.fetch(input, { ...init, signal: controller.signal }); }
    finally { clearTimeout(timer); originalSignal?.removeEventListener('abort', abort); }
  }
  function createClient(url, key) {
    return root.supabase.createClient(url, key, { global: { fetch: boundedFetch } });
  }
  function showUnavailable(error) {
    if (document.getElementById('auth-service-warning')) return;
    const cover = document.createElement('section');
    cover.id = 'auth-service-warning';
    cover.setAttribute('role', 'alertdialog');
    cover.setAttribute('aria-modal', 'true');
    cover.setAttribute('aria-label', '通信状況のお知らせ');
    cover.style.cssText = 'position:fixed;inset:0;z-index:10000;background:#fff7f8;display:flex;align-items:center;justify-content:center;padding:24px;color:#555;font-family:inherit;';
    const box = document.createElement('div');
    box.style.cssText = 'max-width:440px;background:white;padding:28px;border-radius:20px;line-height:1.9;';
    const heading = document.createElement('h2'); heading.textContent = '通信状況のお知らせ';
    const text = document.createElement('p'); text.textContent = message(error);
    const note = document.createElement('p'); note.textContent = 'この画面から自動でログアウトや再登録は行いません。確認が取れるまで会員情報の表示・操作を止めています。';
    const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = '30秒後に再確認できます'; retry.disabled = true;
    retry.style.cssText = 'padding:12px 20px;border:0;border-radius:12px;background:#e87580;color:white;font:inherit;';
    setTimeout(() => { retry.disabled = false; retry.textContent = '再確認する'; }, 30000);
    retry.onclick = () => root.location.reload();
    box.append(heading, text, note, retry); cover.append(box);
    // Block keyboard interaction with the underlying forms as well as pointer input.
    for (const child of document.body.children) child.inert = true;
    document.body.append(cover);
    heading.tabIndex = -1; heading.focus();
  }
  async function requireUser(client) {
    try {
      const result = await client.auth.getUser();
      if (result.error) {
        if (kind(result.error) === 'session') root.location.replace('index.html');
        else showUnavailable(result.error);
        return null;
      }
      if (!result.data?.user) { root.location.replace('index.html'); return null; }
      return result.data.user;
    } catch (error) { showUnavailable(error); return null; }
  }
  async function profileFor(client, userId, columns) {
    const { data, error } = await client.from('profiles').select(columns).eq('id', userId).maybeSingle();
    if (error) throw error;
    return data;
  }
  function routeFor(user, profile) {
    if (!profile || !profile.name) return 'onboarding.html';
    if (user.email === '129@lily-member.app' && !profile.full_name) return 'member-profile.html';
    return 'dashboard.html';
  }
  async function login(client, email, password) {
    const { data, error } = await client.auth.signInWithPassword({ email, password });
    if (error) throw error;
    if (!data?.user) throw new Error('Missing authenticated user');
    // Read failure is never treated as a missing profile; login never inserts a row.
    const profile = await profileFor(client, data.user.id, 'name,enrollment_date,full_name');
    return routeFor(data.user, profile);
  }
  function singleFlight(fn) {
    let pending = false;
    return async function (...args) {
      if (pending) return;
      pending = true;
      try { return await fn.apply(this, args); } finally { pending = false; }
    };
  }
  root.MemberAuth = { createClient, requireUser, profileFor, routeFor, login, message, kind, showUnavailable, singleFlight, boundedFetch };
})(typeof window === 'undefined' ? globalThis : window);
