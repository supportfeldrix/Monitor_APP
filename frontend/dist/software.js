// ═══════════════════════════════════════════
// SOFTWARE INVENTORY
// ═══════════════════════════════════════════

// ── Sub-tab switcher ──────────────────────────────────────────────────────────

function swSwitchTab(tab) {
  const tabs    = ['inventory', 'catalogue', 'version'];
  const labels  = { inventory: '📦 Installed Software', catalogue: '📋 Catalogue', version: '🔍 Version Checks' };

  tabs.forEach(t => {
    const panel  = document.getElementById(`sw-panel-${t}`);
    const btn    = document.getElementById(`sw-subtab-${t}`);
    const actions = document.getElementById(`sw-tab-actions-${t}`);
    if (panel)   panel.style.display   = t === tab ? '' : 'none';
    if (actions) actions.style.display = t === tab ? '' : 'none';
    if (btn) {
      btn.style.color        = t === tab ? 'var(--fnb-teal)' : 'var(--text3)';
      btn.style.borderBottom = t === tab ? '2px solid var(--fnb-teal)' : '2px solid transparent';
    }
  });

  // Lazy-load data when switching to a tab
  if (tab === 'catalogue')  loadCatalogue();
  if (tab === 'version')    loadVersionChecksPage();
}

let allSoftware  = [];
let swServerFilter  = '';
let swRiskFilter    = '';
let swStatusFilter  = '';
let swEnvFilter     = '';
let swSearchQuery   = '';

// ── Risk badge helpers ────────────────────────────────────────────────────────

function swRiskBadge(risk) {
  if (!risk) return '<span style="font-size:11px;color:var(--text3)">–</span>';
  const map = {
    'Low':      { bg: 'var(--green-dim)',  color: 'var(--green)',  icon: '🟢' },
    'Medium':   { bg: 'var(--yellow-dim)', color: 'var(--yellow)', icon: '🟡' },
    'High':     { bg: 'var(--red-dim)',    color: 'var(--red)',    icon: '🔴' },
    'Critical': { bg: 'rgba(139,0,0,.12)', color: '#8b0000',       icon: '🚨' },
  };
  const s = map[risk] || { bg: 'var(--surface2)', color: 'var(--text3)', icon: '⚪' };
  return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;background:${s.bg};color:${s.color}">${s.icon} ${esc(risk)}</span>`;
}

function swStatusBadge(status) {
  if (!status) return '<span style="font-size:11px;color:var(--text3)">–</span>';
  if (status === 'End of Life')
    return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;background:var(--red-dim);color:var(--red)">⚠ End of Life</span>`;
  if (status === 'Extended Support')
    return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;background:var(--yellow-dim);color:var(--yellow)">⏳ Extended Support</span>`;
  if (status === 'Supported')
    return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;background:var(--green-dim);color:var(--green)">✓ Supported</span>`;
  return `<span style="font-size:11px;color:var(--text2)">${esc(status)}</span>`;
}

function swDiscoveredBadge(by) {
  if (by === 'agent')
    return `<span style="font-size:10px;padding:1px 6px;border-radius:8px;background:var(--blue-dim);color:var(--blue);font-weight:600">🤖 Agent</span>`;
  return `<span style="font-size:10px;padding:1px 6px;border-radius:8px;background:var(--surface2);color:var(--text3);border:1px solid var(--border);font-weight:600">✏️ Manual</span>`;
}

// ── Summary stats ─────────────────────────────────────────────────────────────

function renderSwSummary(sw) {
  const total    = sw.length;
  const eol      = sw.filter(s => s.support_status === 'End of Life').length;
  const highRisk = sw.filter(s => s.risk_rating === 'High' || s.risk_rating === 'Critical').length;
  const prod     = sw.filter(s => s.environment === 'PROD').length;
  const uat      = sw.filter(s => s.environment === 'UAT').length;
  const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  setEl('sw-total',     total);
  setEl('sw-eol',       eol);
  setEl('sw-high-risk', highRisk);
  setEl('sw-prod',      prod);
  setEl('sw-uat',       uat);
}

// ── Filter helpers ────────────────────────────────────────────────────────────

