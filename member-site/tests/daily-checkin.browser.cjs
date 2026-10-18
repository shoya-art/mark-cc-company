// Mock-only browser tests: all remote requests are intercepted; no real login or DB writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require(process.env.PLAYWRIGHT_PATH || 'playwright');
const base = path.resolve(__dirname,'..');
const fixture = `
window.fixture = { user: {id:'fixture-a',email:'fixture@example.invalid'}, rows:[], failRead:false, failSave:false, writes:0 };
window.supabase = {createClient(){return {auth:{getUser:async()=>({data:{user:fixture.user}})},from(table){
 let filters=[],record=null,one=false,limit=Infinity,start=0,end=Infinity;
 const q={select(){return q;},eq(k,v){filters.push(r=>r[k]===v);return q;},gte(k,v){filters.push(r=>r[k]>=v);return q;},lte(k,v){filters.push(r=>r[k]<=v);return q;},not(){return q;},order(){return q;},limit(n){limit=n;return q;},range(a,b){start=a;end=b;return q;},single(){one=true;return q;},maybeSingle(){one=true;return q;},upsert(r){record=r;return q;},async then(resolve,reject){try{
 if(table==='checkins' && (fixture.failRead&&!record || fixture.failSave&&record)) return resolve({data:null,error:{status:504}});
 if(record){fixture.writes++;const i=fixture.rows.findIndex(r=>r.user_id===record.user_id&&r.date===record.date);if(i<0)fixture.rows.push(record);else fixture.rows[i]=record;await new Promise(r=>setTimeout(r,30));return resolve({data:{date:record.date}});}
 const profile={id:'fixture-a',name:'架空会員A',goal:'reconnect',created_at:'2026-10-01T00:00:00Z',enrollment_date:'2026-10-01'};
 let rows=table==='profiles'?[profile]:table==='checkins'?fixture.rows:[];
 rows=rows.filter(r=>filters.every(f=>f(r))).sort((a,b)=>String(b.date).localeCompare(String(a.date))).slice(start,Math.min(end+1,start+limit));
 return resolve({data:one?(rows[0]||null):rows,error:null});
 }catch(e){return reject(e);}}};return q;
}}}};
`;
async function main(){
 const server=http.createServer((req,res)=>{
   const file=path.resolve(base,'.'+new URL(req.url,'http://localhost').pathname);
   if(!file.startsWith(base+path.sep)){res.writeHead(403).end();return;}
   try{res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':'text/html');res.end(fs.readFileSync(file));}catch{res.writeHead(404).end();}
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 let browser;
 try{
 browser=await chromium.launch({headless:true,channel:'chrome'});
 const context=await browser.newContext({viewport:{width:390,height:844},timezoneId:'America/Los_Angeles'});
 const errors=[];
 await context.route('**/*',route=>{
   const url=route.request().url();
   if(url.startsWith('http://127.0.0.1:'))return route.continue();
   if(url.includes('supabase-js'))return route.fulfill({contentType:'text/javascript',body:fixture});
   if(/chart/i.test(url))return route.fulfill({contentType:'text/javascript',body:'window.Chart = function(){};'});
   return route.abort();
 });
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.clock.install({time:new Date('2026-10-17T22:00:00Z')});
 const url='http://127.0.0.1:'+server.address().port;
 await page.goto(url+'/dashboard.html');
 await page.waitForFunction(()=>document.getElementById('daily-checkin-prompt').open);
 assert.match(await page.locator('#daily-checkin-title').innerText(),/今日/);
 await page.getByText('あとで記録する',{exact:true}).click();
 await page.reload();
 await page.waitForFunction(()=>document.getElementById('welcome-name').textContent.includes('架空'));
 assert.equal(await page.locator('#daily-checkin-prompt').evaluate(e=>e.open),false);
 await page.locator('#daily-checkin-card').click();
 await page.waitForFunction(()=>!document.getElementById('submit-btn').disabled);
 assert.match(await page.locator('#date-badge').innerText(),/10月18日/);
 await page.evaluate(()=>{setScore('mood',4);setScore('action',3);setScore('state',2);document.getElementById('note').value='架空メモ';});
 await page.evaluate(()=>{submitCheckin();submitCheckin();});
 await page.waitForFunction(()=>document.getElementById('done-screen').style.display==='block');
 assert.equal(await page.evaluate(()=>fixture.writes),1);
 assert.equal(await page.evaluate(()=>fixture.rows[0].date),'2026-10-18');
 // A read error must not become a new blank writable form.
 await page.addInitScript(()=>{window.failOnLoad=true;});
 await context.route(url=>url.href.includes('supabase-js'),route=>route.fulfill({contentType:'text/javascript',body:fixture+'fixture.failRead=true;'}));
 await page.reload();
 await page.waitForSelector('#auth-service-warning');
 assert.equal(await page.locator('#submit-btn').isDisabled(),true);
 // Existing same-day record is editable; failures preserve input, not a success screen.
 await context.route(url=>url.href.includes('supabase-js'),route=>route.fulfill({contentType:'text/javascript',body:fixture+`fixture.rows=[{user_id:'fixture-a',date:'2026-10-18',mood:3,action:3,state:3,note:'既存',tags:['普通']}];`}));
 await page.reload();await page.waitForFunction(()=>!document.getElementById('submit-btn').disabled);
 assert.match(await page.locator('#submit-btn').innerText(),/更新/);
 await page.evaluate(()=>{fixture.failSave=true;document.getElementById('note').value='未保存の入力';submitCheckin();});
 await page.waitForFunction(()=>document.getElementById('checkin-status').textContent.includes('保存を確認できません'));
 assert.equal(await page.locator('#note').inputValue(),'未保存の入力');
 assert.equal(await page.locator('#done-screen').isVisible(),false);
 // An overnight form cannot accidentally update zero rows on a new date.
 await page.clock.fastForward(17*3600000+60000);
 assert.match(await page.locator('#checkin-status').innerText(),/日付が変わりました/);
 assert.match(await page.locator('#submit-btn').innerText(),/再読み込み/);
 await page.locator('#submit-btn').click();
 await page.waitForFunction(()=>!document.getElementById('submit-btn').disabled);
 assert.match(await page.locator('#submit-btn').innerText(),/チェックインする/);
 await page.evaluate(()=>{setScore('mood',2);setScore('action',4);setScore('state',3);submitCheckin();});
 await page.waitForFunction(()=>document.getElementById('done-screen').style.display==='block');
 assert.equal(await page.evaluate(()=>fixture.rows.length),2);
 assert.equal(await page.evaluate(()=>fixture.rows[1].date),'2026-10-19');
 await page.goto(url+'/dashboard.html');
 await page.waitForFunction(()=>document.getElementById('daily-checkin-prompt').open);
 await page.getByText('あとで記録する',{exact:true}).click();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.screenshot({path:path.join(base,'tests/daily-dashboard-mobile.png'),fullPage:true});
 // Admin comparison and gap display; same day is in Japan regardless of browser zone.
 await context.route(url=>url.href.includes('supabase-js'),route=>route.fulfill({contentType:'text/javascript',body:fixture+`fixture.user.email='shoyaaaaaa1127@gmail.com';fixture.rows=[{user_id:'fixture-a',date:'2026-10-19',mood:4,action:4,state:4},{user_id:'fixture-a',date:'2026-10-18',mood:2,action:2,state:2}];`}));
 await page.goto(url+'/admin.html');
 await page.locator('button[data-detail]').first().waitFor();
 assert.match(await page.locator('#member-table').innerText(),/前日差：\+2.0/);
 await page.locator('button[data-detail]').first().click();
 await page.waitForFunction(()=>document.getElementById('modal-body').textContent.includes('直近14日の変化'));
 assert.match(await page.locator('#modal-body').innerText(),/未記録/);
 await page.screenshot({path:path.join(base,'tests/daily-admin-mobile.png'),fullPage:true});
 assert.deepEqual(errors,[]);
 console.log('PASS browser: daily prompt/skip/next day, JST overseas, single flight, read/save failures, preserved input, midnight rollover, admin trends, mobile layout; no external DB requests');
 }finally{await browser?.close();server.closeAllConnections();await new Promise(r=>server.close(r));}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
