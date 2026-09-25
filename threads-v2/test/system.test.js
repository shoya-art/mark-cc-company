import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {LP,validateChain,validateBatch,schedule,dueWindows,jstDate,compare,cost} from '../src/content.js';
import worker,{ai,bootstrap,prepare,publish,tick,tokenMaintenance,dashboardData} from '../src/worker.js';
import {dashboardHTML} from '../src/dashboard.js';

function chain(n=0) {
 return {parent:['男性が復縁を考える瞬間って……','復縁したら幸せになれる2人って……','彼があなたを思い出す瞬間って……','復縁を考える2人の共通点って……','彼との関係を見直すきっかけって……'][n],
 details:'実は、4つあるんです！！\n\n①日常を楽しめた\nご飯の時間も大切な思い出です。\n\n②素を見せられた\n安心感は大切です。\n\n③支え合えた\n大切にした時間は残ります。\n\n④話し合える\nこれからを一緒に考えられます。',
 cta:'あなたは何個当てはまりましたか？\n\n今は別れていても、\n関係を考え直す可能性はあります。\n\n今の2人に合った方法を\n僕が一緒に考えます。\n\n僕と一緒に復縁を頑張りたい方は\nこちらから相談できます。',hook_type:'特徴'+n};
}
function env() {
 const db=new DatabaseSync(':memory:');
 db.exec(readFileSync(new URL('../migrations/0001.sql',import.meta.url),'utf8'));
 const wrap=(sql,args=[])=>({bind:(...v)=>wrap(sql,v),
  first:async()=>db.prepare(sql).get(...args),
  all:async()=>({results:db.prepare(sql).all(...args)}),
  run:async()=>({meta:{changes:Number(db.prepare(sql).run(...args).changes)}})});
 return {raw:db,DB:{prepare:sql=>wrap(sql),batch:async statements=>{
  db.exec('BEGIN');try{const r=[];for(const s of statements)r.push(await s.run());db.exec('COMMIT');return r;}catch(e){db.exec('ROLLBACK');throw e;}
 }},MODEL:'gpt-5.6-sol',MONTHLY_CAP_USD:'20',WARNING_USD:'16',OPENAI_API_KEY:'test',ENABLE_AI:'true',ENABLE_PUBLISH:'false',ENABLE_REFRESH:'false',THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'test-token',TOKEN_ENCRYPTION_KEY:Buffer.alloc(32,1).toString('base64'),THREADS_TOKEN_EXPIRES_AT:new Date(Date.now()+60*86400000).toISOString(),ADMIN_TOKEN:'a'.repeat(32),DASHBOARD_TOKEN:'d'.repeat(32)};
}
const response=data=>new Response(JSON.stringify(data),{status:200});
function llm(posts=Array.from({length:5},(_,i)=>chain(i))) { return response({status:'completed',usage:{input_tokens:2000,output_tokens:3000},output:[{content:[{type:'output_text',text:JSON.stringify({posts})}]}]}); }

