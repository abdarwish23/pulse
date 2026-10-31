// Stable identities stay in the API; names are presentation metadata only.
const networkView = {data: null, query: '', agent: '', request: '', pane: 'agents', collapsed: new Set(), scroll: {}, pageScroll: {}, generation: 0, stale: false};
const networkTypes = {pc: 'PC', vps: 'VPS', cloud: 'Cloud', other: 'Other'};
const networkIcons = {pc: 'pc-display', vps: 'hdd-network', cloud: 'cloud', other: 'hdd-network'};
const ni = name => `<img class="net-icon" src="/vendor/bootstrap-icons/${name}.svg" alt="" width="18" height="18">`;
const networkStatus = {queued: 'Queued', leased: 'Running', completed: 'Completed', failed: 'Failed', expired: 'Expired', interrupted: 'Needs attention', cancelled: 'Cancelled'};
function networkName(a) {
  if (!a) return 'Unknown agent';
  if (a.label && a.label !== a.id) return a.label;
  const name = a.id.split('/').pop();
  return ({codex:'Codex', claude:'Claude', pi:'Pi', opencode:'OpenCode'})[name] || name;
}
function networkTitle(r) {
  const text = r.kind === 'message' ? r.payload.message : `${r.kind === 'file.list' ? 'List folder' : 'Read file'}: ${r.payload.path || r.share}`;
  return String(text || 'Message').split('\n').find(s => s.trim())?.slice(0, 100) || 'Message';
}
function networkPreview(r) {
  return r.error || r.result?.message || r.payload.message || r.payload.path || r.share || '';
}
function networkPresence(a) {
  if (networkView.stale) return '<span class="net-presence unknown"><i></i>Status unavailable</span>';
  const online = ['ready','busy'].includes(a.status);
  const activity = {working: 'Working', idle: 'Idle', 'files-only': 'Files only', connected: 'Connected'}[a.activity];
  return `<span class="net-presence ${online ? 'online' : 'offline'}"><i></i>${a.revoked ? 'Revoked' : online ? 'Online' : 'Offline'}</span>${online && activity ? `<span class="mut"> · ${activity}</span>` : !a.revoked ? `<span class="mut"> · ${a.last_seen ? 'Seen '+esc(ago(a.last_seen)) : 'Not seen yet'}</span>` : ''}`;
}
function networkAvatar(a) {
  const name = a?.id.split('/').pop() || '';
  return `<span class="net-avatar ${['codex','claude','pi','opencode'].includes(name) ? name : 'other'}" aria-hidden="true">${esc(networkName(a).slice(0,1).toUpperCase())}</span>`;
}
function networkBadge(r) { return `<span class="net-badge ${esc(r.status)}">${esc(networkStatus[r.status] || r.status)}</span>`; }
function networkParticipants(r) {
  return [r.sender,r.recipient].map(id => {
    const a = networkView.data.agents.find(a => a.id === id);
    const d = networkView.data.devices.find(d => d.id === a?.device);
    return `${networkName(a)} · ${d?.label || a?.device || id}`;
  }).join(' ↔ ');
}
function networkRememberScroll() {
  const pane = $('#networkWorkspace')?.dataset.pane;
  if (pane) networkView.pageScroll[pane] = window.scrollY;
  $$('.net-scroll').forEach(el => networkView.scroll[el.id] = el.scrollTop);
}
function networkGo(pane, agent = networkView.agent, request = networkView.request) {
  networkRememberScroll();
  const q = new URLSearchParams();
  if (agent) q.set('agent', agent);
  if (request) q.set('session', request);
  if (pane !== 'agents') q.set('view', pane);
  const query = q.toString();
  location.hash = '#/agents' + (query ? '?' + query : '');
}
async function renderNetwork() {
  const generation = ++networkView.generation;
  const previousRoot = $('#networkWorkspace');
  const navigated = previousRoot && previousRoot.dataset.route !== location.hash;
  const focused = document.activeElement;
  const focusKey = focused?.closest('.net-page') ? ['id','data-agent','data-request','data-device-toggle','data-edit-device','data-pane']
    .find(key => focused.hasAttribute(key)) : null;
  const focusValue = focusKey ? focused.getAttribute(focusKey) : null;
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  networkRememberScroll();
  const previousRequest = networkView.request;
  const previousAgent = networkView.agent;
  networkView.agent = q.get('agent') || '';
  networkView.request = q.get('session') || '';
  networkView.pane = ['sessions','conversation'].includes(q.get('view')) ? q.get('view') : 'agents';
  if (previousRequest !== networkView.request) networkView.scroll.netConversation = 0;
  if (previousAgent !== networkView.agent) networkView.scroll.netSessions = 0;
  try {
    const [agents, devices, requests, grants, artifacts] = await Promise.all([
      api('GET','/network/agents'), api('GET','/network/devices'), api('GET','/network/requests'),
      api('GET','/network/grants'), api('GET','/network/artifacts')]);
    // A selected old session can be outside the newest 200 requests.
    if (networkView.request && !requests.some(r => r.id === networkView.request)) {
      try { requests.push(await api('GET','/network/requests/'+encodeURIComponent(networkView.request))); }
      catch (_) { /* Render a clear missing/retained-out session state. */ }
    }
    if (generation !== networkView.generation || !location.hash.startsWith('#/agents') || loginShown) return;
    networkView.data = {agents,devices,requests,grants,artifacts}; networkView.stale = false;
  } catch (error) {
    if (generation !== networkView.generation || !location.hash.startsWith('#/agents') || loginShown) return;
    if (error.message === 'agent network is disabled') {
      networkView.data = null;
      $('#app').innerHTML = '<div class="pagehead"><h1>Agents</h1></div><section class="panel"><h2>Agent network is not enabled</h2><p>Finish server setup to connect your agents and share files.</p></section>'; return;
    }
    if (!networkView.data) {
      $('#app').innerHTML = `<section class="panel"><h1>Agents unavailable</h1><p role="alert">${esc(error.message)}</p><button id="networkRefresh">Try again</button></section>`;
      $('#networkRefresh').onclick = renderNetwork; return;
    }
    networkView.stale = true;
  }
  const {agents, devices} = networkView.data;
  const active = agents.filter(a => !a.revoked);
  const deviceCount = devices.filter(d => active.some(a => a.device === d.id)).length;
  $('#app').innerHTML = `<div class="net-page" data-pane="${networkView.pane}">
    <div class="net-heading"><div><h1 id="networkHeading">Agents</h1><p class="mut">${deviceCount} devices · ${active.length} agents <span class="net-live">· Updates every 30s</span></p></div>
      <div class="net-actions"><button id="networkRefresh" title="Refresh agent status">Refresh</button><button id="networkSettings">Settings</button></div></div>
    ${networkView.stale ? '<p class="net-warning" role="alert">Connection lost. Status is unavailable; messages below are from the last successful refresh.</p>' : ''}
    <div class="net-toolbar"><label class="net-search">${ni('search')}<span class="sr-only">Search agents, devices or sessions</span><input id="networkSearch" type="search" placeholder="Search agents or sessions…" value="${esc(networkView.query)}"></label>
    <div class="net-mobile-tabs" aria-label="Agent views"><button data-pane="agents" class="${networkView.pane==='agents'?'on':''}">Agents</button><button data-pane="sessions" class="${networkView.pane!=='agents'?'on':''}">Sessions</button></div></div>
    <div class="net-workspace" data-pane="${networkView.pane}" data-route="${esc(location.hash)}" id="networkWorkspace"></div></div>`;
  networkPaint(false);
  if (navigated) {
    const heading = $(networkView.pane === 'conversation' ? '.net-conversation h2' : networkView.pane === 'sessions' ? '.net-sessions h2' : '.net-heading h1');
    if (heading) { heading.tabIndex = -1; heading.focus({preventScroll:true}); }
  } else if (focusKey) {
    const target = $(`[${focusKey}="${CSS.escape(focusValue)}"]`);
    target?.focus({preventScroll:true});
  }
  if (matchMedia('(max-width: 900px)').matches) scrollTo(0, networkView.pageScroll[networkView.pane] || 0);
  $('#networkRefresh').onclick = renderNetwork;
  $('#networkSettings').onclick = () => networkSettings();
  $('#networkSearch').oninput = e => { networkView.query = e.target.value; networkPaint(); };
  $$('.net-mobile-tabs [data-pane]').forEach(b => b.onclick = () => networkGo(b.dataset.pane));
}
function networkPaint(remember = true) {
  if (remember) networkRememberScroll();
  const {agents, devices, requests} = networkView.data;
  const query = networkView.query.trim().toLocaleLowerCase();
  const active = agents.filter(a => !a.revoked);
  const selectedAgent = agents.find(a => a.id === networkView.agent);
  const matching = requests.filter(r => (!networkView.agent || [r.sender,r.recipient].includes(networkView.agent)) &&
    (!query || [networkTitle(r), networkPreview(r), networkParticipants(r)].join(' ').toLocaleLowerCase().includes(query)));
  const selected = requests.find(r => r.id === networkView.request) || (!networkView.request ? matching[0] : null);
  const directory = [...devices].sort((a,b) => ['pc','vps','cloud','other'].indexOf(a.kind)-['pc','vps','cloud','other'].indexOf(b.kind) || a.label.localeCompare(b.label)).map(d => {
    const rows = active.filter(a => a.device === d.id && (!query || [networkName(a), a.id, d.label, networkTypes[d.kind]].join(' ').toLocaleLowerCase().includes(query)));
    if (!rows.length) return '';
    const collapsed = networkView.collapsed.has(d.id) && !query;
    return `<section class="net-device"><div class="net-device-head"><button class="net-device-toggle" data-device-toggle="${esc(d.id)}" aria-expanded="${!collapsed}">${ni(networkIcons[d.kind] || 'hdd-network')}<span><b>${esc(d.label)}</b><small>${esc(networkTypes[d.kind] || 'Other')} · ${rows.length} ${rows.length===1?'agent':'agents'}</small></span>${ni('chevron-down')}</button><button class="net-icon-button" data-edit-device="${esc(d.id)}" aria-label="Edit ${esc(d.label)}">${ni('pencil')}</button></div>
      ${collapsed ? '' : rows.map(a => `<button class="net-agent ${a.id===networkView.agent?'selected':''}" data-agent="${esc(a.id)}" aria-pressed="${a.id===networkView.agent}">${networkAvatar(a)}<span class="net-agent-copy"><b>${esc(networkName(a))}</b><span class="net-agent-status">${networkPresence(a)}</span></span>${ni('chevron-right')}</button>`).join('')}</section>`;
  }).join('');
  $('#networkWorkspace').innerHTML = `<section class="net-directory net-column" aria-label="Agents by device"><div class="net-column-head"><h2>Devices</h2><button id="networkAll" class="net-text-button">All agents</button></div><div class="net-scroll" id="netDirectory">${directory || `<div class="net-empty"><h3>${active.length ? 'No matching agents' : 'No agents enrolled'}</h3><p>${active.length ? 'Try another name or device.' : 'Enroll a device to see its agents here. PC, VPS and Cloud devices can each have their own name.'}</p></div>`}</div></section>
    <section class="net-sessions net-column" aria-label="Sessions"><div class="net-column-head"><div><h2 id="networkSessionHeading">Sessions <span class="mut">(${matching.length})</span></h2>${selectedAgent?`<p class="mut sm">${esc(networkName(selectedAgent))} <button id="networkAgentDetails" class="net-text-button">Details</button><button id="networkClearAgent" class="net-text-button">All agents</button></p>`:''}</div><button id="networkBackAgents" class="net-mobile-back">${ni('chevron-left')} Agents</button></div><div class="net-scroll" id="netSessions">${matching.map(r=>`<button class="net-session ${selected?.id===r.id?'selected':''}" data-request="${esc(r.id)}" aria-pressed="${selected?.id===r.id}"><span class="net-session-title"><b>${esc(networkTitle(r))}</b><time title="${esc(when(r.updated_at || r.created_at))}">${esc(ago(r.updated_at || r.created_at))}</time></span><span class="net-participants">${esc(networkParticipants(r))}</span><span class="net-preview">${esc(networkPreview(r))}</span>${networkBadge(r)}</button>`).join('') || '<div class="net-empty"><h3>No sessions found</h3><p>Agent requests and replies will appear here. Try All agents or clear your search.</p></div>'}</div><p class="net-footnote">Latest 200 requests. Each task and reply stays together.</p></section>
    <section class="net-conversation net-column" aria-label="Conversation">${selected ? networkConversation(selected) : `<div class="net-empty"><h2>${networkView.request?'Session unavailable':'Select a session'}</h2><p>${networkView.request?'This session may have expired under the retention policy.':'Choose a session to read its request and reply.'}</p><button data-back-sessions>Back to sessions</button></div>`}</section>`;
  $$('.net-scroll').forEach(el => { el.scrollTop = networkView.scroll[el.id] || 0; });
  $$('[data-device-toggle]').forEach(b => b.onclick = () => { const id=b.dataset.deviceToggle; networkView.collapsed.has(id)?networkView.collapsed.delete(id):networkView.collapsed.add(id); networkPaint(); });
  $$('[data-edit-device]').forEach(b => b.onclick = () => networkEditDevice(b.dataset.editDevice));
  $$('[data-agent]').forEach(b => b.onclick = () => { networkGo('sessions', b.dataset.agent, ''); });
  $$('[data-request]').forEach(b => b.onclick = () => networkGo('conversation', networkView.agent, b.dataset.request));
  $$('[data-back-sessions]').forEach(b => b.onclick = () => networkGo('sessions'));
  $('#networkBackAgents').onclick = () => networkGo('agents');
  $('#networkAll').onclick = () => networkGo('sessions', '', '');
  if ($('#networkClearAgent')) $('#networkClearAgent').onclick = () => networkGo('sessions', '', '');
  if ($('#networkAgentDetails')) $('#networkAgentDetails').onclick = () => networkAgentDetails(selectedAgent);
  if ($('#networkRequestDetails')) $('#networkRequestDetails').onclick = () => networkRequestDetails(selected);
}
function networkConversation(r) {
  const agents = networkView.data.agents;
  const sender = agents.find(a => a.id===r.sender), recipient=agents.find(a=>a.id===r.recipient);
  const message = (a, body, time, label) => {
    const device = networkView.data.devices.find(d=>d.id===a?.device);
    return `<article class="net-message">${networkAvatar(a)}<div><div class="net-message-meta"><button class="net-sender" data-message-agent="${esc(a?.id||'')}">${esc(networkName(a))}</button>${time ? `<time title="${esc(when(time))}">${esc(new Date(time*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}))}</time>`:`<span class="mut sm">${esc(label)}</span>`}</div><p class="net-message-device">${esc(device?.label || a?.device || '')}</p><div class="net-message-body" dir="auto">${esc(body)}</div></div></article>`;
  };
  let result = r.result?.message;
  if (!result && r.result) result = r.kind==='file.list' ? JSON.stringify(r.result, null, 2) : r.artifact ? `File ready: ${r.payload.path}` : 'Task completed. Open Details to inspect the result.';
  const notice = {queued:'Waiting for an available agent.',leased:'The agent is processing this request.',interrupted:'Delivery was interrupted. Check whether the agent acted before retrying.',failed:r.error || 'The task failed.',expired:'This request expired before completion.',cancelled:'This request was cancelled.'}[r.status];
  // Keep the request/reply contract honest: no invented intermediate messages or timestamps.
  const roster = [sender,recipient].filter(Boolean).map(a => `<button class="net-participant" data-message-agent="${esc(a.id)}"><span><b>${esc(networkName(a))}</b><small>${esc(networkView.data.devices.find(d=>d.id===a.device)?.label || a.device)}</small></span><span class="sm">${networkPresence(a)}</span></button>`).join('');
  const html = `<div class="net-conversation-head"><button class="net-mobile-back" data-back-sessions>${ni('chevron-left')} Sessions</button><div class="net-conversation-title"><h2 id="networkConversationHeading">${esc(networkTitle(r))}</h2><button id="networkRequestDetails" class="net-icon-button" aria-label="Session details">${ni('three-dots')}</button></div><p class="net-conversation-participants">${esc(networkParticipants(r))}</p><div class="net-conversation-roster">${roster}</div><div class="row">${networkBadge(r)}<span class="mut sm">Started ${esc(when(r.created_at))}</span></div></div>
    <div class="net-scroll" id="netConversation">${notice?`<p class="net-activity ${['failed','interrupted','expired'].includes(r.status)?'attention':''}" role="status">${esc(notice)}</p>`:''}
    ${message(sender, r.kind==='message'?r.payload.message:`${r.kind==='file.list'?'List folder':'Read file'}: ${r.payload.path || r.share}`,r.created_at,'Request')}
    ${result ? message(recipient,result,r.finished_at,'Reply') : r.status==='completed'?'<p class="mut">Completed without a message reply.</p>':''}
    ${r.artifact?`<a class="btn" href="/api/network/requests/${encodeURIComponent(r.id)}/artifact" download>${esc(r.payload.path)} · ${(r.artifact.size/1024).toFixed(1)} KB</a>`:''}</div>`;
  // Bind sender controls after the surrounding DOM has been installed.
  queueMicrotask(() => $$('[data-message-agent]').forEach(b => b.onclick=()=>networkAgentDetails(agents.find(a=>a.id===b.dataset.messageAgent))));
  return html;
}
function networkDialog(title, content) {
  $('#networkDialog')?.remove();
  const dialog=document.createElement('dialog'); dialog.id='networkDialog'; dialog.className='net-dialog'; dialog.setAttribute('aria-labelledby','networkDialogTitle');
  dialog.innerHTML=`<div class="net-dialog-head"><h2 id="networkDialogTitle">${esc(title)}</h2><button class="net-icon-button" aria-label="Close dialog">${ni('x-lg')}</button></div>${content}`;
  document.body.append(dialog); $('.net-dialog-head button',dialog).onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>dialog.remove()); dialog.showModal(); return dialog;
}
function networkEditDevice(id) {
  const d=networkView.data.devices.find(d=>d.id===id);
  const dialog=networkDialog('Edit device', `<form class="form" id="networkDeviceForm"><label class="f">Device name<input name="label" value="${esc(d.label)}" required maxlength="100" autocomplete="off"></label><label class="f">Device type<select name="kind">${Object.entries(networkTypes).map(([k,v])=>`<option value="${k}" ${k===d.kind?'selected':''}>${v}</option>`).join('')}</select></label><p class="mut sm">Names help you recognize devices. Renaming keeps all agents, permissions and conversations connected.</p><p role="alert" class="err" hidden></p><div class="row"><button type="button" data-dismiss>Cancel</button><button class="pri">Save changes</button></div></form>`);
  $('[data-dismiss]',dialog).onclick=()=>dialog.close();
  $('#networkDeviceForm').onsubmit=e=>networkSave(e,dialog,'/network/devices/'+encodeURIComponent(id),Object.fromEntries(new FormData(e.target)));
}
async function networkSave(e,dialog,path,body) {
  e.preventDefault(); const button=$('button.pri',e.target);button.disabled=true;
  try {await api('POST',path,body);dialog.close();await renderNetwork();toast('Changes saved');}
  catch(error){const el=$('[role="alert"]',dialog);el.textContent=error.message;el.hidden=false;button.disabled=false;}
}
function networkAgentDetails(a) {
  if (!a) return;
  const d=networkView.data.devices.find(d=>d.id===a.device);
  const dialog=networkDialog(networkName(a),`<p>${esc(d?.label || a.device)} · ${networkPresence(a)}</p><form class="form" id="networkAgentForm"><label class="f">Agent name<input name="label" required maxlength="100" value="${esc(networkName(a))}"></label><p role="alert" class="err" hidden></p><button class="pri">Save name</button></form><p class="mut sm">Capabilities: ${esc(a.capabilities.map(c=>({'message':'Messages','file.list':'List folders','file.read':'Read files'})[c]).join(', ') || 'Requesting only')}</p><details><summary>Connection history</summary><p class="mut sm">Identity: ${esc(a.id)}. Connections are separate from task sessions.</p>${a.sessions.map(s=>`<p class="sm">${esc(s.state)} · ${esc(ago(s.last_seen))}<br>${esc(s.capabilities.join(', ') || 'No serving capabilities')}</p>`).join('') || '<p>No connections yet.</p>'}</details>${a.revoked?'':`<hr><button id="networkRevoke" class="danger">Revoke access</button>`}`);
  $('#networkAgentForm').onsubmit=e=>networkSave(e,dialog,'/network/agents/label',{agent:a.id,label:e.target.elements.label.value});
  if ($('#networkRevoke')) $('#networkRevoke').onclick=async()=>{
    if(confirm(`Revoke ${networkName(a)}? Its credential will stop working and its shared artifacts will be withdrawn.`)) {
      try{await api('POST','/network/revoke',{agent:a.id});dialog.close();await renderNetwork();}catch(e){toast(e.message);}
    }
  };
}
function networkRequestDetails(r) {
  const dialog=networkDialog('Session details',`<dl><dt>Request</dt><dd>${esc(r.id)}</dd><dt>Status</dt><dd>${esc(networkStatus[r.status])}</dd><dt>Attempts</dt><dd>${r.attempts}</dd><dt>Deadline</dt><dd>${esc(when(r.expires_at))}</dd></dl>${r.status==='interrupted'?'<p>Check whether the agent acted before explicitly retrying.</p>':''}<details><summary>Technical details</summary><pre>${esc(JSON.stringify({request:r.payload,result:r.result,error:r.error},null,2))}</pre></details>${['queued','leased','interrupted'].includes(r.status)||r.artifact?`<button id="networkCancel" class="danger">${r.artifact?'Withdraw artifact':'Cancel request'}</button>`:''}`);
  if($('#networkCancel')) $('#networkCancel').onclick=async()=>{if(confirm(r.artifact?'Withdraw this stored artifact?':'Cancel this request?')){try{await api('POST',`/network/requests/${encodeURIComponent(r.id)}/cancel`,{});dialog.close();await renderNetwork();}catch(e){toast(e.message);}}};
}
function networkSettings(tab='permissions') {
  const {agents,grants,artifacts}=networkView.data, active=agents.filter(a=>!a.revoked);
  const options=active.map(a=>`<option value="${esc(a.id)}">${esc(networkName(a))} (${esc(networkView.data.devices.find(d=>d.id===a.device)?.label || a.device)})</option>`).join('');
  const label=id=>{const a=agents.find(a=>a.id===id);return a?`${networkName(a)} · ${networkView.data.devices.find(d=>d.id===a.device)?.label || a.device}`:id;};
  const dialog=networkDialog('Agent settings',`<div class="net-settings-tabs"><button data-setting="permissions" ${tab==='permissions'?'class="on"':''}>Permissions</button><button data-setting="files" ${tab==='files'?'class="on"':''}>Shared files</button><button data-setting="agents" ${tab==='agents'?'class="on"':''}>Manage agents</button></div>${tab==='permissions'?`<p class="mut sm">Permission flows from a source agent to a requester. File shares also require approval in the source connector's local configuration.</p>${active.length?`<form id="networkGrant" class="form"><label class="f">Source<select name="source">${options}</select></label><label class="f">Requester<select name="requester">${options}</select></label><label class="f">Operation<select name="kind"><option value="message">Send message</option><option value="file.list">List folder</option><option value="file.read">Read file</option></select></label><label class="f">Folder alias<input name="share" disabled pattern="[a-z0-9][a-z0-9_.-]{0,47}"></label><p role="alert" class="err" hidden></p><button class="pri">Allow</button></form>`:''}<div>${grants.map((g,i)=>`<div class="network-rule"><span>${esc(label(g.source))} → ${esc(label(g.requester))}<br><span class="mut sm">${esc(g.kind)} ${esc(g.share)}</span></span><button data-ungrant="${i}">Remove permission</button></div>`).join('')||'<p>No permissions yet.</p>'}</div>`:tab==='files'?`<p class="mut sm">Stored on the VPS. Available even when the source device is offline.</p>${artifacts.map(a=>`<article class="network-request"><b>${esc(a.path)}</b><p class="mut sm">${esc(label(a.source))} · ${(a.size/1024).toFixed(1)} KB</p><a class="btn" href="/api/network/artifacts/${encodeURIComponent(a.id)}" download>Download</a><p class="mut sm">${a.expires_at?'Expires '+esc(when(a.expires_at)):'Kept until withdrawn'}</p></article>`).join('')||'<p>No shared files yet.</p>'}`:`<p class="mut sm">Edit names and inspect connections. Revoked identities remain visible here for their history.</p>${agents.map(a=>`<button class="net-manage-agent" data-manage-agent="${esc(a.id)}">${esc(label(a.id))}<span>${networkPresence(a)}</span></button>`).join('')||'<p>No agents enrolled.</p>'}`}`);
  $$('[data-setting]',dialog).forEach(b=>b.onclick=()=>networkSettings(b.dataset.setting));
  $$('[data-manage-agent]',dialog).forEach(b=>b.onclick=()=>networkAgentDetails(agents.find(a=>a.id===b.dataset.manageAgent)));
  $$('[data-ungrant]',dialog).forEach(b=>b.onclick=async()=>{if(confirm('Remove this permission? Pending requests and shared artifacts may be withdrawn.')){try{await api('DELETE','/network/grants',grants[+b.dataset.ungrant]);await renderNetwork();networkSettings();}catch(e){toast(e.message);}}});
  const form=$('#networkGrant'); if(form){form.elements.kind.onchange=()=>{form.elements.share.disabled=form.elements.kind.value==='message';form.elements.share.required=!form.elements.share.disabled;};form.onsubmit=e=>networkSave(e,dialog,'/network/grants',Object.fromEntries(new FormData(form)));}
}
