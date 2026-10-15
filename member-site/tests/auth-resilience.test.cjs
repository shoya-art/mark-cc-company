const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const base = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(base, 'auth-resilience.js'), 'utf8');
function setup() {
  const elements = new Map();
  function element() { return {style:{}, append(){}, setAttribute(){}, focus(){}}; }
  const c = {setTimeout, clearTimeout, AbortController, fetch: global.fetch,
    location:{replace(url){c.redirect=url;},reload(){}},
    document:{getElementById(id){return elements.get(id);},createElement:element,body:{children:[{inert:false}],append(el){elements.set(el.id,el);}}}};
  // UI cooldown does not keep Node running; transport deadlines are tested independently.
  c.setTimeout=(fn,ms)=>{const t=setTimeout(fn,ms);t.unref();return t;};
  c.window=c; vm.createContext(c); vm.runInContext(source,c); return c;
}
function client(profile, error=null, authError=null) {
  return {auth:{getUser:async()=>({data:{user:{id:'u',email:'128@lily-member.app'}},error:authError}),signInWithPassword:async()=>({data:{user:{id:'u',email:'128@lily-member.app'}},error:authError})},
    from(){return {select(){return this;},eq(){return this;},maybeSingle:async()=>({data:profile,error})};}};
}
test('all inline scripts compile and use shared guarded auth',()=>{
  for(const name of fs.readdirSync(base).filter(n=>n.endsWith('.html'))) {
    const html=fs.readFileSync(path.join(base,name),'utf8');
    for(const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(m[1],{filename:name});
    assert.match(html,/auth-resilience\.js\?v=20261015/);
    assert.doesNotMatch(html,/await sb\.auth\.getUser\(/);
  }
});
for(const error of [{status:504},{status:500,code:'unexpected_failure'},{name:'TypeError'},{name:'AbortError'},{code:'request_timeout'}]) {
  test('transport error does not claim wrong password '+JSON.stringify(error),async()=>{
    const c=setup(); assert.match(c.MemberAuth.message(error),/通信/);
    assert.equal(await c.MemberAuth.requireUser(client(null,null,error)),null);
    assert.equal(c.redirect,undefined); assert.ok(c.document.getElementById('auth-service-warning'));
  });
}
test('wrong password, rate limit, unknown error are distinguished',()=>{
  const {MemberAuth:a}=setup(); assert.equal(a.kind({code:'invalid_credentials'}),'credentials');
  assert.equal(a.kind({status:429}),'rate'); assert.match(a.message({code:'mystery'}),/通信/);
});
test('valid user is server checked; missing session redirects',async()=>{
  const c=setup();assert.equal((await c.MemberAuth.requireUser(client({name:'test'}))).id,'u');
  await c.MemberAuth.requireUser(client(null,null,{name:'AuthSessionMissingError'})); assert.equal(c.redirect,'index.html');
});
test('thrown network error fails closed',async()=>{
  const c=setup();assert.equal(await c.MemberAuth.requireUser({auth:{getUser:async()=>{throw new TypeError('offline');}}}),null);assert.equal(c.redirect,undefined);
  assert.equal(c.document.body.children[0].inert,true);
});
test('login routes existing and new profiles without database writes',async()=>{
  const a=setup().MemberAuth;
  assert.equal(await a.login(client({name:'test'}),'test','fixture'),'dashboard.html');
  assert.equal(await a.login(client(null),'test','fixture'),'onboarding.html');
  assert.equal(a.routeFor({email:'129@lily-member.app'},{name:'test'}),'member-profile.html');
  assert.equal(a.routeFor({email:'129@lily-member.app'},{name:'test',full_name:'test'}),'dashboard.html');
});
test('profile read failure never routes to registration',async()=>{
  await assert.rejects(setup().MemberAuth.login(client(null,{status:504}),'test','fixture'));
});
test('duplicate login calls are ignored until settled, then reusable',async()=>{
  const a=setup().MemberAuth;let resolve;let calls=0;
  const once=a.singleFlight(()=>{calls++;return new Promise(r=>{resolve=r;});});
  const p=once();await once();assert.equal(calls,1);resolve();await p;
  const p2=once();assert.equal(calls,2);resolve();await p2;
});
test('single flight releases after failure',async()=>{
  let calls=0;const run=setup().MemberAuth.singleFlight(async()=>{calls++;throw Error('fixture');});
  await assert.rejects(run());await assert.rejects(run());assert.equal(calls,2);
});
test('index never signs out on load and never inserts profile',()=>{
  const h=fs.readFileSync(path.join(base,'index.html'),'utf8');
  assert.doesNotMatch(h,/sb\.auth\.signOut|\.insert\(|\.upsert\(/);
  assert.match(h,/MemberAuth.singleFlight/);
});
test('fetch enforces deadline and retains caller cancellation',async()=>{
  const c=setup();let abortCallback; c.setTimeout=fn=>{abortCallback=fn;return 1;};c.clearTimeout=()=>{};
  c.fetch=(_,init)=>new Promise((resolve,reject)=>{
    if(init.signal.aborted)return reject(new Error('aborted'));
    init.signal.addEventListener('abort',()=>reject(new Error('aborted')));
  });
  const p=c.MemberAuth.boundedFetch('https://example.test');abortCallback();await assert.rejects(p,/aborted/);
  const controller=new AbortController();controller.abort();await assert.rejects(c.MemberAuth.boundedFetch('https://example.test',{signal:controller.signal}),/aborted/);
});
