// Run before the stylesheet so the first paint uses the saved appearance.
(() => {
  const key = 'pulse-theme';
  const valid = value => ['light', 'dark', 'system'].includes(value) ? value : 'system';
  const system = matchMedia('(prefers-color-scheme: dark)');
  let preference = 'system';
  try { preference = valid(localStorage.getItem(key)); } catch (_) { /* Storage may be disabled. */ }

  function apply() {
    const theme = preference === 'system' ? (system.matches ? 'dark' : 'light') : preference;
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#151215' : '#faf7f5');
    const select = document.querySelector('#themeSelect');
    if (select) {
      select.value = preference;
      select.title = `Appearance: ${preference}${preference === 'system' ? ` (${theme})` : ''}`;
    }
  }
  apply();
  system.addEventListener('change', () => { if (preference === 'system') apply(); });
  addEventListener('storage', event => {
    if (event.key === key || event.key === null) { preference = valid(event.newValue); apply(); }
  });
  document.addEventListener('DOMContentLoaded', () => {
    apply();
    document.querySelector('#themeSelect')?.addEventListener('change', event => {
      preference = valid(event.target.value);
      try { localStorage.setItem(key, preference); } catch (_) { /* Keep this tab usable. */ }
      apply();
    });
  });
})();
