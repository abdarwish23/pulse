const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const STATUS = ["idea", "active", "blocked", "paused", "done"];
const COLORS = {idea: "var(--idea)", active: "var(--active)", blocked: "var(--blocked)", paused: "var(--paused)", done: "var(--done)"};
const COLS = [["ideas", "Ideas", "General feature ideas"], ["todo", "To do", "Features / issues to implement"],
  ["doing", "In progress", "Ongoing development"], ["done", "Done", "Developed and closed"], ["blocked", "Blocked", "With reason and owner"]];
const COLNAME = Object.fromEntries(COLS.map(([k, l]) => [k, l]));
const OWNERS = {me: "Action on me", agent: "Action on agent", financial: "Financial / budget", external: "External / third party", other: "Other"};
const STALE_DAYS = 7;
let projects = [], current = null, drag = null;

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const safeUrl = u => /^https?:\/\//i.test(u || "") ? u : "";
const notificationUrl = value => {
  if (typeof value !== "string" || /[\x00-\x20\x7f\\]/.test(value)) return "#/inbox";
  if (value.startsWith("#/")) return value;
  try { const u = new URL(value); if (["http:", "https:"].includes(u.protocol) && u.host) return value; } catch (_) {}
  return "#/inbox";
};
function ago(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  for (const [u, n] of [["d", 86400], ["h", 3600], ["m", 60]]) if (s >= n) return Math.floor(s / n) + u + " ago";
}
const when = ts => new Date(ts * 1000).toLocaleString([], {dateStyle: "medium", timeStyle: "short"});
const isStale = p => p.status === "active" && Date.now() / 1000 - p.updated_at > STALE_DAYS * 86400;
const linkify = t => esc(t).replace(/https?:\/\/[^\s<]+/g, u => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
const linkLabel = u => { const m = u.match(/github\.com\/[^/]+\/([^/]+)\/(issues|pull)\/(\d+)/); return m ? (m[2] === "pull" ? "PR #" : "#") + m[3] : "link"; };

async function api(method, path, body) {
  const r = await fetch("/api" + path, {method, headers: {"Content-Type": "application/json"},
    body: body ? JSON.stringify(body) : undefined, credentials: "same-origin"});
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && !path.startsWith("/login")) { await showLogin(); throw new Error("Please sign in"); }
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

// ---------- sign in ----------
let loginShown = false;
async function showLogin() {
  if (loginShown) return;
  loginShown = true;
  const opts = await fetch("/api/auth").then(r => r.json()).catch(() => ({}));
  $("#nav").innerHTML = $("#bnav").innerHTML = "";
  $("#app").innerHTML = `<form class="panel login" id="login">
    <div class="logo" style="justify-content:center;font-size:24px"><i></i>Pulse</div>
    ${opts.password ? `<input type="password" name="password" placeholder="Password" autocomplete="current-password" required autofocus>
      <button class="pri">Sign in</button>` : ""}
    ${opts.cloudflare ? `<a class="btn" href="/">Sign in with Cloudflare Access</a>` : ""}
    ${!opts.password && !opts.cloudflare ? `<p class="mut sm">No sign-in method is configured. On the server run:<br><code>python3 server.py set-password</code></p>` : ""}
    <p class="err" id="lerr" style="display:none"></p></form>`;
  const f = $("#login");
  f.onsubmit = async e => { e.preventDefault();
    const r = await fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({password: f.password.value})});
    if (r.ok) { loginShown = false; route(); }
    else { const d = await r.json().catch(() => ({})); $("#lerr").textContent = d.error || "Sign in failed"; $("#lerr").style.display = ""; } };
}
async function signOut() { await fetch("/api/logout", {method: "POST"}); location.hash = "#/"; showLogin(); }
function toast(msg) { const t = document.createElement("div"); t.className = "toast"; t.textContent = msg;
  document.body.append(t); setTimeout(() => t.remove(), 4000); }
function fail(e) { $(".err")?.remove(); $("#app").insertAdjacentHTML("afterbegin", `<div class="err">${esc(e.message)}</div>`); }
const progBar = p => `<div class="prog"><div style="width:${p.progress}%;background:${COLORS[p.status]}"></div></div><span class="pct">${p.progress}%</span>`;
const order = {blocked: 0, active: 1, paused: 2, idea: 3, done: 4};


