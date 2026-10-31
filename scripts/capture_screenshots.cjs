#!/usr/bin/env node
// Always owns a fresh demo subprocess. No live URL/database input is accepted.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const {spawn} = require('node:child_process');
const {once} = require('node:events');
const {chromium} = require(process.env.PULSE_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const output = path.resolve(process.env.PULSE_SCREENSHOT_OUTPUT || path.join(root, 'docs/screenshots'));
const expectedProjects = ['Book draft', 'Home renovation', 'Mobile app', 'Website redesign'].sort();
const routes = [['today', '/'], ['board', '/p/website'], ['notes', '/notes/1'],
  ['todos', '/todos'], ['reminders', '/reminders'], ['memory', '/memory'], ['inbox', '/inbox']];
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

async function main() {
  const socket = net.createServer();
  socket.listen(0, '127.0.0.1'); await once(socket, 'listening');
  const port = socket.address().port; await new Promise(resolve => socket.close(resolve));
  // A minimal environment prevents inherited production integration settings.
  const demo = spawn(process.env.PULSE_TEST_PYTHON || 'python3', ['scripts/demo.py'], {
    cwd: root, env: {PATH: process.env.PATH, HOME: process.env.HOME, LANG: 'C.UTF-8', TZ: 'UTC',
      PULSE_DEMO_PORT: String(port)}, stdio: ['ignore', 'pipe', 'pipe']
  });
  let outputText = '', startupError;
  demo.on('error', error => { startupError = error; });
  demo.stdout.on('data', chunk => { outputText += chunk; });
  demo.stderr.on('data', chunk => { outputText += chunk; });
  const base = `http://127.0.0.1:${port}`;
  let browser;
  try {
    for (let attempt = 0; attempt < 100 && !outputText.includes('Pulse demo running'); attempt++) {
      if (startupError) throw startupError;
      if (demo.exitCode !== null) throw new Error(`Demo failed: ${outputText}`);
      await wait(100);
    }
    assert.ok(outputText.includes('Pulse demo running'), 'Owned demo server started');
    const projects = await (await fetch(base + '/api/projects')).json();
    assert.deepEqual(projects.map(p => p.name).sort(), expectedProjects, 'Only known fictional projects');
    fs.mkdirSync(output, {recursive: true});
    browser = await chromium.launch({executablePath: process.env.PULSE_CHROMIUM || undefined, args: ['--no-sandbox']});
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}, colorScheme: 'light', timezoneId: 'UTC'});
    const errors = [];
    await context.route('**/*', route => new URL(route.request().url()).origin === base ? route.continue() : route.abort());
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    await page.goto(base); await page.waitForLoadState('networkidle');
    let captureVisit = 0;
    const selectors = {'/': '.dash', '/p/website': '.board', '/notes/1': '.nview',
      '/todos': '#qa', '/reminders': '#ra', '/memory': '#mnew', '/inbox': '#readAll'};
    async function visit(route, label = false) {
      // Force a new document: hash-only navigation can finish before async routing.
      await page.goto(base + '/?capture=' + (++captureVisit) + '#' + route);
      await page.locator(selectors[route]).waitFor({state: 'visible'});
      await page.waitForLoadState('networkidle');
      if (label) await page.evaluate(() => {
        const notice = document.createElement('aside'); notice.className = 'demo-notice';
        notice.textContent = 'Demo workspace · All projects, names and content are fictional';
        document.querySelector('header').after(notice);
      });
    }
    const theme = () => page.locator('html').getAttribute('data-theme');
    assert.equal(await theme(), 'light');
    await page.emulateMedia({colorScheme: 'dark'});
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await page.selectOption('#themeSelect', 'light');
    await page.reload(); await page.waitForLoadState('networkidle');
    assert.equal(await theme(), 'light', 'Explicit choice survives reload and overrides system');
    const second = await context.newPage();
    await second.goto(base); await second.waitForLoadState('networkidle');
    await page.selectOption('#themeSelect', 'dark');
    await second.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await second.close();
    await page.selectOption('#themeSelect', 'system');
    await page.emulateMedia({colorScheme: 'light'});
    await page.waitForFunction(() => document.documentElement.dataset.theme === 'light');

    for (const width of [320, 390, 768, 820, 821, 900, 1024, 1280]) {
      await page.setViewportSize({width, height: 1000});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `No page overflow at ${width}px`);
    }
    await page.setViewportSize({width: 1440, height: 1000});
    for (const appearance of ['light', 'dark']) {
      await page.selectOption('#themeSelect', appearance);
      const ratios = await page.evaluate(() => {
        const style = getComputedStyle(document.documentElement);
        const value = token => style.getPropertyValue('--' + token).trim();
        const luminance = hex => {
          const [r, g, b] = hex.match(/[\da-f]{2}/gi).map(n => parseInt(n, 16) / 255)
            .map(n => n <= .04045 ? n / 12.92 : ((n + .055) / 1.055) ** 2.4);
          return .2126 * r + .7152 * g + .0722 * b;
        };
        const contrast = (a, b) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
        return ['fg', 'mut', 'acc', 'idea', 'active', 'blocked', 'paused', 'done']
          .flatMap(token => ['bg', 'card', 'card2'].map(surface => contrast(luminance(value(token)), luminance(value(surface)))))
          .concat(contrast(luminance(value('on-primary')), luminance(value('primary'))));
      });
      assert.ok(ratios.every(ratio => ratio >= 4.5), `Text/action token contrast in ${appearance}`);
    }

    // A theme change must preserve unsaved work in a real dialog.
    await visit('/todos');
    await page.locator('.todo .tt').first().click();
    await page.locator('#todoDlg').waitFor({state: 'visible'});
    await page.locator('#todoForm input[name="title"]').fill('Unsaved demo edit');
    await page.evaluate(() => {
      const select = document.querySelector('#themeSelect'); select.value = 'dark';
      select.dispatchEvent(new Event('change', {bubbles: true}));
    });
    assert.equal(await page.locator('#todoForm input[name="title"]').inputValue(), 'Unsaved demo edit');
    await page.locator('#todoDlg button[value="cancel"]').click();
    await page.locator('#qa input[name="title"]').fill('Synthetic browser persistence check');
    await page.locator('#qa button').click();
    await page.getByText('Synthetic browser persistence check', {exact: true}).waitFor();
    await page.reload(); await page.getByText('Synthetic browser persistence check', {exact: true}).waitFor();
    const todos = await (await page.request.get(base + '/api/todos?view=open')).json();
    const todo = todos.find(item => item.title === 'Synthetic browser persistence check');
    assert.ok(todo); assert.ok((await page.request.delete(base + '/api/todos/' + todo.id)).ok());

    for (const appearance of ['light', 'dark']) {
      await page.selectOption('#themeSelect', appearance);
      for (const [name, route] of routes) {
        await visit(route, true);
        assert.equal(await theme(), appearance);
        assert.ok((await page.locator('main').innerText()).length > 40);
        await page.screenshot({path: path.join(output, `${name}-${appearance}.png`), fullPage: true});
      }
      await page.setViewportSize({width: 390, height: 844});
      for (const [name, route] of routes.slice(0, 2)) {
        await visit(route, true);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No viewport overflow');
        await page.screenshot({path: path.join(output, `mobile-${name}-${appearance}.png`)});
      }
      await page.setViewportSize({width: 1440, height: 1000});
    }
    for (const name of ['today', 'board', 'notes', 'todos', 'reminders', 'memory', 'mobile-today', 'mobile-board']) {
      fs.copyFileSync(path.join(output, `${name}-light.png`), path.join(output, `${name}.png`));
    }
    // Browser storage restrictions must not prevent rendering or switching themes.
    const restricted = await browser.newContext({colorScheme: 'dark'});
    await restricted.addInitScript(() => Object.defineProperty(window, 'localStorage', {get() { throw new DOMException('Blocked', 'SecurityError'); }}));
    const restrictedPage = await restricted.newPage();
    restrictedPage.on('pageerror', error => errors.push(error.message));
    await restrictedPage.goto(base); await restrictedPage.waitForLoadState('networkidle');
    assert.equal(await restrictedPage.locator('html').getAttribute('data-theme'), 'dark');
    await restrictedPage.selectOption('#themeSelect', 'light');
    assert.equal(await restrictedPage.locator('html').getAttribute('data-theme'), 'light');
    await restricted.close();
    assert.deepEqual(errors, []);
    console.log(`Theme persistence/system/cross-tab/blocked-storage and dialog/todo checks passed. Synthetic screenshots: ${output}`);
  } finally {
    if (browser) await browser.close();
    if (demo.exitCode === null && demo.pid) {
      const stopped = once(demo, 'exit'); demo.kill('SIGTERM');
      const timer = setTimeout(() => demo.kill('SIGKILL'), 5000);
      await stopped; clearTimeout(timer);
    }
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
