// Pure rendering tests: no browser or npm dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const app = {innerHTML: ''}, readAll = {};
const context = vm.createContext({
  URL, console, setInterval: () => {}, addEventListener: () => {},
  document: {addEventListener: () => {}, querySelector: selector => selector === '#app' ? app : readAll,
             querySelectorAll: () => []}
});
vm.runInContext(fs.readFileSync(path.join(root, 'static/core.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(root, 'static/hub.js'), 'utf8'), context);
const evaluate = expression => vm.runInContext(expression, context);
const unsafe = ['javascript:alert(1)', 'JaVaScRiPt:alert(1)', 'java\nscript:alert(1)',
                'data:text/html,bad', '//evil.example', 'https://example.com\\@evil', null];
for (const value of unsafe) assert.equal(evaluate(`notificationUrl(${JSON.stringify(value)})`), '#/inbox');
for (const value of ['#/todos/1', 'https://example.com/path?q=1&b=2', 'http://localhost:4100/']) {
  assert.equal(evaluate(`notificationUrl(${JSON.stringify(value)})`), value);
}
(async () => {
  // Render a legacy stored link that predates API validation.
  evaluate(`api = async () => [{id: 1, kind: 'agent', read: 0, ts: 0,
    title: '<img src=x onerror=alert(1)>', body: '<script>bad</script>',
    link: 'javascript:alert(1)', delivery_status: 'retrying'}]`);
  await evaluate('renderInbox()');
  assert.ok(app.innerHTML.includes('href="#/inbox"'));
  assert.ok(!app.innerHTML.includes('javascript:'));
  assert.ok(!app.innerHTML.includes('<img'));
  assert.ok(!app.innerHTML.includes('<script>'));
  assert.ok(app.innerHTML.includes('Telegram retry scheduled'));
  console.log('Frontend URL, escaping and delivery rendering checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