// ---------- shared UI helpers ----------
const ICONS = {
  network: '<path d="M9 3h6v6H9zM2 15h6v6H2zM16 15h6v6h-6zM12 9v3M5 15v-3h14v3"/>',
  today: '<path d="M4 6h16M4 6v13a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V6M4 6V5a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v1M8 2v4M16 2v4M8 12h3v3H8z"/>',
  projects: '<path d="M3 4h5v16H3zM10 4h5v10h-5zM17 4h4v7h-4z"/>',
  notes: '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7"/>',
  todos: '<path d="M4 6l2 2 3-3M4 13l2 2 3-3M12 7h8M12 14h8M12 20h8M4 20h3"/>',
  reminders: '<path d="M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM12 9v4l2.5 2.5M5 3 2 6M19 3l3 3"/>',
  memory: '<path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a3 3 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
  lock: '<path d="M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4"/>',
  pin: '<path d="M9 4h6l-1 6 4 3v2H6v-2l4-3zM12 15v6"/>',
  wait: '<path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2"/>',
};
const icon = (n, cls = "ic") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[n]}</svg>`;
const SECTIONS = [["today", "Today", "#/"], ["projects", "Projects", "#/projects"], ["notes", "Notes", "#/notes"],
  ["todos", "Todos", "#/todos"], ["reminders", "Reminders", "#/reminders"], ["memory", "Memory", "#/memory"], ["network", "Agents", "#/agents"]];
const PRIO = {1: "high", 2: "normal", 3: "low"};
const lockMark = x => x.private ? `<span class="lock" title="Private: hidden from agents">${icon("lock", "ic xs")}</span>` : "";

function fmtWhen(ts) {  // "in 2h · Thu 29 Oct 09:00"
  const d = ts - Date.now() / 1000, a = Math.abs(d);
  const rel = a < 60 ? "now" : a < 3600 ? Math.round(a / 60) + "m" : a < 86400 ? Math.round(a / 3600) + "h" : Math.round(a / 86400) + "d";
  return rel === "now" ? "now" : d > 0 ? "in " + rel : rel + " ago";
}
function dueLabel(t) {
  if (!t.due_date) return "";
  const today = new Date().toLocaleDateString("en-CA"), tmr = new Date(Date.now() + 864e5).toLocaleDateString("en-CA");
  const day = t.due_date === today ? "Today" : t.due_date === tmr ? "Tomorrow" :
    new Date(t.due_date + "T12:00").toLocaleDateString([], {weekday: "short", day: "numeric", month: "short"});
  const cls = t.status !== "done" && t.due_date < today ? "late" : t.due_date === today ? "now" : "";
  return `<span class="due ${cls}">${t.due_date < today && t.status !== "done" ? "Overdue · " : ""}${day}${t.due_time ? " " + t.due_time : ""}</span>`;
}

// Small, safe Markdown renderer (input is escaped first).
function md(src) {
  const blocks = [];
  let s = esc(src || "").replace(/```([\s\S]*?)```/g, (_, c) => (blocks.push(`<pre><code>${c.replace(/^\n/, "")}</code></pre>`), `\u0000${blocks.length - 1}\u0000`));
  const inline = t => t.replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  const out = []; let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const line of s.split("\n")) {
    let m;
    if ((m = line.match(/^\u0000(\d+)\u0000$/))) { close(); out.push(blocks[+m[1]]); }
    else if ((m = line.match(/^(#{1,4})\s+(.*)/))) { close(); out.push(`<h${m[1].length + 1} dir="auto">${inline(m[2])}</h${m[1].length + 1}>`); }
    else if ((m = line.match(/^\s*[-*]\s+\[( |x)\]\s+(.*)/i))) { if (list !== "ul") { close(); out.push('<ul class="chk">'); list = "ul"; }
      out.push(`<li dir="auto">${m[1].trim() ? "☑" : "☐"} ${inline(m[2])}</li>`); }
    else if ((m = line.match(/^\s*[-*]\s+(.*)/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li dir="auto">${inline(m[1])}</li>`); }
    else if ((m = line.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li dir="auto">${inline(m[1])}</li>`); }
    else if ((m = line.match(/^&gt;\s?(.*)/))) { close(); out.push(`<blockquote dir="auto">${inline(m[1])}</blockquote>`); }
    else if (!line.trim()) { close(); }
    else { close(); out.push(`<p dir="auto">${inline(line)}</p>`); }
  }
  close();
  return out.join("");
}

// ---------- navigation + router ----------
function renderNav(active) {
  const links = SECTIONS.map(([k, l, h]) => `<a class="nav-i ${active === k ? "on" : ""}" href="${h}">${icon(k)}<span>${l}</span></a>`).join("");
  $("#nav").innerHTML = links; $("#bnav").innerHTML = links;
  $("#tabs").style.display = active === "projects" ? "" : "none";
}
async function refreshBell() {
  try { const n = (await api("GET", "/notifications?unread=1&limit=99")).length;
    $("#bellN").textContent = n || ""; $("#bellN").style.display = n ? "" : "none"; } catch {}
}

async function route() {
  if (typeof drag !== "undefined" && drag) return;
  const h = location.hash || "#/";
  let m;
  try {
    if ((m = h.match(/^#\/p\/([^/]+)(\/activity)?$/))) {
      renderNav("projects");
      projects = await api("GET", "/projects");
      current = await api("GET", "/projects/" + encodeURIComponent(decodeURIComponent(m[1])));
      renderTabs(current.slug);
      m[2] ? renderActivity(current) : renderBoard(current);
    } else if (h.startsWith("#/projects")) {
      renderNav("projects"); projects = await api("GET", "/projects"); current = null; renderTabs(null); renderOverview();
    } else if ((m = h.match(/^#\/notes(?:\/(\w+))?/))) { renderNav("notes"); await renderNotes(m[1]); }
    else if ((m = h.match(/^#\/todos(?:\/(\d+))?/))) { renderNav("todos"); await renderTodos(m[1]); }
    else if (h.startsWith("#/reminders")) { renderNav("reminders"); await renderReminders(); }
    else if (h.startsWith("#/memory")) { renderNav("memory"); await renderMemory(); }
    else if (h.startsWith("#/agents")) { renderNav("network"); await renderNetwork(); }
    else if (h.startsWith("#/inbox")) { renderNav(""); await renderInbox(); }
    else { renderNav("today"); await renderToday(); }
  } catch (e) { if (!loginShown) { $("#app").innerHTML = ""; fail(e); } return; }
  refreshBell();
}
const idle = () => !(typeof drag !== "undefined" && drag) && !$("dialog[open]") &&
  !$("#app textarea:focus, #app input:focus, #app select:focus") && !$(".editing");
addEventListener("hashchange", () => { route(); scrollTo(0, 0); });
document.addEventListener("visibilitychange", () => { if (!document.hidden && idle()) route(); });
setInterval(() => { if (!document.hidden && idle()) route(); }, 30000);
document.addEventListener("DOMContentLoaded", () => {
  api("GET", "/me").then(m => { $("#me").textContent = m.name; $("#me").title = "Sign out"; $("#me").onclick = () => confirm("Sign out?") && signOut(); }).catch(() => {});
  route();
});
