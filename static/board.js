function renderTabs(active) {
  const ps = [...projects].sort((a, b) => order[a.status] - order[b.status] || a.name.localeCompare(b.name));
  $("#tabs").innerHTML = `<a class="tab ${!active ? "on" : ""}" href="#/projects">All projects</a>` + ps.map(p =>
    `<a class="tab ${active === p.slug ? "on" : ""}" href="#/p/${esc(p.slug)}"><span class="d" style="background:${COLORS[p.status]}"></span>${esc(p.name)}</a>`).join("");
  $("#tabs .on")?.scrollIntoView({block: "nearest", inline: "nearest"});
}

// ---------- overview ----------
function renderOverview() {
  const ps = [...projects].sort((a, b) => order[a.status] - order[b.status] || b.updated_at - a.updated_at);
  const n = s => ps.filter(p => p.status === s).length;
  const blockedCards = ps.reduce((a, p) => a + p.counts.blocked, 0);
  $("#app").innerHTML = `
    <div class="pagehead"><h1>Projects</h1><span class="sp"></span><button id="newBtn" class="pri">+ Project</button></div>
    <div class="stats"><span>${ps.length} projects</span><span>${n("active")} active</span><span>${n("blocked")} blocked</span>
      <span>${blockedCards} blocked cards</span><span>${ps.filter(isStale).length} stale (&gt;${STALE_DAYS}d)</span></div>
    ${ps.length ? `<div class="grid">${ps.map(pcard).join("")}</div>` : `<div class="empty">No projects yet.</div>`}`;
  $$(".pcard").forEach(c => c.onclick = () => location.hash = "#/p/" + c.dataset.slug);
  $("#newBtn").onclick = () => $("#newDlg").showModal();
}
function pcard(p) {
  const u = p.last_update;
  const counts = COLS.filter(([k]) => p.counts[k]).map(([k, l]) => `<span class="cnt"><i style="background:var(--c-${k})"></i>${l} ${p.counts[k]}</span>`).join("");
  return `<div class="pcard ${isStale(p) ? "stale" : ""}" data-slug="${esc(p.slug)}">
    <div class="row"><span class="name">${esc(p.name)}</span><span class="badge b-${p.status}">${p.status}</span></div>
    <div class="row">${progBar(p)}</div>
    ${counts ? `<div class="counts">${counts}</div>` : ""}
    ${p.next_step ? `<div class="next"><b>Next:</b> ${esc(p.next_step)}</div>` : ""}
    ${u ? `<div class="last"><b>${esc(u.author)}</b> · ${ago(u.ts)} — ${esc(u.text)}</div>` : ""}
    ${isStale(p) ? `<span class="stale-tag">⚠ no update for ${ago(p.updated_at)}</span>` : ""}
  </div>`;
}

// ---------- project ----------
function projectHead(p, view) {
  return `<div class="phead"><h2>${esc(p.name)}</h2><span class="badge b-${p.status}">${p.status}</span>
    <div class="row" style="flex:1;min-width:160px;max-width:260px">${progBar(p)}</div><span class="sp"></span>
    <div class="seg"><a href="#/p/${esc(p.slug)}" class="${view === "board" ? "on" : ""}">Board</a><a href="#/p/${esc(p.slug)}/activity" class="${view === "activity" ? "on" : ""}">Activity</a></div></div>
    ${p.next_step ? `<p class="next" style="margin:-4px 0 10px"><b>Next:</b> ${esc(p.next_step)}</p>` : ""}`;
}

function kcard(c) {
  const link = safeUrl(c.link);
  return `<div class="kc" data-id="${c.id}" style="--cc:var(--c-${c.col})">
    <div class="t">${esc(c.title)}</div>
    ${c.body ? `<div class="b">${esc(c.body)}</div>` : ""}
    ${c.col === "blocked" ? `<div class="blk"><b>${esc(OWNERS[c.block_owner] || c.block_owner)}:</b> ${esc(c.block_reason)}</div>` : ""}
    <div class="m">${link ? `<a class="chip" href="${esc(link)}" target="_blank" rel="noopener" data-nodrag>${esc(linkLabel(link))} ↗</a>` : ""}
      <span>${esc(c.created_by)} · ${ago(c.updated_at)}</span></div></div>`;
}

