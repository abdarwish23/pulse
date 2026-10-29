// Agent network: owner visibility and explicit sharing rules.
async function renderNetwork() {
  let agents, requests, grants, artifacts;
  try { [agents, requests, grants, artifacts] = await Promise.all([
    api('GET', '/network/agents'), api('GET', '/network/requests'), api('GET', '/network/grants'), api('GET', '/network/artifacts')
  ]); } catch (error) {
    if (error.message === 'agent network is disabled') {
      $('#app').innerHTML = '<div class="pagehead"><h1>Agents</h1></div><section class="panel"><h2>Agent network is not enabled</h2><p>Finish server setup to connect your agents and share files.</p></section>';
      return;
    }
    throw error;
  }
  const active = agents.filter(a => !a.revoked);
  const devices = [...new Set(agents.map(a => a.device))];
  const options = active.map(a => `<option value="${esc(a.id)}">${esc(a.label)} (${esc(a.id)})</option>`).join('');
  $('#app').innerHTML = `<div class="pagehead"><div><h1>Agents</h1><p class="mut">${devices.length} devices · ${active.length} enrolled agents</p></div>
    <button id="networkRefresh">Refresh</button></div>
    <p class="mut">Availability reflects recent sessions. Files already uploaded remain accessible while their source is offline.</p>
    <div class="network-grid">${devices.map(device => `<section class="panel"><h2>${esc(device)}</h2>${agents.filter(a => a.device === device).map(a => `
      <article class="network-agent"><div class="row"><b>${esc(a.label)}</b><span class="sp"></span><span class="chip">${esc(a.status)}</span></div>
      <p class="mut sm">${esc(a.id)}</p><p class="sm">${esc(a.capabilities.join(' · ') || 'Requesting only')}</p>
      ${a.sessions.map(s => `<div class="mut sm">${esc(s.capabilities.join(', ') || 'No serving capabilities')} · ${esc(s.state)} · ${esc(ago(s.last_seen))}</div>`).join('')}
      ${!a.revoked ? `<button class="sm danger" data-revoke="${esc(a.id)}">Revoke access</button>` : ''}</article>`).join('')}</section>`).join('') ||
      `<section class="panel"><h2>No agents enrolled</h2><p>Enroll each agent with the local <code>pulse network admin enroll</code> command. Each gets a separate credential.</p></section>`}</div>
    <section class="panel"><h2>Sharing permissions</h2><p class="mut sm">Permission flows from a source agent to a requester. File shares also require approval in the source connector's local configuration.</p>
      ${active.length ? `<form id="networkGrant" class="network-grant"><label class="f">Source<select name="source">${options}</select></label>
      <label class="f">Requester<select name="requester">${options}</select></label>
      <label class="f">Operation<select name="kind"><option value="file.list">List folder</option><option value="file.read">Read file</option><option value="message">Send message</option></select></label>
      <label class="f">Folder alias<input name="share" required pattern="[a-z0-9][a-z0-9_.-]{0,47}" placeholder="demos"></label><button class="pri">Allow</button>
      <p id="networkGrantError" role="alert" class="err" hidden></p></form>` : ''}
      ${grants.map((g,i) => `<div class="network-rule"><span>${esc(g.source)} → ${esc(g.requester)}<br><span class="mut sm">${esc(g.kind)} ${esc(g.share)}</span></span>
        <button data-ungrant="${i}">Remove permission</button></div>`).join('') || '<p class="mut sm">No sharing permissions yet.</p>'}</section>
    <section class="panel"><h2>Shared files</h2><p class="mut sm">Stored on the VPS. Available independently of the source device.</p>
      ${artifacts.map(a => `<article class="network-request"><b>${esc(a.path)}</b><p class="mut sm">${esc(a.source)} · ${esc(a.share)} · ${(a.size/1024).toFixed(1)} KB</p>
        <a class="btn" href="/api/network/artifacts/${enc(a.id)}" download="${esc(a.path.split('/').pop())}">Download</a>
        <span class="mut sm">${a.expires_at ? 'Expires ' + esc(when(a.expires_at)) : 'Kept until withdrawn'}</span></article>`).join('') || '<p class="mut">No shared files yet.</p>'}</section>
    <section class="panel"><h2>Requests and artifacts</h2><p class="mut sm">Latest 200 requests. Retention follows the server policy; each stored artifact shows its expiry.</p>
      ${requests.map(r => `<article class="network-request"><div class="row"><b>${esc(r.kind === 'message' ? 'Message' : r.payload.path || r.share)}</b><span class="sp"></span><span class="chip">${esc(r.status)}</span></div>
        <p class="mut sm">${esc(r.sender)} → ${esc(r.recipient)} · ${esc(when(r.created_at))}</p>
        ${r.error ? `<p class="err">${esc(r.error)}</p>` : ''}
        ${r.status === 'interrupted' ? '<p class="mut sm">Delivery was interrupted. Check whether the agent acted before explicitly retrying.</p>' : ''}
        <details><summary>Details</summary><pre>${esc(JSON.stringify({request:r.payload,result:r.result,attempts:r.attempts,deadline:when(r.expires_at)},null,2))}</pre></details>
        <div class="row">${r.artifact ? `<a class="btn" href="/api/network/requests/${enc(r.id)}/artifact" download="${esc(r.payload.path.split('/').pop() || 'artifact.bin')}">Download · ${(r.artifact.size/1024).toFixed(1)} KB</a><span class="mut sm">Expires ${r.artifact.expires_at ? esc(when(r.artifact.expires_at)) : 'never (until withdrawn)'}</span>` : ''}
        ${['queued','leased','interrupted'].includes(r.status) || r.artifact ? `<button data-cancel="${esc(r.id)}">${r.artifact ? 'Withdraw artifact' : 'Cancel request'}</button>` : ''}</div></article>`).join('') || '<p class="mut">No requests yet.</p>'}</section>`;
  $('#networkRefresh').onclick = () => run(renderNetwork, () => {});
  $$('[data-revoke]').forEach(b => b.onclick = () => {
    if (confirm(`Revoke ${b.dataset.revoke}? Its credential will stop working and its shared artifacts will be withdrawn.`))
      run(() => api('POST','/network/revoke',{agent:b.dataset.revoke}));
  });
  $$('[data-ungrant]').forEach(b => b.onclick = () => run(() => api('DELETE','/network/grants',grants[+b.dataset.ungrant])));
  $$('[data-cancel]').forEach(b => b.onclick = () => run(() => api('POST',`/network/requests/${enc(b.dataset.cancel)}/cancel`,{})));
  const form = $('#networkGrant');
  if (form) {
    form.kind.onchange = () => { form.share.disabled = form.kind.value === 'message'; form.share.required = !form.share.disabled; };
    form.onsubmit = async e => {
      e.preventDefault();
      const button = $('button',form); button.disabled = true;
      try { await api('POST','/network/grants',Object.fromEntries(new FormData(form))); await renderNetwork(); }
      catch (error) { const el = $('#networkGrantError'); el.textContent = error.message; el.hidden = false; button.disabled = false; }
    };
  }
}