test('content has three parts, one LP and mandatory blank line',()=>{
 const texts=validateChain(chain()); assert.equal(texts.length,3);assert.ok(texts[2].endsWith(LP));
 assert.throws(()=>validateChain({...chain(),details:chain().details.replace('！！\n\n','！！\n')}));
 assert.throws(()=>validateChain({...chain(),details:chain().details.replace('4つ','5つ')}));
 assert.throws(()=>validateChain({...chain(),cta:chain().cta.replace('可能性はあります','必ず復縁できます')}));
 assert.throws(()=>validateBatch({posts:Array(5).fill(chain())}));
 assert.throws(()=>validateChain({...chain(),cta:'あ'.repeat(500)}));
});
test('daily JST slots including UTC previous day',()=>{
 assert.deepEqual(schedule('2026-09-25'),['2026-09-24T21:00:00.000Z','2026-09-24T22:00:00.000Z','2026-09-25T11:00:00.000Z','2026-09-25T12:00:00.000Z','2026-09-25T13:00:00.000Z']);
 assert.equal(jstDate(new Date('2026-09-24T15:00Z')),'2026-09-25');
});
test('1h collection never uses too-early or stale samples',()=>{
 assert.deepEqual(dueWindows(59),[]);assert.deepEqual(dueWindows(60),['1h']);
 assert.deepEqual(dueWindows(74.99),['1h']);assert.deepEqual(dueWindows(75),[]);
 assert.deepEqual(dueWindows(61,['1h']),[]);assert.deepEqual(dueWindows(361),['6h']);
});
test('comparison uses same hour, null rates for zero views, insufficient samples held',()=>{
 const r=compare([{id:'a',slot:6,views:0,likes:0,reposts:0},{id:'b',slot:7,views:100,likes:10,reposts:2}]);
 assert.equal(r[0].likes_rate,null);assert.equal(r[1].baseline_count,0);assert.equal(r[1].views_ratio,null);
});
test('AI charges tracked once, completed result reused',async t=>{
 const e=env();let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;return llm();});
 await prepare(e,'2026-09-25');await prepare(e,'2026-09-25');
 assert.equal(calls,1);assert.equal(e.raw.prepare('SELECT COUNT(*) n FROM jobs').get().n,5);
 const run=e.raw.prepare('SELECT * FROM ai_runs').get();assert.equal(run.actual_usd,cost(2000,3000));
});
test('budget and disabled flags prevent billable calls',async t=>{
 const e=env();let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;return llm();});
 e.MONTHLY_CAP_USD='0.001';await assert.rejects(prepare(e,'2026-09-25'),/budget/);
 e.ENABLE_AI='false';await assert.rejects(ai(e,'x','x',{},100),/disabled/);assert.equal(calls,0);
});
test('unknown AI result is not automatically billed again',async t=>{
 const e=env();let calls=0;t.mock.method(globalThis,'fetch',async()=>{calls++;throw new Error('network');});
 await assert.rejects(prepare(e,'2026-09-25'));await assert.rejects(prepare(e,'2026-09-25'),/requires_review/);assert.equal(calls,1);
});
test('bad generated formatting never enters queue',async t=>{
 const e=env();t.mock.method(globalThis,'fetch',async()=>llm(Array(5).fill(chain())));
 await assert.rejects(prepare(e,'2026-09-25'),/duplicate/);assert.equal(e.raw.prepare('SELECT COUNT(*) n FROM jobs').get().n,0);
});
test('credentials stored encrypted, wrong account rejected',async t=>{
 const e=env();t.mock.method(globalThis,'fetch',async()=>response({id:'123'}));await bootstrap(e);
 assert.ok(!e.raw.prepare("SELECT value FROM state WHERE key='threads_token'").get().value.includes('test-token'));
 e.THREADS_USER_ID='other';await assert.rejects(bootstrap(e),/wrong/);
});
test('published chain is linked, persisted, and not duplicated',async t=>{
 const e=env();let published=0;const replies=[];
 t.mock.method(globalThis,'setTimeout',(fn)=>{fn();return 0;});
 t.mock.method(globalThis,'fetch',async(url,options)=>{
  if(String(url).includes('/me?'))return response({id:'123'});
  if(String(url).endsWith('/threads_publish'))return response({id:'p'+(++published)});
  replies.push(options.body.get('reply_to_id'));return response({id:'c'+replies.length});
 });
 await bootstrap(e);const now=new Date();
 e.raw.prepare('INSERT INTO jobs(id,scheduled_at,payload,updated_at) VALUES (?,?,?,?)').run('2026-09-25/6',now.toISOString(),JSON.stringify(chain()),now.toISOString());
 e.ENABLE_PUBLISH='true';await publish(e,now);await publish(e,now);
 assert.equal(published,3);assert.deepEqual(replies,[null,'p1','p2']);assert.equal(e.raw.prepare('SELECT status FROM jobs').get().status,'published');
});
test('ambiguous publish stops for review and never retries',async t=>{
 const e=env();let attempts=0;
 t.mock.method(globalThis,'setTimeout',(fn)=>{fn();return 0;});
 t.mock.method(globalThis,'fetch',async url=>{
  if(String(url).includes('/me?'))return response({id:'123'});
  if(String(url).endsWith('/threads_publish')){attempts++;throw new Error('timeout');}
  return response({id:'container'});
 });
 await bootstrap(e);const now=new Date();e.ENABLE_PUBLISH='true';
 e.raw.prepare('INSERT INTO jobs(id,scheduled_at,payload,updated_at) VALUES (?,?,?,?)').run('2026-09-25/6',now.toISOString(),JSON.stringify(chain()),now.toISOString());
 await publish(e,now);await publish(e,now);
 assert.equal(attempts,1);assert.equal(e.raw.prepare('SELECT status FROM jobs').get().status,'needs_review');
 assert.equal(e.raw.prepare('SELECT container_id FROM jobs').get().container_id,'container');
});
test('late jobs are marked missed, not dumped in a batch',async()=>{
 const e=env();e.ENABLE_PUBLISH='true';const now=new Date();
 e.raw.prepare('INSERT INTO jobs(id,scheduled_at,payload,updated_at) VALUES (?,?,?,?)').run('2026-09-25/6',new Date(+now-16*60000).toISOString(),JSON.stringify(chain()),now.toISOString());
 await publish(e,now);assert.equal(e.raw.prepare('SELECT status FROM jobs').get().status,'missed');
});
test('disabled deployment has zero API traffic, health requires authentication',async t=>{
 const e=env();e.ENABLE_AI='false';t.mock.method(globalThis,'fetch',async()=>{throw new Error('must not call');});
 await tick(e,new Date('2026-09-24T14:15Z'));
 assert.equal((await worker.fetch(new Request('https://local/health'),e)).status,401);
 const res=await worker.fetch(new Request('https://local/health',{headers:{Authorization:'Bearer '+e.ADMIN_TOKEN}}),e);
 assert.equal(res.status,200);assert.ok(!(await res.text()).includes('test-token'));
});

