// Security and data semantics of the session reader; browser interaction is checked separately.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const context = vm.createContext({URL, URLSearchParams, console, setInterval:()=>{}, addEventListener:()=>{}, queueMicrotask:()=>{},
  document:{addEventListener:()=>{},querySelector:()=>null,querySelectorAll:()=>[]}});
for (const name of ['core','network']) vm.runInContext(fs.readFileSync(`static/${name}.js`,'utf8'),context);
const run=code=>vm.runInContext(code,context);
run(`networkView.data={agents:[{id:'pc/codex',device:'pc',label:'<img src=x onerror=alert(1)>'},{id:'cloud/codex',device:'cloud',label:'Codex'}],devices:[{id:'pc',label:'Home PC'},{id:'cloud',label:'Build Cloud'}]}`);
const request={id:'r',sender:'pc/codex',recipient:'cloud/codex',kind:'message',payload:{message:'Review <script>bad()</script>\nDetails'},result:{message:'<img src=x onerror=alert(2)>\nReply'},status:'completed',created_at:1,finished_at:null};
const html=run(`networkConversation(${JSON.stringify(request)})`);
assert.ok(!html.includes('<script>')); assert.ok(!html.includes('<img src=x'));
assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('&lt;img'));
assert.ok(html.includes('Home PC'));assert.ok(html.includes('Build Cloud'));
assert.ok(html.includes('Reply</span>'),'Unknown reply timestamp is not invented');
assert.equal(run(`networkTitle(${JSON.stringify(request)})`),'Review <script>bad()</script>');
assert.ok(run(`networkParticipants(${JSON.stringify(request)})`).includes('Build Cloud'));
const online={status:'busy',activity:'working',last_seen:1};
assert.ok(run(`networkPresence(${JSON.stringify(online)})`).includes('Working'));
run('networkView.stale=true');
assert.ok(!run(`networkPresence(${JSON.stringify(online)})`).includes('Online'));
assert.ok(run(`networkPresence(${JSON.stringify(online)})`).includes('Status unavailable'));
console.log('Network escaping, device labels, request/reply semantics and stale presence checks passed.');