function swSetServerFilter(val) {
  swServerFilter = val;
  renderSwTable();
}
function swSetRisk(val) {
  swRiskFilter = val;
  document.querySelectorAll('#sw-risk-filter .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.risk === val));
  renderSwTable();
}
function swSetStatus(val) {
  swStatusFilter = val;
  document.querySelectorAll('#sw-status-filter .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.status === val));
  renderSwTable();
}
function swSetEnv(val) {
  swEnvFilter = val;
  document.querySelectorAll('#sw-env-filter .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.env === val));
  renderSwTable();
}
function swSearch() {
  swSearchQuery = (document.getElementById('sw-search')?.value || '').toLowerCase();
  renderSwTable();
}

function swFilteredData() {
  // No filters active — return null to show the select-server prompt
  const hasFilter = swServerFilter || swRiskFilter || swStatusFilter || swEnvFilter || swSearchQuery;
  if (!hasFilter) return null;

  return allSoftware.filter(s => {
    if (swServerFilter && String(s.server_id) !== String(swServerFilter)) return false;
    if (swRiskFilter   && s.risk_rating    !== swRiskFilter)   return false;
    if (swStatusFilter && s.support_status !== swStatusFilter) return false;
    if (swEnvFilter    && s.environment    !== swEnvFilter)    return false;
    if (swSearchQuery) {
      const hay = `${s.name} ${s.version||''} ${s.vendor||''} ${s.hostname||''} ${s.install_path||''}`.toLowerCase();
      if (!hay.includes(swSearchQuery)) return false;
    }
    return true;
  });
}

// ── Table render ──────────────────────────────────────────────────────────────

function renderSwTable() {
  const tbody = document.getElementById('sw-tbody');
  if (!tbody) return;
  const data = swFilteredData();

  // null = no filter selected — show prompt
  if (data === null) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:60px;color:var(--text3)">
      <div style="font-size:48px;margin-bottom:16px">📦</div>
      <div style="font-size:15px;font-weight:600;margin-bottom:8px;color:var(--text2)">Select a server to view its software</div>
      <div style="font-size:13px;margin-bottom:20px">Use the Server dropdown above, or use the environment and risk filters to browse all software</div>
    </td></tr>`;
    return;
  }

  if (!data.length) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:40px;color:var(--text3)">
      <div style="font-size:32px;margin-bottom:8px">📦</div>
      <div>No software entries found</div>
    </td></tr>`;
    return;
  }

  tbody.innerHTML = data.map(s => {
    const isEol = s.support_status === 'End of Life';
    const rowStyle = isEol ? 'background:rgba(229,62,62,.06)' : '';
    return `<tr style="${rowStyle}">
      <td>
        <div style="font-size:12px;font-weight:600;color:var(--text)">${esc(s.hostname||'–')}</div>
        <div style="font-size:10px;color:var(--text3)">${esc(s.environment||'')}</div>
      </td>
      <td>
        <div style="font-weight:600;color:var(--text)">${esc(s.name)}</div>
        ${s.install_path ? `<div style="font-size:10px;color:var(--text3);font-family:monospace">${esc(s.install_path)}</div>` : ''}
      </td>
      <td style="font-size:12px;color:var(--text2)">${esc(s.version||'–')}</td>
      <td style="font-size:12px;color:var(--text2)">${esc(s.vendor||'–')}</td>
      <td style="font-size:12px;color:var(--text2)">${esc(s.license_type||'–')}</td>
      <td>${swStatusBadge(s.support_status)}</td>
      <td>${swRiskBadge(s.risk_rating)}</td>
      <td>${swDiscoveredBadge(s.discovered_by)}</td>
      <td>
        <div style="display:flex;gap:4px">
          <button class="btn btn-secondary btn-sm btn-icon" onclick="openEditSwModal(${s.id})" title="Edit">
            <svg width="12" height="12"><use href="#ic-edit"/></svg>
          </button>
          <button class="btn btn-danger btn-sm btn-icon" onclick="confirmDeleteSw(${s.id},'${esc(s.name)}')" title="Delete">
            <svg width="12" height="12"><use href="#ic-trash"/></svg>
          </button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

// ── Load data ─────────────────────────────────────────────────────────────────

async function loadSoftware() {
  const tbody = document.getElementById('sw-tbody');
  if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:30px"><div class="spinner" style="margin:0 auto"></div></td></tr>`;
  try {
    const res = await fetch(`${API}/api/software`, { credentials: 'include' });
    allSoftware = await res.json();
    renderSwSummary(allSoftware);
    populateSwServerFilter();
    renderSwTable();
    ensureExportCsvButton();
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="9" style="color:var(--red);padding:20px">Error: ${esc(e.message)}</td></tr>`;
  }
}

function populateSwServerFilter() {
  const sel = document.getElementById('sw-server-select');
  if (!sel) return;
  const servers = {};
  allSoftware.forEach(s => { servers[s.server_id] = s.hostname; });
  let html = '<option value="">-- Select a server --</option>';
  Object.entries(servers).sort((a,b) => a[1].localeCompare(b[1])).forEach(([id, name]) => {
    html += `<option value="${id}">${esc(name)}</option>`;
  });
  sel.innerHTML = html;
  sel.value = swServerFilter;
}

// ── Load software for a specific server (used from server detail panel) ───────

async function loadServerSoftware(serverId) {
  try {
    const res = await fetch(`${API}/api/servers/${serverId}/software`, { credentials: 'include' });
    return await res.json();
  } catch (e) {
    return [];
  }
}

// ── Add/Edit modal ────────────────────────────────────────────────────────────

async function openAddSwModal(presetServerId) {
  document.getElementById('modal-sw-title').textContent = 'Add Software';
  document.getElementById('sw-entry-id').value = '';
  ['sw-name','sw-version','sw-vendor','sw-install-path'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  document.getElementById('sw-license').value        = '';
  document.getElementById('sw-support-status').value = 'Supported';
  document.getElementById('sw-risk').value           = 'Low';
  document.getElementById('sw-discovered-by').value  = 'manual';
  await populateSwServerDropdown(presetServerId || '');
  openModal('modal-sw');
}

async function openEditSwModal(id) {
  const sw = allSoftware.find(s => s.id === id);
  if (!sw) return;
  document.getElementById('modal-sw-title').textContent = 'Edit Software';
  document.getElementById('sw-entry-id').value          = sw.id;
  document.getElementById('sw-name').value              = sw.name || '';
  document.getElementById('sw-version').value           = sw.version || '';
  document.getElementById('sw-vendor').value            = sw.vendor || '';
  document.getElementById('sw-license').value           = sw.license_type || '';
  document.getElementById('sw-support-status').value    = sw.support_status || 'Supported';
  document.getElementById('sw-risk').value              = sw.risk_rating || 'Low';
  document.getElementById('sw-install-path').value      = sw.install_path || '';
  document.getElementById('sw-discovered-by').value     = sw.discovered_by || 'manual';
  await populateSwServerDropdown(sw.server_id);
  openModal('modal-sw');
}

async function populateSwServerDropdown(selectedId) {
  const sel = document.getElementById('sw-server-id');
  if (!sel) return;
  try {
    const res = await fetch(`${API}/api/servers`, { credentials: 'include' });
    const servers = await res.json();
    let html = '<option value="">Select server...</option>';
    servers.forEach(s => {
      const sel2 = String(s.id) === String(selectedId) ? 'selected' : '';
      html += `<option value="${s.id}" ${sel2}>${esc(s.hostname)} (${esc(s.environment)})</option>`;
    });
    sel.innerHTML = html;
  } catch (e) {
    sel.innerHTML = '<option value="">Error loading servers</option>';
  }
}

async function saveSw() {
  const id = document.getElementById('sw-entry-id').value;
  const payload = {
    server_id:      document.getElementById('sw-server-id').value,
    name:           document.getElementById('sw-name').value.trim(),
    version:        document.getElementById('sw-version').value.trim(),
    vendor:         document.getElementById('sw-vendor').value.trim(),
    license_type:   document.getElementById('sw-license').value,
    support_status: document.getElementById('sw-support-status').value,
    risk_rating:    document.getElementById('sw-risk').value,
    install_path:   document.getElementById('sw-install-path').value.trim(),
    discovered_by:  document.getElementById('sw-discovered-by').value,
  };
  if (!payload.server_id) { toast('Please select a server', 'error'); return; }
  if (!payload.name)      { toast('Software name is required', 'error'); return; }
  try {
    const method = id ? 'PUT' : 'POST';
    const url    = id ? `${API}/api/software/${id}` : `${API}/api/software`;
    const res    = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    });
    if (!res.ok) { const e = await res.json(); toast(e.error || 'Error', 'error'); return; }
    closeModal('modal-sw');
    toast(id ? 'Software updated' : 'Software added', 'success');
    loadSoftware();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

function confirmDeleteSw(id, name) {
  document.getElementById('confirm-msg').textContent = `Delete "${name}" from software inventory?`;
  document.getElementById('confirm-ok-btn').textContent = 'Delete';
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    const res = await fetch(`${API}/api/software/${id}`, { method: 'DELETE', credentials: 'include' });
    if (res.ok) { toast('Software deleted', 'success'); loadSoftware(); }
    else toast('Error deleting software', 'error');
  };
  openModal('modal-confirm');
}

// ── Server detail panel integration ──────────────────────────────────────────

async function renderServerSoftwareSection(serverId) {
  const sw = await loadServerSoftware(serverId);
  if (!sw.length) {
    return `
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Software (0)</div>
      <div style="font-size:12px;color:var(--text3);padding:8px;background:var(--surface2);border-radius:var(--radius)">
        No software recorded. <a href="#" onclick="navigate('software');return false" style="color:var(--fnb-teal)">Go to Software Inventory</a> to add entries, or wait for agent auto-discovery.
      </div>`;
  }
  const eolCount  = sw.filter(s => s.support_status === 'End of Life').length;
  const highCount = sw.filter(s => s.risk_rating === 'High' || s.risk_rating === 'Critical').length;
  let warningHtml = '';
  if (eolCount > 0)
    warningHtml += `<div style="padding:6px 10px;background:var(--red-dim);border:1px solid var(--red);border-radius:6px;font-size:12px;color:var(--red);margin-bottom:8px">⚠ ${eolCount} End-of-Life software package${eolCount>1?'s':''} detected</div>`;
  if (highCount > 0)
    warningHtml += `<div style="padding:6px 10px;background:var(--yellow-dim);border:1px solid var(--yellow);border-radius:6px;font-size:12px;color:var(--yellow);margin-bottom:8px">⚠ ${highCount} High/Critical risk package${highCount>1?'s':''}</div>`;
  const sorted  = [...sw].sort((a, b) => {
    const order = { Critical: 0, High: 1, Medium: 2, Low: 3 };
    return (order[a.risk_rating] ?? 4) - (order[b.risk_rating] ?? 4);
  });
  const preview = sorted.slice(0, 5);
  return `
    <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Software (${sw.length})</div>
    ${warningHtml}
    <div class="table-wrap" style="margin-bottom:8px">
      <table>
        <thead><tr><th>Name</th><th>Version</th><th>Support</th><th>Risk</th></tr></thead>
        <tbody>
          ${preview.map(s => `<tr>
            <td style="font-size:12px;font-weight:600">${esc(s.name)}</td>
            <td style="font-size:11px;color:var(--text3)">${esc(s.version||'–')}</td>
            <td>${swStatusBadge(s.support_status)}</td>
            <td>${swRiskBadge(s.risk_rating)}</td>
          </tr>`).join('')}
          ${sw.length > 5 ? `<tr><td colspan="4" style="text-align:center;font-size:11px;color:var(--text3);padding:6px">… and ${sw.length - 5} more</td></tr>` : ''}
        </tbody>
      </table>
    </div>
    <div style="display:flex;gap:8px">
      <button class="btn btn-secondary btn-sm" onclick="navigate('software');swSetServerFilter('${serverId}')">
        📦 View All Software
      </button>
      <button class="btn btn-primary btn-sm" onclick="openAddSwModal(${serverId})">
        + Add Software
      </button>
    </div>`;
}

// ── Software Catalogue ────────────────────────────────────────────────────────

let allCatalogue = [];

async function loadCatalogue() {
  try {
    const res = await fetch(`${API}/api/software-catalogue`, { credentials: 'include' });
    allCatalogue = await res.json();
    renderCatalogueTable();
  } catch (e) {
    const el = document.getElementById('cat-tbody');
    if (el) el.innerHTML = `<tr><td colspan="7" style="color:var(--red);padding:20px">Error: ${esc(e.message)}</td></tr>`;
  }
}

function renderCatalogueTable() {
  const tbody = document.getElementById('cat-tbody');
  if (!tbody) return;
  if (!allCatalogue.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--text3)">
      <div style="font-size:32px;margin-bottom:8px">📋</div>
      <div>No catalogue rules yet. Add rules to auto-classify discovered software.</div>
    </td></tr>`;
    return;
  }
  tbody.innerHTML = allCatalogue.map(c => `<tr>
    <td style="font-family:monospace;font-size:12px;font-weight:600;color:var(--fnb-teal)">${esc(c.name_pattern)}</td>
    <td style="font-size:12px;color:var(--text2)">${esc(c.vendor||'–')}</td>
    <td style="font-size:12px;color:var(--text2)">${esc(c.license_type||'–')}</td>
    <td>${swStatusBadge(c.support_status)}</td>
    <td>${swRiskBadge(c.risk_rating)}</td>
    <td style="font-size:11px;color:var(--text3)">${esc(c.notes||'–')}</td>
    <td>
      <div style="display:flex;gap:4px">
        <button class="btn btn-secondary btn-sm btn-icon" onclick="openEditCatModal(${c.id})" title="Edit">
          <svg width="12" height="12"><use href="#ic-edit"/></svg>
        </button>
        <button class="btn btn-danger btn-sm btn-icon" onclick="confirmDeleteCat(${c.id},'${esc(c.name_pattern)}')" title="Delete">
          <svg width="12" height="12"><use href="#ic-trash"/></svg>
        </button>
      </div>
    </td>
  </tr>`).join('');
}

function openAddCatModal() {
  document.getElementById('modal-cat-title').textContent = 'Add Catalogue Rule';
  document.getElementById('cat-entry-id').value    = '';
  document.getElementById('cat-pattern').value     = '';
  document.getElementById('cat-vendor').value      = '';
  document.getElementById('cat-license').value     = '';
  document.getElementById('cat-status').value      = 'Supported';
  document.getElementById('cat-risk').value        = 'Low';
  document.getElementById('cat-notes').value       = '';
  openModal('modal-cat');
}

function openEditCatModal(id) {
  const c = allCatalogue.find(x => x.id === id);
  if (!c) return;
  document.getElementById('modal-cat-title').textContent = 'Edit Catalogue Rule';
  document.getElementById('cat-entry-id').value    = c.id;
  document.getElementById('cat-pattern').value     = c.name_pattern || '';
  document.getElementById('cat-vendor').value      = c.vendor || '';
  document.getElementById('cat-license').value     = c.license_type || '';
  document.getElementById('cat-status').value      = c.support_status || 'Supported';
  document.getElementById('cat-risk').value        = c.risk_rating || 'Low';
  document.getElementById('cat-notes').value       = c.notes || '';
  openModal('modal-cat');
}

async function saveCat() {
  const id = document.getElementById('cat-entry-id').value;
  const payload = {
    name_pattern:   document.getElementById('cat-pattern').value.trim(),
    vendor:         document.getElementById('cat-vendor').value.trim(),
    license_type:   document.getElementById('cat-license').value,
    support_status: document.getElementById('cat-status').value,
    risk_rating:    document.getElementById('cat-risk').value,
    notes:          document.getElementById('cat-notes').value.trim(),
  };
  if (!payload.name_pattern) { toast('Pattern is required', 'error'); return; }
  try {
    const method = id ? 'PUT' : 'POST';
    const url    = id ? `${API}/api/software-catalogue/${id}` : `${API}/api/software-catalogue`;
    const res    = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    });
    if (!res.ok) { const e = await res.json(); toast(e.error || 'Error', 'error'); return; }
    closeModal('modal-cat');
    toast(id ? 'Rule updated' : 'Rule added', 'success');
    loadCatalogue();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

function confirmDeleteCat(id, pattern) {
  document.getElementById('confirm-msg').textContent = `Delete catalogue rule "${pattern}"?`;
  document.getElementById('confirm-ok-btn').textContent = 'Delete';
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    const res = await fetch(`${API}/api/software-catalogue/${id}`, { method: 'DELETE', credentials: 'include' });
    if (res.ok) { toast('Rule deleted', 'success'); loadCatalogue(); }
    else toast('Error deleting rule', 'error');
  };
  openModal('modal-confirm');
}

async function applyCatalogue() {
  const btn = document.getElementById('cat-apply-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Applying...'; }
  try {
    const res  = await fetch(`${API}/api/software-catalogue/apply`, { method: 'POST', credentials: 'include' });
    const data = await res.json();
    toast(`Catalogue applied — ${data.enriched} software entries enriched`, 'success');
    loadSoftware();
  } catch (e) {
    toast('Error applying catalogue: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '⚡ Apply to All'; }
  }
}


// ═══════════════════════════════════════════
// VERSION CHECKS
// ═══════════════════════════════════════════

let allFindings  = [];
let allTrackers  = [];
let vcStatusFilter = '';

// ── Status badge ──────────────────────────────────────────────────────────────

function vcStatusBadge(status) {
  if (status === 'outdated')
    return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;background:var(--red-dim);color:var(--red)">⬆ Outdated</span>`;
  if (status === 'up_to_date')
    return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;background:var(--green-dim);color:var(--green)">✓ Up to Date</span>`;
  return `<span style="display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;background:var(--surface2);color:var(--text3)">? Unknown</span>`;
}

function vcCheckTypeBadge(type) {
  const map = {
    'github_release':         { label: 'GitHub',          color: 'var(--text2)' },
    'jenkins_update_center':  { label: 'Jenkins UC',      color: '#d97706' },
    'url_regex':              { label: 'URL+Regex',        color: 'var(--blue)' },
  };
  const s = map[type] || { label: type, color: 'var(--text3)' };
  return `<span style="font-size:11px;color:${s.color};font-weight:600">${esc(s.label)}</span>`;
}

// ── Summary ───────────────────────────────────────────────────────────────────

async function loadVcSummary() {
  try {
    const res  = await fetch(`${API}/api/version-findings/summary`, { credentials: 'include' });
    const data = await res.json();
    const setEl = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setEl('vc-outdated', data.outdated   ?? '–');
    setEl('vc-uptodate', data.up_to_date ?? '–');
    setEl('vc-unknown',  data.unknown    ?? '–');
    setEl('vc-servers',  data.servers_affected ?? '–');
    // Update sidebar badge
    const badge = document.getElementById('nav-outdated-badge');
    if (badge) {
      if (data.outdated > 0) {
        badge.textContent = data.outdated;
        badge.style.display = 'inline-block';
      } else {
        badge.style.display = 'none';
      }
    }
  } catch (e) { /* silent */ }
}

// ── Findings table ────────────────────────────────────────────────────────────

function vcSetStatus(val) {
  vcStatusFilter = val;
  document.querySelectorAll('#vc-status-filter .tf-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.vcstatus === val));
  renderVcFindings();
}

function renderVcFindings() {
  const tbody = document.getElementById('vc-findings-tbody');
  if (!tbody) return;
  const data = vcStatusFilter
    ? allFindings.filter(f => f.status === vcStatusFilter)
    : allFindings;

  if (!data.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text3)">
      <div style="font-size:32px;margin-bottom:8px">✅</div>
      <div>No findings yet — run a version check or wait for the next scheduled run (every 6 hours)</div>
    </td></tr>`;
    return;
  }

  tbody.innerHTML = data.map(f => {
    const isOutdated = f.status === 'outdated';
    const rowStyle   = isOutdated ? 'background:rgba(229,62,62,.04)' : '';
    return `<tr style="${rowStyle}">
      <td>
        <div style="font-size:12px;font-weight:600">${esc(f.hostname || '–')}</div>
        <div style="font-size:10px;color:var(--text3)">${esc(f.environment || '')}</div>
      </td>
      <td style="font-weight:600">${esc(f.display_name || f.sw_name)}</td>
      <td style="font-family:monospace;font-size:12px;color:${isOutdated ? 'var(--red)' : 'var(--text2)'}">
        ${esc(f.installed_ver || '–')}
      </td>
      <td style="font-family:monospace;font-size:12px;color:var(--green);font-weight:600">
        ${esc(f.latest_ver || '–')}
      </td>
      <td>${vcStatusBadge(f.status)}</td>
      <td style="font-size:11px;color:var(--text3)">${esc(f.last_seen ? f.last_seen.slice(0,16) : '–')}</td>
    </tr>`;
  }).join('');
}

async function loadVcFindings() {
  const tbody = document.getElementById('vc-findings-tbody');
  if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:30px"><div class="spinner" style="margin:0 auto"></div></td></tr>`;
  try {
    const res  = await fetch(`${API}/api/version-findings`, { credentials: 'include' });
    allFindings = await res.json();
    renderVcFindings();
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="6" style="color:var(--red);padding:20px">Error: ${esc(e.message)}</td></tr>`;
  }
}

// ── Trackers table ────────────────────────────────────────────────────────────

function renderVcTrackers() {
  const tbody = document.getElementById('vc-trackers-tbody');
  if (!tbody) return;
  if (!allTrackers.length) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:40px;color:var(--text3)">No trackers configured.</td></tr>`;
    return;
  }
  tbody.innerHTML = allTrackers.map(t => `<tr>
    <td style="font-weight:600">${esc(t.display_name)}</td>
    <td style="font-family:monospace;font-size:12px;color:var(--fnb-teal)">${esc(t.name_match)}</td>
    <td>${vcCheckTypeBadge(t.check_type)}</td>
    <td style="font-size:11px;color:var(--text3);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(t.check_source)}">${esc(t.check_source)}</td>
    <td style="font-family:monospace;font-size:12px;font-weight:600;color:var(--green)">${esc(t.latest_version || '–')}</td>
    <td style="font-size:11px;color:var(--text3)">${esc(t.last_checked ? t.last_checked.slice(0,16) : 'Never')}</td>
    <td>
      ${t.enabled
        ? '<span style="font-size:11px;color:var(--green);font-weight:600">✓ Yes</span>'
        : '<span style="font-size:11px;color:var(--text3)">No</span>'}
    </td>
    <td>
      <div style="display:flex;gap:4px">
        <button class="btn btn-secondary btn-sm btn-icon" onclick="openEditTrackerModal(${t.id})" title="Edit">
          <svg width="12" height="12"><use href="#ic-edit"/></svg>
        </button>
        <button class="btn btn-danger btn-sm btn-icon" onclick="confirmDeleteTracker(${t.id},'${esc(t.display_name)}')" title="Delete">
          <svg width="12" height="12"><use href="#ic-trash"/></svg>
        </button>
      </div>
    </td>
  </tr>`).join('');
}

async function loadVcTrackers() {
  try {
    const res  = await fetch(`${API}/api/version-tracker`, { credentials: 'include' });
    allTrackers = await res.json();
    renderVcTrackers();
  } catch (e) { /* silent */ }
}

// ── Page load ─────────────────────────────────────────────────────────────────

async function loadVersionChecksPage() {
  await Promise.all([loadVcSummary(), loadVcFindings(), loadVcTrackers()]);
}

// ── Run now ───────────────────────────────────────────────────────────────────

async function runVersionChecks() {
  const btn = document.getElementById('vc-run-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Running...'; }
  try {
    await fetch(`${API}/api/version-tracker/run`, { method: 'POST', credentials: 'include' });
    toast('Version check started — results will appear in ~30 seconds', 'success');
    setTimeout(() => loadVersionChecksPage(), 15000);
  } catch (e) {
    toast('Error: ' + e.message, 'error');
  } finally {
    setTimeout(() => {
      if (btn) { btn.disabled = false; btn.textContent = '▶ Run Now'; }
    }, 20000);
  }
}

// ── Add/Edit Tracker modal ────────────────────────────────────────────────────

function trackerCheckTypeChanged() {
  const type = document.getElementById('tracker-check-type')?.value;
  const srcLabel   = document.getElementById('tracker-source-label');
  const srcInput   = document.getElementById('tracker-check-source');
  const regexGroup = document.getElementById('tracker-regex-group');
  if (!srcLabel) return;
  if (type === 'github_release') {
    srcLabel.textContent = 'GitHub repo (owner/repo)';
    srcInput.placeholder = 'e.g. jenkinsci/jenkins';
    regexGroup.style.display = 'none';
  } else if (type === 'jenkins_update_center') {
    srcLabel.textContent = 'Update Center URL';
    srcInput.placeholder = 'https://updates.jenkins.io/stable/latestCore.txt';
    regexGroup.style.display = 'none';
  } else {
    srcLabel.textContent = 'URL to fetch';
    srcInput.placeholder = 'https://example.com/releases';
    regexGroup.style.display = 'block';
  }
}

function openAddTrackerModal() {
  document.getElementById('modal-tracker-title').textContent = 'Add Version Tracker';
  document.getElementById('tracker-entry-id').value    = '';
  document.getElementById('tracker-display-name').value = '';
  document.getElementById('tracker-name-match').value   = '';
  document.getElementById('tracker-check-type').value   = 'github_release';
  document.getElementById('tracker-check-source').value = '';
  document.getElementById('tracker-regex').value        = '';
  document.getElementById('tracker-notes').value        = '';
  document.getElementById('tracker-enabled').checked    = true;
  trackerCheckTypeChanged();
  openModal('modal-tracker');
}

function openEditTrackerModal(id) {
  const t = allTrackers.find(x => x.id === id);
  if (!t) return;
  document.getElementById('modal-tracker-title').textContent  = 'Edit Version Tracker';
  document.getElementById('tracker-entry-id').value           = t.id;
  document.getElementById('tracker-display-name').value       = t.display_name || '';
  document.getElementById('tracker-name-match').value         = t.name_match || '';
  document.getElementById('tracker-check-type').value         = t.check_type || 'github_release';
  document.getElementById('tracker-check-source').value       = t.check_source || '';
  document.getElementById('tracker-regex').value              = t.regex_pattern || '';
  document.getElementById('tracker-notes').value              = t.notes || '';
  document.getElementById('tracker-enabled').checked          = !!t.enabled;
  trackerCheckTypeChanged();
  openModal('modal-tracker');
}

async function saveTracker() {
  const id = document.getElementById('tracker-entry-id').value;
  const payload = {
    display_name:  document.getElementById('tracker-display-name').value.trim(),
    name_match:    document.getElementById('tracker-name-match').value.trim(),
    check_type:    document.getElementById('tracker-check-type').value,
    check_source:  document.getElementById('tracker-check-source').value.trim(),
    regex_pattern: document.getElementById('tracker-regex').value.trim(),
    notes:         document.getElementById('tracker-notes').value.trim(),
    enabled:       document.getElementById('tracker-enabled').checked,
  };
  if (!payload.display_name) { toast('Display name is required', 'error'); return; }
  if (!payload.name_match)   { toast('Name match is required', 'error'); return; }
  if (!payload.check_source) { toast('Check source is required', 'error'); return; }
  try {
    const method = id ? 'PUT' : 'POST';
    const url    = id ? `${API}/api/version-tracker/${id}` : `${API}/api/version-tracker`;
    const res    = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(payload),
    });
    if (!res.ok) { const e = await res.json(); toast(e.error || 'Error', 'error'); return; }
    closeModal('modal-tracker');
    toast(id ? 'Tracker updated' : 'Tracker added', 'success');
    loadVcTrackers();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

function confirmDeleteTracker(id, name) {
  document.getElementById('confirm-msg').textContent = `Delete version tracker "${name}"? This will also remove all findings for this tracker.`;
  document.getElementById('confirm-ok-btn').textContent = 'Delete';
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    const res = await fetch(`${API}/api/version-tracker/${id}`, { method: 'DELETE', credentials: 'include' });
    if (res.ok) { toast('Tracker deleted', 'success'); loadVersionChecksPage(); }
    else toast('Error deleting tracker', 'error');
  };
  openModal('modal-confirm');
}

// Load sidebar badge on startup
window.addEventListener('DOMContentLoaded', () => {
  setTimeout(loadVcSummary, 3000);
});


// ═══════════════════════════════════════════
// CSV EXPORT
// ═══════════════════════════════════════════

function ensureExportCsvButton() {
  const actions = document.getElementById('sw-tab-actions-inventory');
  if (!actions || document.getElementById('btn-export-sw-csv')) return;
  const btn = document.createElement('button');
  btn.id = 'btn-export-sw-csv';
  btn.className = 'btn btn-secondary';
  btn.innerHTML = '📥 Export CSV';
  btn.title = 'Download software inventory as CSV';
  btn.onclick = exportSwCsv;
  actions.appendChild(btn);
}

async function exportSwCsv() {
  const btn = document.getElementById('btn-export-sw-csv');
  if (!btn) return;

  // Loading state
  const originalText = btn.innerHTML;
  btn.innerHTML = '⏳ Exporting...';
  btn.disabled = true;

  try {
    let url = `${API}/api/software/export-csv`;
    if (swServerFilter) {
      url += `?server_id=${swServerFilter}`;
    }

    const res = await fetch(url, { credentials: 'include' });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Export failed' }));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    // Get filename from Content-Disposition header or use default
    let filename = 'software-inventory.csv';
    const disposition = res.headers.get('Content-Disposition');
    if (disposition) {
      const match = disposition.match(/filename="?([^"]+)"?/);
      if (match) filename = match[1];
    }

    // Download the file
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);

    toast('CSV exported successfully', 'success');
  } catch (e) {
    toast('Export failed: ' + e.message, 'error');
  } finally {
    btn.innerHTML = originalText;
    btn.disabled = false;
  }
}