function renderBoard(p) {
  const prevScroll = $(".board")?.scrollLeft || 0;
  const by = Object.fromEntries(COLS.map(([k]) => [k, []]));
  p.cards.forEach(c => (by[c.col] || by.todo).push(c));
  $("#app").innerHTML = projectHead(p, "board") +
    `<div class="row" style="flex-wrap:wrap;margin-bottom:6px"><p class="hint" style="margin:0;flex:1">Drag cards between columns · on phone/tablet press and hold a card, then drag · tap a card to edit</p>
      ${p.github_repo ? `<span class="sm mut"><a href="https://github.com/${esc(p.github_repo)}/issues" target="_blank" rel="noopener">${esc(p.github_repo)} ↗</a>
        · synced ${p.gh_synced_at ? ago(p.gh_synced_at) : "never"}</span><button id="ghSync" class="sm">⟳ Sync GitHub</button>` : ""}</div>
    <div class="jump">${COLS.map(([k, l]) => `<button data-jump="${k}"><i style="background:var(--c-${k})"></i>${l} ${by[k].length}</button>`).join("")}</div>
    <div class="board">${COLS.map(([k, l, sub]) => `<section class="col" data-col="${k}">
      <div class="ch"><i style="background:var(--c-${k})"></i><div><b>${l}</b> <span class="n">${by[k].length}</span><small>${sub}</small></div>
        <button data-add="${k}" title="Add card">+</button></div>
      <div class="list">${by[k].map(kcard).join("")}</div></section>`).join("")}</div>`;
  $(".board").scrollLeft = prevScroll;
  $$("[data-add]").forEach(b => b.onclick = () => openCard(null, b.dataset.add));
  if ($("#ghSync")) $("#ghSync").onclick = async e => { e.target.disabled = true; e.target.textContent = "Syncing…";
    try { const r = await api("POST", `/projects/${encodeURIComponent(p.slug)}/github/sync`);
      await route(); toast(`GitHub: ${r.imported} imported · ${r.closed} closed · ${r.reopened} reopened · ${r.renamed} renamed`); }
    catch (err) { fail(err); e.target.disabled = false; e.target.textContent = "⟳ Sync GitHub"; } };
  $$("[data-jump]").forEach(b => b.onclick = () => { const bd = $(".board"), c = $(`.col[data-col=${b.dataset.jump}]`);
    bd.scrollTo({left: bd.scrollLeft + c.getBoundingClientRect().left - bd.getBoundingClientRect().left - 16, behavior: "smooth"}); });
  $$(".kc").forEach(el => bindDrag(el));
}