test('read-only dashboard requires its own token and never exposes credentials',async()=>{
 const e=env();
 e.raw.prepare('INSERT INTO jobs(id,scheduled_at,payload,updated_at) VALUES (?,?,?,?)').run('2026-09-25/6',new Date().toISOString(),JSON.stringify(chain()),new Date().toISOString());
 const page=await worker.fetch(new Request('https://local/admin'),e);
 assert.equal(page.status,200);assert.match(page.headers.get('content-type'),/text\/html/);
 assert.equal((await worker.fetch(new Request('https://local/admin/data'),e)).status,401);
 const res=await worker.fetch(new Request('https://local/admin/data',{headers:{Authorization:'Bearer '+e.DASHBOARD_TOKEN}}),e);
 assert.equal(res.status,200);const body=await res.text();assert.match(body,/男性が復縁/);
 assert.ok(!body.includes('test-token'));assert.ok(!body.includes(e.ADMIN_TOKEN));assert.ok(!body.includes(e.DASHBOARD_TOKEN));
 const data=await dashboardData(e);assert.equal(data.jobs.length,1);assert.equal(data.jobs[0].parent,chain().parent);
 const script=dashboardHTML().match(/<script>([\s\S]*)<\/script>/)?.[1];
 assert.ok(script);assert.doesNotThrow(()=>new vm.Script(script));
});

test('tick captures actual 1h sample once and excludes child posts',async t=>{
 const e=env();e.ENABLE_AI='false';let insights=0;
 t.mock.method(globalThis,'fetch',async url=>{
  if(String(url).includes('/insights')){insights++;return response({data:[{name:'views',values:[{value:123}]},{name:'likes',values:[{value:12}]},{name:'reposts',values:[{value:2}]}]});}
  return response({id:'123'});
 });
 await bootstrap(e);const now=new Date('2026-09-25T04:00Z');
 e.raw.prepare('INSERT INTO jobs(id,scheduled_at,payload,updated_at) VALUES (?,?,?,?)').run('d/6',now.toISOString(),JSON.stringify(chain()),now.toISOString());
 for(let i=0;i<2;i++)e.raw.prepare('INSERT INTO posts VALUES (?,?,?,?,?,?,?)').run('p'+i,'d/6',i,'text',new Date(+now-62*60000).toISOString(),6,'type');
 await tick(e,now);await tick(e,new Date(+now+5*60000));
 const sample=e.raw.prepare('SELECT * FROM snapshots').get();
 assert.equal(insights,1);assert.equal(sample.post_id,'p0');assert.equal(sample.age_minutes,62);assert.equal(sample.views,123);
});
test('daily maintenance contacts Meta only inside the 14-day renewal window',async t=>{
 const e=env();e.ENABLE_AI='false';e.ENABLE_REFRESH='true';let refreshes=0;
 t.mock.method(globalThis,'fetch',async url=>{
  if(String(url).includes('/refresh_access_token')){refreshes++;return response({access_token:'new-token',expires_in:5184000});}
  return response({id:'123'});
 });
 await bootstrap(e);const before=e.raw.prepare("SELECT value FROM state WHERE key='threads_token'").get().value;
 const now=new Date();e.raw.prepare("UPDATE state SET value=? WHERE key='token_meta'").run(JSON.stringify({refreshed_at:new Date(+now-50*86400000).toISOString(),expires_at:new Date(+now+15*86400000).toISOString()}));
 await tokenMaintenance(e,now);assert.equal(refreshes,0);
 e.raw.prepare("UPDATE state SET value=? WHERE key='token_meta'").run(JSON.stringify({refreshed_at:new Date(+now-50*86400000).toISOString(),expires_at:new Date(+now+13*86400000).toISOString()}));
 await tokenMaintenance(e,now);await tokenMaintenance(e,new Date(+now+86400000));
 assert.equal(refreshes,1);assert.notEqual(e.raw.prepare("SELECT value FROM state WHERE key='threads_token'").get().value,before);
});
test('lost token refresh response keeps previous token and records warning',async t=>{
 const e=env();e.ENABLE_AI='false';e.ENABLE_REFRESH='true';
 t.mock.method(globalThis,'fetch',async url=>{
  if(String(url).includes('/refresh_access_token'))throw new Error('network');
  return response({id:'123'});
 });
 await bootstrap(e);const before=e.raw.prepare("SELECT value FROM state WHERE key='threads_token'").get().value;
 const now=new Date();e.raw.prepare("UPDATE state SET value=? WHERE key='token_meta'").run(JSON.stringify({refreshed_at:new Date(+now-50*86400000).toISOString(),expires_at:new Date(+now+13*86400000).toISOString()}));
 await tokenMaintenance(e,now);assert.equal(e.raw.prepare("SELECT value FROM state WHERE key='threads_token'").get().value,before);
 assert.ok(e.raw.prepare("SELECT * FROM alerts WHERE id LIKE 'refresh/%'").get());
});
