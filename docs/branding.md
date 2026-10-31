# Pulse identity and appearance

The selected mark is a curved pulse joining two rounded nodes, with a burgundy,
cherry-red and coral gradient. It represents connected people and agents. The
lowercase wordmark uses the approved artwork rather than a downloaded font.

`static/brand/pulse-logo.png` is the transparent lockup for the header and sign-in
screen; `pulse-mark.png` is its symbol-only companion. Both were prepared from
the owner-selected design with the built-in image generator. The exact prompts
are in `brand-prompts.json`. `static/icon.svg` is a simplified small-size vector
adaptation for the favicon and installed app. The CSS crops transparent padding
and recolors only a clipped copy of the wordmark for dark mode; the pulse keeps
its original red colors. No external font or asset service is required.

## Themes

Choose **System**, **Light** or **Dark** in the header, including before sign-in.
The default follows the device's color preference. An explicit choice is saved
under `pulse-theme` in browser storage and shared across tabs on that origin.
If browser storage is blocked, switching still works for the current page.
Appearance does not change records or discard unsaved form contents.

`static/theme.js` runs before the stylesheet to apply the preference before
painting. Colors are semantic variables in `static/app.css`, including surfaces,
text, links, actions, focus and status indicators. The browser theme color and
native form-control color scheme follow the active appearance.

| Token | Light | Dark |
| --- | --- | --- |
| Page | `#faf7f5` | `#151215` |
| Card | `#ffffff` | `#201b20` |
| Text | `#292227` | `#f6eff1` |
| Secondary text | `#71636a` | `#bcaeb4` |
| Links/focus | `#b51d3b` | `#ff9da9` |
| Primary action | `#b51d3b` | `#bd2341` |

Browser behavior follows [prefers-color-scheme](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-color-scheme)
and [localStorage](https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage).

## Public screenshots: fictional data only

Never capture the maintainer's live instance, real project names, plans, feature
descriptions, personal notes, memory or notifications for public documentation.
Use `scripts/capture_screenshots.cjs`. It launches its own loopback demo server
with a new temporary database and configuration, asserts the known fictional
project inventory, blocks external browser requests, and labels every capture
as demo content. It accepts no target URL or database. The demo disables external
integrations and removes its temporary data when stopped.

For development, use Node.js 20+ and an existing Playwright installation with
Chromium. These are screenshot/test tools, not app runtime dependencies:

```bash
PULSE_PLAYWRIGHT_MODULE=/path/to/playwright \
PULSE_CHROMIUM=/path/to/chromium \
node scripts/capture_screenshots.cjs
```

When Playwright and its Chromium are installed in the normal Node resolution and
browser-cache locations, simply run `node scripts/capture_screenshots.cjs`.
Optional `PULSE_TEST_PYTHON` chooses a Python executable; `PULSE_SCREENSHOT_OUTPUT`
changes only the output directory. The default is `docs/screenshots`.

The script exercises theme persistence, system changes, cross-tab updates,
blocked storage, preservation of dialog input and todo creation/reload. It
captures desktop and mobile views in both themes and refreshes the historical
unsuffixed screenshot filenames with light-theme samples. Review the resulting
images before committing. Never substitute live screenshots if a capture fails.