function renderActivity(p) {
  const links = (p.links || []).map(l => typeof l === "string" ? {label: l, url: l} : l).filter(l => safeUrl(l.url));
  $("#app").innerHTML = projectHead(p, "activity") + `
    <div class="cols2"><div>
      <div class="panel"><h3>Post an update</h3>
        <form class="form" id="upd">
          <textarea name="note" placeholder="What happened? (optional)"></textarea>
          <div class="two"><select name="status">${STATUS.map(s => `<option ${s === p.status ? "selected" : ""}>${s}</option>`).join("")}</select>
            <input name="progress" type="number" min="0" max="100" value="${p.progress}" title="Progress % (auto from board when it has cards)"></div>
          <input name="next_step" value="${esc(p.next_step)}" placeholder="Next step">
          <input name="link" placeholder="Link (PR, doc…) optional">
          <div class="row"><span class="sp"></span><button class="pri">Save</button></div>
        </form></div>
      <div class="panel"><h3>Timeline</h3><ul class="tl">${p.updates.map(u => `<li class="k-${u.kind}"><span class="dot"></span><div>
          <div>${linkify(u.text)} ${safeUrl(u.link) ? `<a href="${esc(u.link)}" target="_blank" rel="noopener">↗</a>` : ""}</div>
          <div class="meta">${esc(u.author)} · ${u.kind} · <span title="${when(u.ts)}">${ago(u.ts)}</span></div></div></li>`).join("") || `<li class="mut">No updates yet.</li>`}</ul></div>
    </div><div>
      <div class="panel"><h3>Project</h3>
        ${p.summary ? `<p class="mut" style="margin:0 0 10px">${linkify(p.summary)}</p>` : ""}
        ${links.length ? `<p class="links" style="margin:0 0 10px">${links.map(l => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label || l.url)} ↗</a>`).join("")}</p>` : ""}
        <form class="form" id="meta">
          <input name="name" value="${esc(p.name)}" placeholder="Name">
          <textarea name="summary" placeholder="Summary">${esc(p.summary)}</textarea>
          <label class="f">GitHub repo for issue sync (owner/name)<input name="github_repo" value="${esc(p.github_repo || "")}" placeholder="e.g. octocat/hello-world"></label>
          <textarea name="links" placeholder="Links, one per line: Label | https://…">${esc(links.map(l => (l.label && l.label !== l.url ? l.label + " | " : "") + l.url).join("\n"))}</textarea>
          <div class="row"><button type="button" id="arch">${p.archived ? "Unarchive" : "Archive"}</button><span class="sp"></span><button>Save details</button></div>
        </form><p class="meta" style="margin:10px 0 0">Created ${when(p.created_at)} · updated ${ago(p.updated_at)}</p></div>
    </div></div>`;
  const path = "/projects/" + encodeURIComponent(p.slug);
  const run = async fn => { try { await fn(); await route(); } catch (e) { fail(e); } };
  $("#upd").onsubmit = e => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    const body = {status: f.status, next_step: f.next_step};
    if (+f.progress !== p.progress) body.progress = +f.progress;
    if (f.note.trim()) body.note = f.note; if (f.link.trim()) body.link = f.link.trim();
    run(() => api("PATCH", path, body)); };
  $("#meta").onsubmit = e => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    const links = f.links.split("\n").map(s => s.trim()).filter(Boolean).map(s => { const [a, b] = s.split("|").map(x => x.trim()); return b ? {label: a, url: b} : {label: "", url: a}; });
    run(() => api("PATCH", path, {name: f.name, summary: f.summary, links, github_repo: f.github_repo.trim()})); };
  $("#arch").onclick = () => run(() => api("PATCH", path, {archived: !p.archived}));
}

// ---------- card dialog ----------
const cf = $("#cardForm");
cf.column.innerHTML = COLS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
cf.block_owner.innerHTML = `<option value="">Choose…</option>` + Object.entries(OWNERS).map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
const syncBlock = () => { const b = cf.column.value === "blocked"; $("#blockFields").style.display = b ? "" : "none";
  cf.block_owner.required = b; cf.block_reason.required = b; };
cf.column.onchange = syncBlock;
let dlgResolve = null;

// opens the card editor; resolves with saved card or null. `force` preselects a column (used for drag-to-Blocked)
function openCard(card, col, force) {
  cf.reset();
  $("#cardTitle").textContent = card ? (force === "blocked" ? "Why is it blocked?" : "Edit card") : `New card · ${COLNAME[col]}`;
  cf.title.value = card?.title || ""; cf.body.value = card?.body || ""; cf.link.value = card?.link || "";
  cf.column.value = force || card?.col || col;
  cf.block_owner.value = card?.block_owner || ""; cf.block_reason.value = card?.block_reason || "";
  $("#cardDel").style.display = card ? "" : "none";
  const isIssue = /github\.com\/[^/]+\/[^/]+\/issues\/\d+/.test(card?.link || "");
  $("#cardIssue").style.display = card && current?.github_repo && !isIssue ? "" : "none";
  $("#cardIssue").onclick = async () => { $("#cardIssue").disabled = true;
    try { const c = await api("POST", `/cards/${card.id}/github-issue`); cf.link.value = c.link; card.link = c.link;
      $("#cardIssue").style.display = "none"; toast("GitHub issue created"); }
    catch (e) { alert(e.message); } finally { $("#cardIssue").disabled = false; } };
  $("#cardMeta").textContent = card ? `#${card.id} · created by ${card.created_by} ${ago(card.created_at)} · updated ${ago(card.updated_at)}` : "";
  syncBlock();
  $("#cardDlg").showModal();
  (force === "blocked" ? cf.block_owner : cf.title).focus();
  $("#cardDel").onclick = async () => { if (!confirm("Delete this card?")) return;
    $("#cardDlg").close("cancel"); try { await api("DELETE", "/cards/" + card.id); } catch (e) { fail(e); } route(); };
  return new Promise(res => dlgResolve = async (ok, extra = {}) => {
    if (!ok) return res(null);
    const f = Object.fromEntries(new FormData(cf));
    const body = {title: f.title, body: f.body, link: f.link.trim(), column: f.column, ...extra};
    if (f.column === "blocked") Object.assign(body, {block_owner: f.block_owner, block_reason: f.block_reason});
    try { res(card ? await api("PATCH", "/cards/" + card.id, body) : await api("POST", `/projects/${encodeURIComponent(current.slug)}/cards`, body)); }
    catch (e) { fail(e); res(null); }
  });
}
let dlgExtra = {};
$("#cardDlg").onclose = async () => { const ok = $("#cardDlg").returnValue === "ok"; const r = dlgResolve; dlgResolve = null;
  if (r) { await r(ok, dlgExtra); dlgExtra = {}; route(); } };

