// ═══════════════════════════════════════════
// Uptime Monitor - App JS (KUMA-style)
// ═══════════════════════════════════════════
const API = '';

// ── State ──
let allMonitors   = [];
let dashPreset    = '24h';
let dashFrom      = null;
let dashTo        = null;
let selectedMid   = null;
let refreshTimer  = null;
let collapsedGroups = {};  // groupName -> true/false
let selectedApp   = null;  // dashboard application tab (a group_name); null until first app auto-selected
let dashServers   = [];    // cache of servers for the dashboard linked-server lookup
let spPreset      = '24h';
let spFrom        = null;
let spTo          = null;
let currentSlug   = null;
let spServiceFilter = 'all';  // 'all' or monitor id as string
let spLastMonitors  = [];     // cache of last loaded monitors for client-side filtering

// ── Role-based page access ──
const ROLE_ALLOWED_PAGES = {
  dba: ['databases'],
  viewer: null,  // viewer sees everything except settings/user management (already handled)
  admin: null    // admin sees everything
};

// ── Toast ──
function toast(msg, type='info', dur=3500) {
  const c = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  const icons = {success:'&#10003;', error:'&#10007;', info:'&#8505;'};
  t.innerHTML = `<span style="font-weight:700;font-size:15px">${icons[type]||icons.info}</span><span>${esc(msg)}</span>`;
  c.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; t.style.transition='opacity .4s'; setTimeout(()=>t.remove(),400); }, dur);
}

// ── Escape HTML ──
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Navigation ──
function navigate(page) {
  // Role-based navigation guard: DBA can only access databases
  if (currentUserInfo && currentUserInfo.role === 'dba' && page !== 'databases') {
    page = 'databases';
  }
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sidebar-item[id^=nav-]').forEach(i => i.classList.remove('active'));
  const el = document.getElementById('page-'+page);
  if (el) el.classList.add('active');
  const nav = document.getElementById('nav-'+page);
  if (nav) nav.classList.add('active');
  if (page === 'dashboard')    refreshDashboard();
  if (page === 'status-pages') loadStatusPages();
  if (page === 'settings')     { loadSettings(); loadUsers(); loadMaintenance(); }
  if (page === 'ssl')          loadSSLPage();
  if (page === 'topology')     loadTopology();
  if (page === 'databases')    loadDatabases();
  if (page === 'servers')      loadServers();
  if (page === 'software')        loadSoftware();
  if (page === 'catalogue')       loadCatalogue();
  if (page === 'version-checks')  loadVersionChecksPage();
  if (page !== 'topology')     stopTopoAnimation();
}

// ── Timeframe helpers ──
function dashQS() {
  if (dashFrom && dashTo) return `?from_dt=${encodeURIComponent(dashFrom)}&to_dt=${encodeURIComponent(dashTo)}`;
  return `?preset=${dashPreset}`;
}
function spQS() {
  if (spFrom && spTo) return `?from_dt=${encodeURIComponent(spFrom)}&to_dt=${encodeURIComponent(spTo)}`;
  return `?preset=${spPreset || '24h'}`;
}

