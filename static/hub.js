// Personal hub: Today, Notes, Todos, Reminders, Inbox (notifications), Memory.
const enc = encodeURIComponent;
const run = async (fn, after = route) => { try { await fn(); await after(); } catch (e) { fail(e); } };
const projOptions = (sel, blank = "No project") => `<option value="">${blank}</option>` +
  projects.map(p => `<option value="${esc(p.slug)}" ${p.slug === sel ? "selected" : ""}>${esc(p.name)}</option>`).join("");
const ensureProjects = async () => { if (!projects.length) projects = await api("GET", "/projects"); };
const projName = slug => projects.find(p => p.slug === slug)?.name || slug;

// ---------- Today ----------
async function renderToday() {
  await ensureProjects();
  const t = await api("GET", "/today");
  const hr = new Date().getHours();
  const hello = hr < 5 ? "Good night" : hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  const date = new Date().toLocaleDateString([], {weekday: "long", day: "numeric", month: "long"});
  $("#app").innerHTML = `
    <div class="pagehead"><div><h1>${hello}</h1><div class="mut">${date}</div></div></div>
    <form class="capture panel" id="cap">
      <div class="seg" id="capKind"><a data-k="todo" class="on">Todo</a><a data-k="note">Note</a><a data-k="reminder">Reminder</a></div>
      <input name="text" placeholder="Add a todo…" autocomplete="off" required dir="auto">
      <input name="when" type="datetime-local" class="capWhen" style="display:none">
      <select name="due" class="capDue"><option value="">No date</option><option value="today">Today</option><option value="tomorrow">Tomorrow</option></select>
      <button class="pri">Add</button>
    </form>
    <div class="dash">
      <section class="panel"><h3>${icon("todos", "ic sm")} Due today &amp; overdue <span class="n">${t.todos_due.length}</span></h3>
        ${t.todos_due.map(todoRow).join("") || `<p class="mut sm">Nothing due. ${t.open_todos} open todo${t.open_todos === 1 ? "" : "s"} in total.</p>`}
        <a class="more" href="#/todos">All todos →</a></section>
      <section class="panel"><h3>${icon("reminders", "ic sm")} Next reminders <span class="n">${t.reminders_next_48h.length}</span></h3>
        ${t.reminders_next_48h.map(r => `<div class="li"><span class="when">${esc(fmtWhen(r.at))}</span><span dir="auto">${esc(r.text)}</span>${r.repeat ? `<span class="chip">${r.repeat}</span>` : ""}</div>`).join("")
          || `<p class="mut sm">No reminders in the next 48 hours.</p>`}
        <a class="more" href="#/reminders">All reminders →</a></section>
      <section class="panel"><h3>${icon("wait", "ic sm")} Waiting on you <span class="n">${t.waiting_on_me.length}</span></h3>
        ${t.waiting_on_me.map(c => `<a class="li" href="#/p/${esc(c.project)}"><b>${esc(c.project_name)}</b><span dir="auto">${esc(c.title)}</span>
          <span class="mut sm">${esc(OWNERS[c.block_owner])}: ${esc(c.block_reason)}</span></a>`).join("") || `<p class="mut sm">Nothing is blocked on you.</p>`}</section>
      <section class="panel"><h3>${icon("projects", "ic sm")} Active projects</h3>
        ${t.active_projects.map(p => `<a class="li proj" href="#/p/${esc(p.slug)}"><b>${esc(p.name)}</b>
          <div class="row">${progBar(p)}</div>${p.next_step ? `<span class="mut sm">Next: ${esc(p.next_step)}</span>` : ""}</a>`).join("")}</section>
      <section class="panel"><h3>${icon("notes", "ic sm")} Recent notes</h3>
        ${t.recent_notes.map(n => `<a class="li" href="#/notes/${n.id}"><b dir="auto">${n.pinned ? icon("pin", "ic xs") + " " : ""}${esc(n.title || "Untitled")}</b>${lockMark(n)}
          <span class="mut sm" dir="auto">${esc(n.snippet)}</span></a>`).join("") || `<p class="mut sm">No notes yet.</p>`}
        <a class="more" href="#/notes">All notes →</a></section>
    </div>`;
  let kind = "todo";
  const f = $("#cap");
  $$("#capKind a").forEach(a => a.onclick = () => {
    kind = a.dataset.k; $$("#capKind a").forEach(x => x.classList.toggle("on", x === a));
    f.text.placeholder = {todo: "Add a todo…", note: "Write a quick note…", reminder: "Remind me to…"}[kind];
    f.when.style.display = kind === "reminder" ? "" : "none"; f.when.required = kind === "reminder";
    f.due.style.display = kind === "todo" ? "" : "none";
  });
  f.onsubmit = e => { e.preventDefault(); const text = f.text.value.trim();
    const req = kind === "todo" ? api("POST", "/todos", {title: text, ...(f.due.value && {due: f.due.value})})
      : kind === "note" ? api("POST", "/notes", {body: text, title: text.split("\n")[0].slice(0, 80)})
      : api("POST", "/reminders", {text, at: f.when.value.replace("T", " ")});
    run(async () => { await req; toast({todo: "Todo added", note: "Note saved", reminder: "Reminder set"}[kind]); }); };
  bindTodoRows();
}