// ---------- drag & drop (mouse + long-press touch) ----------
function bindDrag(el) {
  const card = () => current.cards.find(c => c.id === +el.dataset.id);
  let t0 = null, sx = 0, sy = 0, timer = null;
  el.addEventListener("click", e => { if (e.target.closest("[data-nodrag]")) return; if (el.dataset.justDragged) { delete el.dataset.justDragged; return; } openCard(card()); });
  el.addEventListener("mousedown", e => {
    if (e.button !== 0 || e.target.closest("[data-nodrag]")) return;
    sx = e.clientX; sy = e.clientY;
    const mm = ev => { if (!drag && Math.hypot(ev.clientX - sx, ev.clientY - sy) > 6) startDrag(el, sx, sy); if (drag) moveDrag(ev.clientX, ev.clientY); };
    const mu = () => { document.removeEventListener("mousemove", mm); document.removeEventListener("mouseup", mu); if (drag) endDrag(); };
    document.addEventListener("mousemove", mm); document.addEventListener("mouseup", mu);
  });
  el.addEventListener("touchstart", e => {
    if (e.touches.length !== 1 || e.target.closest("[data-nodrag]")) return;
    const t = e.touches[0]; sx = t.clientX; sy = t.clientY;
    timer = setTimeout(() => { timer = null; navigator.vibrate?.(12); startDrag(el, sx, sy); }, 300);
  }, {passive: true});
  el.addEventListener("touchmove", e => {
    const t = e.touches[0];
    if (timer && Math.hypot(t.clientX - sx, t.clientY - sy) > 8) { clearTimeout(timer); timer = null; }
    if (drag) { e.preventDefault(); moveDrag(t.clientX, t.clientY); }
  }, {passive: false});
  const tend = e => { if (timer) { clearTimeout(timer); timer = null; } if (drag) { e.preventDefault(); endDrag(); } };
  el.addEventListener("touchend", tend); el.addEventListener("touchcancel", tend);
  el.addEventListener("contextmenu", e => { if (drag || timer) e.preventDefault(); });
}

function startDrag(el, x, y) {
  const r = el.getBoundingClientRect();
  const ghost = el.cloneNode(true); ghost.classList.add("ghost"); ghost.style.width = r.width + "px";
  const ph = document.createElement("div"); ph.className = "ph"; ph.style.height = r.height + "px";
  el.after(ph); el.style.display = "none"; document.body.append(ghost); document.body.classList.add("dragging");
  drag = {el, ghost, ph, id: +el.dataset.id, from: el.closest(".col").dataset.col,
    fromIndex: $$(".kc", el.parentElement).indexOf(el), offX: x - r.left, offY: y - r.top, x, y, raf: 0};
  moveDrag(x, y); autoScroll();
}
function moveDrag(x, y) {
  drag.x = x; drag.y = y;
  drag.ghost.style.transform = `translate(${x - drag.offX}px,${y - drag.offY}px) rotate(2deg)`;
  const col = document.elementFromPoint(x, y)?.closest(".col");
  $$(".col.over").forEach(c => c !== col && c.classList.remove("over"));
  if (!col) return;
  col.classList.add("over");
  const list = $(".list", col);
  const before = $$(".kc", list).filter(k => k !== drag.el).find(k => { const r = k.getBoundingClientRect(); return y < r.top + r.height / 2; });
  before ? list.insertBefore(drag.ph, before) : list.append(drag.ph);
}
function autoScroll() {  // scroll board/page while dragging near edges (phones)
  if (!drag) return;
  const b = $(".board"), e = 48, w = innerWidth, h = innerHeight;
  if (drag.x < e) b.scrollLeft -= 12; else if (drag.x > w - e) b.scrollLeft += 12;
  if (drag.y < e + 90) scrollBy(0, -10); else if (drag.y > h - e) scrollBy(0, 10);
  drag.raf = requestAnimationFrame(() => { if (drag) { moveDrag(drag.x, drag.y); autoScroll(); } });
}
async function endDrag() {
  const d = drag; drag = null; cancelAnimationFrame(d.raf);
  d.ghost.remove(); document.body.classList.remove("dragging"); $$(".col.over").forEach(c => c.classList.remove("over"));
  d.el.dataset.justDragged = 1; setTimeout(() => delete d.el.dataset.justDragged, 400);
  const to = d.ph.closest(".col").dataset.col;
  const index = $$(".kc, .ph", d.ph.parentElement).filter(k => k !== d.el).indexOf(d.ph);
  d.ph.replaceWith(d.el); d.el.style.display = "";
  if (to === d.from && index === d.fromIndex) return;
  const card = current.cards.find(c => c.id === d.id);
  if (to === "blocked" && d.from !== "blocked") { dlgExtra = {index}; return openCard(card, null, "blocked"); }
  try { await api("PATCH", "/cards/" + d.id, {column: to, index}); } catch (e) { fail(e); }
  route();
}


$("#newDlg").onclose = async () => {
  if ($("#newDlg").returnValue !== "ok") return;
  const f = Object.fromEntries(new FormData($("#newForm")));
  try { await api("POST", "/projects", f); $("#newForm").reset(); location.hash = "#/p/" + f.slug; } catch (e) { fail(e); }
};
$("#newForm").name.oninput = e => { const s = $("#newForm").slug; if (!s.dataset.touched) s.value = e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, ""); };
$("#newForm").slug.oninput = e => e.target.dataset.touched = 1;