// Chart-specific timeframe (independent of main status page timeframe)
let chartPreset = '24h', chartFrom = null, chartTo = null;
function chartQS() {
  if (chartFrom && chartTo) return `?from_dt=${encodeURIComponent(chartFrom)}&to_dt=${encodeURIComponent(chartTo)}`;
  return `?preset=${chartPreset}`;
}
function chartSetPreset(p) {
  chartPreset = p; chartFrom = null; chartTo = null;
  document.querySelectorAll('#chart-tf-presets .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.p === p));
  document.getElementById('chart-from').value = '';
  document.getElementById('chart-to').value = '';
  document.getElementById('chart-clear-btn').style.display = 'none';
  const sel = document.getElementById('sp-detail-select');
  if (sel && sel.value) spDetailChanged();
}
function chartApplyCustom() {
  const f = document.getElementById('chart-from').value;
  const t = document.getElementById('chart-to').value;
  if (!f || !t) { toast('Select both From and To dates','error'); return; }
  if (new Date(f) >= new Date(t)) { toast('"From" must be before "To"','error'); return; }
  // Convert local datetime to UTC ISO string (YYYY-MM-DDTHH:MM format for backend)
  const fromUTC = new Date(f).toISOString().slice(0,19).replace('T',' ');
  const toUTC   = new Date(t).toISOString().slice(0,19).replace('T',' ');
  chartFrom = fromUTC;
  chartTo   = toUTC;
  chartPreset = null;
  document.querySelectorAll('#chart-tf-presets .tf-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('chart-clear-btn').style.display = '';
  const sel = document.getElementById('sp-detail-select');
  if (sel && sel.value) spDetailChanged();
}
function chartClearCustom() {
  chartFrom = null; chartTo = null; chartPreset = '24h';
  document.getElementById('chart-from').value = '';
  document.getElementById('chart-to').value = '';
  document.getElementById('chart-clear-btn').style.display = 'none';
  document.querySelectorAll('#chart-tf-presets .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.p === '24h'));
  const sel = document.getElementById('sp-detail-select');
  if (sel && sel.value) spDetailChanged();
}
function dashSetPreset(p) {
  dashPreset = p; dashFrom = null; dashTo = null;
  document.querySelectorAll('#dash-tf .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.p === p));
  refreshDashboard();
}
function dashApplyCustom() {
  const f = document.getElementById('dash-from').value;
  const t = document.getElementById('dash-to').value;
  if (!f || !t) { toast('Select both From and To dates','error'); return; }
  if (new Date(f) >= new Date(t)) { toast('"From" must be before "To"','error'); return; }
  dashFrom = f; dashTo = t; dashPreset = null;
  document.querySelectorAll('#dash-tf .tf-btn').forEach(b => b.classList.remove('active'));
  refreshDashboard();
}
function spSetPreset(p) {
  spPreset = p; spFrom = null; spTo = null;
  document.querySelectorAll('#sp-tf-presets .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.p === p));
  // clear custom inputs visually
  document.getElementById('sp-from').value = '';
  document.getElementById('sp-to').value   = '';
  document.getElementById('sp-clear-btn').style.display = 'none';
  updateSpFilterBadge();
  loadStatusPageView(currentSlug);
}
function spApplyCustom() {
  const f = document.getElementById('sp-from').value;
  const t = document.getElementById('sp-to').value;
  if (!f || !t) { toast('Select both From and To dates','error'); return; }
  if (new Date(f) >= new Date(t)) { toast('"From" must be before "To"','error'); return; }
  spFrom = f; spTo = t; spPreset = null;
  document.querySelectorAll('#sp-tf-presets .tf-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('sp-clear-btn').style.display = '';
  // Show the service filter bar and populate it
  const bar = document.getElementById('sp-custom-service-bar');
  bar.style.display = '';
  spPopulateCustomServiceDropdown();
  updateSpFilterBadge();
  loadStatusPageView(currentSlug);
}
function spClearCustom() {
  spFrom = null; spTo = null; spPreset = '24h';
  document.getElementById('sp-from').value = '';
  document.getElementById('sp-to').value   = '';
  document.getElementById('sp-clear-btn').style.display = 'none';
  // Hide service filter bar and reset it
  document.getElementById('sp-custom-service-bar').style.display = 'none';
  document.getElementById('sp-custom-service').value = 'all';
  document.querySelectorAll('#sp-tf-presets .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.p === '24h'));
  updateSpFilterBadge();
  loadStatusPageView(currentSlug);
}
function spPopulateCustomServiceDropdown() {
  const sel = document.getElementById('sp-custom-service');
  const prev = sel.value;
  sel.innerHTML = '<option value="all">All Services</option>';
  spLastMonitors.forEach(m => {
    const opt = document.createElement('option');
    opt.value = String(m.id);
    opt.textContent = m.name;
    sel.appendChild(opt);
  });
  if (prev && [...sel.options].some(o => o.value === prev)) sel.value = prev;
}
function spCustomServiceChanged() {
  const mid = document.getElementById('sp-custom-service').value;
  const el  = document.getElementById('sp-monitors');
  if (mid === 'all') {
    // Show all monitors with custom range
    renderSpMonitors(spLastMonitors);
    return;
  }
  // Filter to just the selected monitor
  const filtered = spLastMonitors.filter(m => String(m.id) === mid);
  if (!filtered.length) return;
  // Fetch fresh data for this monitor with the custom date range
  const qs = spQS();
  el.innerHTML = '<div class="loading-center"><div class="spinner"></div> Loading...</div>';
  fetch(`${API}/api/status-pages/slug/${currentSlug}${qs}`)
    .then(r => r.json())
    .then(data => {
      const mon = data.monitors.find(m => String(m.id) === mid);
      if (mon) {
        spLastMonitors = data.monitors; // update cache
        renderSpMonitors(data.monitors.filter(m => String(m.id) === mid));
      }
    })
    .catch(e => { el.innerHTML = `<div class="empty-state"><p style="color:var(--red)">${esc(e.message)}</p></div>`; });
}
// spServiceChanged removed - replaced by spDetailChanged
function updateSpFilterBadge() {
  // Show active custom date range as a badge in the timeframe bar
  if (spFrom && spTo) {
    const fd = new Date(spFrom).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
    const td = new Date(spTo).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
    // Update the clear button label if it exists
    const clearBtn = document.getElementById('sp-clear-btn');
    if (clearBtn) clearBtn.style.display = '';
  }
}

function toggleGroup(safeId) {
  // safeId is already sanitised (spaces/special chars replaced with _)
  collapsedGroups[safeId] = !collapsedGroups[safeId];
  const body  = document.getElementById('group-body-'  + safeId);
  const arrow = document.getElementById('group-arrow-' + safeId);
  if (body)  body.style.display       = collapsedGroups[safeId] ? 'none' : '';
  if (arrow) arrow.style.transform    = collapsedGroups[safeId] ? 'rotate(-90deg)' : 'rotate(0deg)';
}



// ═══════════════════════════════════════════
// AUTH
// ═══════════════════════════════════════════
let currentUserInfo = null;

function applyRoleRestrictions(role) {
  const allowed = ROLE_ALLOWED_PAGES[role];
  if (allowed === null) return; // admin and viewer see everything (viewer restrictions handled elsewhere)

  // Remove disallowed nav items from DOM entirely
  document.querySelectorAll('.sidebar-item[id^=nav-]').forEach(item => {
    const page = item.id.replace('nav-', '');
    if (!allowed.includes(page)) {
      item.remove();
    }
  });
}

async function checkAuth() {
  try {
    const res = await fetch(`${API}/api/auth/me`, {credentials:'include'});
    if (!res.ok) { window.location.href = '/login'; return false; }
    currentUserInfo = await res.json();
    const el = document.getElementById('sb-username');
    if (el) el.textContent = currentUserInfo.username + (currentUserInfo.role === 'admin' ? ' (admin)' : '');
    const umCard = document.getElementById('user-mgmt-card');
    if (umCard) umCard.style.display = currentUserInfo.role === 'admin' ? '' : 'none';
    const eiCard = document.getElementById('export-import-card');
    if (eiCard) eiCard.style.display = currentUserInfo.role === 'admin' ? '' : 'none';
    applyRoleRestrictions(currentUserInfo.role);
    return true;
  } catch(e) { window.location.href = '/login'; return false; }
}

async function doSignOut() {
  await fetch(`${API}/api/auth/logout`, {method:'POST', credentials:'include'});
  window.location.href = '/login';
}

// ═══════════════════════════════════════════
// USER MANAGEMENT
// ═══════════════════════════════════════════
async function loadUsers() {
  try {
    const res = await fetch(`${API}/api/users`, {credentials:'include'});
    if (!res.ok) return;
    const users = await res.json();
    const tbody = document.getElementById('users-tbody');
    if (!tbody) return;
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text3);padding:20px">No users found.</td></tr>';
      return;
    }
    tbody.innerHTML = users.map(u => `<tr>
      <td><strong>${esc(u.username)}</strong></td>
      <td><span class="badge" style="${u.role==='admin'?'background:rgba(43,125,233,.1);color:var(--blue)':'background:var(--surface2);color:var(--text3);border:1px solid var(--border)'}">${u.role}</span></td>
      <td style="color:var(--text3);font-size:12px">${new Date(u.created_at+'Z').toLocaleDateString()}</td>
      <td style="display:flex;gap:6px">
        <button class="btn btn-secondary btn-sm" onclick="openEditUserModal(${u.id},'${esc(u.username)}','${u.role}')"><svg width="12" height="12"><use href="#ic-edit"/></svg> Edit</button>
        <button class="btn btn-danger btn-sm" onclick="confirmDeleteUser(${u.id},'${esc(u.username)}')"><svg width="12" height="12"><use href="#ic-trash"/></svg></button>
      </td>
    </tr>`).join('');
  } catch(e) {}
}

function openAddUserModal() {
  document.getElementById('modal-user-title').textContent = 'Add User';
  document.getElementById('u-id').value = '';
  document.getElementById('u-username').value = '';
  document.getElementById('u-password').value = '';
  document.getElementById('u-role').value = 'viewer';
  document.getElementById('u-username').disabled = false;
  document.getElementById('u-pass-hint').style.display = 'none';
  openModal('modal-user');
}

function openEditUserModal(id, username, role) {
  document.getElementById('modal-user-title').textContent = 'Edit User';
  document.getElementById('u-id').value = id;
  document.getElementById('u-username').value = username;
  document.getElementById('u-password').value = '';
  document.getElementById('u-role').value = role;
  document.getElementById('u-username').disabled = true;
  document.getElementById('u-pass-hint').style.display = '';
  openModal('modal-user');
}

async function saveUser() {
  const id = document.getElementById('u-id').value;
  const username = document.getElementById('u-username').value.trim();
  const password = document.getElementById('u-password').value;
  const role = document.getElementById('u-role').value;
  if (!id && (!username || !password)) { toast('Username and password required','error'); return; }
  try {
    const method = id ? 'PUT' : 'POST';
    const url = id ? `${API}/api/users/${id}` : `${API}/api/users`;
    const body = id ? {password, role} : {username, password, role};
    const res = await fetch(url, {method, headers:{'Content-Type':'application/json'}, credentials:'include', body:JSON.stringify(body)});
    if (!res.ok) { const e = await res.json(); toast(e.error||'Error','error'); return; }
    closeModal('modal-user');
    toast(id ? 'User updated' : 'User created', 'success');
    loadUsers();
  } catch(e) { toast('Error: '+e.message,'error'); }
}

function confirmDeleteUser(id, name) {
  document.getElementById('confirm-msg').textContent = `Delete user "${name}"? This cannot be undone.`;
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    const res = await fetch(`${API}/api/users/${id}`, {method:'DELETE', credentials:'include'});
    if (res.ok) { toast('User deleted','success'); loadUsers(); }
    else { const e = await res.json(); toast(e.error||'Error','error'); }
  };
  openModal('modal-confirm');
}

// ═══════════════════════════════════════════
async function refreshDashboard() {
  try {
    const res  = await fetch(`${API}/api/status${dashQS()}`, {credentials:'include'});
    allMonitors = await res.json();
    // Load servers for the linked-servers section (best effort — don't block the dashboard)
    try {
      const sres = await fetch(`${API}/api/servers`, {credentials:'include'});
      if (sres.ok) dashServers = await sres.json();
    } catch(e) { /* servers optional */ }
    renderSidebar(allMonitors);
    renderDashboard(allMonitors);
    document.getElementById('dash-last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) {
    document.getElementById('dash-monitor-list').innerHTML =
      `<div class="empty-state"><div class="icon">⚠️</div><p>Cannot reach API server.<br><small>${esc(e.message)}</small></p></div>`;
  }
}

function renderSidebar(monitors) {
  const up     = monitors.filter(m => m.current_status?.status === 1 && m.enabled).length;
  const down   = monitors.filter(m => m.current_status?.status === 0 && m.enabled).length;
  const paused = monitors.filter(m => !m.enabled).length;
  document.getElementById('sb-summary').innerHTML =
    `<span class="text-green">▲ ${up} up</span> · <span class="text-red">▼ ${down} down</span> · <span class="text-muted">${paused} paused</span>`;
  document.getElementById('sb-refresh').textContent = 'Refreshes every 60s';

  const list = document.getElementById('sidebar-monitors');
  if (!monitors.length) { list.innerHTML = '<div style="padding:8px 16px;font-size:12px;color:var(--text3)">No monitors yet</div>'; return; }
  list.innerHTML = monitors.map(m => {
    const st = !m.enabled ? 'paused' : m.current_status ? (m.current_status.status ? 'up' : 'down') : 'pending';
    return `<div class="sidebar-monitor-item ${selectedMid===m.id?'active':''}" onclick="selectMonitor(${m.id})">
      <div class="dot ${st}"></div>
      <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(m.name)}</span>
    </div>`;
  }).join('');
}

// Returns the "application" (group) name for a monitor; blank → 'General'
function appOf(m) {
  return m.group_name && m.group_name.trim() ? m.group_name.trim() : 'General';
}

// Sort helper: keep 'General' last, otherwise alphabetical
function appSort(a, b) {
  if (a === 'General') return 1;
  if (b === 'General') return -1;
  return a.localeCompare(b);
}

// Switch the selected application tab
function selectApp(app) {
  selectedApp = app;
  renderDashboard(allMonitors);
}

// Render the application tab bar from the current monitor set
function renderAppTabs(monitors) {
  const el = document.getElementById('dash-app-tabs');
  if (!el) return;

  const groups = {};
  monitors.forEach(m => {
    const g = appOf(m);
    if (!groups[g]) groups[g] = [];
    groups[g].push(m);
  });
  const groupNames = Object.keys(groups).sort(appSort);

  // Auto-select the first app if none selected or selected app vanished
  if (!selectedApp || !groups[selectedApp]) {
    selectedApp = groupNames[0] || null;
  }

  const tab = (key, label, count, mons) => {
    const down = mons ? mons.filter(m => m.current_status?.status === 0 && m.enabled).length : 0;
    const anyDown = down > 0;
    const dot = `<span class="app-tab-dot" style="background:${anyDown ? 'var(--red)' : 'var(--green)'}"></span>`;
    return `<button class="app-tab ${selectedApp===key?'active':''}" onclick="selectApp('${esc(key).replace(/'/g,"\\'")}')">
      ${dot}<span>${esc(label)}</span><span class="app-tab-count">${count}</span>
    </button>`;
  };

  let html = '';
  groupNames.forEach(g => { html += tab(g, g, groups[g].length, groups[g]); });
  el.innerHTML = html;
}

// Render a single monitor card (shared by grouped + filtered views)
function renderMonitorCard(m) {
  const st       = !m.enabled ? 'paused' : m.current_status ? (m.current_status.status ? 'up' : 'down') : 'pending';
  const upPct    = m.uptime_pct !== null ? m.uptime_pct.toFixed(2)+'%' : '–';
  const lat      = m.avg_latency !== null ? m.avg_latency+'ms' : '–';
  const badgeCls = {up:'badge-up',down:'badge-down',paused:'badge-paused',pending:'badge-pending'}[st];
  const badgeTxt = {up:'Up',down:'Down',paused:'Paused',pending:'Pending'}[st];
  const bars     = renderHBBars(m.timeline, m.from_dt, m.to_dt);
  return `<div class="monitor-card ${selectedMid===m.id?'selected':''}" onclick="selectMonitor(${m.id})">
    <div class="mc-header">
      <div class="dot ${st}" style="width:10px;height:10px"></div>
      <div style="flex:1;min-width:0">
        <div class="mc-name">${esc(m.name)}</div>
        <div class="mc-url">${esc(m.url)}</div>
      </div>
      <span class="badge ${badgeCls}">${badgeTxt}</span>
      <div style="display:flex;gap:4px;margin-left:8px">
        <button class="btn btn-secondary btn-sm btn-icon" onclick="event.stopPropagation();openEditMonitorModal(${m.id})" title="Edit"><svg width="13" height="13"><use href="#ic-edit"/></svg></button>
        <button class="btn btn-secondary btn-sm btn-icon" onclick="event.stopPropagation();toggleMonitor(${m.id})" title="${m.enabled?'Pause':'Resume'}">${m.enabled?'<svg width="13" height="13"><use href="#ic-pause"/></svg>':'<svg width="13" height="13"><use href="#ic-play"/></svg>'}</button>
        <button class="btn btn-danger btn-sm btn-icon" onclick="event.stopPropagation();confirmDelete('monitor',${m.id},'${esc(m.name)}')" title="Delete"><svg width="13" height="13"><use href="#ic-trash"/></svg></button>
      </div>
    </div>
    <div class="mc-meta">
      <div class="mc-stat"><div class="val ${m.uptime_pct>=99?'val-green':m.uptime_pct>=90?'val-blue':'val-red'}">${upPct}</div><div class="lbl">Uptime</div></div>
      <div class="mc-stat"><div class="val val-blue">${lat}</div><div class="lbl">Avg Latency</div></div>
      <div class="mc-stat"><div class="val">${m.total_checks||0}</div><div class="lbl">Checks</div></div>
    </div>
    ${bars}
  </div>`;
}

// Render the "Linked Servers" section for a selected application.
// A server belongs to the app if any of its linked monitors has that group_name.
function renderLinkedServers(app) {
  if (!dashServers || !dashServers.length) {
    return `<div class="linked-servers">
      <div class="linked-servers-title"><svg width="14" height="14" style="color:var(--fnb-teal)"><use href="#ic-dashboard"/></svg> Linked Servers</div>
      <div style="font-size:12px;color:var(--text3)">No servers linked to this application.</div>
    </div>`;
  }

  const matches = dashServers.filter(s =>
    Array.isArray(s.monitors) && s.monitors.some(mon => (mon.group_name && mon.group_name.trim() ? mon.group_name.trim() : 'General') === app)
  );

  let body;
  if (!matches.length) {
    body = `<div style="font-size:12px;color:var(--text3)">No servers linked to this application.</div>`;
  } else {
    const healthColor = { healthy:'var(--green)', degraded:'var(--yellow)', critical:'var(--red)', pending:'var(--blue)', unknown:'var(--text3)' };
    body = matches.map(s => {
      const col = healthColor[s.health] || 'var(--text3)';
      const meta = [s.environment, s.role, s.ip_address, s.os].filter(Boolean).map(esc).join(' · ');
      return `<div class="srv-card">
        <span class="srv-dot" style="background:${col}"></span>
        <div class="srv-main">
          <div class="srv-host">${esc(s.hostname)}</div>
          <div class="srv-meta">${meta || '&nbsp;'}</div>
        </div>
        <div class="srv-counts">${s.up_count||0} up · ${s.down_count||0} down · ${s.total_monitors||0} total</div>
      </div>`;
    }).join('');
  }

  return `<div class="linked-servers">
    <div class="linked-servers-title"><svg width="14" height="14" style="color:var(--fnb-teal)"><use href="#ic-dashboard"/></svg> Linked Servers</div>
    ${body}
  </div>`;
}

// Full detail panel for a single monitor, used stacked in the application view.
// Uses per-monitor element IDs so multiple panels coexist on one page.
function renderDetailPanel(m) {
  const st     = !m.enabled ? 'paused' : m.current_status ? (m.current_status.status ? 'up' : 'down') : 'pending';
  const badgeCls = {up:'badge-up',down:'badge-down',paused:'badge-paused',pending:'badge-pending'}[st];
  const badgeTxt = {up:'Operational',down:'Down',paused:'Paused',pending:'Pending'}[st];
  const upPct  = m.uptime_pct !== null ? m.uptime_pct.toFixed(2)+'%' : '–';
  const lat    = m.avg_latency !== null ? m.avg_latency+'ms' : '–';
  const lastCheck = m.current_status?.checked_at ? new Date(m.current_status.checked_at+'Z').toLocaleString() : '–';
  const typeIconId = {http:'ic-http',https:'ic-http',keyword:'ic-key',tcp:'ic-tcp'};
  const iconId = typeIconId[m.type] || 'ic-http';
  const icon = `<svg width="20" height="20" style="color:var(--fnb-teal)"><use href="#${iconId}"/></svg>`;
  const tags = (m.tags||'').split(',').filter(Boolean).map(t=>`<span class="tag">${esc(t.trim())}</span>`).join('');

  return `
    <div class="detail-panel" style="margin-bottom:16px">
      <div class="detail-header">
        <div class="detail-icon">${icon}</div>
        <div class="detail-title" style="flex:1">
          <h2>${esc(m.name)} <span class="badge ${badgeCls}" style="font-size:11px">${badgeTxt}</span></h2>
          <div class="url"><a href="${esc(m.url)}" target="_blank" style="color:var(--blue)">${esc(m.url)}</a></div>
          ${tags ? `<div style="margin-top:6px">${tags}</div>` : ''}
        </div>
        <div style="display:flex;gap:6px">
          <button class="btn btn-secondary btn-sm" onclick="openEditMonitorModal(${m.id})"><svg width="13" height="13"><use href="#ic-edit"/></svg> Edit</button>
          <button class="btn btn-secondary btn-sm" onclick="toggleMonitor(${m.id})">${m.enabled?'<svg width="13" height="13"><use href="#ic-pause"/></svg> Pause':'<svg width="13" height="13"><use href="#ic-play"/></svg> Resume'}</button>
          <button class="btn btn-danger btn-sm" onclick="confirmDelete('monitor',${m.id},'${esc(m.name)}')"><svg width="13" height="13"><use href="#ic-trash"/></svg></button>
        </div>
      </div>
      <div class="detail-stats">
        <div class="stat-box"><div class="sv ${m.uptime_pct>=99?'val-green':m.uptime_pct>=90?'val-blue':'val-red'}">${upPct}</div><div class="sl">Uptime</div></div>
        <div class="stat-box"><div class="sv val-blue">${lat}</div><div class="sl">Avg Latency</div></div>
        <div class="stat-box"><div class="sv">${m.total_checks||0}</div><div class="sl">Total Checks</div></div>
        <div class="stat-box"><div class="sv val-green">${m.up_checks||0}</div><div class="sl">Up Checks</div></div>
      </div>
      <div style="margin-bottom:16px">
        <div style="font-size:11px;color:var(--text3);margin-bottom:6px;text-transform:uppercase;font-weight:600">Heartbeat Timeline</div>
        ${renderHBBars(m.timeline, m.from_dt, m.to_dt)}
      </div>
      <div style="font-size:12px;color:var(--text3);margin-bottom:16px">
        <span>Type: <strong style="color:var(--text)">${m.type.toUpperCase()}</strong></span> &nbsp;·&nbsp;
        <span>Interval: <strong style="color:var(--text)">${m.interval}s</strong></span> &nbsp;·&nbsp;
        <span>Retries: <strong style="color:var(--text)">${m.retries}</strong></span> &nbsp;·&nbsp;
        <span>Last check: <strong style="color:var(--text)">${lastCheck}</strong></span>
      </div>
      ${m.description ? `<div style="color:var(--text2);font-size:13px;margin-bottom:16px">${esc(m.description)}</div>` : ''}
      <div>
        <div style="font-size:11px;color:var(--text3);margin-bottom:8px;text-transform:uppercase;font-weight:600">Recent Heartbeats</div>
        <div id="hb-table-wrap-${m.id}"><div class="loading-center"><div class="spinner"></div></div></div>
      </div>
      <div style="margin-top:20px;padding:16px;background:var(--surface2);border-radius:var(--radius);border:1px solid var(--border)">
        <div style="font-size:11px;color:var(--text3);margin-bottom:10px;text-transform:uppercase;font-weight:600">📋 Audit Report</div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <button class="btn btn-secondary btn-sm" onclick="downloadAuditReport(${m.id},'7d')">Last 7 Days</button>
          <button class="btn btn-secondary btn-sm" onclick="downloadAuditReport(${m.id},'30d')">Last 30 Days</button>
          <button class="btn btn-secondary btn-sm" onclick="downloadAuditReport(${m.id},'90d')">Last 90 Days</button>
          <span style="color:var(--text3);font-size:11px;margin:0 4px">or</span>
          <input type="date" id="audit-from-${m.id}" style="font-size:11px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text)">
          <span style="font-size:11px;color:var(--text3)">to</span>
          <input type="date" id="audit-to-${m.id}" style="font-size:11px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text)">
          <button class="btn btn-primary btn-sm" onclick="downloadAuditReportCustom(${m.id})">📥 Download</button>
        </div>
        <div id="audit-status-${m.id}" style="font-size:11px;color:var(--text3);margin-top:8px"></div>
      </div>
    </div>`;
}

// Build the recent-heartbeats table HTML (shared markup)
function heartbeatTableHTML(hbs) {
  if (!hbs.length) return '<div style="color:var(--text3);font-size:13px;padding:12px 0">No heartbeats recorded yet.</div>';
  return `<div class="table-wrap" style="max-height:220px;overflow-y:auto">
    <table>
      <thead><tr><th>Status</th><th>Latency</th><th>Message</th><th>Time</th></tr></thead>
      <tbody>${hbs.map(h => `<tr>
        <td><span class="badge ${h.status?'badge-up':'badge-down'}">${h.status?'Up':'Down'}</span></td>
        <td>${h.latency_ms !== null ? h.latency_ms+'ms' : '–'}</td>
        <td style="color:var(--text3);font-size:12px">${esc(h.msg||'')}</td>
        <td style="color:var(--text3);font-size:12px">${new Date(h.checked_at+'Z').toLocaleString()}</td>
      </tr>`).join('')}</tbody>
    </table></div>`;
}

// Fetch and fill recent heartbeats for every monitor currently shown in the app view
async function loadAppHeartbeats(monitors) {
  await Promise.all(monitors.map(async m => {
    const wrap = document.getElementById('hb-table-wrap-' + m.id);
    if (!wrap) return;
    try {
      const res = await fetch(`${API}/api/monitors/${m.id}/heartbeats?limit=50`, {credentials:'include'});
      const hbs = await res.json();
      // Element may have been replaced by a re-render; re-query before writing
      const target = document.getElementById('hb-table-wrap-' + m.id);
      if (target) target.innerHTML = heartbeatTableHTML(hbs);
    } catch(e) {
      const target = document.getElementById('hb-table-wrap-' + m.id);
      if (target) target.innerHTML = '<div style="color:var(--text3);font-size:12px;padding:8px 0">Could not load heartbeats.</div>';
    }
  }));
}

function renderDashboard(monitors) {
  renderAppTabs(monitors);  // auto-selects the first app and normalises selectedApp

  if (!monitors.length) {
    document.getElementById('ds-total').textContent  = 0;
    document.getElementById('ds-up').textContent     = 0;
    document.getElementById('ds-down').textContent   = 0;
    document.getElementById('ds-paused').textContent = 0;
    document.getElementById('ds-avg').textContent    = '–';
    document.getElementById('dash-monitor-list').innerHTML =
      `<div class="empty-state"><svg style="width:48px;height:48px;margin:0 auto 16px;display:block;opacity:.3"><use href="#ic-monitor"/></svg><p>No monitors yet.</p><button class="btn btn-primary" onclick="openAddMonitorModal()">Add your first monitor</button></div>`;
    document.getElementById('dash-detail').style.display = 'none';
    return;
  }

  // Monitors for the currently selected application
  const viewMonitors = monitors.filter(m => appOf(m) === selectedApp);

  // Stat cards reflect the selected application only
  const total  = viewMonitors.length;
  const up     = viewMonitors.filter(m => m.current_status?.status === 1 && m.enabled).length;
  const down   = viewMonitors.filter(m => m.current_status?.status === 0 && m.enabled).length;
  const paused = viewMonitors.filter(m => !m.enabled).length;
  const uptimes = viewMonitors.map(m => m.uptime_pct).filter(v => v !== null);
  const avg    = uptimes.length ? (uptimes.reduce((a,b)=>a+b,0)/uptimes.length).toFixed(1)+'%' : '–';

  document.getElementById('ds-total').textContent  = total;
  document.getElementById('ds-up').textContent     = up;
  document.getElementById('ds-down').textContent   = down;
  document.getElementById('ds-paused').textContent = paused;
  document.getElementById('ds-avg').textContent    = avg;

  // Application view: full-width stack of complete detail panels, one per route.
  // Hide the old right-hand single-detail column and span the list full width.
  document.getElementById('dash-detail').style.display = 'none';
  const listEl = document.getElementById('dash-monitor-list');
  if (listEl.parentElement) listEl.parentElement.style.gridTemplateColumns = '1fr';

  let html = renderLinkedServers(selectedApp);
  if (!viewMonitors.length) {
    html += `<div class="empty-state" style="padding:24px"><p>No monitors in this application.</p></div>`;
    listEl.innerHTML = html;
    return;
  }
  html += viewMonitors.map(renderDetailPanel).join('');
  listEl.innerHTML = html;

  // Fill recent-heartbeat tables for each panel
  loadAppHeartbeats(viewMonitors);
}

function renderHBBars(timeline, fromDt, toDt) {
  if (!timeline || !timeline.length) return '';
  const bars = timeline.map((v) => {
    const cls = v === null ? 'nodata' : v ? 'up' : 'down';
    const tip = v === null ? 'No data' : v ? 'Up' : 'Down';
    return `<div class="hb-bar ${cls}" data-tip="${tip}"></div>`;
  }).join('');
  const fl = fromDt ? new Date(fromDt+'Z').toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
  const tl = toDt   ? new Date(toDt+'Z').toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
  return `<div class="hb-bars">${bars}</div><div class="hb-labels"><span>${fl}</span><span>${tl}</span></div>`;
}

async function selectMonitor(id) {
  selectedMid = id;
  const m = allMonitors.find(x => x.id === id);
  if (!m) return;

  // Switch to this monitor's application so its stacked detail panel is visible
  const app = appOf(m);
  if (app !== selectedApp) {
    selectedApp = app;
    renderDashboard(allMonitors);
  }

  // Highlight the sidebar entry
  document.querySelectorAll('.sidebar-monitor-item').forEach(c => c.classList.remove('active'));

  // Scroll the matching detail panel into view (allow the DOM to render first)
  setTimeout(() => {
    const wrap = document.getElementById('hb-table-wrap-' + id);
    const panel = wrap ? wrap.closest('.detail-panel') : null;
    if (panel) {
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      panel.style.transition = 'box-shadow .3s';
      panel.style.boxShadow = '0 0 0 2px var(--fnb-teal)';
      setTimeout(() => { panel.style.boxShadow = ''; }, 1500);
    }
  }, 60);
}

function renderDetail(m) {
  if (!m) return;
  const st     = !m.enabled ? 'paused' : m.current_status ? (m.current_status.status ? 'up' : 'down') : 'pending';
  const badgeCls = {up:'badge-up',down:'badge-down',paused:'badge-paused',pending:'badge-pending'}[st];
  const badgeTxt = {up:'Operational',down:'Down',paused:'Paused',pending:'Pending'}[st];
  const upPct  = m.uptime_pct !== null ? m.uptime_pct.toFixed(2)+'%' : '–';
  const lat    = m.avg_latency !== null ? m.avg_latency+'ms' : '–';
  const lastCheck = m.current_status?.checked_at ? new Date(m.current_status.checked_at+'Z').toLocaleString() : '–';
  const typeIconId = {http:'ic-http',https:'ic-http',keyword:'ic-key',tcp:'ic-tcp'};
  const iconId = typeIconId[m.type] || 'ic-http';
  const icon = `<svg width="20" height="20" style="color:var(--fnb-teal)"><use href="#${iconId}"/></svg>`;
  const tags = (m.tags||'').split(',').filter(Boolean).map(t=>`<span class="tag">${esc(t.trim())}</span>`).join('');

  document.getElementById('dash-detail').innerHTML = `
    <div class="detail-panel">
      <div class="detail-header">
        <div class="detail-icon">${icon}</div>
        <div class="detail-title" style="flex:1">
          <h2>${esc(m.name)} <span class="badge ${badgeCls}" style="font-size:11px">${badgeTxt}</span></h2>
          <div class="url"><a href="${esc(m.url)}" target="_blank" style="color:var(--blue)">${esc(m.url)}</a></div>
          ${tags ? `<div style="margin-top:6px">${tags}</div>` : ''}
        </div>
        <div style="display:flex;gap:6px">
          <button class="btn btn-secondary btn-sm" onclick="openEditMonitorModal(${m.id})"><svg width="13" height="13"><use href="#ic-edit"/></svg> Edit</button>
          <button class="btn btn-secondary btn-sm" onclick="toggleMonitor(${m.id})">${m.enabled?'<svg width="13" height="13"><use href="#ic-pause"/></svg> Pause':'<svg width="13" height="13"><use href="#ic-play"/></svg> Resume'}</button>
        </div>
      </div>
      <div class="detail-stats">
        <div class="stat-box"><div class="sv ${m.uptime_pct>=99?'val-green':m.uptime_pct>=90?'val-blue':'val-red'}">${upPct}</div><div class="sl">Uptime</div></div>
        <div class="stat-box"><div class="sv val-blue">${lat}</div><div class="sl">Avg Latency</div></div>
        <div class="stat-box"><div class="sv">${m.total_checks||0}</div><div class="sl">Total Checks</div></div>
        <div class="stat-box"><div class="sv val-green">${m.up_checks||0}</div><div class="sl">Up Checks</div></div>
      </div>
      <div style="margin-bottom:16px">
        <div style="font-size:11px;color:var(--text3);margin-bottom:6px;text-transform:uppercase;font-weight:600">Heartbeat Timeline</div>
        ${renderHBBars(m.timeline, m.from_dt, m.to_dt)}
      </div>
      <div style="font-size:12px;color:var(--text3);margin-bottom:16px">
        <span>Type: <strong style="color:var(--text)">${m.type.toUpperCase()}</strong></span> &nbsp;·&nbsp;
        <span>Interval: <strong style="color:var(--text)">${m.interval}s</strong></span> &nbsp;·&nbsp;
        <span>Retries: <strong style="color:var(--text)">${m.retries}</strong></span> &nbsp;·&nbsp;
        <span>Last check: <strong style="color:var(--text)">${lastCheck}</strong></span>
      </div>
      ${m.description ? `<div style="color:var(--text2);font-size:13px;margin-bottom:16px">${esc(m.description)}</div>` : ''}
      <div>
        <div style="font-size:11px;color:var(--text3);margin-bottom:8px;text-transform:uppercase;font-weight:600">Recent Heartbeats</div>
        <div id="hb-table-wrap"><div class="loading-center"><div class="spinner"></div></div></div>
      </div>
      <div style="margin-top:20px;padding:16px;background:var(--surface2);border-radius:var(--radius);border:1px solid var(--border)">
        <div style="font-size:11px;color:var(--text3);margin-bottom:10px;text-transform:uppercase;font-weight:600">📋 Audit Report</div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <button class="btn btn-secondary btn-sm" onclick="downloadAuditReport(${m.id},'7d')">Last 7 Days</button>
          <button class="btn btn-secondary btn-sm" onclick="downloadAuditReport(${m.id},'30d')">Last 30 Days</button>
          <button class="btn btn-secondary btn-sm" onclick="downloadAuditReport(${m.id},'90d')">Last 90 Days</button>
          <span style="color:var(--text3);font-size:11px;margin:0 4px">or</span>
          <input type="date" id="audit-from-${m.id}" style="font-size:11px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text)">
          <span style="font-size:11px;color:var(--text3)">to</span>
          <input type="date" id="audit-to-${m.id}" style="font-size:11px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:var(--surface);color:var(--text)">
          <button class="btn btn-primary btn-sm" onclick="downloadAuditReportCustom(${m.id})">📥 Download</button>
        </div>
        <div id="audit-status-${m.id}" style="font-size:11px;color:var(--text3);margin-top:8px"></div>
      </div>
    </div>`;
}

function renderHeartbeatTable(hbs) {
  const wrap = document.getElementById('hb-table-wrap');
  if (!wrap) return;
  if (!hbs.length) { wrap.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:12px 0">No heartbeats recorded yet.</div>'; return; }
  wrap.innerHTML = `<div class="table-wrap" style="max-height:220px;overflow-y:auto">
    <table>
      <thead><tr><th>Status</th><th>Latency</th><th>Message</th><th>Time</th></tr></thead>
      <tbody>${hbs.map(h => `<tr>
        <td><span class="badge ${h.status?'badge-up':'badge-down'}">${h.status?'Up':'Down'}</span></td>
        <td>${h.latency_ms !== null ? h.latency_ms+'ms' : '–'}</td>
        <td style="color:var(--text3);font-size:12px">${esc(h.msg||'')}</td>
        <td style="color:var(--text3);font-size:12px">${new Date(h.checked_at+'Z').toLocaleString()}</td>
      </tr>`).join('')}</tbody>
    </table></div>`;
}
// ═══════════════════════════════════════════
// MONITOR MODAL (Add / Edit)
// ═══════════════════════════════════════════
function openAddMonitorModal() {
  document.getElementById('modal-monitor-title').textContent = 'Add Monitor';
  document.getElementById('m-id').value       = '';
  document.getElementById('m-name').value     = '';
  document.getElementById('m-url').value      = '';
  document.getElementById('m-type').value     = 'http';
  document.getElementById('m-interval').value = '60';
  document.getElementById('m-retries').value  = '3';
  document.getElementById('m-timeout').value  = '10';
  document.getElementById('m-codes').value    = '200-299';
  document.getElementById('m-keyword').value  = '';
  document.getElementById('m-desc').value     = '';
  document.getElementById('m-tags').value     = '';
  document.getElementById('m-group').value    = '';
  document.getElementById('m-notify').checked = false;
  onMonitorTypeChange();
  openModal('modal-monitor');
}

function openEditMonitorModal(id) {
  const m = allMonitors.find(x => x.id === id);
  if (!m) return;
  document.getElementById('modal-monitor-title').textContent = 'Edit Monitor';
  document.getElementById('m-id').value       = m.id;
  document.getElementById('m-name').value     = m.name;
  document.getElementById('m-url').value      = m.url;
  document.getElementById('m-type').value     = m.type || 'http';
  document.getElementById('m-interval').value = m.interval;
  document.getElementById('m-retries').value  = m.retries;
  document.getElementById('m-timeout').value  = m.timeout;
  document.getElementById('m-codes').value    = m.accepted_codes || '200-299';
  document.getElementById('m-keyword').value  = m.keyword || '';
  document.getElementById('m-desc').value     = m.description || '';
  document.getElementById('m-tags').value     = m.tags || '';
  document.getElementById('m-group').value    = m.group_name || '';
  document.getElementById('m-notify').checked = !!m.notify_email;
  const reqBody = document.getElementById('m-request-body');
  if (reqBody) reqBody.value = m.request_body || '';
  const reqHeaders = document.getElementById('m-request-headers');
  if (reqHeaders) reqHeaders.value = m.request_headers || '';
  onMonitorTypeChange();
  openModal('modal-monitor');
}

function onMonitorTypeChange() {
  const t = document.getElementById('m-type').value;
  const kwGrp      = document.getElementById('m-keyword-group');
  const codesGrp   = document.getElementById('m-codes-group');
  const postGrp    = document.getElementById('m-post-group');
  const headersGrp = document.getElementById('m-headers-group');
  const urlLbl     = document.getElementById('m-url-label');
  const urlHint    = document.getElementById('m-url-hint');

  kwGrp.style.display      = (t === 'keyword' || t === 'http-post') ? '' : 'none';
  codesGrp.style.display   = t === 'tcp' ? 'none' : '';
  postGrp.style.display    = t === 'http-post' ? '' : 'none';
  headersGrp.style.display = t === 'http-post' ? '' : 'none';

  if (t === 'tcp') {
    urlLbl.textContent  = 'Host:Port';
    urlHint.textContent = 'e.g. localhost:5432 or tcp://hostname:8080';
  } else if (t === 'http-post') {
    urlLbl.textContent  = 'URL';
    urlHint.textContent = 'Full URL including https:// — POST request will be sent';
  } else {
    urlLbl.textContent  = 'URL';
    urlHint.textContent = 'Full URL including https://';
  }
}

async function saveMonitor() {
  const id   = document.getElementById('m-id').value;
  const body = {
    name:            document.getElementById('m-name').value.trim(),
    url:             document.getElementById('m-url').value.trim(),
    type:            document.getElementById('m-type').value,
    interval:        parseInt(document.getElementById('m-interval').value),
    retries:         parseInt(document.getElementById('m-retries').value),
    timeout:         parseInt(document.getElementById('m-timeout').value),
    accepted_codes:  document.getElementById('m-codes').value.trim(),
    keyword:         document.getElementById('m-keyword').value.trim(),
    description:     document.getElementById('m-desc').value.trim(),
    tags:            document.getElementById('m-tags').value.trim(),
    group_name:      document.getElementById('m-group').value.trim(),
    notify_email:    document.getElementById('m-notify').checked ? 1 : 0,
    request_body:    document.getElementById('m-request-body')?.value.trim() || null,
    request_headers: document.getElementById('m-request-headers')?.value.trim() || null,
  };
  if (!body.name || !body.url) { toast('Name and URL are required','error'); return; }
  // Validate JSON body if http-post
  if (body.type === 'http-post' && body.request_body) {
    try { JSON.parse(body.request_body); } catch(e) {
      toast('Request Body must be valid JSON', 'error'); return;
    }
  }
  try {
    const method = id ? 'PUT' : 'POST';
    const url    = id ? `${API}/api/monitors/${id}` : `${API}/api/monitors`;
    const res    = await fetch(url, { method, headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!res.ok) { const e = await res.json(); toast(e.error||'Error saving monitor','error'); return; }
    closeModal('modal-monitor');
    toast(id ? 'Monitor updated' : 'Monitor added', 'success');
    refreshDashboard();
  } catch(e) { toast('Network error: '+e.message,'error'); }
}

async function toggleMonitor(id) {
  try {
    await fetch(`${API}/api/monitors/${id}/toggle`, { method:'POST' });
    toast('Monitor toggled','info');
    refreshDashboard();
  } catch(e) { toast('Error: '+e.message,'error'); }
}

// ═══════════════════════════════════════════
// DELETE CONFIRM
// ═══════════════════════════════════════════
let _confirmCb = null;
function confirmDelete(type, id, name) {
  const msgs = {
    monitor: `Delete monitor "${name}" and all its history? This cannot be undone.`,
    page:    `Delete status page "${name}"? Monitors will not be deleted.`,
  };
  document.getElementById('confirm-msg').textContent = msgs[type] || 'Are you sure?';
  _confirmCb = async () => {
    closeModal('modal-confirm');
    if (type === 'monitor') {
      await fetch(`${API}/api/monitors/${id}`, { method:'DELETE' });
      toast('Monitor deleted','success');
      if (selectedMid === id) { selectedMid = null; document.getElementById('dash-detail').innerHTML = '<div class="detail-panel" style="text-align:center;padding:48px 20px;color:var(--text3)"><div style="font-size:3rem;margin-bottom:12px">👈</div><p>Select a monitor to see details</p></div>'; }
      refreshDashboard();
    } else if (type === 'page') {
      await fetch(`${API}/api/status-pages/${id}`, { method:'DELETE' });
      toast('Status page deleted','success');
      loadStatusPages();
    }
  };
  document.getElementById('confirm-ok-btn').onclick = _confirmCb;
  openModal('modal-confirm');
}

// ═══════════════════════════════════════════
// STATUS PAGES
// ═══════════════════════════════════════════
let allPages = [];

async function loadStatusPages() {
  try {
    const res = await fetch(`${API}/api/status-pages`, {credentials:'include'});
    allPages  = await res.json();
    renderStatusPagesList(allPages);
  } catch(e) {
    document.getElementById('status-pages-list').innerHTML =
      `<div class="empty-state"><div class="icon">⚠️</div><p>${esc(e.message)}</p></div>`;
  }
}

function renderStatusPagesList(pages) {
  const el = document.getElementById('status-pages-list');
  if (!pages.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">📄</div><p>No status pages yet.</p><button class="btn btn-primary" onclick="openCreatePageModal()">＋ Create your first status page</button></div>`;
    return;
  }
  el.innerHTML = `
    <div class="card">
      <div class="card-header"><h3>Your Status Pages</h3></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Title</th><th>Slug / URL</th><th>Theme</th><th>Actions</th></tr></thead>
          <tbody>
            ${pages.map(p => `<tr>
              <td><strong>${esc(p.title)}</strong>${p.description?`<div style="font-size:11px;color:var(--text3)">${esc(p.description)}</div>`:''}</td>
              <td>
                <code style="background:var(--bg);padding:2px 6px;border-radius:4px;font-size:12px">/?page=${esc(p.slug)}</code>
                <button class="btn btn-secondary btn-sm" style="margin-left:6px" onclick="viewStatusPage('${esc(p.slug)}')"><svg width="13" height="13"><use href="#ic-eye"/></svg> View</button>
                <a class="btn btn-secondary btn-sm" href="/?page=${esc(p.slug)}" target="_blank" style="margin-left:4px" title="Open in new tab"><svg width="13" height="13"><use href="#ic-eye"/></svg> Share Link</a>
              </td>
              <td><span class="badge badge-paused">${esc(p.theme)}</span></td>
              <td style="display:flex;gap:6px;flex-wrap:wrap">
                <button class="btn btn-secondary btn-sm" onclick="openEditPageModal(${p.id})"><svg width="13" height="13"><use href="#ic-edit"/></svg> Edit</button>
                <button class="btn btn-danger btn-sm" onclick="confirmDelete('page',${p.id},'${esc(p.title)}')"><svg width="13" height="13"><use href="#ic-trash"/></svg> Delete</button>
              </td>
            </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
}

async function openCreatePageModal() {
  document.getElementById('modal-sp-title').textContent = 'New Status Page';
  document.getElementById('sp-id').value           = '';
  document.getElementById('sp-title-input').value  = '';
  document.getElementById('sp-slug').value         = '';
  document.getElementById('sp-desc-input').value   = '';
  document.getElementById('sp-theme').value        = 'dark';
  await renderPageMonitorCheckboxes([]);
  openModal('modal-status-page');
}

async function openEditPageModal(id) {
  const page = allPages.find(p => p.id === id);
  if (!page) return;
  document.getElementById('modal-sp-title').textContent = 'Edit Status Page';
  document.getElementById('sp-id').value           = page.id;
  document.getElementById('sp-title-input').value  = page.title;
  document.getElementById('sp-slug').value         = page.slug;
  document.getElementById('sp-desc-input').value   = page.description || '';
  document.getElementById('sp-theme').value        = page.theme || 'dark';
  // Load monitors already on this page
  const res      = await fetch(`${API}/api/status-pages/${id}/monitors`, {credentials:'include'});
  const assigned = await res.json();
  const assignedIds = assigned.map(m => m.id);
  await renderPageMonitorCheckboxes(assignedIds);
  openModal('modal-status-page');
}

async function renderPageMonitorCheckboxes(selectedIds) {
  const wrap   = document.getElementById('sp-monitor-checkboxes');
  const dbWrap = document.getElementById('sp-db-checkboxes');
  wrap.innerHTML   = '<div style="color:var(--text3);font-size:13px;padding:8px">Loading monitors...</div>';
  dbWrap.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:8px">Loading...</div>';

  // Load both monitors and DB monitors in parallel
  try {
    const [monRes, dbRes] = await Promise.all([
      fetch(`${API}/api/monitors`, {credentials:'include'}),
      fetch(`${API}/api/db-monitors`, {credentials:'include'})
    ]);
    const monitors   = monRes.ok  ? await monRes.json()  : [];
    const dbMonitors = dbRes.ok   ? await dbRes.json()   : [];

    if (monitors.length) allMonitors = monitors;

    // ── Service monitors ──
    if (!monitors.length) {
      wrap.innerHTML = '<div style="color:var(--text3);font-size:13px;padding:8px">No monitors found.</div>';
    } else {
      const groups = {};
      monitors.forEach(m => {
        const g = m.group_name || 'Ungrouped';
        if (!groups[g]) groups[g] = [];
        groups[g].push(m);
      });
      let html = '';
      Object.keys(groups).sort().forEach(g => {
        html += `<div style="font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;padding:8px 0 4px">${esc(g)}</div>`;
        groups[g].forEach(m => {
          const checked = selectedIds.includes(m.id) ? 'checked' : '';
          const st = m.enabled ? (m.current_status?.status === 1 ? 'up' : 'down') : 'paused';
          const dotColor = {up:'var(--green)',down:'var(--red)',paused:'var(--text3)'}[st];
          html += `<label class="form-check" style="padding:7px 6px;border-bottom:1px solid var(--border2);border-radius:4px;cursor:pointer">
            <input type="checkbox" value="${m.id}" ${checked}/>
            <span style="display:inline-flex;align-items:center;gap:6px;flex:1">
              <span style="width:8px;height:8px;border-radius:50%;background:${dotColor};flex-shrink:0;display:inline-block"></span>
              <strong>${esc(m.name)}</strong>
            </span>
            <span style="margin-left:auto;font-size:11px;color:var(--text3);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(m.url)}</span>
          </label>`;
        });
      });
      wrap.innerHTML = html;
    }

    // ── DB monitors ──
    if (!dbMonitors.length) {
      dbWrap.innerHTML = '<div style="color:var(--text3);font-size:12px;padding:8px">No database monitors yet. Add them from the Databases page.</div>';
    } else {
      const dbGroups = {};
      dbMonitors.forEach(d => {
        const g = d.group_name || 'General';
        if (!dbGroups[g]) dbGroups[g] = [];
        dbGroups[g].push(d);
      });
      const dbTypeIcon = t => t==='mssql'?'🗄️':t==='postgres'?'🐘':'🔌';
      let html = '';
      Object.keys(dbGroups).sort().forEach(g => {
        html += `<div style="font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;padding:8px 0 4px">${esc(g)}</div>`;
        dbGroups[g].forEach(d => {
          const last = d.last_check;
          const isDown = d.enabled && last?.status === 0;
          const dotColor = !d.enabled ? 'var(--text3)' : isDown ? 'var(--red)' : 'var(--green)';
          html += `<label class="form-check" style="padding:7px 6px;border-bottom:1px solid var(--border2);border-radius:4px;cursor:pointer">
            <input type="checkbox" data-db="1" value="${d.id}"/>
            <span style="display:inline-flex;align-items:center;gap:6px;flex:1">
              <span style="width:8px;height:8px;border-radius:50%;background:${dotColor};flex-shrink:0;display:inline-block"></span>
              <span>${dbTypeIcon(d.db_type)}</span>
              <strong>${esc(d.name)}</strong>
            </span>
            <span style="margin-left:auto;font-size:11px;color:var(--text3)">${esc(d.host)}:${d.port}</span>
          </label>`;
        });
      });
      dbWrap.innerHTML = html;
    }
  } catch(e) {
    wrap.innerHTML   = `<div style="color:var(--red);font-size:13px;padding:8px">Error: ${esc(e.message)}</div>`;
    dbWrap.innerHTML = '';
  }
}

async function saveStatusPage() {
  const id    = document.getElementById('sp-id').value;
  const title = document.getElementById('sp-title-input').value.trim();
  const slug  = document.getElementById('sp-slug').value.trim().toLowerCase().replace(/[^a-z0-9\-]/g,'-');
  const desc  = document.getElementById('sp-desc-input').value.trim();
  const theme = document.getElementById('sp-theme').value;
  if (!title || !slug) { toast('Title and slug are required','error'); return; }

  const checked   = [...document.querySelectorAll('#sp-monitor-checkboxes input:checked')].map(i => parseInt(i.value));
  const dbChecked = [...document.querySelectorAll('#sp-db-checkboxes input[data-db]:checked')].map(i => parseInt(i.value));

  try {
    let pageId = id;
    if (id) {
      await fetch(`${API}/api/status-pages/${id}`, {
        method:'PUT', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({title, description:desc, theme})
      });
    } else {
      const res = await fetch(`${API}/api/status-pages`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({slug, title, description:desc, theme})
      });
      if (!res.ok) { const e = await res.json(); toast(e.error||'Error','error'); return; }
      const created = await res.json();
      pageId = created.id;
    }

    // Sync monitors: remove all then re-add checked
    const curRes = await fetch(`${API}/api/status-pages/${pageId}/monitors`, {credentials:'include'});
    const curMons = await curRes.json();
    for (const m of curMons) {
      await fetch(`${API}/api/status-pages/${pageId}/monitors/${m.id}`, { method:'DELETE', credentials:'include' });
    }
    for (const mid of checked) {
      await fetch(`${API}/api/status-pages/${pageId}/monitors`, {
        method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
        body: JSON.stringify({monitor_id: mid})
      });
    }

    // For DB monitors — create/find a mirror TCP monitor and add it to the page
    if (dbChecked.length) {
      const dbRes  = await fetch(`${API}/api/db-monitors`, {credentials:'include'});
      const allDbs = await dbRes.json();
      const monRes = await fetch(`${API}/api/monitors`, {credentials:'include'});
      const allMons = await monRes.json();

      for (const dbId of dbChecked) {
        const db = allDbs.find(d => d.id === dbId);
        if (!db) continue;

        // Check if a mirror monitor already exists (tagged as database)
        const tcpUrl = `tcp://${db.host}:${db.port}`;
        let mirror = allMons.find(m => m.url === tcpUrl && m.name === db.name);

        if (!mirror) {
          // Create the mirror TCP monitor
          const dbTypeLabel = {mssql:'SQL Server', postgres:'PostgreSQL'}[db.db_type] || 'Database';
          const cr = await fetch(`${API}/api/monitors`, {
            method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
            body: JSON.stringify({
              name: db.name, url: tcpUrl, type: 'tcp',
              interval: db.interval, group_name: db.group_name || '',
              description: `[DB] ${dbTypeLabel} — ${db.database || db.host}`,
              tags: 'database'
            })
          });
          if (cr.ok) mirror = await cr.json();
        }

        if (mirror) {
          await fetch(`${API}/api/status-pages/${pageId}/monitors`, {
            method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
            body: JSON.stringify({monitor_id: mirror.id})
          });
        }
      }
    }

    closeModal('modal-status-page');
    toast(id ? 'Status page updated' : 'Status page created', 'success');
    loadStatusPages();
  } catch(e) { toast('Error: '+e.message,'error'); }
}

// ═══════════════════════════════════════════
// STATUS PAGE PUBLIC VIEW
// ═══════════════════════════════════════════
async function viewStatusPage(slug) {
  currentSlug = slug;
  // Reset state
  spFrom = null; spTo = null; spPreset = '24h';
  document.getElementById('sp-from').value = '';
  document.getElementById('sp-to').value   = '';
  const clearBtn = document.getElementById('sp-clear-btn');
  if (clearBtn) clearBtn.style.display = 'none';
  // Hide custom service filter bar
  const csBar = document.getElementById('sp-custom-service-bar');
  if (csBar) { csBar.style.display = 'none'; }
  const csSel = document.getElementById('sp-custom-service');
  if (csSel) csSel.value = 'all';
  // Reset timeframe buttons to 24h
  document.querySelectorAll('#sp-tf-presets .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.p === '24h'));
  // Reset detail dropdown
  const detSel = document.getElementById('sp-detail-select');
  if (detSel) detSel.value = '';
  const detBody = document.getElementById('sp-detail-body');
  if (detBody) detBody.innerHTML = '<div style="text-align:center;padding:32px;color:var(--text3)"><svg style="width:40px;height:40px;margin:0 auto 12px;display:block;opacity:.3"><use href="#ic-select"/></svg><p style="font-size:13px">Select a service above to view its response time chart and outage history</p></div>';
  // Show status page view — make it full width
  const appShell = document.getElementById('app-shell');
  appShell.style.display = 'none';
  const spView = document.getElementById('status-page-view');
  spView.style.position = 'fixed';
  spView.style.inset = '0';
  spView.style.overflowY = 'auto';
  spView.style.zIndex = '200';
  spView.style.display = 'block';
  spView.classList.add('open');
  await loadStatusPageView(slug);
}

function closeStatusPageView() {
  const spView = document.getElementById('status-page-view');
  spView.classList.remove('open');
  spView.style.display = 'none';
  spView.style.position = '';
  spView.style.inset = '';
  spView.style.overflowY = '';
  spView.style.zIndex = '';
  document.getElementById('app-shell').style.display = 'flex';
  currentSlug = null;
}

async function loadStatusPageView(slug) {
  if (!slug) return;
  const el = document.getElementById('sp-monitors');
  el.innerHTML = '<div class="loading-center"><div class="spinner"></div> Loading...</div>';
  try {
    const res  = await fetch(`${API}/api/status-pages/slug/${slug}${spQS()}`, {credentials:'include'});
    if (!res.ok) { el.innerHTML = '<div class="empty-state"><svg class="es-icon" style="width:48px;height:48px;margin:0 auto 16px;display:block;opacity:.3"><use href="#ic-alert"/></svg><p>Status page not found.</p></div>'; return; }
    const data = await res.json();
    const page = data.page;
    const mons = data.monitors;

    document.getElementById('sp-title').textContent = page.title;
    document.getElementById('sp-desc').textContent  = page.description || '';

    // Cache monitors for client-side filtering
    spLastMonitors = mons;

    renderSpMonitors(mons);
  } catch(e) {
    document.getElementById('sp-monitors').innerHTML =
      `<div class="empty-state"><p style="color:var(--red)">${esc(e.message)}</p></div>`;
  }
}

function renderSpMonitors(mons) {
  const el = document.getElementById('sp-monitors');

  // Overall status banner
  const allUp = mons.length > 0 && mons.every(m => !m.enabled || m.current_status?.status === 1);
  const overall = document.getElementById('sp-overall');
  overall.className = 'sp-overall ' + (allUp ? 'all-up' : 'has-down');
  overall.innerHTML = allUp
    ? '<svg width="14" height="14"><use href="#ic-check-circle"/></svg> All Systems Operational'
    : '<svg width="14" height="14"><use href="#ic-alert"/></svg> Some Systems Are Experiencing Issues';

  if (!mons.length) {
    el.innerHTML = '<div class="empty-state"><svg style="width:48px;height:48px;margin:0 auto 16px;display:block;opacity:.3"><use href="#ic-monitor"/></svg><p>No monitors on this page yet.</p></div>';
    document.getElementById('sp-detail-panel').style.display = 'none';
    return;
  }

  // Tile grid — group monitors by group_name, render as tiles
  // Group monitors
  const groups = {};
  mons.forEach(m => {
    const g = m.group_name && m.group_name.trim() ? m.group_name.trim() : 'General';
    if (!groups[g]) groups[g] = [];
    groups[g].push(m);
  });
  const groupNames = Object.keys(groups).sort((a,b) => {
    if (a==='General') return 1; if (b==='General') return -1;
    return a.localeCompare(b);
  });

  el.innerHTML = groupNames.map(groupName => {
    const gMons   = groups[groupName];
    const gUp     = gMons.filter(m => m.current_status?.status === 1 && m.enabled).length;
    const gDown   = gMons.filter(m => m.current_status?.status === 0 && m.enabled).length;
    const gColor  = gDown > 0 ? 'var(--red)' : 'var(--green)';

    const tiles = gMons.map(m => {
      const st      = !m.enabled ? 'paused' : m.current_status ? (m.current_status.status ? 'up' : 'down') : 'pending';
      const upPct   = m.uptime_pct !== null ? m.uptime_pct.toFixed(2)+'%' : '-';
      const lat     = m.avg_latency !== null ? m.avg_latency+'ms' : '-';
      const bars    = renderHBBars(m.timeline, m.from_dt, m.to_dt);

      // Tile border colour by status
      const borderColor = {up:'var(--green)',down:'var(--red)',paused:'var(--border)',pending:'var(--yellow)'}[st];
      const dotColor    = {up:'var(--green)',down:'var(--red)',paused:'var(--text3)',pending:'var(--yellow)'}[st];
      const stLabel     = {up:'Operational',down:'Disruption',paused:'Paused',pending:'Pending'}[st];
      const stBg        = {up:'var(--green-dim)',down:'var(--red-dim)',paused:'var(--surface2)',pending:'var(--yellow-dim)'}[st];
      const stTxt       = {up:'var(--green)',down:'var(--red)',paused:'var(--text3)',pending:'var(--yellow)'}[st];
      const upColor     = m.uptime_pct >= 99 ? 'var(--green)' : m.uptime_pct >= 90 ? 'var(--blue)' : 'var(--red)';

      return `<div class="sp-tile" style="border-top:3px solid ${borderColor}">
        <div class="sp-tile-header">
          <span style="width:9px;height:9px;border-radius:50%;background:${dotColor};flex-shrink:0;display:inline-block"></span>
          <span class="sp-tile-name" title="${esc(m.name)}">${esc(m.name)}</span>
          <span class="sp-tile-badge" style="background:${stBg};color:${stTxt}">${stLabel}</span>
        </div>
        <div class="sp-tile-stats">
          <div class="sp-tile-stat">
            <div class="sp-tile-val" style="color:${upColor}">${upPct}</div>
            <div class="sp-tile-lbl">Uptime</div>
          </div>
          <div class="sp-tile-stat">
            <div class="sp-tile-val" style="color:var(--blue)">${lat}</div>
            <div class="sp-tile-lbl">Latency</div>
          </div>
          <div class="sp-tile-stat">
            <div class="sp-tile-val">${m.total_checks||0}</div>
            <div class="sp-tile-lbl">Checks</div>
          </div>
        </div>
        <div class="sp-tile-bars" style="margin-top:auto;padding:0 2px 6px 2px">${bars}</div>
      </div>`;
    }).join('');

    return `<div class="sp-group">
      <div class="sp-group-header">
        <span class="sp-group-name">${esc(groupName)}</span>
        <span style="font-size:12px;font-weight:600;color:${gColor}">${gUp} up${gDown > 0 ? ' &middot; <span style="color:var(--red)">'+gDown+' down</span>' : ''}</span>
        <span style="font-size:11px;color:var(--text3);margin-left:auto">${gMons.length} service${gMons.length!==1?'s':''}</span>
      </div>
      <div class="sp-tile-grid">${tiles}</div>
    </div>`;
  }).join('');

  // Populate detail dropdown
  const sel = document.getElementById('sp-detail-select');
  const prevVal = sel.value;
  sel.innerHTML = '<option value="">-- Select a service --</option>';
  mons.forEach(m => {
    const opt = document.createElement('option');
    opt.value = String(m.id);
    opt.textContent = m.name;
    sel.appendChild(opt);
  });
  if (prevVal && [...sel.options].some(o => o.value === prevVal)) {
    sel.value = prevVal;
  }

  // Show detail panel
  document.getElementById('sp-detail-panel').style.display = '';

  // Reload charts if service already selected
  if (sel.value) { spDetailChanged(); }

  updateSpFilterBadge();
}

async function spDetailChanged() {
  const sel  = document.getElementById('sp-detail-select');
  const mid  = sel.value;
  const body = document.getElementById('sp-detail-body');
  if (!mid) {
    body.innerHTML = '<div style="text-align:center;padding:32px;color:var(--text3)"><svg style="width:40px;height:40px;margin:0 auto 12px;display:block;opacity:.3"><use href="#ic-select"/></svg><p style="font-size:13px">Select a service above to view its response time chart and outage history</p></div>';
    return;
  }
  const mon     = spLastMonitors.find(m => String(m.id) === mid);
  const monName = mon ? mon.name : 'Service';
  const st      = mon ? (!mon.enabled ? 'paused' : mon.current_status?.status === 1 ? 'up' : 'down') : 'pending';
  const badgeCls = {up:'badge-up',down:'badge-down',paused:'badge-paused',pending:'badge-pending'}[st];
  const badgeTxt = {up:'Operational',down:'Disruption',paused:'Paused',pending:'Pending'}[st];
  body.innerHTML = `
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:16px">
      <div>
        <div style="font-size:15px;font-weight:700;color:var(--text)">${esc(monName)}</div>
        <div style="font-size:11px;color:var(--text3)">${mon ? esc(mon.url) : ''}</div>
      </div>
      <div id="sp-detail-stats" style="display:flex;gap:16px;flex-wrap:wrap">
        <div class="mc-stat"><div class="val" id="sp-detail-uptime">–</div><div class="lbl">Uptime</div></div>
        <div class="mc-stat"><div class="val val-blue" id="sp-detail-latency">–</div><div class="lbl">Avg Latency</div></div>
        <div class="mc-stat"><div class="val" id="sp-detail-checks">–</div><div class="lbl">Checks</div></div>
        <span class="badge ${badgeCls}" style="align-self:center">${badgeTxt}</span>
      </div>
    </div>
    <div id="charts-${mid}"><div class="loading-center" style="padding:20px"><div class="spinner"></div></div></div>`;
  await loadMonitorCharts(parseInt(mid));
}

// ═══════════════════════════════════════════
// CHARTS — Response Time + Outage Timeline
// ═══════════════════════════════════════════

async function loadMonitorCharts(mid) {
  const wrap = document.getElementById('charts-' + mid);
  if (!wrap) return;
  try {
    const qs  = chartQS().replace('?', '&');
    const res = await fetch(`${API}/api/monitors/${mid}/heartbeats?limit=5000${qs}`, {credentials:'include'});
    const hbs = await res.json();
    if (!hbs.length) { wrap.innerHTML = '<div style="color:var(--text3);font-size:12px;padding:8px 0">No data for selected period.</div>'; return; }

    // Calculate stats from the chart timeframe heartbeats (so stats match the chart)
    const totalChecks = hbs.length;
    const upChecks    = hbs.filter(h => h.status === 1).length;
    const chartUpPct  = totalChecks > 0 ? (upChecks / totalChecks * 100).toFixed(2) : null;
    const latencies   = hbs.map(h => h.latency_ms).filter(v => v != null);
    const chartAvgLat = latencies.length ? Math.round(latencies.reduce((a,b)=>a+b,0)/latencies.length) : null;

    // Update the detail stats to reflect chart timeframe
    const upEl  = document.getElementById('sp-detail-uptime');
    const latEl = document.getElementById('sp-detail-latency');
    const chkEl = document.getElementById('sp-detail-checks');
    if (upEl) {
      upEl.textContent = chartUpPct !== null ? chartUpPct + '%' : '–';
      upEl.className = 'val ' + (chartUpPct >= 99 ? 'val-green' : chartUpPct >= 90 ? 'val-blue' : 'val-red');
    }
    if (latEl) latEl.textContent = chartAvgLat !== null ? chartAvgLat + 'ms' : '–';
    if (chkEl) chkEl.textContent = totalChecks;

    // Build outage incidents from heartbeat sequence
    const incidents = buildIncidents(hbs);

    wrap.innerHTML = `
      <div style="margin-top:16px">
        <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">
          Response Time (ms)
        </div>
        <div style="position:relative">
          <canvas id="chart-latency-${mid}" height="90" style="width:100%;display:block;border-radius:6px"></canvas>
        </div>
      </div>
      <div style="margin-top:20px">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
          <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.06em">
            Outage Timeline
          </div>
          <div style="display:flex;align-items:center;gap:12px;font-size:11px;color:var(--text3)">
            <span style="display:flex;align-items:center;gap:4px">
              <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#1a9e5c"></span> Up
            </span>
            <span style="display:flex;align-items:center;gap:4px">
              <span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#e53e3e"></span> Down
            </span>
          </div>
        </div>
        <canvas id="chart-outage-${mid}" height="36" style="width:100%;display:block;border-radius:6px"></canvas>
        <div id="incidents-${mid}" style="margin-top:10px"></div>
      </div>`;

    // Draw after DOM update
    requestAnimationFrame(() => {
      drawLatencyChart(mid, hbs);
      drawOutageChart(mid, hbs);
      renderIncidentList(mid, incidents);
    });
  } catch(e) {
    wrap.innerHTML = `<div style="color:var(--red);font-size:12px;padding:8px 0">Chart error: ${esc(e.message)}</div>`;
  }
}

function buildIncidents(hbs) {
  // hbs is sorted ASC by checked_at
  const incidents = [];
  let outageStart = null;
  for (let i = 0; i < hbs.length; i++) {
    const h = hbs[i];
    if (h.status === 0 && outageStart === null) {
      outageStart = h.checked_at;
    } else if (h.status === 1 && outageStart !== null) {
      const start = new Date(outageStart + 'Z');
      const end   = new Date(h.checked_at + 'Z');
      const dur   = Math.round((end - start) / 1000);
      incidents.push({ start: outageStart, end: h.checked_at, duration_sec: dur });
      outageStart = null;
    }
  }
  // Still down at end of period
  if (outageStart !== null) {
    const start = new Date(outageStart + 'Z');
    const end   = new Date(hbs[hbs.length-1].checked_at + 'Z');
    const dur   = Math.round((end - start) / 1000);
    incidents.push({ start: outageStart, end: null, duration_sec: dur });
  }
  return incidents;
}

function formatDuration(sec) {
  if (sec < 60)   return sec + 's';
  if (sec < 3600) return Math.round(sec/60) + 'm';
  return (sec/3600).toFixed(1) + 'h';
}

function drawLatencyChart(mid, hbs) {
  const canvas = document.getElementById('chart-latency-' + mid);
  if (!canvas) return;
  canvas.width  = canvas.offsetWidth || canvas.parentElement.offsetWidth || 800;
  canvas.height = 90;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const PAD = { top:10, right:10, bottom:22, left:42 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top  - PAD.bottom;

  // Filter to points with latency
  const pts = hbs.filter(h => h.latency_ms !== null && h.status === 1);
  if (pts.length < 2) { ctx.fillStyle='#8a94a6'; ctx.font='12px sans-serif'; ctx.fillText('Not enough data', PAD.left+4, H/2); return; }

  const times    = pts.map(h => new Date(h.checked_at+'Z').getTime());
  const latencies = pts.map(h => h.latency_ms);
  const tMin = times[0], tMax = times[times.length-1];
  const lMin = Math.max(0, Math.min(...latencies) * 0.85);
  const lMax = Math.max(...latencies) * 1.1;
  const tRange = tMax - tMin || 1;
  const lRange = lMax - lMin || 1;

  const tx = t => PAD.left + ((t - tMin) / tRange) * cW;
  const ty = l => PAD.top  + cH - ((l - lMin) / lRange) * cH;

  // Background
  ctx.fillStyle = '#f8fffe';
  ctx.fillRect(0, 0, W, H);

  // Grid lines
  ctx.strokeStyle = '#dde1e7'; ctx.lineWidth = 1;
  const gridLines = 4;
  for (let i = 0; i <= gridLines; i++) {
    const y = PAD.top + (cH / gridLines) * i;
    ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(W - PAD.right, y); ctx.stroke();
    const val = Math.round(lMax - (lRange / gridLines) * i);
    ctx.fillStyle = '#8a94a6'; ctx.font = '10px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(val + 'ms', PAD.left - 4, y + 3);
  }

  // DOWN periods as red background bands
  hbs.forEach((h, i) => {
    if (h.status === 0) {
      const t1 = new Date(h.checked_at+'Z').getTime();
      const t2 = i+1 < hbs.length ? new Date(hbs[i+1].checked_at+'Z').getTime() : t1 + 60000;
      ctx.fillStyle = 'rgba(229,62,62,.12)';
      ctx.fillRect(tx(t1), PAD.top, tx(t2)-tx(t1), cH);
    }
  });

  // Fill area under line
  ctx.beginPath();
  ctx.moveTo(tx(times[0]), ty(latencies[0]));
  pts.forEach((p, i) => ctx.lineTo(tx(times[i]), ty(latencies[i])));
  ctx.lineTo(tx(times[times.length-1]), PAD.top + cH);
  ctx.lineTo(tx(times[0]), PAD.top + cH);
  ctx.closePath();
  ctx.fillStyle = 'rgba(0,169,157,.12)';
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.strokeStyle = '#00a99d'; ctx.lineWidth = 2; ctx.lineJoin = 'round';
  pts.forEach((p, i) => i === 0 ? ctx.moveTo(tx(times[i]), ty(latencies[i])) : ctx.lineTo(tx(times[i]), ty(latencies[i])));
  ctx.stroke();

  // X-axis time labels
  ctx.fillStyle = '#8a94a6'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
  const labelCount = Math.min(6, pts.length);
  for (let i = 0; i < labelCount; i++) {
    const idx = Math.round((pts.length - 1) * i / (labelCount - 1));
    const x   = tx(times[idx]);
    const lbl = new Date(times[idx]).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    ctx.fillText(lbl, x, H - 4);
  }
}

function drawOutageChart(mid, hbs) {
  const canvas = document.getElementById('chart-outage-' + mid);
  if (!canvas) return;
  canvas.width  = canvas.offsetWidth || canvas.parentElement.offsetWidth || 800;
  canvas.height = 36;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const PAD = { top:2, right:10, bottom:18, left:42 };
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top  - PAD.bottom;

  if (!hbs.length) return;
  const times = hbs.map(h => new Date(h.checked_at+'Z').getTime());
  const tMin  = times[0], tMax = times[times.length-1];
  const tRange = tMax - tMin || 1;
  const tx = t => PAD.left + ((t - tMin) / tRange) * cW;

  // Background
  ctx.fillStyle = '#f8fffe';
  ctx.fillRect(0, 0, W, H);

  // Draw each heartbeat as a coloured segment
  hbs.forEach((h, i) => {
    const t1 = times[i];
    const t2 = i+1 < hbs.length ? times[i+1] : t1 + 60000;
    const x1 = tx(t1), x2 = tx(t2);
    ctx.fillStyle = h.status === 1 ? '#1a9e5c' : '#e53e3e';
    ctx.fillRect(x1, PAD.top, Math.max(x2-x1-1, 2), cH);
  });

  // Border
  ctx.strokeStyle = '#dde1e7'; ctx.lineWidth = 1;
  ctx.strokeRect(PAD.left, PAD.top, cW, cH);

  // X-axis labels
  ctx.fillStyle = '#8a94a6'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
  const labelCount = Math.min(6, hbs.length);
  for (let i = 0; i < labelCount; i++) {
    const idx = Math.round((hbs.length - 1) * i / (labelCount - 1));
    const x   = tx(times[idx]);
    const lbl = new Date(times[idx]).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
    ctx.fillText(lbl, x, H - 2);
  }

}

function renderIncidentList(mid, incidents) {
  const wrap = document.getElementById('incidents-' + mid);
  if (!wrap) return;
  if (!incidents.length) {
    wrap.innerHTML = '<div style="font-size:12px;color:var(--green);font-weight:600">No outages in this period.</div>';
    return;
  }
  wrap.innerHTML = `
    <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">
      Outages (${incidents.length})
    </div>
    <div style="border:1px solid var(--border);border-radius:6px;overflow:hidden">
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead>
          <tr style="background:var(--surface2)">
            <th style="padding:7px 12px;text-align:left;font-weight:700;color:var(--text3);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border)">Started</th>
            <th style="padding:7px 12px;text-align:left;font-weight:700;color:var(--text3);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border)">Recovered</th>
            <th style="padding:7px 12px;text-align:left;font-weight:700;color:var(--text3);font-size:10px;text-transform:uppercase;border-bottom:1px solid var(--border)">Duration</th>
          </tr>
        </thead>
        <tbody>
          ${incidents.map((inc, i) => `
            <tr style="${i%2===0?'background:var(--surface)':'background:var(--surface2)'}">
              <td style="padding:7px 12px;color:var(--red);font-weight:600">${new Date(inc.start+'Z').toLocaleString()}</td>
              <td style="padding:7px 12px;color:${inc.end?'var(--green)':'var(--yellow)'};font-weight:600">${inc.end ? new Date(inc.end+'Z').toLocaleString() : 'Still down'}</td>
              <td style="padding:7px 12px;color:var(--text2)">${formatDuration(inc.duration_sec)}</td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
}

// ═══════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════
async function loadSettings() {
  try {
    const res  = await fetch(`${API}/api/settings`, {credentials:'include'});
    const data = await res.json();
    document.getElementById('s-smtp-host').value = data.smtp_host || '';
    document.getElementById('s-smtp-port').value = data.smtp_port || '25';
    document.getElementById('s-smtp-from').value = data.smtp_from || '';
    document.getElementById('s-smtp-to').value   = data.smtp_to   || '';
    document.getElementById('s-smtp-user').value = data.smtp_user || '';
    // Notification groups
    const el = (id) => document.getElementById(id);
    if (el('s-smtp-to-monitors')) el('s-smtp-to-monitors').value = data.smtp_to_monitors || '';
    if (el('s-smtp-to-servers'))  el('s-smtp-to-servers').value  = data.smtp_to_servers  || '';
    if (el('s-smtp-to-software')) el('s-smtp-to-software').value = data.smtp_to_software || '';
    if (el('s-smtp-to-patches'))  el('s-smtp-to-patches').value  = data.smtp_to_patches  || '';
  } catch(e) {}
}

async function saveSettings() {
  const body = {
    smtp_host: document.getElementById('s-smtp-host').value.trim(),
    smtp_port: document.getElementById('s-smtp-port').value.trim(),
    smtp_from: document.getElementById('s-smtp-from').value.trim(),
    smtp_to:   document.getElementById('s-smtp-to').value.trim(),
    smtp_user: document.getElementById('s-smtp-user').value.trim(),
    smtp_pass: document.getElementById('s-smtp-pass').value,
    smtp_to_monitors: (document.getElementById('s-smtp-to-monitors')?.value || '').trim(),
    smtp_to_servers:  (document.getElementById('s-smtp-to-servers')?.value || '').trim(),
    smtp_to_software: (document.getElementById('s-smtp-to-software')?.value || '').trim(),
    smtp_to_patches:  (document.getElementById('s-smtp-to-patches')?.value || '').trim(),
  };
  try {
    await fetch(`${API}/api/settings`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const msg = document.getElementById('settings-msg');
    msg.style.color = 'var(--green)';
    msg.textContent = 'Settings saved successfully.';
    setTimeout(() => msg.textContent = '', 3000);
    toast('Settings saved','success');
  } catch(e) { toast('Error saving settings','error'); }
}

async function testEmail() {
  const body = {
    smtp_host: document.getElementById('s-smtp-host').value.trim(),
    smtp_port: parseInt(document.getElementById('s-smtp-port').value) || 25,
    smtp_from: document.getElementById('s-smtp-from').value.trim(),
    smtp_to:   document.getElementById('s-smtp-to').value.trim(),
  };
  const msg = document.getElementById('settings-msg');
  msg.style.color = 'var(--text3)';
  msg.textContent = 'Sending test email...';
  try {
    const res  = await fetch(`${API}/api/settings/test-email`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const data = await res.json();
    if (data.ok) { msg.style.color='var(--green)'; msg.textContent='Test email sent: '+data.message; toast('Test email sent','success'); }
    else         { msg.style.color='var(--red)';   msg.textContent='Failed: '+data.message; toast('Email failed','error'); }
  } catch(e) { msg.style.color='var(--red)'; msg.textContent='❌ '+e.message; }
}

// ═══════════════════════════════════════════
// EXPORT / IMPORT
// ═══════════════════════════════════════════
function onImportFileSelected() {
  const fileInput = document.getElementById('import-file');
  const fname = document.getElementById('import-filename');
  const btn = document.getElementById('btn-import');
  if (fileInput.files.length > 0) {
    fname.textContent = fileInput.files[0].name;
    btn.disabled = false;
  } else {
    fname.textContent = '';
    btn.disabled = true;
  }
}

async function doExportBackup() {
  const btn = document.getElementById('btn-export');
  const btnImport = document.getElementById('btn-import');
  const msg = document.getElementById('export-msg');
  btn.disabled = true;
  if (btnImport) btnImport.disabled = true;
  msg.style.color = 'var(--text3)';
  msg.textContent = 'Exporting...';
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    const res = await fetch(`${API}/api/export`, {credentials:'include', signal: controller.signal});
    clearTimeout(timeoutId);
    if (!res.ok) {
      const err = await res.json();
      msg.style.color = 'var(--red)';
      msg.textContent = err.error || 'Export failed';
      toast(err.error || 'Export failed', 'error');
      return;
    }
    // Trigger download
    const blob = await res.blob();
    const disposition = res.headers.get('Content-Disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
    const filename = filenameMatch ? filenameMatch[1] : 'croit-monitor-backup.json';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    msg.style.color = 'var(--green)';
    msg.textContent = 'Export complete!';
    toast('Backup exported successfully', 'success');
    setTimeout(() => msg.textContent = '', 5000);
  } catch(e) {
    msg.style.color = 'var(--red)';
    if (e.name === 'AbortError') {
      msg.textContent = 'Request timed out. Please try again.';
      toast('Export timed out', 'error');
    } else {
      msg.textContent = 'Could not connect to server. Please check your connection.';
      toast('Export failed: ' + e.message, 'error');
    }
  } finally {
    btn.disabled = false;
    if (btnImport && document.getElementById('import-file').files.length > 0) btnImport.disabled = false;
  }
}

async function doImportBackup() {
  const fileInput = document.getElementById('import-file');
  const btn = document.getElementById('btn-import');
  const btnExport = document.getElementById('btn-export');
  const msg = document.getElementById('import-msg');
  if (!fileInput.files.length) { toast('Select a file first', 'error'); return; }

  const mode = document.querySelector('input[name="import-mode"]:checked')?.value || 'clean';

  // Confirm before clean import
  if (mode === 'clean') {
    if (!confirm('⚠️ Clean Restore will DELETE all existing monitors, settings, and configuration (users are preserved). Continue?')) return;
  }

  btn.disabled = true;
  btnExport.disabled = true;
  msg.style.color = 'var(--text3)';
  msg.textContent = 'Importing...';

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  formData.append('mode', mode);

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    const res = await fetch(`${API}/api/import`, {method:'POST', credentials:'include', body: formData, signal: controller.signal});
    clearTimeout(timeoutId);
    const data = await res.json();
    if (!res.ok) {
      msg.style.color = 'var(--red)';
      msg.textContent = data.error || 'Import failed';
      toast(data.error || 'Import failed', 'error');
      return;
    }
    // Success — show summary
    const s = data.summary;
    const parts = [];
    for (const [cat, counts] of Object.entries(s)) {
      if (counts.inserted > 0) parts.push(`${cat}: ${counts.inserted}`);
    }
    const summaryText = parts.length ? parts.join(', ') : 'No records imported';
    msg.style.color = 'var(--green)';
    msg.textContent = `✓ Import complete (${mode}) — ${summaryText}`;
    toast(`Import successful! ${summaryText}`, 'success');
    setTimeout(() => msg.textContent = '', 8000);
    // Reset file input
    fileInput.value = '';
    document.getElementById('import-filename').textContent = '';
  } catch(e) {
    msg.style.color = 'var(--red)';
    if (e.name === 'AbortError') {
      msg.textContent = 'Request timed out. Please try again.';
      toast('Import timed out', 'error');
    } else {
      msg.textContent = 'Could not connect to server. Please check your connection.';
      toast('Import failed: ' + e.message, 'error');
    }
  } finally {
    btn.disabled = !fileInput.files.length;
    btnExport.disabled = false;
  }
}

// ═══════════════════════════════════════════
// SSL CERTIFICATES
// ═══════════════════════════════════════════
async function loadSSLPage() {
  const fullTable = document.getElementById('ssl-full-table');
  if (!fullTable) return;
  fullTable.innerHTML = '<div class="loading-center" style="padding:32px"><div class="spinner"></div> Checking certificates...</div>';

  try {
    const res  = await fetch(`${API}/api/ssl`, {credentials:'include'});
    const data = await res.json();

    // Update summary cards
    const ok   = data.filter(s => s.days_left !== null && s.days_left > 30).length;
    const warn = data.filter(s => s.days_left !== null && s.days_left > 7 && s.days_left <= 30).length;
    const crit = data.filter(s => s.days_left !== null && s.days_left <= 7).length;
    const err  = data.filter(s => s.days_left === null || s.days_left < 0).length;
    document.getElementById('ssl-ok').textContent    = ok;
    document.getElementById('ssl-warn').textContent  = warn + err;
    document.getElementById('ssl-crit').textContent  = crit;
    document.getElementById('ssl-total').textContent = data.length;

    // Update last check time
    const lastCheck = data.find(s => s.last_checked);
    if (lastCheck) {
      document.getElementById('ssl-last-check').textContent =
        'Last checked: ' + new Date(lastCheck.last_checked + 'Z').toLocaleString();
    }

    if (!data.length) {
      fullTable.innerHTML = '<div style="padding:24px;color:var(--text3);text-align:center">No HTTPS monitors found. Add HTTPS monitors to see SSL data.</div>';
      return;
    }

    fullTable.innerHTML = `
      <table style="width:100%;border-collapse:collapse">
        <thead>
          <tr>
            <th style="padding:12px 16px;text-align:left;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;border-bottom:2px solid var(--border);background:var(--surface2)">Monitor</th>
            <th style="padding:12px 16px;text-align:left;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;border-bottom:2px solid var(--border);background:var(--surface2);white-space:nowrap">Days Left</th>
            <th style="padding:12px 16px;text-align:left;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;border-bottom:2px solid var(--border);background:var(--surface2);white-space:nowrap">Expiry Date</th>
            <th style="padding:12px 16px;text-align:left;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;border-bottom:2px solid var(--border);background:var(--surface2)">Issuer</th>
            <th style="padding:12px 16px;text-align:left;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;border-bottom:2px solid var(--border);background:var(--surface2);white-space:nowrap">Last Checked</th>
          </tr>
        </thead>
        <tbody>
          ${data.map((s, i) => {
            const days  = s.days_left;
            const color = days === null || days < 0 ? 'var(--red)' : days <= 7 ? 'var(--red)' : days <= 30 ? 'var(--yellow)' : 'var(--green)';
            const bg    = i % 2 === 0 ? 'var(--surface)' : 'var(--surface2)';
            const icon  = days === null || days < 0 ? '🚨' : days <= 7 ? '🚨' : days <= 30 ? '⚠️' : '✅';
            const daysStr = days !== null && days >= 0 ? `${days} days` : days !== null ? 'Expired' : 'Error';
            return `<tr style="background:${bg}">
              <td style="padding:12px 16px;border-bottom:1px solid var(--border2)">
                <div style="font-weight:600;color:var(--text)">${esc(s.name)}</div>
                <div style="font-size:11px;color:var(--text3);margin-top:2px;word-break:break-all">${esc(s.url||'')}</div>
              </td>
              <td style="padding:12px 16px;border-bottom:1px solid var(--border2);white-space:nowrap">
                <span style="font-size:16px;font-weight:700;color:${color}">${icon} ${daysStr}</span>
              </td>
              <td style="padding:12px 16px;border-bottom:1px solid var(--border2);white-space:nowrap;color:var(--text2)">${s.expiry_date || '–'}</td>
              <td style="padding:12px 16px;border-bottom:1px solid var(--border2);color:var(--text2);font-size:13px">${esc(s.issuer||'–')}</td>
              <td style="padding:12px 16px;border-bottom:1px solid var(--border2);white-space:nowrap;color:var(--text3);font-size:12px">${s.last_checked ? new Date(s.last_checked+'Z').toLocaleString() : '–'}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>`;
  } catch(e) {
    fullTable.innerHTML = `<div style="padding:24px;color:var(--red);font-size:13px">Error loading SSL data: ${esc(e.message)}</div>`;
  }
}

async function loadSSL() { loadSSLPage(); }  // alias for settings page compat

async function refreshSSL() {
  toast('Refreshing SSL certificates...', 'info');
  try {
    await fetch(`${API}/api/ssl/refresh`, {method:'POST', credentials:'include'});
    setTimeout(() => { loadSSLPage(); toast('SSL refresh complete', 'success'); }, 8000);
  } catch(e) { toast('Error: '+e.message, 'error'); }
}

// ═══════════════════════════════════════════
// MAINTENANCE WINDOWS
// ═══════════════════════════════════════════
async function loadMaintenance() {
  const wrap = document.getElementById('maintenance-table-wrap');
  if (!wrap) return;
  try {
    const res  = await fetch(`${API}/api/maintenance`, {credentials:'include'});
    const data = await res.json();
    if (!data.length) {
      wrap.innerHTML = '<div style="padding:16px;color:var(--text3);font-size:13px">No maintenance windows scheduled.</div>';
      return;
    }
    const now = new Date();
    wrap.innerHTML = `<table>
      <thead><tr><th>Title</th><th>Monitor</th><th>Start</th><th>End</th><th>Repeat</th><th>Status</th><th></th></tr></thead>
      <tbody>${data.map(w => {
        const start  = new Date(w.start_dt+'Z');
        const end    = new Date(w.end_dt+'Z');
        const active = now >= start && now <= end;
        return `<tr>
          <td><strong>${esc(w.title)}</strong></td>
          <td style="color:var(--text2)">${w.monitor_name ? esc(w.monitor_name) : '<em style="color:var(--text3)">All monitors</em>'}</td>
          <td style="font-size:12px;color:var(--text2)">${start.toLocaleString()}</td>
          <td style="font-size:12px;color:var(--text2)">${end.toLocaleString()}</td>
          <td>${w.repeat_weekly ? '<span class="badge badge-pending">Weekly</span>' : '–'}</td>
          <td>${active ? '<span class="badge badge-down">Active</span>' : '<span class="badge badge-paused">Scheduled</span>'}</td>
          <td><button class="btn btn-danger btn-sm" onclick="deleteMaintenance(${w.id})"><svg width="12" height="12"><use href="#ic-trash"/></svg></button></td>
        </tr>`;
      }).join('')}</tbody>
    </table>`;
  } catch(e) {
    wrap.innerHTML = `<div style="padding:16px;color:var(--red);font-size:13px">Error: ${esc(e.message)}</div>`;
  }
}

async function openAddMaintenanceModal() {
  // Populate monitor dropdown
  const sel = document.getElementById('mw-monitor');
  sel.innerHTML = '<option value="">All Monitors</option>';
  if (!allMonitors.length) {
    try { const r = await fetch(`${API}/api/monitors`, {credentials:'include'}); allMonitors = await r.json(); } catch(e) {}
  }
  allMonitors.forEach(m => {
    const opt = document.createElement('option');
    opt.value = m.id; opt.textContent = m.name;
    sel.appendChild(opt);
  });
  document.getElementById('mw-title').value  = '';
  document.getElementById('mw-start').value  = '';
  document.getElementById('mw-end').value    = '';
  document.getElementById('mw-repeat').checked = false;
  openModal('modal-maintenance');
}

async function saveMaintenance() {
  const title  = document.getElementById('mw-title').value.trim();
  const mid    = document.getElementById('mw-monitor').value || null;
  const start  = document.getElementById('mw-start').value;
  const end    = document.getElementById('mw-end').value;
  const repeat = document.getElementById('mw-repeat').checked ? 1 : 0;
  if (!title || !start || !end) { toast('Title, start and end are required','error'); return; }
  if (new Date(start) >= new Date(end)) { toast('Start must be before end','error'); return; }
  try {
    const res = await fetch(`${API}/api/maintenance`, {
      method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
      body: JSON.stringify({title, monitor_id: mid, start_dt: start, end_dt: end, repeat_weekly: repeat})
    });
    if (!res.ok) { const e = await res.json(); toast(e.error||'Error','error'); return; }
    closeModal('modal-maintenance');
    toast('Maintenance window scheduled','success');
    loadMaintenance();
  } catch(e) { toast('Error: '+e.message,'error'); }
}

async function deleteMaintenance(id) {
  if (!confirm('Delete this maintenance window?')) return;
  await fetch(`${API}/api/maintenance/${id}`, {method:'DELETE', credentials:'include'});
  toast('Deleted','success');
  loadMaintenance();
}

// ═══════════════════════════════════════════
// WEEKLY REPORT
// ═══════════════════════════════════════════
async function sendWeeklyReport() {
  const msg = document.getElementById('report-msg');
  msg.style.color = 'var(--text3)';
  msg.textContent = 'Sending...';
  try {
    const res  = await fetch(`${API}/api/reports/weekly/send`, {method:'POST', credentials:'include'});
    const data = await res.json();
    if (data.ok) { msg.style.color='var(--green)'; msg.textContent='Report sent successfully.'; toast('Weekly report sent','success'); }
    else         { msg.style.color='var(--red)';   msg.textContent='Failed: '+data.message; }
  } catch(e) { msg.style.color='var(--red)'; msg.textContent='Error: '+e.message; }
}

// ═══════════════════════════════════════════
// MODAL HELPERS
// ═══════════════════════════════════════════
function openModal(id) {
  // Close all other modals first
  document.querySelectorAll('.modal-overlay').forEach(m => m.classList.remove('open'));
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}
function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

// Close modal on overlay click
document.querySelectorAll('.modal-overlay').forEach(o => {
  o.addEventListener('click', e => { if (e.target === o) o.classList.remove('open'); });
});

// Close modal on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') document.querySelectorAll('.modal-overlay.open').forEach(o => o.classList.remove('open'));
});

// ═══════════════════════════════════════════
// AUTO-REFRESH
// ═══════════════════════════════════════════
function startAutoRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    const dashActive = document.getElementById('page-dashboard').classList.contains('active');
    const spOpen     = document.getElementById('status-page-view').classList.contains('open');
    if (dashActive) refreshDashboard();
    if (spOpen && currentSlug) loadStatusPageView(currentSlug);
  }, 60000);
}

// ═══════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════
(async function init() {
  const params = new URLSearchParams(window.location.search);
  const pageSlug = params.get('page');
  const dbStatus = params.get('dbstatus');
  
  if (dbStatus) {
    // Public DB status page — no auth needed
    await loadDbStatusPage();
    setInterval(loadDbStatusPage, 60000);
  } else if (pageSlug) {
    // Status pages are public — no auth needed
    await viewStatusPage(pageSlug);
  } else {
    // Dashboard requires auth
    const ok = await checkAuth();
    if (!ok) return;
    if (currentUserInfo && currentUserInfo.role === 'dba') {
      navigate('databases');
    } else {
      await refreshDashboard();
    }
  }
  
  if (!dbStatus) startAutoRefresh();
})();


// ═══════════════════════════════════════════
// SERVICE TOPOLOGY
// ═══════════════════════════════════════════

let topoData      = { nodes: [], edges: [] };
let topoView      = 'map';
let topoSelected  = null;   // selected node id
let topoDragging  = null;   // node being dragged
let topoDragOffX  = 0;
let topoDragOffY  = 0;
let topoScale     = 1;
let topoPanX      = 0;
let topoPanY      = 0;
let topoPanning   = false;
let topoPanStartX = 0;
let topoPanStartY = 0;
let topoShowAll   = false;  // false = only show nodes involved in dependencies

// Returns only nodes that should be visible based on topoShowAll flag
function topoVisibleNodes() {
  if (topoShowAll || !topoData.edges.length) return topoData.nodes;
  const connectedIds = new Set();
  topoData.edges.forEach(e => { connectedIds.add(e.from); connectedIds.add(e.to); });
  return topoData.nodes.filter(n => connectedIds.has(n.id));
}

function topoToggleShowAll() {
  topoShowAll = document.getElementById('topo-show-all').checked;
  // Re-run auto layout if switching to connected-only and positions are default
  renderTopoMap();
}

const TOPO_NODE_W  = 160;
const TOPO_NODE_H  = 52;
const TOPO_COLORS  = {
  up:      { fill: '#e8faf2', stroke: '#1a9e5c', dot: '#1a9e5c' },
  down:    { fill: '#fef2f2', stroke: '#e53e3e', dot: '#e53e3e' },
  paused:  { fill: '#f0f2f5', stroke: '#8a94a6', dot: '#8a94a6' },
  pending: { fill: '#fffbeb', stroke: '#d97706', dot: '#d97706' },
};

async function loadTopology() {
  try {
    const [topoRes, monRes, statusRes] = await Promise.all([
      fetch(`${API}/api/topology`, { credentials: 'include' }),
      fetch(`${API}/api/monitors`, { credentials: 'include' }),
      fetch(`${API}/api/status?preset=1h`, { credentials: 'include' })
    ]);
    topoData = await topoRes.json();
    const monitors  = await monRes.json();
    const statusArr = await statusRes.json();

    // Build status+stats map keyed by monitor id
    const statsMap = {};
    statusArr.forEach(m => { statsMap[m.id] = m; });

    // Preserve layout positions
    const layoutMap = {};
    topoData.nodes.forEach(n => { layoutMap[n.id] = { x: n.x, y: n.y }; });

    // Build clean node list from monitors (no duplicates)
    topoData.nodes = monitors.map(m => {
      const pos   = layoutMap[m.id] || { x: 0, y: 0 };
      const stats = statsMap[m.id]  || {};
      const last  = stats.current_status;
      let status  = 'pending';
      if (!m.enabled)          status = 'paused';
      else if (last?.status === 1) status = 'up';
      else if (last?.status === 0) status = 'down';
      return {
        id:          m.id,
        name:        m.name,
        group:       m.group_name || 'General',
        status,
        uptime_pct:  stats.uptime_pct  ?? null,
        avg_latency: stats.avg_latency ?? null,
        total_checks:stats.total_checks ?? 0,
        x: pos.x,
        y: pos.y
      };
    });

    // Enrich edges with dependency latency (avg latency of the "to" node)
    topoData.edges.forEach(edge => {
      const toNode = topoData.nodes.find(n => n.id === edge.to);
      edge.latency = toNode?.avg_latency ?? null;
      edge.uptime  = toNode?.uptime_pct  ?? null;
    });

    const allZero = topoData.nodes.every(n => n.x === 0 && n.y === 0);
    if (allZero) topoAutoLayoutData();

    renderTopology();
    updateTopoStats();
    startTopoAnimation();
  } catch(e) {
    console.error('Topology load error:', e);
    toast('Error loading topology', 'error');
  }
}

function updateTopoStats() {
  const up    = topoData.nodes.filter(n => n.status === 'up').length;
  const down  = topoData.nodes.filter(n => n.status === 'down').length;
  const total = topoData.nodes.length;
  const deps  = topoData.edges.length;
  document.getElementById('topo-stats').textContent =
    `${total} services · ${deps} dependencies · ${up} up · ${down} down`;
}

function topoSetView(v) {
  topoView = v;
  ['map','swimlane','deps'].forEach(name => {
    document.getElementById('topo-view-' + name).classList.toggle('active', name === v);
    document.getElementById('topo-view-' + name + '-panel').style.display = name === v ? '' : 'none';
  });
  if (v === 'map')      renderTopoMap();
  if (v === 'swimlane') renderTopoSwimlane();
  if (v === 'deps')     renderTopoDeps();
}

function renderTopology() {
  if (topoView === 'map')      renderTopoMap();
  if (topoView === 'swimlane') renderTopoSwimlane();
  if (topoView === 'deps')     renderTopoDeps();
}

// ── ANIMATION ────────────────────────────────
let topoAnimFrame  = null;
let topoAnimTick   = 0;
let topoHoverNode  = null;   // node under mouse for tooltip
let topoTooltip    = { x:0, y:0, node:null };

function startTopoAnimation() {
  if (topoAnimFrame) cancelAnimationFrame(topoAnimFrame);
  function loop() {
    topoAnimTick++;
    drawTopoCanvas();
    topoAnimFrame = requestAnimationFrame(loop);
  }
  topoAnimFrame = requestAnimationFrame(loop);
}

function stopTopoAnimation() {
  if (topoAnimFrame) { cancelAnimationFrame(topoAnimFrame); topoAnimFrame = null; }
}

// ── MAP VIEW ─────────────────────────────────

function renderTopoMap() {
  const canvas = document.getElementById('topo-canvas');
  if (!canvas) return;
  const container = canvas.parentElement;
  const W = container.clientWidth || 1200;
  const H = Math.max(600, topoData.nodes.length * 80);
  canvas.style.width  = W + 'px';
  canvas.style.height = H + 'px';
  canvas.width  = W;
  canvas.height = H;
  drawTopoCanvas();
  setupTopoCanvasEvents(canvas);
}

function nodeSize(node) {
  // Node width scales slightly with health: DOWN nodes are slightly larger (more prominent)
  // UP nodes with high uptime are normal, degraded are slightly smaller
  if (node.status === 'down')   return { w: TOPO_NODE_W + 10, h: TOPO_NODE_H + 6 };
  if (node.status === 'paused') return { w: TOPO_NODE_W - 10, h: TOPO_NODE_H - 4 };
  if (node.uptime_pct !== null && node.uptime_pct < 90)
                                return { w: TOPO_NODE_W + 4,  h: TOPO_NODE_H + 2 };
  return { w: TOPO_NODE_W, h: TOPO_NODE_H };
}

function drawTopoCanvas() {
  const canvas = document.getElementById('topo-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const t = topoAnimTick;

  ctx.clearRect(0, 0, W, H);

  // Background grid
  ctx.save();
  ctx.strokeStyle = '#eaecef';
  ctx.lineWidth   = 1;
  const gridSize  = 40;
  for (let x = ((topoPanX % gridSize) + gridSize) % gridSize; x < W; x += gridSize) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  }
  for (let y = ((topoPanY % gridSize) + gridSize) % gridSize; y < H; y += gridSize) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }
  ctx.restore();

  ctx.save();
  ctx.translate(topoPanX, topoPanY);
  ctx.scale(topoScale, topoScale);

  // ── Draw edges ──────────────────────────────
  topoData.edges.forEach(edge => {
    const from = topoVisibleNodes().find(n => n.id === edge.from);
    const to   = topoVisibleNodes().find(n => n.id === edge.to);
    if (!from || !to) return;

    const fs = nodeSize(from), ts = nodeSize(to);
    const fx = from.x + fs.w / 2;
    const fy = from.y + fs.h / 2;
    const tx = to.x   + ts.w / 2;
    const ty = to.y   + ts.h / 2;

    const depStatus = to.status;
    const edgeColor = depStatus === 'down'   ? '#e53e3e' :
                      depStatus === 'up'     ? '#1a9e5c' : '#8a94a6';
    const cpx = (fx + tx) / 2;
    const cpy = (fy + ty) / 2 - 40;

    // Arrow line
    ctx.beginPath();
    ctx.moveTo(fx, fy);
    ctx.quadraticCurveTo(cpx, cpy, tx, ty);
    ctx.strokeStyle = edgeColor;
    ctx.lineWidth   = depStatus === 'down' ? 2.5 : 1.8;
    ctx.setLineDash(depStatus === 'down' ? [6, 3] : []);
    ctx.stroke();
    ctx.setLineDash([]);

    // Animated flow dot along the arrow (only when UP)
    if (depStatus === 'up') {
      const progress = ((t * 0.8) % 100) / 100;
      const bt = progress;
      const dotX = (1-bt)*(1-bt)*fx + 2*(1-bt)*bt*cpx + bt*bt*tx;
      const dotY = (1-bt)*(1-bt)*fy + 2*(1-bt)*bt*cpy + bt*bt*ty;
      ctx.beginPath();
      ctx.arc(dotX, dotY, 4, 0, Math.PI * 2);
      ctx.fillStyle = edgeColor;
      ctx.fill();
    }

    // Arrowhead
    const angle = Math.atan2(ty - cpy, tx - cpx);
    const aLen  = 10;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(tx - aLen * Math.cos(angle - 0.4), ty - aLen * Math.sin(angle - 0.4));
    ctx.lineTo(tx - aLen * Math.cos(angle + 0.4), ty - aLen * Math.sin(angle + 0.4));
    ctx.closePath();
    ctx.fillStyle = edgeColor;
    ctx.fill();

    // Edge label + latency (AppDynamics style)
    const midT  = 0.5;
    const midX  = (1-midT)*(1-midT)*fx + 2*(1-midT)*midT*cpx + midT*midT*tx;
    const midY  = (1-midT)*(1-midT)*fy + 2*(1-midT)*midT*cpy + midT*midT*ty - 8;

    const latText = edge.latency !== null ? `${edge.latency}ms` : '';
    const lblText = [edge.label, latText].filter(Boolean).join(' · ');
    if (lblText) {
      const tw = ctx.measureText(lblText).width + 10;
      ctx.fillStyle   = 'rgba(255,255,255,0.92)';
      ctx.strokeStyle = edgeColor;
      ctx.lineWidth   = 1;
      ctx.beginPath();
      roundRect(ctx, midX - tw/2, midY - 9, tw, 16, 4);
      ctx.fill(); ctx.stroke();
      ctx.fillStyle = depStatus === 'down' ? '#e53e3e' : '#4a5568';
      ctx.font      = '700 10px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText(lblText, midX, midY + 3);
    }
  });

  // ── Draw nodes ──────────────────────────────
  topoVisibleNodes().forEach(node => {
    const colors     = TOPO_COLORS[node.status] || TOPO_COLORS.pending;
    const isSelected = topoSelected === node.id;
    const isHover    = topoHoverNode === node.id;
    const { w, h }   = nodeSize(node);
    const x = node.x, y = node.y;

    // Animated pulse ring for DOWN nodes
    if (node.status === 'down') {
      const pulse = Math.abs(Math.sin(t * 0.05));
      ctx.beginPath();
      roundRect(ctx, x - 6 - pulse*4, y - 6 - pulse*4, w + 12 + pulse*8, h + 12 + pulse*8, 12);
      ctx.strokeStyle = `rgba(229,62,62,${0.4 - pulse*0.3})`;
      ctx.lineWidth   = 2;
      ctx.stroke();
    }

    // Hover glow
    if (isHover || isSelected) {
      ctx.shadowColor = isSelected ? 'rgba(0,169,157,0.5)' : 'rgba(0,0,0,0.15)';
      ctx.shadowBlur  = 16;
    }

    // Node box
    ctx.beginPath();
    roundRect(ctx, x, y, w, h, 8);
    ctx.fillStyle   = colors.fill;
    ctx.fill();
    ctx.strokeStyle = isSelected ? '#00a99d' : isHover ? colors.dot : colors.stroke;
    ctx.lineWidth   = isSelected ? 2.5 : isHover ? 2 : 1.5;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    // Status dot (pulsing for DOWN)
    const dotR = node.status === 'down' ? 5 + Math.abs(Math.sin(t * 0.08)) * 2 : 5;
    ctx.beginPath();
    ctx.arc(x + 16, y + h / 2, dotR, 0, Math.PI * 2);
    ctx.fillStyle = colors.dot;
    ctx.fill();

    // Service name
    ctx.fillStyle = '#1a1f2e';
    ctx.font      = '600 12px -apple-system, sans-serif';
    ctx.textAlign = 'left';
    const maxNameW = w - 36;
    let name = node.name;
    if (ctx.measureText(name).width > maxNameW) {
      while (ctx.measureText(name + '…').width > maxNameW && name.length > 0) name = name.slice(0, -1);
      name += '…';
    }
    ctx.fillText(name, x + 28, y + 18);

    // Stats line: uptime % + latency
    const uptimeTxt  = node.uptime_pct  !== null ? `${node.uptime_pct.toFixed(1)}%` : '';
    const latencyTxt = node.avg_latency !== null ? `${node.avg_latency}ms` : '';
    const statsLine  = [uptimeTxt, latencyTxt].filter(Boolean).join(' · ');
    ctx.fillStyle = node.uptime_pct !== null && node.uptime_pct < 90 ? '#d97706' : '#8a94a6';
    ctx.font      = '10px sans-serif';
    ctx.fillText(statsLine || node.group, x + 28, y + 33);

    // Status badge (top-right)
    const badgeText = node.status.toUpperCase();
    ctx.font        = '700 9px sans-serif';
    const badgeW    = ctx.measureText(badgeText).width + 10;
    ctx.fillStyle   = colors.fill;
    ctx.strokeStyle = colors.stroke;
    ctx.lineWidth   = 1;
    ctx.beginPath();
    roundRect(ctx, x + w - badgeW - 6, y + 6, badgeW, 15, 4);
    ctx.fill(); ctx.stroke();
    ctx.fillStyle = colors.dot;
    ctx.textAlign = 'center';
    ctx.fillText(badgeText, x + w - badgeW / 2 - 6, y + 16);
  });

  // ── Tooltip ─────────────────────────────────
  if (topoTooltip.node) {
    const node   = topoTooltip.node;
    const { w }  = nodeSize(node);
    const ttx    = node.x + w + 8;
    const tty    = node.y;
    const lines  = [
      node.name,
      `Status: ${node.status.toUpperCase()}`,
      node.uptime_pct  !== null ? `Uptime: ${node.uptime_pct.toFixed(2)}%`  : null,
      node.avg_latency !== null ? `Avg Latency: ${node.avg_latency}ms`       : null,
      node.total_checks ? `Checks: ${node.total_checks}` : null,
      `Group: ${node.group}`,
    ].filter(Boolean);

    const ttW = 180, ttH = lines.length * 16 + 16;
    ctx.fillStyle   = 'rgba(26,31,46,0.95)';
    ctx.strokeStyle = TOPO_COLORS[node.status]?.stroke || '#8a94a6';
    ctx.lineWidth   = 1.5;
    ctx.beginPath();
    roundRect(ctx, ttx, tty, ttW, ttH, 8);
    ctx.fill(); ctx.stroke();

    lines.forEach((line, i) => {
      ctx.fillStyle = i === 0 ? '#ffffff' : '#c8cdd6';
      ctx.font      = i === 0 ? '700 11px sans-serif' : '10px sans-serif';
      ctx.textAlign = 'left';
      ctx.fillText(line, ttx + 10, tty + 14 + i * 16);
    });
  }

  ctx.restore();
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
}

function topoCanvasCoords(canvas, e) {
  const rect = canvas.getBoundingClientRect();
  // Account for scroll and device pixel ratio
  const scaleX = canvas.width  / rect.width;
  const scaleY = canvas.height / rect.height;
  const rawX = (e.clientX - rect.left) * scaleX;
  const rawY = (e.clientY - rect.top)  * scaleY;
  const cx = (rawX - topoPanX) / topoScale;
  const cy = (rawY - topoPanY) / topoScale;
  return { cx, cy };
}

function hitTestNode(cx, cy) {
  return topoVisibleNodes().find(n => {
    const { w, h } = nodeSize(n);
    return cx >= n.x && cx <= n.x + w && cy >= n.y && cy <= n.y + h;
  }) || null;
}

function setupTopoCanvasEvents(canvas) {
  // Remove old listeners by replacing with a clone
  const newCanvas = canvas.cloneNode(true);
  canvas.parentNode.replaceChild(newCanvas, canvas);
  const c = document.getElementById('topo-canvas');

  let didDrag = false;  // track if mouse moved during mousedown (drag vs click)

  c.addEventListener('mousedown', e => {
    didDrag = false;
    const { cx, cy } = topoCanvasCoords(c, e);
    const node = hitTestNode(cx, cy);
    if (node) {
      topoDragging  = node;
      topoDragOffX  = cx - node.x;
      topoDragOffY  = cy - node.y;
      c.style.cursor = 'grabbing';
    } else {
      topoPanning   = true;
      topoPanStartX = e.clientX - topoPanX;
      topoPanStartY = e.clientY - topoPanY;
      c.style.cursor = 'grab';
    }
  });

  c.addEventListener('mousemove', e => {
    if (topoDragging) {
      didDrag = true;
      const { cx, cy } = topoCanvasCoords(c, e);
      topoDragging.x = cx - topoDragOffX;
      topoDragging.y = cy - topoDragOffY;
      topoHoverNode  = null;
      topoTooltip.node = null;
    } else if (topoPanning) {
      didDrag = true;
      topoPanX = e.clientX - topoPanStartX;
      topoPanY = e.clientY - topoPanStartY;
      topoHoverNode  = null;
      topoTooltip.node = null;
    } else {
      const { cx, cy } = topoCanvasCoords(c, e);
      const node = hitTestNode(cx, cy);
      topoHoverNode    = node ? node.id : null;
      topoTooltip.node = node || null;
      c.style.cursor   = node ? 'pointer' : 'default';
    }
  });

  c.addEventListener('mouseup', async e => {
    if (topoDragging && didDrag) {
      await saveTopoLayout();
    }
    topoDragging = null;
    topoPanning  = false;
    c.style.cursor = 'default';
  });

  c.addEventListener('click', e => {
    // Ignore if this was a drag operation
    if (didDrag) { didDrag = false; return; }
    const { cx, cy } = topoCanvasCoords(c, e);
    const node = hitTestNode(cx, cy);
    if (node) {
      topoSelected = node.id;
      drawTopoCanvas();
      showImpactPanel(node);
    } else {
      topoSelected = null;
      drawTopoCanvas();
      document.getElementById('topo-impact-panel').style.display = 'none';
    }
  });

  c.addEventListener('wheel', e => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    topoScale   = Math.min(2, Math.max(0.3, topoScale * delta));
    drawTopoCanvas();
  }, { passive: false });
}

async function showImpactPanel(node) {
  const panel = document.getElementById('topo-impact-panel');
  const title = document.getElementById('topo-impact-title');
  const body  = document.getElementById('topo-impact-body');

  panel.style.display       = '';
  panel.style.pointerEvents = 'auto';
  title.textContent   = `Impact Analysis — ${node.name}`;
  body.innerHTML      = '<div class="loading-center" style="padding:16px"><div class="spinner"></div></div>';

  try {
    const res    = await fetch(`${API}/api/topology/impact/${node.id}`, { credentials: 'include' });
    const data   = await res.json();
    const colors = TOPO_COLORS[node.status] || TOPO_COLORS.pending;

    // What this node depends on
    const dependsOn = topoData.edges
      .filter(e => e.from === node.id)
      .map(e => topoData.nodes.find(n => n.id === e.to))
      .filter(Boolean);

    // What depends on this node
    const dependents = topoData.edges
      .filter(e => e.to === node.id)
      .map(e => topoData.nodes.find(n => n.id === e.from))
      .filter(Boolean);

    const statusBadge = (s) => {
      const c = TOPO_COLORS[s] || TOPO_COLORS.pending;
      return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${c.dot};margin-right:4px"></span>`;
    };

    body.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px">
        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">This Service</div>
          <div style="display:flex;align-items:center;gap:8px;padding:10px 14px;background:${colors.fill};border:1px solid ${colors.stroke};border-radius:var(--radius)">
            <span style="width:10px;height:10px;border-radius:50%;background:${colors.dot};flex-shrink:0"></span>
            <div>
              <div style="font-weight:700;font-size:13px">${esc(node.name)}</div>
              <div style="font-size:11px;color:var(--text3)">${esc(node.group)} · ${node.status.toUpperCase()}</div>
            </div>
          </div>
        </div>

        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Depends On (${dependsOn.length})</div>
          ${dependsOn.length ? dependsOn.map(n => `
            <div style="display:flex;align-items:center;gap:6px;padding:6px 10px;background:var(--surface2);border-radius:6px;margin-bottom:4px;font-size:12px">
              ${statusBadge(n.status)}${esc(n.name)}
              ${n.status === 'down' ? '<span style="margin-left:auto;font-size:10px;font-weight:700;color:var(--red)">⚠ DOWN</span>' : ''}
            </div>`).join('') : '<div style="font-size:12px;color:var(--text3);padding:6px">No dependencies</div>'}
        </div>

        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Used By (${dependents.length})</div>
          ${dependents.length ? dependents.map(n => `
            <div style="display:flex;align-items:center;gap:6px;padding:6px 10px;background:var(--surface2);border-radius:6px;margin-bottom:4px;font-size:12px">
              ${statusBadge(n.status)}${esc(n.name)}
            </div>`).join('') : '<div style="font-size:12px;color:var(--text3);padding:6px">Nothing depends on this</div>'}
        </div>

        <div>
          <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">
            Blast Radius (${data.impacted.length})
          </div>
          ${data.impacted.length ? `
            <div style="padding:10px 14px;background:var(--red-dim);border:1px solid var(--red);border-radius:var(--radius)">
              <div style="font-size:12px;font-weight:700;color:var(--red);margin-bottom:6px">⚠ If this goes DOWN, these are impacted:</div>
              ${data.impacted.map(i => `<div style="font-size:12px;color:var(--text2);padding:2px 0">• ${esc(i.name)}</div>`).join('')}
            </div>` :
            '<div style="font-size:12px;color:var(--text3);padding:6px">No downstream impact</div>'}
        </div>
      </div>`;
  } catch(e) {
    body.innerHTML = `<div style="color:var(--red);font-size:12px">Error loading impact: ${esc(e.message)}</div>`;
  }
}

// ── SWIMLANE VIEW ─────────────────────────────

function renderTopoSwimlane() {
  const wrap = document.getElementById('topo-swimlane-content');
  if (!wrap) return;

  // Group nodes by group_name
  const groups = {};
  topoData.nodes.forEach(n => {
    const g = n.group || 'General';
    if (!groups[g]) groups[g] = [];
    groups[g].push(n);
  });

  const groupNames = Object.keys(groups).sort((a, b) => {
    if (a === 'General') return 1;
    if (b === 'General') return -1;
    return a.localeCompare(b);
  });

  wrap.innerHTML = groupNames.map(groupName => {
    const nodes   = groups[groupName];
    const up      = nodes.filter(n => n.status === 'up').length;
    const down    = nodes.filter(n => n.status === 'down').length;
    const groupColor = down > 0 ? 'var(--red)' : 'var(--green)';

    return `
      <div style="margin-bottom:20px">
        <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius) var(--radius) 0 0;border-bottom:2px solid var(--border)">
          <span style="font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--text)">${esc(groupName)}</span>
          <span style="font-size:11px;color:${groupColor};font-weight:600">${up} up${down > 0 ? ' · ' + down + ' down' : ''}</span>
          <span style="font-size:11px;color:var(--text3);margin-left:auto">${nodes.length} service${nodes.length !== 1 ? 's' : ''}</span>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:12px;padding:16px;background:var(--surface);border:1px solid var(--border);border-top:none;border-radius:0 0 var(--radius) var(--radius)">
          ${nodes.map(n => {
            const colors = TOPO_COLORS[n.status] || TOPO_COLORS.pending;
            // Find what this node depends on
            const deps = topoData.edges
              .filter(e => e.from === n.id)
              .map(e => topoData.nodes.find(nd => nd.id === e.to))
              .filter(Boolean);
            const usedBy = topoData.edges
              .filter(e => e.to === n.id)
              .map(e => topoData.nodes.find(nd => nd.id === e.from))
              .filter(Boolean);

            return `
              <div onclick="topoSelectSwimlaneNode(${n.id})" style="cursor:pointer;min-width:180px;max-width:240px;flex:1;padding:12px 14px;background:${colors.fill};border:1.5px solid ${colors.stroke};border-radius:var(--radius);transition:box-shadow .15s" onmouseover="this.style.boxShadow='var(--shadow-md)'" onmouseout="this.style.boxShadow=''">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                  <span style="width:10px;height:10px;border-radius:50%;background:${colors.dot};flex-shrink:0"></span>
                  <span style="font-weight:700;font-size:13px;color:var(--text)">${esc(n.name)}</span>
                  <span style="margin-left:auto;font-size:9px;font-weight:700;color:${colors.dot};text-transform:uppercase">${n.status}</span>
                </div>
                ${deps.length ? `<div style="font-size:10px;color:var(--text3);margin-top:4px">→ Depends on: ${deps.map(d => `<span style="color:${TOPO_COLORS[d.status]?.dot||'#8a94a6'}">${esc(d.name)}</span>`).join(', ')}</div>` : ''}
                ${usedBy.length ? `<div style="font-size:10px;color:var(--text3);margin-top:2px">← Used by: ${usedBy.map(d => esc(d.name)).join(', ')}</div>` : ''}
              </div>`;
          }).join('')}
        </div>
      </div>`;
  }).join('');
}

function topoSelectSwimlaneNode(id) {
  const node = topoData.nodes.find(n => n.id === id);
  if (node) showImpactPanel(node);
}

// ── DEPENDENCY LIST VIEW ──────────────────────

async function renderTopoDeps() {
  const tbody = document.getElementById('topo-deps-tbody');
  if (!tbody) return;
  try {
    const res  = await fetch(`${API}/api/topology/dependencies`, { credentials: 'include' });
    const deps = await res.json();
    if (!deps.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text3);padding:20px">No dependencies defined yet. Click "Add Dependency" to get started.</td></tr>';
      return;
    }
    tbody.innerHTML = deps.map(d => {
      const fromNode = topoData.nodes.find(n => n.id === d.monitor_id);
      const toNode   = topoData.nodes.find(n => n.id === d.depends_on);
      const fromColor = TOPO_COLORS[fromNode?.status]?.dot || '#8a94a6';
      const toColor   = TOPO_COLORS[toNode?.status]?.dot   || '#8a94a6';
      return `<tr>
        <td><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${fromColor};margin-right:6px"></span>${esc(d.monitor_name)}</td>
        <td><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${toColor};margin-right:6px"></span>${esc(d.depends_on_name)}</td>
        <td style="color:var(--text3)">${esc(d.label || '–')}</td>
        <td><button class="btn btn-danger btn-sm" onclick="deleteDependency(${d.id})"><svg width="12" height="12"><use href="#ic-trash"/></svg></button></td>
      </tr>`;
    }).join('');
  } catch(e) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:var(--red);padding:16px">Error: ${esc(e.message)}</td></tr>`;
  }
}

// ── AUTO LAYOUT ───────────────────────────────

function topoAutoLayoutData() {
  const visible = topoVisibleNodes();
  const groups = {};
  visible.forEach(n => {
    const g = n.group || 'General';
    if (!groups[g]) groups[g] = [];
    groups[g].push(n);
  });

  const groupNames = Object.keys(groups).sort();
  const colW = TOPO_NODE_W + 80;
  const rowH = TOPO_NODE_H + 50;
  const startX = 40, startY = 40;

  groupNames.forEach((g, gi) => {
    groups[g].forEach((n, ni) => {
      n.x = startX + gi * colW;
      n.y = startY + ni * rowH;
    });
  });
}

function topoAutoLayout() {
  topoAutoLayoutData();
  drawTopoCanvas();
  saveTopoLayout();
}

async function saveTopoLayout() {
  const positions = topoData.nodes.map(n => ({ monitor_id: n.id, x: n.x, y: n.y }));
  try {
    await fetch(`${API}/api/topology/layout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(positions)
    });
  } catch(e) { /* silent */ }
}

// ── ADD / DELETE DEPENDENCY ───────────────────

async function openAddDependencyModal() {
  // Fetch fresh monitor list if topoData is empty
  if (!topoData.nodes || topoData.nodes.length === 0) {
    try {
      const res = await fetch(`${API}/api/monitors`, { credentials: 'include' });
      const monitors = await res.json();
      topoData.nodes = monitors.map(m => ({
        id: m.id,
        name: m.name,
        group: m.group_name || 'General',
        status: 'pending',
        x: 0,
        y: 0
      }));
    } catch(e) {
      toast('Error loading monitors', 'error');
      return;
    }
  }

  const selA = document.getElementById('dep-monitor-id');
  const selB = document.getElementById('dep-depends-on');
  const opts = topoData.nodes.map(n =>
    `<option value="${n.id}">${esc(n.name)} (${esc(n.group)})</option>`
  ).join('');
  selA.innerHTML = '<option value="">Select service...</option>' + opts;
  selB.innerHTML = '<option value="">Select dependency...</option>' + opts;
  document.getElementById('dep-label').value = '';
  openModal('modal-dependency');
}

async function saveDependency() {
  const monitorId = document.getElementById('dep-monitor-id').value;
  const dependsOn = document.getElementById('dep-depends-on').value;
  const label     = document.getElementById('dep-label').value.trim();

  if (!monitorId || !dependsOn) { toast('Select both services', 'error'); return; }
  if (monitorId === dependsOn)  { toast('A service cannot depend on itself', 'error'); return; }

  try {
    const res = await fetch(`${API}/api/topology/dependencies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ monitor_id: parseInt(monitorId), depends_on: parseInt(dependsOn), label })
    });
    if (!res.ok) { const e = await res.json(); toast(e.error || 'Error', 'error'); return; }
    closeModal('modal-dependency');
    toast('Dependency added', 'success');
    await loadTopology();
  } catch(e) { toast('Error: ' + e.message, 'error'); }
}

async function deleteDependency(id) {
  document.getElementById('confirm-msg').textContent = 'Remove this dependency link?';
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    const res = await fetch(`${API}/api/topology/dependencies/${id}`, {
      method: 'DELETE', credentials: 'include'
    });
    if (res.ok) { toast('Dependency removed', 'success'); await loadTopology(); }
    else { toast('Error removing dependency', 'error'); }
  };
  openModal('modal-confirm');
}


// ═══════════════════════════════════════════
// AUDIT REPORT DOWNLOAD
// ═══════════════════════════════════════════

async function downloadAuditReport(mid, preset) {
  const statusEl = document.getElementById(`audit-status-${mid}`);
  if (statusEl) statusEl.innerHTML = '<span style="color:var(--blue)">⏳ Generating report...</span>';

  try {
    const url = `${API}/api/monitors/${mid}/audit-report?preset=${preset}`;
    const res = await fetch(url, { credentials: 'include' });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Export failed' }));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    let filename = 'audit-report.csv';
    const disposition = res.headers.get('Content-Disposition');
    if (disposition) {
      const match = disposition.match(/filename="?([^"]+)"?/);
      if (match) filename = match[1];
    }

    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);

    if (statusEl) statusEl.innerHTML = '<span style="color:var(--green)">✓ Report downloaded</span>';
    toast('Audit report downloaded', 'success');
  } catch (e) {
    if (statusEl) statusEl.innerHTML = `<span style="color:var(--red)">✗ ${esc(e.message)}</span>`;
    toast('Audit report failed: ' + e.message, 'error');
  }
}

async function downloadAuditReportCustom(mid) {
  const fromEl = document.getElementById(`audit-from-${mid}`);
  const toEl = document.getElementById(`audit-to-${mid}`);
  if (!fromEl || !toEl || !fromEl.value || !toEl.value) {
    toast('Please select both From and To dates', 'error');
    return;
  }
  const statusEl = document.getElementById(`audit-status-${mid}`);
  if (statusEl) statusEl.innerHTML = '<span style="color:var(--blue)">⏳ Generating report...</span>';

  try {
    const fromDt = fromEl.value + 'T00:00:00';
    const toDt = toEl.value + 'T23:59:59';
    const url = `${API}/api/monitors/${mid}/audit-report?from_dt=${fromDt}&to_dt=${toDt}`;
    const res = await fetch(url, { credentials: 'include' });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Export failed' }));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    let filename = 'audit-report.csv';
    const disposition = res.headers.get('Content-Disposition');
    if (disposition) {
      const match = disposition.match(/filename="?([^"]+)"?/);
      if (match) filename = match[1];
    }

    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);

    if (statusEl) statusEl.innerHTML = '<span style="color:var(--green)">✓ Report downloaded</span>';
    toast('Audit report downloaded', 'success');
  } catch (e) {
    if (statusEl) statusEl.innerHTML = `<span style="color:var(--red)">✗ ${esc(e.message)}</span>`;
    toast('Audit report failed: ' + e.message, 'error');
  }
}