// ---------- Todos ----------
const todoRow = t => `<div class="todo ${t.status === "done" ? "done" : ""} p${t.priority}" data-id="${t.id}">
  <input type="checkbox" ${t.status === "done" ? "checked" : ""} title="Done">
  <div class="tb"><div class="tt" dir="auto">${esc(t.title)}${lockMark(t)}</div>
    <div class="tm">${dueLabel(t)}${t.priority === 1 ? '<span class="chip hi">high</span>' : ""}
      ${t.project ? `<span class="chip">${esc(projName(t.project))}</span>` : ""}
      ${t.reminders?.length ? `<span class="chip">⏰ ${esc(t.reminders[0].at_local)}</span>` : ""}
      ${t.card_id ? '<span class="chip">→ card</span>' : ""}${t.notes ? '<span class="mut">📝</span>' : ""}</div></div></div>`;

function bindTodoRows() {
  $$(".todo").forEach(el => {
    const id = el.dataset.id;
    $("input", el).onclick = e => { e.stopPropagation();
      run(() => api("PATCH", `/todos/${id}`, {status: e.target.checked ? "done" : "open"})); };
    el.onclick = () => openTodo(+id);
  });
}

async function renderTodos(openId) {
  await ensureProjects();
  const [open, done] = await Promise.all([api("GET", "/todos?view=open"), api("GET", "/todos?view=done&limit=30")]);
  const td = new Date().toLocaleDateString("en-CA");
  const groups = [["Overdue", open.filter(t => t.due_date && t.due_date < td)], ["Today", open.filter(t => t.due_date === td)],
    ["Upcoming", open.filter(t => t.due_date > td)], ["No date", open.filter(t => !t.due_date)]];
  $("#app").innerHTML = `
    <div class="pagehead"><h1>Todos</h1><span class="mut">${open.length} open</span></div>
    <form class="panel quick" id="qa">
      <input name="title" placeholder="Add a todo…" required dir="auto" autocomplete="off">
      <input name="due_date" type="date" title="Due date">
      <select name="priority"><option value="2">Normal</option><option value="1">High</option><option value="3">Low</option></select>
      <select name="project">${projOptions("")}</select>
      <button class="pri">Add</button>
    </form>
    ${groups.filter(([, l]) => l.length).map(([g, l]) => `<section class="panel"><h3>${g} <span class="n">${l.length}</span></h3>${l.map(todoRow).join("")}</section>`).join("")
      || `<div class="empty">No open todos 🎉</div>`}
    <details class="panel"><summary><h3 style="display:inline">Done <span class="n">${done.length}</span></h3></summary>${done.map(todoRow).join("")}</details>`;
  $("#qa").onsubmit = e => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    const body = {title: f.title, priority: +f.priority}; if (f.due_date) body.due_date = f.due_date; if (f.project) body.project = f.project;
    run(() => api("POST", "/todos", body)); };
  bindTodoRows();
  if (openId) openTodo(+openId);
}

