// Social posts: Drafts -> Approved (owner-only gate) -> Scheduled -> Posted.
// Gated by config.social_posting; the API returns 404 when disabled.
const SCOLS = [["draft", "Drafts", "Proposed by you or your agents"], ["approved", "Approved", "You approved these; agents can schedule them"],
  ["scheduled", "Scheduled", "Waiting for their post time"], ["posted", "Posted", "Published — failures appear here too"]];
const SOCIAL_STATUSES = ["draft", "approved", "scheduled", "posted", "failed", "cancelled"];

const socialRow = p => `<div class="spost" data-id="${p.id}">
  <div class="st" dir="auto">${esc(p.text).slice(0, 500)}${p.text.length > 500 ? "…" : ""}</div>
  ${(p.media || []).map((m, i) => `<img class="smedia" loading="lazy" alt="${esc(m)}" data-post="${p.id}" data-n="${i}" src="">`).join("")}
  <div class="sm">
    <span class="chip">${esc(p.platform)}</span>
    ${p.status === "scheduled" ? `<span class="due">${esc(p.due_local)}</span>` : ""}
    ${p.status === "posted" ? `<span class="chip ok">posted</span>` : ""}
    ${p.status === "failed" ? `<span class="chip late">failed</span>` : ""}
    ${p.status === "cancelled" ? `<span class="mut sm">cancelled</span>` : ""}
    ${p.status === "failed" && p.error ? `<span class="mut sm" title="${esc(p.error)}">${esc(p.error.slice(0, 80))}</span>` : ""}
    ${p.posted_id && p.status === "posted" ? `<span class="mut sm sm-id" title="${esc(p.posted_id)}">✓ ${esc(p.posted_id.slice(-14))}</span>` : ""}
    <span class="mut sm">by ${esc(p.created_by)} ${ago(p.created_at) || ""}</span>
  </div>
  <div class="sactions">
    ${p.status === "draft" && ME.role === "user" ? `<button class="mini pri" data-a="approve">Approve</button>` : ""}
    ${p.status === "approved" ? `<button class="mini pri" data-a="schedule">Schedule</button>` : ""}
    ${p.status === "scheduled" ? `<button class="mini" data-a="reschedule">Move</button>` : ""}
    ${["draft", "approved", "scheduled"].includes(p.status) && ME.role === "user" ? `<button class="mini" data-a="cancel">Cancel</button>` : ""}
    ${["draft", "approved", "scheduled", "cancelled", "failed"].includes(p.status) && ME.role === "user" ? `<button class="mini danger" data-a="delete">Delete</button>` : ""}
  </div></div>`;

function socialThumb(el) {
  api("GET", `/social/${el.dataset.post}/media/${el.dataset.n}`).then(m => {
    el.src = `data:${m.mime};base64,${m.data_b64}`;
  }).catch(() => el.remove());
}

async function renderSocial() {
  const [posts, meta] = await Promise.all([api("GET", "/social"), api("GET", "/meta")]);
  const by = Object.fromEntries(SCOLS.map(([k]) => [k, []]));
  posts.forEach(p => (by[p.status === "failed" ? "posted" : p.status] || by.draft).push(p));
  $("#app").innerHTML = `
    <div class="pagehead"><h1>Social</h1><span class="mut">Posts go live only after you approve them</span></div>
    <form class="panel quick" id="sform">
      <textarea name="text" rows="2" placeholder="Draft a post… (agents can propose drafts via the API/MCP)" dir="auto" required maxlength="3000"></textarea>
      <select name="platform"><option value="linkedin">LinkedIn</option></select>
      <input name="image" type="file" accept=".png,.jpg,.jpeg,.webp,.gif" title="Optional image">
      <button class="pri">Add draft</button>
    </form>
    <div class="sboard">
      ${SCOLS.map(([k, label, hint]) => `<section class="panel scol"><h3>${esc(label)} <span class="n">${by[k].length}</span>
        <span class="mut sm" style="font-weight:normal">${esc(hint)}</span></h3>
        ${by[k].map(socialRow).join("") || `<p class="mut sm">Empty</p>`}</section>`).join("")}
    </div>`;
  $$(".smedia").forEach(socialThumb);
  const f = $("#sform");
  f.onsubmit = async e => {
    e.preventDefault();
    const body = {text: f.text.value.trim(), platform: f.platform.value};
    const file = f.image.files[0];
    const done = m => run(async () => { await api("POST", "/social", m); f.reset(); });
    if (file) { const reader = new FileReader();
      reader.onload = () => done({text: body.text, platform: body.platform,
        media: [{filename: file.name, data_b64: reader.result.split(",")[1]}]});
      reader.readAsDataURL(file);
    } else done(body);
  };
  $$(".spost").forEach(el => {
    const id = el.dataset.id;
    el.onclick = e => {
      const a = e.target.closest("button")?.dataset.a;
      if (a === "approve") run(() => api("POST", `/social/${id}/approve`));
      else if (a === "schedule" || a === "reschedule") {
        const due = prompt("Post at? (YYYY-MM-DD HH:MM or 'tomorrow 09:00', server local time)");
        if (due) run(() => api("POST", `/social/${id}/schedule`, {due}));
      } else if (a === "cancel") run(() => api("POST", `/social/${id}/cancel`));
      else if (a === "delete") { if (confirm("Delete this post (and its images)?")) run(() => api("DELETE", `/social/${id}`)); }
    };
  });
}
