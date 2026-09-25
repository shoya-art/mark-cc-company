const html = `<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Threads運用ダッシュボード</title>
<style>
:root{color-scheme:light;--bg:#f5f6f8;--card:#fff;--ink:#172033;--muted:#697386;--line:#e5e8ee;--ok:#137a4a;--warn:#b46800;--bad:#c73535;--brand:#191919}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}button,input{font:inherit}
.wrap{max-width:1180px;margin:auto;padding:28px 20px 64px}.top{display:flex;gap:18px;align-items:flex-start;justify-content:space-between;margin-bottom:22px}.eyebrow{font-size:12px;font-weight:700;letter-spacing:.12em;color:var(--muted)}h1{font-size:28px;margin:5px 0 4px}.sub{color:var(--muted);font-size:14px}.actions{display:flex;gap:8px}.btn{border:1px solid var(--line);background:#fff;border-radius:10px;padding:9px 13px;cursor:pointer;font-weight:650}.btn.dark{background:var(--brand);color:#fff;border-color:var(--brand)}
.login{max-width:500px;margin:15vh auto 0;background:var(--card);border:1px solid var(--line);border-radius:18px;padding:26px;box-shadow:0 16px 45px #17203314}.login h2{margin:0 0 8px}.login p{color:var(--muted);line-height:1.6}.login-row{display:flex;gap:8px;margin-top:18px}.login input{min-width:0;flex:1;border:1px solid #cfd5df;border-radius:10px;padding:11px 12px}.error{color:var(--bad);font-size:13px;margin-top:10px;min-height:20px}
.cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:20px}.card,.panel{background:var(--card);border:1px solid var(--line);border-radius:15px}.card{padding:17px}.label{font-size:12px;color:var(--muted);margin-bottom:8px}.value{font-size:22px;font-weight:760}.note{font-size:12px;color:var(--muted);margin-top:6px}.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.grid{display:grid;grid-template-columns:1.55fr 1fr;gap:16px}.panel{overflow:hidden;margin-bottom:16px}.panel-head{display:flex;align-items:center;justify-content:space-between;padding:15px 17px;border-bottom:1px solid var(--line)}.panel h2{font-size:16px;margin:0}.count{font-size:12px;color:var(--muted)}.scroll{overflow:auto}.empty{padding:28px;color:var(--muted);text-align:center}
table{border-collapse:collapse;width:100%;min-width:680px}th,td{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left;font-size:13px;vertical-align:top}th{font-size:11px;color:var(--muted);letter-spacing:.04em;background:#fafbfc;position:sticky;top:0}.hook{font-weight:700;max-width:360px}.small{font-size:12px;color:var(--muted);margin-top:4px}.badge{display:inline-flex;border-radius:999px;padding:4px 8px;font-size:11px;font-weight:750;background:#eef1f5;color:#4a5568}.badge.ready{background:#fff5d8;color:#8b5a00}.badge.published{background:#e8f7ef;color:#137a4a}.badge.needs_review,.badge.missed{background:#fdeaea;color:#a72525}.metric{font-variant-numeric:tabular-nums}.analysis{padding:17px;white-space:pre-wrap;line-height:1.65;font-size:14px}.alerts{list-style:none;padding:0;margin:0}.alerts li{padding:13px 17px;border-bottom:1px solid var(--line);font-size:13px;line-height:1.55}.alert-time{display:block;color:var(--muted);font-size:11px;margin-top:3px}.draft{border:0;background:none;color:#3c5db3;padding:0;cursor:pointer;font-weight:700}.draft-body{white-space:pre-wrap;background:#f7f8fa;padding:12px;border-radius:9px;margin-top:9px;display:none;max-width:560px;line-height:1.6}.draft-body.open{display:block}
@media(max-width:900px){.cards{grid-template-columns:repeat(2,1fr)}.grid{grid-template-columns:1fr}.top{display:block}.actions{margin-top:14px}}@media(max-width:520px){.wrap{padding:20px 12px 50px}.cards{grid-template-columns:1fr 1fr}.card{padding:14px}.value{font-size:18px}h1{font-size:23px}.login-row{display:block}.login button{width:100%;margin-top:8px}}
</style>
</head>
<body>
<main class="wrap">
  <section id="login" class="login" hidden>
    <h2>管理画面にログイン</h2>
    <p>読み取り専用の管理キーを入力してください。このブラウザだけに保存されます。</p>
    <div class="login-row"><input id="token" type="password" autocomplete="current-password" placeholder="管理キー"><button id="loginButton" class="btn dark">開く</button></div>
    <div id="loginError" class="error"></div>
  </section>
  <section id="app" hidden>
    <header class="top"><div><div class="eyebrow">JIRO / THREADS V2</div><h1>Threads運用ダッシュボード</h1><div id="updated" class="sub"></div></div><div class="actions"><button id="refresh" class="btn">更新</button><button id="logout" class="btn">ログアウト</button></div></header>
    <div class="cards">
      <div class="card"><div class="label">システム</div><div id="system" class="value"></div><div id="heartbeat" class="note"></div></div>
      <div class="card"><div class="label">予約中</div><div id="ready" class="value"></div><div class="note">親＋子2件のセット数</div></div>
      <div class="card"><div class="label">公開済み</div><div id="published" class="value"></div><div class="note">完了した投稿セット</div></div>
      <div class="card"><div class="label">今月のAI費用</div><div id="spend" class="value"></div><div id="budget" class="note"></div></div>
      <div class="card"><div class="label">Threads認証期限</div><div id="expiry" class="value"></div><div id="expiryNote" class="note"></div></div>
    </div>
    <div class="panel"><div class="panel-head"><h2>予約・投稿一覧</h2><span id="jobCount" class="count"></span></div><div id="jobs" class="scroll"></div></div>
    <div class="panel"><div class="panel-head"><h2>投稿パフォーマンス</h2><span class="count">表示数 / いいね / 再投稿</span></div><div id="performance" class="scroll"></div></div>
    <div class="grid">
      <div class="panel"><div class="panel-head"><h2>最新の初速分析</h2></div><div id="analysis" class="analysis"></div></div>
      <div class="panel"><div class="panel-head"><h2>警告・通知</h2></div><ul id="alerts" class="alerts"></ul></div>
    </div>
  </section>
</main>
<script>
(function(){
var storageKey='jiro_threads_dashboard_token';
var jp=new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
var el=function(id){return document.getElementById(id)};
var text=function(id,value){el(id).textContent=value};
var fmt=function(value){return value?jp.format(new Date(value)):'—'};
var statusLabel={ready:'予約中',publishing:'投稿中',published:'公開済み',needs_review:'要確認',missed:'未投稿'};
function node(tag,value,cls){var x=document.createElement(tag);if(value!==undefined)x.textContent=value;if(cls)x.className=cls;return x}
function cell(tr,value,cls){var td=node('td',value,cls);tr.appendChild(td);return td}
function table(headers){var t=node('table'),head=node('thead'),tr=node('tr');headers.forEach(function(h){tr.appendChild(node('th',h))});head.appendChild(tr);t.appendChild(head);t.appendChild(node('tbody'));return t}
function jobTable(rows){var host=el('jobs');host.replaceChildren();if(!rows.length){host.appendChild(node('div','まだ投稿データがありません','empty'));return}var t=table(['予定','状態','親投稿','進捗','エラー']);var b=t.tBodies[0];rows.forEach(function(r){var tr=node('tr');cell(tr,fmt(r.scheduled_at));var s=cell(tr);s.appendChild(node('span',statusLabel[r.status]||r.status,'badge '+r.status));var h=cell(tr);h.appendChild(node('div',r.parent,'hook'));h.appendChild(node('div',r.hook_type||'','small'));var button=node('button','原稿を見る','draft');var body=node('div',(r.details||'')+'\\n\\n'+(r.cta||''),'draft-body');button.onclick=function(){body.classList.toggle('open')};h.appendChild(button);h.appendChild(body);cell(tr,String(r.part||0)+'/3','metric');cell(tr,r.error||'—');b.appendChild(tr)});host.appendChild(t)}
function performanceTable(rows){var host=el('performance');host.replaceChildren();if(!rows.length){host.appendChild(node('div','公開後に数値が表示されます','empty'));return}var t=table(['公開','親投稿','1時間','6時間','24時間','72時間','7日']);var b=t.tBodies[0];var m=function(r,w){var v=r['views_'+w];return v==null?'—':v+' / '+r['likes_'+w]+' / '+r['reposts_'+w]};rows.forEach(function(r){var tr=node('tr');cell(tr,fmt(r.published_at));var h=cell(tr);h.appendChild(node('div',r.body,'hook'));h.appendChild(node('div',(r.slot||'—')+'時枠・'+(r.hook_type||''),'small'));['1h','6h','24h','72h','7d'].forEach(function(w){cell(tr,m(r,w),'metric')});b.appendChild(tr)});host.appendChild(t)}
function render(d){el('login').hidden=true;el('app').hidden=false;text('updated','最終更新 '+fmt(d.generated_at));var live=d.flags.ai&&d.flags.publishing;text('system',live?'稼働中':'一部停止');el('system').className='value '+(live?'ok':'warn');text('heartbeat','最終起動 '+fmt(d.heartbeat));var counts={};d.job_counts.forEach(function(x){counts[x.status]=Number(x.count)});text('ready',counts.ready||0);text('published',counts.published||0);text('spend','$'+Number(d.monthly_spend||0).toFixed(4));text('budget','上限 $'+d.monthly_cap);var ex=d.token_meta&&d.token_meta.expires_at;var days=ex?Math.ceil((new Date(ex)-new Date())/86400000):null;text('expiry',days==null?'—':days+'日');text('expiryNote',ex?'期限 '+fmt(ex):'未登録');text('jobCount',d.jobs.length+'件');jobTable(d.jobs);performanceTable(d.performance);var a=d.latest_analysis;if(!a){text('analysis','データが貯まると、毎日23:10に分析結果が表示されます。')}else{text('analysis',(a.summary||'')+'\\n\\n仮説\\n・'+(a.hypotheses||[]).join('\\n・')+'\\n\\n次の検証\\n・'+(a.next_tests||[]).join('\\n・'))}var list=el('alerts');list.replaceChildren();if(!d.alerts.length)list.appendChild(node('li','警告はありません'));d.alerts.forEach(function(a){var li=node('li',a.message);li.appendChild(node('span',(a.sent_at?'送信済み ':'未送信 ')+fmt(a.created_at),'alert-time'));list.appendChild(li)})}
async function load(token){var res=await fetch('/admin/data',{headers:{Authorization:'Bearer '+token},cache:'no-store'});if(res.status===401)throw new Error('管理キーが違います');if(!res.ok)throw new Error('読み込みに失敗しました');render(await res.json())}
async function login(){var token=el('token').value.trim();el('loginError').textContent='';try{await load(token);localStorage.setItem(storageKey,token)}catch(e){el('loginError').textContent=e.message}}
el('loginButton').onclick=login;el('token').onkeydown=function(e){if(e.key==='Enter')login()};el('refresh').onclick=function(){load(localStorage.getItem(storageKey)).catch(function(e){alert(e.message)})};el('logout').onclick=function(){localStorage.removeItem(storageKey);location.reload()};
var saved=localStorage.getItem(storageKey);if(saved){load(saved).catch(function(){localStorage.removeItem(storageKey);el('login').hidden=false})}else el('login').hidden=false;
})();
</script>
</body>
</html>`;

export function dashboardHTML() { return html; }