async function openTodo(id) {
  await ensureProjects();
  const t = await api("GET", `/todos/${id}`);
  const d = $("#todoDlg"), f = $("#todoForm");
  f.reset();
  f.title.value = t.title; f.notes.value = t.notes; f.due_date.value = t.due_date || ""; f.due_time.value = t.due_time || "";
  f.priority.value = t.priority; f.project.innerHTML = projOptions(t.project); f.private.checked = !!t.private;
  $("#todoRems").innerHTML = t.reminders.map(r => `<span class="chip">⏰ ${esc(r.at_local)}</span>`).join(" ");
  $("#todoMeta").textContent = `#${t.id} · added by ${t.created_by} ${ago(t.created_at)}${t.card_id ? ` · promoted to card #${t.card_id}` : ""}`;
  $("#todoPromote").style.display = t.status === "open" ? "" : "none";
  $("#todoPromote").onclick = async () => {
    const proj = f.project.value || prompt("Promote to which project? (id, e.g. website)");
    if (!proj) return;
    try { const r = await api("POST", `/todos/${id}/promote`, {project: proj}); d.close("cancel");
      toast(`Card created on ${projName(proj)}`); location.hash = `#/p/${r.card.project}`; } catch (e) { alert(e.message); } };
  $("#todoDel").onclick = async () => { if (!confirm("Delete this todo?")) return; d.close("cancel"); run(() => api("DELETE", `/todos/${id}`)); };
  d.onclose = () => {
    if (location.hash.match(/^#\/todos\/\d+/)) history.replaceState(null, "", "#/todos");
    if (d.returnValue !== "ok") return;
    const v = Object.fromEntries(new FormData(f));
    const body = {title: v.title, notes: v.notes, due_date: v.due_date || null, due_time: v.due_date && v.due_time ? v.due_time : null,
      priority: +v.priority, project: v.project || null, private: f.private.checked};
    if (v.remind_at) body.remind_at = v.remind_at.replace("T", " ");
    run(() => api("PATCH", `/todos/${id}`, body));
  };
  d.showModal();
}

// ---------- Notes ----------
let noteState = {q: "", tag: "", editing: false};
async function renderNotes(id) {
  await ensureProjects();
  const qs = new URLSearchParams(); if (noteState.q) qs.set("q", noteState.q); if (noteState.tag) qs.set("tag", noteState.tag);
  const [list, tags] = await Promise.all([api("GET", "/notes?" + qs), api("GET", "/notes/tags")]);
  const note = id === "new" ? {id: null, title: "", body: "", tags: [], project: null, pinned: 0, private: 0}
    : id ? await api("GET", `/notes/${id}`) : null;
  $("#app").innerHTML = `
    <div class="notes ${note ? "has-note" : ""}">
      <aside class="nlist">
        <div class="pagehead"><h1>Notes</h1><span class="sp"></span><a class="btn pri" href="#/notes/new">+ Note</a></div>
        <input id="nq" type="search" placeholder="Search notes…" value="${esc(noteState.q)}" dir="auto">
        <div class="tagbar">${Object.entries(tags).map(([t, n]) => `<button class="tag ${noteState.tag === t ? "on" : ""}" data-tag="${esc(t)}">#${esc(t)} <span>${n}</span></button>`).join("")}</div>
        ${list.map(n => `<a class="nitem ${note && note.id === n.id ? "on" : ""}" href="#/notes/${n.id}">
          <b dir="auto">${n.pinned ? icon("pin", "ic xs") + " " : ""}${esc(n.title || "Untitled")}</b>${lockMark(n)}
          <span class="mut sm" dir="auto">${esc(n.snippet)}</span>
          <span class="meta">${ago(n.updated_at)}${n.project ? " · " + esc(projName(n.project)) : ""}${n.tags.length ? " · #" + n.tags.map(esc).join(" #") : ""}</span></a>`).join("")
          || `<p class="mut sm">${noteState.q || noteState.tag ? "No matching notes." : "No notes yet."}</p>`}
      </aside>
      <article class="nview">${note ? (note.id === null || noteState.editing ? noteEditor(note) : noteViewer(note))
        : `<div class="empty">Select a note, or create a new one.</div>`}</article>
    </div>`;
  let timer;
  $("#nq").oninput = e => { clearTimeout(timer); timer = setTimeout(() => { noteState.q = e.target.value; renderNotes(id).then(() => { const q = $("#nq"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }); }, 250); };
  $$("[data-tag]").forEach(b => b.onclick = () => { noteState.tag = noteState.tag === b.dataset.tag ? "" : b.dataset.tag; renderNotes(id); });
  if (!note) return;
  if ($("#nEdit")) $("#nEdit").onclick = () => { noteState.editing = true; renderNotes(id); };
  if ($("#nPin")) $("#nPin").onclick = () => run(() => api("PATCH", `/notes/${note.id}`, {pinned: !note.pinned}), () => renderNotes(id));
  if ($("#nDel")) $("#nDel").onclick = () => { if (confirm("Delete this note?")) run(() => api("DELETE", `/notes/${note.id}`), () => { location.hash = "#/notes"; }); };
  const form = $("#nForm");
  if (form) {
    form.onsubmit = async e => { e.preventDefault(); const v = Object.fromEntries(new FormData(form));
      const body = {title: v.title, body: v.body, tags: v.tags, project: v.project || null, private: form.private.checked, pinned: form.pinned.checked};
      try { const n = note.id ? await api("PATCH", `/notes/${note.id}`, body) : await api("POST", "/notes", body);
        noteState.editing = false; toast("Saved"); location.hash === `#/notes/${n.id}` ? renderNotes(n.id) : location.hash = `#/notes/${n.id}`; }
      catch (err) { fail(err); } };
    $("#nCancel").onclick = () => { noteState.editing = false; note.id ? renderNotes(note.id) : location.hash = "#/notes"; };
    form.body.focus();
  }
}
const noteViewer = n => `
  <div class="row nbar"><a class="btn back" href="#/notes">←</a><span class="sp"></span>
    <button id="nPin" title="Pin">${n.pinned ? "Unpin" : icon("pin", "ic xs") + " Pin"}</button><button id="nEdit" class="pri">Edit</button></div>
  <h1 class="ntitle" dir="auto">${esc(n.title || "Untitled")} ${lockMark(n)}</h1>
  <div class="meta">${n.project ? `<a class="chip" href="#/p/${esc(n.project)}">${esc(projName(n.project))}</a> ` : ""}${n.tags.map(t => `<span class="chip">#${esc(t)}</span>`).join(" ")}
    · updated ${ago(n.updated_at)} · by ${esc(n.created_by)}</div>
  <div class="md">${md(n.body)}</div>
  <div class="row" style="margin-top:20px"><button id="nDel" class="danger">Delete note</button></div>`;
const noteEditor = n => `
  <form id="nForm" class="form editing">
    <div class="row nbar"><button type="button" id="nCancel">Cancel</button><span class="sp"></span><button class="pri">Save</button></div>
    <input name="title" placeholder="Title" value="${esc(n.title)}" class="big" dir="auto">
    <textarea name="body" class="nbody" placeholder="Write in Markdown: # heading, **bold**, - lists, - [ ] checklist, [link](https://…)" dir="auto">${esc(n.body)}</textarea>
    <div class="two"><input name="tags" placeholder="tags, comma separated" value="${esc(n.tags.join(", "))}">
      <select name="project">${projOptions(n.project)}</select></div>
    <div class="row"><label class="ck"><input type="checkbox" name="pinned" ${n.pinned ? "checked" : ""}> Pinned</label>
      <label class="ck"><input type="checkbox" name="private" ${n.private ? "checked" : ""}> ${icon("lock", "ic xs")} Private (hidden from agents)</label></div>
  </form>`;

// ---------- Reminders ----------
async function renderReminders() {
  const [pending, history] = await Promise.all([api("GET", "/reminders?status=pending"), api("GET", "/reminders?status=all")]);
  const past = history.filter(r => r.status !== "pending").slice(0, 30);
  const in1h = new Date(Date.now() + 36e5), pad = n => String(n).padStart(2, "0");
  const dl = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  $("#app").innerHTML = `
    <div class="pagehead"><h1>Reminders</h1><span class="mut">Sent to Telegram and the 🔔 inbox</span></div>
    <form class="panel quick" id="ra">
      <input name="text" placeholder="Remind me to…" required dir="auto" autocomplete="off">
      <input name="at" type="datetime-local" value="${dl(in1h)}" required>
      <select name="repeat"><option value="">Once</option><option value="daily">Daily</option><option value="weekdays">Weekdays</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>
      <button class="pri">Set</button>
      <div class="presets"><span class="mut sm">Quick:</span><button type="button" data-in="10">10 min</button><button type="button" data-in="60">1 hour</button>
        <button type="button" data-at="tomorrow 09:00">Tomorrow 9:00</button></div>
    </form>
    <section class="panel"><h3>Upcoming <span class="n">${pending.length}</span></h3>
      ${pending.map(r => `<div class="rem" data-id="${r.id}"><div class="rw"><span class="when">${esc(fmtWhen(r.at))}</span><span class="mut sm">${esc(r.at_local)}</span></div>
        <div class="rt" dir="auto">${esc(r.text)} ${lockMark(r)}${r.repeat ? `<span class="chip">↻ ${r.repeat}</span>` : ""}${r.todo_id ? `<a class="chip" href="#/todos/${r.todo_id}">todo</a>` : ""}</div>
        <div class="ra"><button data-snz="10">+10m</button><button data-snz="60">+1h</button><button data-snz="tomorrow">Tomorrow</button>
          <button data-edit>Edit</button><button data-cancel class="danger">Cancel</button></div></div>`).join("") || `<p class="mut sm">No upcoming reminders.</p>`}
    </section>
    <details class="panel"><summary><h3 style="display:inline">History</h3></summary>
      ${past.map(r => `<div class="li"><span class="chip">${r.status}</span><span dir="auto">${esc(r.text)}</span><span class="mut sm">${r.last_fired_at ? when(r.last_fired_at) : ""}</span></div>`).join("") || `<p class="mut sm">Nothing yet.</p>`}
    </details>`;
  const f = $("#ra");
  f.onsubmit = e => { e.preventDefault(); run(() => api("POST", "/reminders", {text: f.text.value, at: f.at.value.replace("T", " "), repeat: f.repeat.value})); };
  $$("[data-in]").forEach(b => b.onclick = () => f.text.reportValidity() && run(() => api("POST", "/reminders", {text: f.text.value, in_minutes: +b.dataset.in})));
  $$("[data-at]").forEach(b => b.onclick = () => f.text.reportValidity() && run(() => api("POST", "/reminders", {text: f.text.value, at: b.dataset.at, repeat: f.repeat.value})));
  $$(".rem").forEach(el => {
    const id = el.dataset.id, r = pending.find(x => x.id == id);
    $$("[data-snz]", el).forEach(b => b.onclick = () => run(() => api("PATCH", `/reminders/${id}`,
      b.dataset.snz === "tomorrow" ? {at: "tomorrow 09:00"} : {snooze_minutes: +b.dataset.snz})));
    $("[data-cancel]", el).onclick = () => confirm("Cancel this reminder?") && run(() => api("PATCH", `/reminders/${id}`, {status: "cancelled"}));
    $("[data-edit]", el).onclick = () => {
      const text = prompt("Reminder text", r.text); if (text === null) return;
      const at = prompt("When? (YYYY-MM-DD HH:MM, HH:MM, tomorrow 09:00, in 30m)", r.at_local.replace(/^\w+ /, "")); if (at === null) return;
      run(() => api("PATCH", `/reminders/${id}`, {text, ...(at.trim() && at !== r.at_local.replace(/^\w+ /, "") ? {at} : {})}));
    };
  });
}

// ---------- Inbox (notifications) ----------
const KIND_ICON = {reminder: "⏰", card_done: "✅", card_blocked: "⛔", agent: "🤖", github: "🐙"};
async function renderInbox() {
  const list = await api("GET", "/notifications?limit=150");
  $("#app").innerHTML = `
    <div class="pagehead"><h1>Inbox</h1><span class="sp"></span><button id="readAll">Mark all read</button></div>
    <section class="panel">${list.map(n => `<a class="li notif ${n.read ? "" : "unread"}" data-id="${n.id}" href="${esc(notificationUrl(n.link))}">
      <span class="ki">${KIND_ICON[n.kind] || "🔔"}</span><div><b dir="auto">${esc(n.title)}</b>${n.body ? `<div class="mut sm" dir="auto">${esc(n.body)}</div>` : ""}
      <div class="meta">${when(n.ts)}${n.delivered ? " · sent to Telegram" : n.delivery_status === "retrying" ? " · Telegram retry scheduled" : n.delivery_status === "pending" || n.delivery_status === "delivering" ? " · Telegram pending" : n.delivery_status === "cancelled" ? " · Telegram cancelled" : n.error ? " · Telegram failed" : ""}</div></div></a>`).join("")
      || `<p class="mut sm">No notifications yet.</p>`}</section>`;
  $("#readAll").onclick = () => run(() => api("POST", "/notifications/read", {}));
  $$(".notif").forEach(a => a.addEventListener("click", () => { if (a.classList.contains("unread")) api("POST", "/notifications/read", {ids: [+a.dataset.id]}).then(refreshBell); }));
}

// ---------- Memory ----------
let memFilter = "";
async function renderMemory() {
  const {entities} = await api("GET", "/memory");
  const q = memFilter.toLowerCase();
  const shown = entities.filter(e => !q || e.name.toLowerCase().includes(q) || e.type.toLowerCase().includes(q) || e.facts.some(f => f.text.toLowerCase().includes(q)));
  $("#app").innerHTML = `
    <div class="pagehead"><div><h1>Memory</h1><div class="mut sm">Facts you and your agents save about people, projects and preferences.</div></div></div>
    <div class="row" style="margin-bottom:12px"><input id="mq" type="search" placeholder="Search memory…" value="${esc(memFilter)}"></div>
    <form class="panel quick" id="mnew"><input name="entity" placeholder="Who / what (e.g. Alex, My App)" required><input name="type" placeholder="type (person, project…)">
      <input name="fact" placeholder="New fact" required dir="auto"><button class="pri">Remember</button></form>
    <div class="memgrid">${shown.map(e => `<section class="panel mem" data-e="${esc(e.name)}">
      <div class="row"><h3 style="margin:0;flex:1;text-transform:none;letter-spacing:0;color:var(--fg);font-size:16px">${esc(e.name)}</h3><span class="chip">${esc(e.type)}</span>
        <button class="x" data-forget title="Forget everything about ${esc(e.name)}">✕</button></div>
      <ul class="facts">${e.facts.map(f => `<li data-f="${esc(f.text)}"><span dir="auto">${esc(f.text)}</span>
        <span class="fa"><button data-ed title="Edit">✎</button><button data-del title="Forget">✕</button></span></li>`).join("")}</ul>
      <form class="row addf"><input name="fact" placeholder="Add a fact…" required dir="auto"><button>Add</button></form></section>`).join("")}</div>`;
  let timer;
  $("#mq").oninput = e => { clearTimeout(timer); timer = setTimeout(() => { memFilter = e.target.value; renderMemory().then(() => { const m = $("#mq"); m.focus(); m.setSelectionRange(m.value.length, m.value.length); }); }, 250); };
  const msg = r => toast(r.message);
  const reload = () => renderMemory();
  $("#mnew").onsubmit = e => { e.preventDefault(); const v = Object.fromEntries(new FormData(e.target));
    run(async () => msg(await api("POST", "/memory/remember", {entity: v.entity, type: v.type || "general", facts: [v.fact]})), reload); };
  $$(".mem").forEach(sec => {
    const entity = sec.dataset.e;
    $("[data-forget]", sec).onclick = () => confirm(`Forget everything about ${entity}?`) && run(async () => msg(await api("POST", "/memory/forget", {entity})), reload);
    $(".addf", sec).onsubmit = e => { e.preventDefault(); run(async () => msg(await api("POST", "/memory/remember", {entity, facts: [e.target.fact.value]})), reload); };
    $$("li", sec).forEach(li => {
      const fact = li.dataset.f;
      $("[data-del]", li).onclick = () => confirm(`Forget: "${fact}"?`) && run(async () => msg(await api("POST", "/memory/forget", {entity, fact})), reload);
      $("[data-ed]", li).onclick = () => { const nt = prompt("Edit fact", fact); if (nt && nt !== fact)
        run(async () => msg(await api("POST", "/memory/update", {entity, old_text: fact, new_text: nt})), reload); };
    });
  });
}
