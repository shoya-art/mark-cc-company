const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const base = path.join(__dirname, '..');
function setup() {
  const c = {}; vm.createContext(c);
  vm.runInContext(fs.readFileSync(path.join(base, 'daily-checkin.js'), 'utf8'), c);
  return c.DailyCheckin;
}
const d = setup();
test('Japan midnight, morning, month/year and leap boundaries', () => {
  assert.equal(d.dayKey(new Date('2026-10-17T14:59:59Z')), '2026-10-17');
  assert.equal(d.dayKey(new Date('2026-10-17T15:00:00Z')), '2026-10-18');
  assert.equal(d.dayKey(new Date('2026-10-17T22:00:00Z')), '2026-10-18');
  assert.equal(d.dayKey(new Date('2026-12-31T15:00:00Z')), '2027-01-01');
  assert.equal(d.shiftDay('2028-03-01', -1), '2028-02-29');
});
function client() {
  const rows = new Map();
  return { rows, from(table) {
    assert.equal(table, 'checkins');
    let record, filters = {};
    return { upsert(r, opts) { assert.equal(opts.onConflict, 'user_id,date'); record = r; return this; },
      select() { return this; }, eq(k,v) { filters[k] = v; return this; },
      async maybeSingle() { return {data:rows.get(filters.user_id + ':' + filters.date) || null}; },
      async single() { rows.set(record.user_id + ':' + record.date, {...record}); return {data:{date:record.date}}; } };
  } };
}
const record = {user_id:'fixture-a',date:'2026-10-18',mood:3,action:4,state:2,tags:['普通'],note:'架空テスト'};
test('same day edits one row, next day preserves prior day, accounts stay separate', async () => {
  const c = client();
  await d.save(c, record); await d.save(c, {...record,mood:5});
  assert.equal(c.rows.size,1);
  await d.save(c,{...record,date:'2026-10-19'});
  await d.save(c,{...record,user_id:'fixture-b'});
  assert.equal(c.rows.size,3);
  assert.equal((await d.loadToday(c,'fixture-a','2026-10-18')).mood,5);
  assert.equal((await d.loadToday(c,'fixture-b','2026-10-18')).mood,3);
  assert.equal(await d.loadToday(c,'fixture-c','2026-10-18'),null);
});
test('read failure is not missing data; save failure and missing write confirmation reject', async () => {
  const bad = {from(){return {select(){return this;},eq(){return this;},upsert(){return this;},
    maybeSingle:async()=>({error:{status:504}}),single:async()=>({data:null})};}};
  await assert.rejects(d.loadToday(bad,'a'));
  await assert.rejects(d.save(bad,record));
  await assert.rejects(d.save(client(),{...record,mood:0}));
  await assert.rejects(d.save(client(),{...record,user_id:null}));
});
test('summary uses calendar days, excludes missing days and future, names comparison basis', () => {
  const rows = [{...record,mood:4,action:4,state:4}, {...record,date:'2026-10-17',mood:2,action:2,state:2},
    {...record,date:'2026-10-10',mood:1,action:1,state:1},{...record,date:'2026-10-19',mood:5,action:5,state:5}];
  const s = d.summary(rows,'2026-10-18');
  assert.equal(s.avg,3); assert.equal(s.delta,2); assert.equal(s.moodDelta,2);
  assert.equal(s.recentCount,2); assert.equal(s.priorCount,1);
  assert.equal(d.summary([record],'2026-10-18').moodDelta,null);
  assert.equal(d.summary([],'2026-10-18').avg,null);
  assert.match(d.summaryText(rows,'2026-10-18'),/比較元1日/);
});
test('prompt dismissal is isolated by user and Japan date', () => {
  assert.notEqual(d.promptKey('a','2026-10-18'),d.promptKey('a','2026-10-19'));
  assert.notEqual(d.promptKey('a','2026-10-18'),d.promptKey('b','2026-10-18'));
});
test('admin reads all bounded pages and fails instead of returning partial data', async () => {
  let calls=0;
  const c={from(){return {select(){return this;},gte(k,v){assert.equal(v,'2026-10-05');return this;},lte(k,v){assert.equal(v,'2026-10-18');return this;},order(){return this;},
    async range(start,end){calls++;assert.equal(end-start,499);return {data:Array(start===0?500:2).fill(record)};}};}};
  assert.equal((await d.loadRecent(c,'2026-10-18')).data.length,502);assert.equal(calls,2);
});
