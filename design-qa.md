# Agents directory design verification

**Final result: passed**

No actionable P0/P1/P2 findings remain in the verified implementation. This is
the approved Layout 1 adapted to the existing Pulse application, with editable
PC/VPS/Cloud device names and a single-pane mobile flow.

## Evidence and normalization

All evidence under `docs/agents-design/` uses fictional agents and activity.
The implementation was browser-rendered at `http://127.0.0.1:4102/#/agents`
using `python3 scripts/demo_agents.py` and the in-app browser.

| View | Source visual truth | Implementation | CSS viewport | Image pixels |
| --- | --- | --- | --- | --- |
| Desktop | [Approved layout](docs/agents-design/approved-desktop.png) | [Directory/session reader](docs/agents-design/desktop-final.png) | 1440 × 1024 | Source 1487 × 1058; capture 1425 × 1013 |
| Mobile directory | [Approved directory](docs/agents-design/approved-mobile-directory.png) | [Directory](docs/agents-design/mobile-directory.png) | 390 × 844 | Source 853 × 1844; capture 375 × 812 |
| Mobile conversation | [Approved conversation](docs/agents-design/approved-mobile-conversation.png) | [Request and reply](docs/agents-design/mobile-conversation.png) | 390 × 844 | Source 853 × 1844; capture 390 × 844 |

Browser device pixel ratio was 1. The capture provider scaled some screenshots;
comparison copies normalize desktop images to 1100px wide and mobile images to
390px wide, preserving aspect ratios. There are no device frames or browser
toolbars in the comparisons. An initially undersized conversation capture was
discarded and recaptured at 390 × 844 before review.

Source and implementation were opened together in these comparison inputs:

- [Desktop comparison](docs/agents-design/desktop-comparison.png)
- [Mobile directory comparison](docs/agents-design/mobile-directory-comparison.png)
- [Mobile conversation comparison](docs/agents-design/mobile-conversation-comparison.png)

The mobile comparisons make text, controls and spacing legible at their intended
CSS width, so separate crops were unnecessary. The full desktop implementation
and [completed conversation](docs/agents-design/desktop-conversation.png) were also
inspected for small text and message hierarchy.

## Findings and accepted differences

- **Typography:** Existing Pulse system sans-serif is retained; no font was
  identified or licensed from the generated reference. The hierarchy uses bold
  page/task titles, 16px directory names, secondary device labels, and 15px message
  text. Names wrap, session titles/previews truncate, and full text remains in the
  conversation. Keyboard focus remains visible.
- **Layout and spacing:** Desktop retains three independently scrollable panels.
  At 900px and below, Agents, Sessions and Conversation occupy separate views.
  The conversation removes redundant page/search headers. Named device cards,
  rename controls, and participant information are visible on phones. More
  fictional agents than the mock naturally require scrolling; device cards were
  not compressed to force every device above the fold.
- **Colors:** Existing warm backgrounds, burgundy selection, subdued borders and
  pastel initial avatars follow the selected direction. Green and red presence
  dots have text labels; Working/Idle are separate. Dark theme uses the existing
  Pulse tokens with readable presence and message colors.
- **Assets:** The existing Pulse logo is preserved. Local Bootstrap Icons 1.11.3
  provide device, search, edit and navigation icons with their MIT license.
  Initial avatars and status indicators are UI primitives. No generated mockup
  is embedded as the functioning interface.
- **Content:** Real request/reply semantics replace illustrative streaming text.
  Running requests show their actual state; intermediate messages, typing
  indicators and reply timestamps are not invented. The mobile reply comparison
  therefore uses a completed task, while its source depicts a running task.
  The demo banner, existing application header/bottom navigation, and larger
  multi-device dataset intentionally differ from the conceptual mockup.

## Comparison history

Before the final combined-image comparison, browser inspection identified a
mobile navigation click-bubbling bug, excessive conversation header space, and
small desktop metadata. The click binding was limited to mobile tab buttons;
the conversation now uses its own header/participant list; desktop directory,
preview and message type sizes were increased. The final combined inputs above
show those corrected states. The final comparison introduced no further
P0/P1/P2 changes.

## Verification

- Python 3.12.3: `python3 scripts/check.py` ran 72 tests, 70 passed and two optional
  real-Copyparty tests skipped. JavaScript syntax and both frontend checks passed.
- Focused network suite rerun: 14 passed, two optional integration skips.
- Schema 7 → 8 migration is idempotent and preserves identities, credential
  hashes, sessions, grants and requests. Rename tests also verify owner-only and
  cross-origin restrictions and preservation of routing/permissions.
- Presence tests cover a busy message worker alongside a ready file connector,
  stale worker, file-only presence, active lease, idle and offline states.
- Browser verified device and agent rename/reload persistence, two Cloud device
  groups, long names, search/no-result state, task/reply selection, mobile Back,
  browser Back retaining the agent filter, Settings, and dark theme.
- No horizontal overflow at 320, 390, 768, 900, 901, 1024 and 1440px widths.
- Console warning/error inspection returned no entries.
- Frontend checks verify escaping names/messages and unavailable status after a
  failed refresh. An actual browser transport outage was not simulated.

## Implementation checklist

- [x] Editable device names/types and agent names without identity changes.
- [x] Labeled online/offline presence and separate activity state.
- [x] Readable per-task sessions and request/reply conversations.
- [x] Desktop and mobile flow, existing permissions/files/history retained.
- [x] Local checks and browser-rendered visual verification.
- [ ] Review/merge and production rollout; live Pulse has not been changed.

Residual test gaps: optional real storage integration was not rerun for this UI
change; only Python 3.12 was run in this task. No production migration or live
device rename has been performed.

final result: passed
