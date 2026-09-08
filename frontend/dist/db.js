// DATABASE MONITORS
let dbPreset = '24h';
let dbMonitors = [];
let extMetricsInterval = null;

function dbSetPreset(p) {
  dbPreset = p;
  document.querySelectorAll('#db-tf-presets .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.p === p));
  loadDatabases();
}

async function loadDatabases() {
  try {
    const res = await fetch(`${API}/api/db-monitors`, {credentials:'include'});
    dbMonitors = await res.json();
    renderDbSummary(dbMonitors);
    renderDbCards(dbMonitors);
  } catch(e) {
    document.getElementById('db-cards-grid').innerHTML = `<div style="color:var(--red);padding:20px">Error: ${esc(e.message)}</div>`;
  }
}

function renderDbSummary(dbs) {
  const total = dbs.length;
  const up    = dbs.filter(d => d.last_check?.status === 1).length;
  const down  = dbs.filter(d => d.last_check?.status === 0 && d.enabled).length;
  const lats  = dbs.map(d => d.last_check?.latency_ms).filter(v => v != null);
  const conns = dbs.map(d => d.last_check?.connections).filter(v => v != null);
  document.getElementById('db-total').textContent    = total;
  document.getElementById('db-up').textContent       = up;
  document.getElementById('db-down').textContent     = down;
  document.getElementById('db-avg-lat').textContent  = lats.length ? Math.round(lats.reduce((a,b)=>a+b,0)/lats.length)+'ms' : '-';
  document.getElementById('db-avg-conn').textContent = conns.length ? Math.round(conns.reduce((a,b)=>a+b,0)/conns.length) : '-';
}

function dbHealthBadge(db) {
  const last = db.last_check;
  if (!db.enabled) return {label:'PAUSED', cls:'badge-paused', color:'var(--text3)'};
  if (!last)       return {label:'PENDING', cls:'badge-pending', color:'var(--yellow)'};
  if (last.status === 1) return {label:'NORMAL', cls:'badge-up', color:'var(--green)'};
  return {label:'OFFLINE', cls:'badge-down', color:'var(--red)'};
}

function dbTypeIcon(type) {
  if (type === 'mssql')    return '🗄️';
  if (type === 'postgres') return '🐘';
  return '🔌';
}

function dbTypeName(type) {
  if (type === 'mssql')    return 'Microsoft SQL Server';
  if (type === 'postgres') return 'PostgreSQL';
  return 'TCP Monitor';
}

function renderDbCards(dbs) {
  const grid = document.getElementById('db-cards-grid');
  if (!dbs.length) {
    grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--text3)">
      <div style="font-size:48px;margin-bottom:16px">🗄️</div>
      <p style="font-size:15px;font-weight:600;margin-bottom:8px">No database monitors yet</p>
      <p style="font-size:13px;margin-bottom:20px">Add your MSSQL and PostgreSQL servers to start monitoring</p>
      <button class="btn btn-primary" onclick="openAddDbModal()">+ Add Database</button>
    </div>`;
    return;
  }

  const groups = {};
  dbs.forEach(d => {
    const g = d.group_name || 'General';
    if (!groups[g]) groups[g] = [];
    groups[g].push(d);
  });

  let html = '';
  Object.keys(groups).sort().forEach(g => {
    html += `<div style="grid-column:1/-1;font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.08em;padding:4px 0 8px;border-bottom:2px solid var(--border);margin-bottom:4px">${esc(g)}</div>`;
    groups[g].forEach(db => {
      const badge = dbHealthBadge(db);
      const last  = db.last_check;
      const lat   = last?.latency_ms != null ? last.latency_ms+'ms' : '–';
      const conn  = last?.connections != null ? last.connections : '–';
      const msg   = last?.msg || '';
      const checkedAt = last?.checked_at ? new Date(last.checked_at+'Z').toLocaleTimeString() : 'Never';
      const borderColor = badge.label === 'NORMAL' ? 'var(--green)' : badge.label === 'OFFLINE' ? 'var(--red)' : 'var(--border)';

      html += `
        <div class="card" style="border-left:4px solid ${borderColor};cursor:pointer;transition:box-shadow .15s"
             onclick="openDbDetail(${db.id})"
             onmouseover="this.style.boxShadow='var(--shadow-md)'"
             onmouseout="this.style.boxShadow=''">
          <div class="card-header" style="background:var(--surface)">
            <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
              <span style="font-size:22px">${dbTypeIcon(db.db_type)}</span>
              <div style="min-width:0;flex:1">
                <div style="font-size:14px;font-weight:700;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(db.name)}</div>
                <div style="font-size:11px;color:var(--text3)">${esc(db.host)}:${db.port}</div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
              <span class="badge ${badge.cls}">${badge.label}</span>
              <button class="btn btn-secondary btn-sm btn-icon" onclick="event.stopPropagation();openEditDbModal(${db.id})" title="Edit"><svg width="12" height="12"><use href="#ic-edit"/></svg></button>
              <button class="btn btn-danger btn-sm btn-icon" onclick="event.stopPropagation();confirmDeleteDb(${db.id},'${esc(db.name)}')" title="Delete"><svg width="12" height="12"><use href="#ic-trash"/></svg></button>
            </div>
          </div>
          <div class="card-body" style="padding:14px 18px">
            <div style="display:flex;gap:0;border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:14px">
              <div style="flex:1;text-align:center;padding:10px 6px;border-right:1px solid var(--border)">
                <div style="font-size:16px;font-weight:700;color:${badge.color}">${lat}</div>
                <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">Latency</div>
              </div>
              <div style="flex:1;text-align:center;padding:10px 6px;border-right:1px solid var(--border)">
                <div style="font-size:16px;font-weight:700;color:var(--blue)">${conn}</div>
                <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">Connections</div>
              </div>
              <div style="flex:1;text-align:center;padding:10px 6px">
                <div style="font-size:11px;font-weight:600;color:var(--text2)">${esc(dbTypeName(db.db_type))}</div>
                <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">Type</div>
              </div>
            </div>
            <div id="db-sparkline-${db.id}" style="height:36px;margin-bottom:8px">
              <div style="font-size:11px;color:var(--text3);text-align:center;padding:10px">Loading chart...</div>
            </div>
            ${badge.label === 'OFFLINE' && msg ? `
            <div style="display:flex;align-items:flex-start;gap:6px;padding:8px 10px;background:var(--red-dim);border:1px solid var(--red);border-radius:6px;margin-bottom:8px">
              <span style="color:var(--red);font-size:14px;flex-shrink:0">⚠</span>
              <div>
                <div style="font-size:11px;font-weight:700;color:var(--red);margin-bottom:2px">Error</div>
                <div style="font-size:11px;color:var(--red);word-break:break-word">${esc(msg)}</div>
              </div>
            </div>` : ''}
            <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text3)">
              <span style="color:${badge.label==='NORMAL'?'var(--green)':'var(--text3)'}">${badge.label==='NORMAL'?'✓ '+esc(msg):''}</span>
              <span>Last: ${checkedAt}</span>
            </div>
          </div>
        </div>`;
    });
  });

  grid.innerHTML = html;

  // Load sparklines for each DB
  dbs.forEach(db => loadDbSparkline(db.id));
}

async function loadDbSparkline(dbId) {
  try {
    const res  = await fetch(`${API}/api/db-monitors/${dbId}/heartbeats?preset=${dbPreset}&limit=100`, {credentials:'include'});
    const hbs  = await res.json();
    const wrap = document.getElementById('db-sparkline-' + dbId);
    if (!wrap) return;
    if (!hbs.length) { wrap.innerHTML = '<div style="font-size:11px;color:var(--text3);text-align:center;padding:10px">No data yet</div>'; return; }

    const canvas = document.createElement('canvas');
    canvas.width  = wrap.offsetWidth || 300;
    canvas.height = 36;
    canvas.style.width  = '100%';
    canvas.style.height = '36px';
    wrap.innerHTML = '';
    wrap.appendChild(canvas);

    const ctx = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    const PAD = {top:2, right:4, bottom:14, left:4};
    const cW = W - PAD.left - PAD.right;
    const cH = H - PAD.top - PAD.bottom;

    // Draw status bars
    const segW = Math.max(cW / hbs.length, 2);
    hbs.forEach((h, i) => {
      ctx.fillStyle = h.status === 1 ? '#1a9e5c' : '#e53e3e';
      ctx.fillRect(PAD.left + i * segW, PAD.top, Math.max(segW - 1, 1), cH);
    });

    // Time labels
    ctx.fillStyle = '#8a94a6';
    ctx.font = '9px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(new Date(hbs[0].checked_at+'Z').toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}), PAD.left, H-2);
    ctx.textAlign = 'right';
    ctx.fillText(new Date(hbs[hbs.length-1].checked_at+'Z').toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}), W-PAD.right, H-2);
  } catch(e) { /* silent */ }
}

function dbStateColor(state) {
  if (state === 'ONLINE') return 'var(--green, #22c55e)';
  if (state === 'OFFLINE') return 'var(--red, #ef4444)';
  if (state === 'RESTORING' || state === 'RECOVERING') return 'var(--yellow, #eab308)';
  return 'var(--text2, #888)';
}

async function openDbDetail(dbId) {
  // Clear any existing auto-refresh interval to avoid memory leaks
  if (extMetricsInterval) { clearInterval(extMetricsInterval); extMetricsInterval = null; }

  const panel = document.getElementById('db-detail-panel');
  const title = document.getElementById('db-detail-title');
  const body  = document.getElementById('db-detail-body');
  panel.style.display = '';
  panel.scrollIntoView({behavior:'smooth', block:'start'});

  try {
    const [statsRes, hbRes] = await Promise.all([
      fetch(`${API}/api/db-monitors/${dbId}/stats?preset=${dbPreset}`, {credentials:'include'}),
      fetch(`${API}/api/db-monitors/${dbId}/heartbeats?preset=${dbPreset}&limit=500`, {credentials:'include'})
    ]);
    const stats = await statsRes.json();
    const hbs   = await hbRes.json();
    const badge = dbHealthBadge(stats);

    // Fetch extended metrics for MSSQL monitors with credentials
    let extMetrics = null;
    if (stats.db_type === 'mssql' && stats.username) {
      try {
        const extRes = await fetch(`${API}/api/db-monitors/${dbId}/extended-metrics`, {credentials:'include'});
        if (extRes.ok) {
          extMetrics = await extRes.json();
        }
      } catch(ex) { /* silent — extended metrics are optional */ }
    }

    title.textContent = stats.name + ' — Detail';

    const uptime  = stats.uptime_pct  != null ? stats.uptime_pct.toFixed(2)+'%' : '–';
    const avgLat  = stats.avg_latency != null ? stats.avg_latency+'ms' : '–';
    const avgConn = stats.avg_connections != null ? stats.avg_connections : '–';
    const maxConn = stats.max_connections != null ? stats.max_connections : '–';

    // Determine Active Requests display value
    const activeRequestsVal = (stats.db_type === 'mssql' && stats.username && extMetrics && extMetrics.active_requests != null) ? extMetrics.active_requests : '–';

    // Build Active Requests stat box HTML (only for MSSQL with credentials)
    const activeRequestsBox = (stats.db_type === 'mssql' && stats.username)
      ? `<div class="stat-box"><div class="sv val-blue" id="db-ext-active-requests-val">${activeRequestsVal}</div><div class="sl">Active Requests</div></div>`
      : '';

    body.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap">
        <span style="font-size:32px">${dbTypeIcon(stats.db_type)}</span>
        <div>
          <div style="font-size:16px;font-weight:700">${esc(stats.name)}</div>
          <div style="font-size:12px;color:var(--text3)">${esc(stats.host)}:${stats.port}${stats.database ? ' / '+esc(stats.database) : ''}</div>
          <div style="font-size:11px;color:var(--text3);margin-top:2px">${esc(dbTypeName(stats.db_type))}</div>
        </div>
        <span class="badge ${badge.cls}" style="margin-left:auto;font-size:12px;padding:5px 14px">${badge.label}</span>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin-bottom:20px">
        <div class="stat-box"><div class="sv ${stats.uptime_pct>=99?'val-green':stats.uptime_pct>=90?'val-yellow':'val-red'}">${uptime}</div><div class="sl">Uptime</div></div>
        <div class="stat-box"><div class="sv val-blue">${avgLat}</div><div class="sl">Avg Latency</div></div>
        <div class="stat-box"><div class="sv val-yellow">${avgConn}</div><div class="sl">Avg Connections</div></div>
        <div class="stat-box"><div class="sv">${maxConn}</div><div class="sl">Peak Connections</div></div>
        <div class="stat-box"><div class="sv">${stats.total_checks}</div><div class="sl">Total Checks</div></div>
        ${activeRequestsBox}
      </div>

      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Response Time (ms)</div>
      <canvas id="db-detail-latency" height="80" style="width:100%;display:block;border-radius:6px;margin-bottom:16px"></canvas>

      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Connection Count</div>
      <canvas id="db-detail-conns" height="60" style="width:100%;display:block;border-radius:6px;margin-bottom:16px"></canvas>

      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Availability Timeline</div>
      <canvas id="db-detail-timeline" height="32" style="width:100%;display:block;border-radius:6px"></canvas>`;

    requestAnimationFrame(() => {
      drawDbLatencyChart('db-detail-latency', hbs);
      drawDbConnectionChart('db-detail-conns', hbs);
      drawDbTimeline('db-detail-timeline', hbs);
    });

    // Extended metrics: Running Queries table + Database List (only for MSSQL with credentials)
    if (stats.db_type === 'mssql' && stats.username) {
      fetchAndRenderExtendedMetrics(dbId, body);
      // Start 60-second auto-refresh for extended metrics
      extMetricsInterval = setInterval(() => fetchAndRenderExtendedMetrics(dbId, body), 60000);
    }
  } catch(e) {
    body.innerHTML = `<div style="color:var(--red)">Error: ${esc(e.message)}</div>`;
  }
}

async function fetchAndRenderExtendedMetrics(dbId, body) {
  // Create a container for extended metrics sections
  let extContainer = document.getElementById('db-ext-metrics-container');
  if (!extContainer) {
    extContainer = document.createElement('div');
    extContainer.id = 'db-ext-metrics-container';
    extContainer.style.marginTop = '20px';
    body.appendChild(extContainer);
  }

  // Show loading state for running queries, blocking queries, and database list
  extContainer.innerHTML = `
    <div id="db-ext-active-requests"></div>
    <div id="db-ext-long-running-queries">
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Long-Running Queries</div>
      <div style="font-size:12px;color:var(--text3);padding:12px">Loading...</div>
    </div>
    <div id="db-ext-running-queries">
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Running Queries</div>
      <div style="font-size:12px;color:var(--text3);padding:12px">Loading...</div>
    </div>
    <div id="db-ext-blocking-queries">
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Blocking Queries</div>
      <div style="font-size:12px;color:var(--text3);padding:12px">Loading...</div>
    </div>
    <div id="db-ext-database-list">
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Server Databases</div>
      <div style="font-size:12px;color:var(--text3);padding:12px">Loading...</div>
    </div>`;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000);

    const res = await fetch(`${API}/api/db-monitors/${dbId}/extended-metrics`, {
      credentials: 'include',
      signal: controller.signal
    });
    clearTimeout(timeoutId);

    if (!res.ok) {
      throw new Error(`API returned ${res.status}`);
    }

    const data = await res.json();
    // Update Active Requests stat box value
    const arEl = document.getElementById('db-ext-active-requests-val');
    if (arEl) { arEl.textContent = data.active_requests != null ? data.active_requests : '–'; }
    renderRunningQueries(data.running_queries);
    renderBlockingQueries(data.blocking_queries);
    renderLongRunningQueries(data.running_queries, data.long_running_threshold_seconds);
    renderThresholdControl(dbId, data.long_running_threshold_seconds || 5);
    renderDatabaseList(data.databases_list);
  } catch(e) {
    const section = document.getElementById('db-ext-running-queries');
    if (section) {
      const errMsg = e.name === 'AbortError' ? 'Request timed out — could not load running queries' : `Could not load running queries: ${esc(e.message)}`;
      section.innerHTML = `
        <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Running Queries</div>
        <div style="color:var(--red);font-size:12px;padding:12px;background:var(--red-dim);border:1px solid var(--red);border-radius:6px">${errMsg}</div>`;
    }
    const dbListSection = document.getElementById('db-ext-database-list');
    if (dbListSection) {
      dbListSection.innerHTML = `
        <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Server Databases</div>
        <div style="font-size:12px;color:var(--text3);padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;text-align:center">No database list available — credentials may be required</div>`;
    }
    const bqSection = document.getElementById('db-ext-blocking-queries');
    if (bqSection) {
      bqSection.innerHTML = `
        <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Blocking Queries</div>
        <div style="font-size:12px;color:var(--text3);padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;text-align:center">Could not load blocking queries</div>`;
    }
  }
}

function renderRunningQueries(queries) {
  const section = document.getElementById('db-ext-running-queries');
  if (!section) return;

  let html = `<div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Running Queries</div>`;

  if (!queries || queries.length === 0) {
    html += `<div style="font-size:12px;color:var(--text3);padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;text-align:center">No active queries</div>`;
    section.innerHTML = html;
    return;
  }

  // Sort by elapsed_time_ms descending, limit to 50
  const sorted = queries
    .slice()
    .sort((a, b) => (b.elapsed_time_ms || 0) - (a.elapsed_time_ms || 0))
    .slice(0, 50);

  html += `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;border:1px solid var(--border);border-radius:6px">
    <thead>
      <tr style="background:var(--surface);border-bottom:2px solid var(--border)">
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">SQL Text</th>
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">Status</th>
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">Wait Type</th>
        <th style="text-align:right;padding:8px 10px;font-weight:700;color:var(--text2)">Elapsed Time (ms)</th>
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">Database</th>
      </tr>
    </thead>
    <tbody>`;

  sorted.forEach((q, idx) => {
    const sqlText = q.sql_text || '';
    const truncated = sqlText.length > 200 ? sqlText.substring(0, 200) : sqlText;
    const needsExpand = sqlText.length > 200;
    const rowBg = idx % 2 === 0 ? '' : 'background:var(--surface);';
    const rowId = `rq-row-${idx}`;

    html += `<tr style="border-bottom:1px solid var(--border);${rowBg}">
        <td style="padding:8px 10px;font-family:monospace;font-size:11px;max-width:400px;word-break:break-all;color:var(--text)">
          <span id="${rowId}-short">${esc(truncated)}${needsExpand ? '…' : ''}</span>`;

    if (needsExpand) {
      html += `<span id="${rowId}-full" style="display:none">${esc(sqlText)}</span>
          <a href="#" id="${rowId}-toggle" onclick="event.preventDefault();toggleSqlText('${rowId}')" style="display:inline-block;margin-left:6px;font-size:10px;color:var(--blue);text-decoration:none;font-family:sans-serif">&#9654; Show more</a>`;
    }

    html += `</td>
        <td style="padding:8px 10px;white-space:nowrap;color:var(--text2)">${esc(q.status || '–')}</td>
        <td style="padding:8px 10px;white-space:nowrap;color:var(--text2)">${esc(q.wait_type || '–')}</td>
        <td style="padding:8px 10px;text-align:right;white-space:nowrap;font-weight:600;color:var(--text)">${q.elapsed_time_ms != null ? q.elapsed_time_ms.toLocaleString() : '–'}</td>
        <td style="padding:8px 10px;white-space:nowrap;color:var(--text2)">${esc(q.database_name || '–')}</td>
      </tr>`;
  });

  html += `</tbody></table></div>`;
  section.innerHTML = html;
}

function renderLongRunningQueries(queries, thresholdSeconds) {
  const section = document.getElementById('db-ext-long-running-queries');
  if (!section) return;

  const threshold = thresholdSeconds || 5;
  const thresholdMs = threshold * 1000;

  let html = `<div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Long-Running Queries <span style="font-weight:400;font-size:10px;text-transform:none">(threshold: ${threshold}s)</span></div>`;

  if (!queries || queries.length === 0) {
    html += `<div style="font-size:12px;color:var(--text3);padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;text-align:center">No long-running queries (threshold: ${threshold} seconds)</div>`;
    section.innerHTML = html;
    return;
  }

  // Filter to only queries exceeding threshold
  const longRunning = queries
    .filter(q => (q.elapsed_time_ms || 0) > thresholdMs)
    .sort((a, b) => (b.elapsed_time_ms || 0) - (a.elapsed_time_ms || 0));

  if (longRunning.length === 0) {
    html += `<div style="font-size:12px;color:var(--text3);padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;text-align:center">No long-running queries (threshold: ${threshold} seconds)</div>`;
    section.innerHTML = html;
    return;
  }

  html += `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;border:1px solid var(--border);border-radius:6px">
    <thead>
      <tr style="background:var(--surface);border-bottom:2px solid var(--border)">
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">SQL Text</th>
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">Status</th>
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">Wait Type</th>
        <th style="text-align:right;padding:8px 10px;font-weight:700;color:var(--text2)">Elapsed Time (ms)</th>
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">Database</th>
      </tr>
    </thead>
    <tbody>`;

  longRunning.forEach((q, idx) => {
    const sqlText = q.sql_text || '';
    const truncated = sqlText.length > 200 ? sqlText.substring(0, 200) : sqlText;
    const needsExpand = sqlText.length > 200;
    const rowId = `lrq-row-${idx}`;
    // Highlighted row background for long-running queries
    const rowBg = 'background:rgba(239,68,68,0.08);';

    html += `<tr style="border-bottom:1px solid var(--border);${rowBg}">
        <td style="padding:8px 10px;font-family:monospace;font-size:11px;max-width:400px;word-break:break-all;color:var(--text)">
          <span id="${rowId}-short">${esc(truncated)}${needsExpand ? '…' : ''}</span>`;

    if (needsExpand) {
      html += `<span id="${rowId}-full" style="display:none">${esc(sqlText)}</span>
          <a href="#" id="${rowId}-toggle" onclick="event.preventDefault();toggleSqlText('${rowId}')" style="display:inline-block;margin-left:6px;font-size:10px;color:var(--blue);text-decoration:none;font-family:sans-serif">&#9654; Show more</a>`;
    }

    html += `</td>
        <td style="padding:8px 10px;white-space:nowrap;color:var(--text2)">${esc(q.status || '–')}</td>
        <td style="padding:8px 10px;white-space:nowrap;color:var(--text2)">${esc(q.wait_type || '–')}</td>
        <td style="padding:8px 10px;text-align:right;white-space:nowrap;font-weight:600;color:var(--red)">${q.elapsed_time_ms != null ? q.elapsed_time_ms.toLocaleString() : '–'}</td>
        <td style="padding:8px 10px;white-space:nowrap;color:var(--text2)">${esc(q.database_name || '–')}</td>
      </tr>`;
  });

  html += `</tbody></table></div>`;
  section.innerHTML = html;
}

function renderDatabaseList(databases) {
  const section = document.getElementById('db-ext-database-list');
  if (!section) return;

  let html = `<div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Server Databases</div>`;

  if (!databases || databases.length === 0) {
    html += `<div style="font-size:12px;color:var(--text3);padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;text-align:center">No database list available — credentials may be required</div>`;
    section.innerHTML = html;
    return;
  }

  // Sort alphabetically by name
  const sorted = [...databases].sort((a, b) => a.name.localeCompare(b.name));

  html += `<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:12px;border:1px solid var(--border);border-radius:6px">
    <thead>
      <tr style="background:var(--surface);border-bottom:2px solid var(--border)">
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">Name</th>
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">State</th>
        <th style="text-align:left;padding:8px 10px;font-weight:700;color:var(--text2)">Compatibility Level</th>
      </tr>
    </thead>
    <tbody>`;

  sorted.forEach((db, idx) => {
    const stateColor = dbStateColor(db.state_desc || '');
    const rowBg = idx % 2 === 0 ? '' : 'background:var(--surface);';
    html += `<tr style="border-bottom:1px solid var(--border);${rowBg}">
        <td style="padding:6px 10px;color:var(--text)">${esc(db.name)}</td>
        <td style="padding:6px 10px;font-weight:600;color:${stateColor}">${esc(db.state_desc || '–')}</td>
        <td style="padding:6px 10px;color:var(--text2)">${db.compatibility_level != null ? db.compatibility_level : '–'}</td>
      </tr>`;
  });

  html += `</tbody></table></div>`;
  section.innerHTML = html;
}

function renderBlockingQueries(blockingChains) {
  const section = document.getElementById('db-ext-blocking-queries');
  if (!section) return;

  let html = `<div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px;margin-top:16px">Blocking Queries</div>`;

  if (!blockingChains || blockingChains.length === 0) {
    html += `<div style="font-size:12px;color:var(--text3);padding:12px;background:var(--surface);border:1px solid var(--border);border-radius:6px;text-align:center">No blocking queries detected</div>`;
    section.innerHTML = html;
    return;
  }

  html += `<div style="border:1px solid var(--border);border-radius:6px;overflow:hidden">`;

  blockingChains.forEach((chain, chainIdx) => {
    const headBlocker = chain.head_blocker;
    const blockedSessions = chain.blocked_sessions || [];
    const blockedCount = chain.blocked_count || blockedSessions.length;
    const headSql = headBlocker.sql_text || '';
    const headTruncated = headSql.length > 200 ? headSql.substring(0, 200) + '…' : headSql;
    const headRowId = `bq-head-${chainIdx}`;
    const chainBg = chainIdx % 2 === 0 ? '' : 'background:var(--surface);';

    // Head Blocker row (red accent)
    html += `<div style="padding:10px 12px;border-bottom:1px solid var(--border);${chainBg}">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
        <span style="background:var(--red);color:#fff;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700">HEAD BLOCKER</span>
        <span style="font-size:12px;font-weight:700;color:var(--text)">Session ${headBlocker.session_id}</span>
        <span style="font-size:11px;color:var(--text3);margin-left:auto">Blocking ${blockedCount} session${blockedCount !== 1 ? 's' : ''}</span>
      </div>
      <div style="font-family:monospace;font-size:11px;color:var(--text2);word-break:break-all">
        <span id="${headRowId}-short">${esc(headTruncated)}</span>`;

    if (headSql.length > 200) {
      html += `<span id="${headRowId}-full" style="display:none">${esc(headSql)}</span>
        <a href="#" id="${headRowId}-toggle" onclick="event.preventDefault();toggleSqlText('${headRowId}')" style="margin-left:6px;font-size:10px;color:var(--blue);text-decoration:none;font-family:sans-serif">&#9654; Show more</a>`;
    }
    html += `</div></div>`;

    // Blocked sessions (indented, orange accent) — cap at 50
    const displayBlocked = blockedSessions.slice(0, 50);
    displayBlocked.forEach((blocked, bIdx) => {
      const bSql = blocked.sql_text || '';
      const bTruncated = bSql.length > 200 ? bSql.substring(0, 200) + '…' : bSql;
      const bRowId = `bq-blocked-${chainIdx}-${bIdx}`;

      html += `<div style="padding:8px 12px 8px 36px;border-bottom:1px solid var(--border);background:var(--surface)">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;flex-wrap:wrap">
          <span style="background:var(--orange,#f59e0b);color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600">BLOCKED</span>
          <span style="font-size:12px;font-weight:600;color:var(--text)">Session ${blocked.session_id}</span>
          <span style="font-size:11px;color:var(--text3)">Wait: ${esc(blocked.wait_type || '–')}</span>
          <span style="font-size:11px;color:var(--text3)">Resource: ${esc(blocked.wait_resource || '–')}</span>
          <span style="font-size:11px;color:var(--text3)">Time: ${blocked.wait_time_ms != null ? blocked.wait_time_ms.toLocaleString() + 'ms' : '–'}</span>
        </div>
        <div style="font-family:monospace;font-size:11px;color:var(--text2);word-break:break-all">
          <span id="${bRowId}-short">${esc(bTruncated)}</span>`;

      if (bSql.length > 200) {
        html += `<span id="${bRowId}-full" style="display:none">${esc(bSql)}</span>
          <a href="#" id="${bRowId}-toggle" onclick="event.preventDefault();toggleSqlText('${bRowId}')" style="margin-left:6px;font-size:10px;color:var(--blue);text-decoration:none;font-family:sans-serif">&#9654; Show more</a>`;
      }
      html += `</div></div>`;
    });

    // Overflow indicator
    if (blockedSessions.length > 50) {
      html += `<div style="padding:6px 12px 6px 36px;font-size:11px;color:var(--text3);font-style:italic;border-bottom:1px solid var(--border)">… and ${blockedSessions.length - 50} more blocked sessions</div>`;
    }
  });

  html += `</div>`;
  section.innerHTML = html;
}

function toggleSqlText(rowId) {
  const shortEl = document.getElementById(rowId + '-short');
  const fullEl = document.getElementById(rowId + '-full');
  const toggleEl = document.getElementById(rowId + '-toggle');
  if (!shortEl || !fullEl || !toggleEl) return;

  if (fullEl.style.display === 'none') {
    shortEl.style.display = 'none';
    fullEl.style.display = 'inline';
    toggleEl.innerHTML = '&#9660; Show less';
  } else {
    shortEl.style.display = 'inline';
    fullEl.style.display = 'none';
    toggleEl.innerHTML = '&#9654; Show more';
  }
}

function drawDbLatencyChart(canvasId, hbs) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.width  = canvas.offsetWidth || 800;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const PAD = {top:8, right:8, bottom:20, left:44};
  const cW = W - PAD.left - PAD.right;
  const cH = H - PAD.top - PAD.bottom;

  const pts = hbs.filter(h => h.latency_ms != null && h.status === 1);
  ctx.fillStyle = '#f8fffe'; ctx.fillRect(0,0,W,H);
  if (pts.length < 2) { ctx.fillStyle='#8a94a6'; ctx.font='12px sans-serif'; ctx.textAlign='center'; ctx.fillText('Not enough data', W/2, H/2); return; }

  const times = pts.map(h => new Date(h.checked_at+'Z').getTime());
  const lats  = pts.map(h => h.latency_ms);
  const tMin = times[0], tMax = times[times.length-1], tRange = tMax-tMin||1;
  const lMin = 0, lMax = Math.max(...lats)*1.15||1, lRange = lMax-lMin;
  const tx = t => PAD.left + ((t-tMin)/tRange)*cW;
  const ty = l => PAD.top + cH - ((l-lMin)/lRange)*cH;

  // Grid
  ctx.strokeStyle='#eaecef'; ctx.lineWidth=1;
  for (let i=0;i<=4;i++) {
    const y = PAD.top + (cH/4)*i;
    ctx.beginPath(); ctx.moveTo(PAD.left,y); ctx.lineTo(W-PAD.right,y); ctx.stroke();
    ctx.fillStyle='#8a94a6'; ctx.font='9px sans-serif'; ctx.textAlign='right';
    ctx.fillText(Math.round(lMax-(lRange/4)*i)+'ms', PAD.left-4, y+3);
  }

  // Fill
  ctx.beginPath(); ctx.moveTo(tx(times[0]), ty(lats[0]));
  pts.forEach((_,i) => ctx.lineTo(tx(times[i]), ty(lats[i])));
  ctx.lineTo(tx(times[times.length-1]), PAD.top+cH);
  ctx.lineTo(tx(times[0]), PAD.top+cH); ctx.closePath();
  ctx.fillStyle='rgba(43,125,233,.1)'; ctx.fill();

  // Line
  ctx.beginPath(); ctx.strokeStyle='#2b7de9'; ctx.lineWidth=2; ctx.lineJoin='round';
  pts.forEach((_,i) => i===0 ? ctx.moveTo(tx(times[i]),ty(lats[i])) : ctx.lineTo(tx(times[i]),ty(lats[i])));
  ctx.stroke();

  // X labels
  ctx.fillStyle='#8a94a6'; ctx.font='9px sans-serif'; ctx.textAlign='center';
  [0,0.25,0.5,0.75,1].forEach(f => {
    const idx = Math.round(f*(pts.length-1));
    ctx.fillText(new Date(times[idx]).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}), tx(times[idx]), H-4);
  });
}

function drawDbConnectionChart(canvasId, hbs) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.width = canvas.offsetWidth || 800;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const PAD = {top:6, right:8, bottom:18, left:36};
  const cW = W-PAD.left-PAD.right, cH = H-PAD.top-PAD.bottom;

  const pts = hbs.filter(h => h.connections != null);
  ctx.fillStyle='#f8fffe'; ctx.fillRect(0,0,W,H);
  if (!pts.length) { ctx.fillStyle='#8a94a6'; ctx.font='11px sans-serif'; ctx.textAlign='center'; ctx.fillText('No connection data (credentials required)', W/2, H/2); return; }

  const times = pts.map(h => new Date(h.checked_at+'Z').getTime());
  const conns = pts.map(h => h.connections);
  const tMin=times[0], tMax=times[times.length-1], tRange=tMax-tMin||1;
  const cMax=Math.max(...conns)*1.2||1;
  const tx = t => PAD.left+((t-tMin)/tRange)*cW;
  const ty = c => PAD.top+cH-(c/cMax)*cH;

  // Bars
  const bW = Math.max(cW/pts.length-1, 2);
  pts.forEach((_,i) => {
    const h = (conns[i]/cMax)*cH;
    ctx.fillStyle='rgba(217,119,6,.7)';
    ctx.fillRect(tx(times[i]), PAD.top+cH-h, bW, h);
  });

  // Y label
  ctx.fillStyle='#8a94a6'; ctx.font='9px sans-serif'; ctx.textAlign='right';
  ctx.fillText(Math.round(cMax), PAD.left-4, PAD.top+8);
  ctx.fillText('0', PAD.left-4, PAD.top+cH);

  // X labels
  ctx.textAlign='center';
  [0,1].forEach(f => {
    const idx = Math.round(f*(pts.length-1));
    ctx.fillText(new Date(times[idx]).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}), tx(times[idx]), H-3);
  });
}

function drawDbTimeline(canvasId, hbs) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.width = canvas.offsetWidth || 800;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const PAD = {top:2, right:4, bottom:14, left:4};
  const cW = W-PAD.left-PAD.right, cH = H-PAD.top-PAD.bottom;

  ctx.fillStyle='#f8fffe'; ctx.fillRect(0,0,W,H);
  if (!hbs.length) return;

  const times = hbs.map(h => new Date(h.checked_at+'Z').getTime());
  const tMin=times[0], tMax=times[times.length-1], tRange=tMax-tMin||1;
  const tx = t => PAD.left+((t-tMin)/tRange)*cW;

  hbs.forEach((h,i) => {
    const t1=times[i], t2=i+1<hbs.length?times[i+1]:t1+60000;
    ctx.fillStyle = h.status===1?'#1a9e5c':'#e53e3e';
    ctx.fillRect(tx(t1), PAD.top, Math.max(tx(t2)-tx(t1)-1,2), cH);
  });

  ctx.strokeStyle='#dde1e7'; ctx.lineWidth=1;
  ctx.strokeRect(PAD.left, PAD.top, cW, cH);

  ctx.fillStyle='#8a94a6'; ctx.font='9px sans-serif';
  ctx.textAlign='left';  ctx.fillText(new Date(tMin).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}), PAD.left, H-2);
  ctx.textAlign='right'; ctx.fillText(new Date(tMax).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}), W-PAD.right, H-2);
}

// ── THRESHOLD CONFIGURATION CONTROL ─────────────

function renderThresholdControl(dbId, currentThreshold) {
  // Find or create the threshold control container within the long-running queries section
  let controlContainer = document.getElementById('db-ext-threshold-control');
  if (!controlContainer) {
    controlContainer = document.createElement('div');
    controlContainer.id = 'db-ext-threshold-control';
    controlContainer.style.cssText = 'display:inline-flex;align-items:center;gap:6px;margin-left:12px;font-size:11px;';
    // Insert it after the Long-Running Queries header
    const lrqSection = document.getElementById('db-ext-long-running-queries');
    if (lrqSection) {
      const header = lrqSection.querySelector('div');
      if (header) header.appendChild(controlContainer);
    }
  }

  controlContainer.innerHTML = `
    <label style="color:var(--text3);font-weight:400;text-transform:none">Threshold:</label>
    <input type="number" id="threshold-input" value="${currentThreshold}" min="1" max="3600" style="width:60px;padding:2px 6px;font-size:11px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--text)"/>
    <span style="color:var(--text3)">sec</span>
    <button id="threshold-save-btn" onclick="saveThreshold(${dbId})" style="padding:2px 8px;font-size:10px;background:var(--blue);color:#fff;border:none;border-radius:4px;cursor:pointer">Save</button>
    <span id="threshold-msg" style="font-size:10px;color:var(--text3)"></span>
  `;
}

async function saveThreshold(dbId) {
  const input = document.getElementById('threshold-input');
  const msg = document.getElementById('threshold-msg');
  if (!input || !msg) return;

  const val = parseInt(input.value, 10);
  if (isNaN(val) || val < 1 || val > 3600) {
    msg.style.color = 'var(--red)';
    msg.textContent = 'Must be 1-3600';
    return;
  }

  msg.style.color = 'var(--text3)';
  msg.textContent = 'Saving...';

  try {
    const res = await fetch(`${API}/api/db-monitors/${dbId}`, {
      method: 'PATCH',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ long_running_threshold_seconds: val })
    });

    if (!res.ok) {
      const data = await res.json();
      msg.style.color = 'var(--red)';
      msg.textContent = data.error || 'Failed';
      return;
    }

    msg.style.color = 'var(--green,#22c55e)';
    msg.textContent = '✓ Saved';

    // Re-fetch and re-render extended metrics immediately
    const body = document.getElementById('db-detail-body');
    if (body) {
      await fetchAndRenderExtendedMetrics(dbId, body);
    }

    // Clear success message after 2 seconds
    setTimeout(() => { if (msg) msg.textContent = ''; }, 2000);
  } catch(e) {
    msg.style.color = 'var(--red)';
    msg.textContent = 'Error: ' + e.message;
  }
}

// ── ADD / EDIT / DELETE DB MODAL ─────────────

function dbTypeChanged() {
  const type = document.getElementById('db-type').value;
  const portEl = document.getElementById('db-port');
  if (type === 'mssql')    portEl.value = 1433;
  if (type === 'postgres') portEl.value = 5432;
  if (type === 'tcp')      portEl.value = 1433;
}

function openAddDbModal() {
  document.getElementById('modal-db-title').textContent = 'Add Database Monitor';
  document.getElementById('db-id').value = '';
  document.getElementById('db-type').value = 'mssql';
  document.getElementById('db-name').value = '';
  document.getElementById('db-host').value = '';
  document.getElementById('db-port').value = '1433';
  document.getElementById('db-database').value = '';
  document.getElementById('db-username').value = '';
  document.getElementById('db-password').value = '';
  document.getElementById('db-interval').value = '60';
  document.getElementById('db-description').value = '';
  document.getElementById('db-group').value = '';
  document.getElementById('db-notify').checked = false;
  openModal('modal-db');
}

function openEditDbModal(id) {
  const db = dbMonitors.find(d => d.id === id);
  if (!db) return;
  document.getElementById('modal-db-title').textContent = 'Edit Database Monitor';
  document.getElementById('db-id').value = db.id;
  document.getElementById('db-type').value = db.db_type;
  document.getElementById('db-name').value = db.name;
  document.getElementById('db-host').value = db.host;
  document.getElementById('db-port').value = db.port;
  document.getElementById('db-database').value = db.database || '';
  document.getElementById('db-username').value = db.username || '';
  document.getElementById('db-password').value = '';
  document.getElementById('db-interval').value = db.interval;
  document.getElementById('db-description').value = db.description || '';
  document.getElementById('db-group').value = db.group_name || '';
  document.getElementById('db-notify').checked = !!db.notify_email;
  openModal('modal-db');
}

async function saveDbMonitor() {
  const id       = document.getElementById('db-id').value;
  const payload  = {
    name:         document.getElementById('db-name').value.trim(),
    db_type:      document.getElementById('db-type').value,
    host:         document.getElementById('db-host').value.trim(),
    port:         parseInt(document.getElementById('db-port').value),
    database:     document.getElementById('db-database').value.trim(),
    username:     document.getElementById('db-username').value.trim(),
    password:     document.getElementById('db-password').value,
    interval:     parseInt(document.getElementById('db-interval').value),
    description:  document.getElementById('db-description').value.trim(),
    group_name:   document.getElementById('db-group').value.trim(),
    notify_email: document.getElementById('db-notify').checked ? 1 : 0,
  };
  if (!payload.name || !payload.host) { toast('Name and host are required','error'); return; }
  try {
    const method = id ? 'PUT' : 'POST';
    const url    = id ? `${API}/api/db-monitors/${id}` : `${API}/api/db-monitors`;
    const res    = await fetch(url, {method, headers:{'Content-Type':'application/json'}, credentials:'include', body:JSON.stringify(payload)});
    if (!res.ok) { const e=await res.json(); toast(e.error||'Error','error'); return; }
    closeModal('modal-db');
    toast(id ? 'Database updated' : 'Database added','success');
    loadDatabases();
  } catch(e) { toast('Error: '+e.message,'error'); }
}

function confirmDeleteDb(id, name) {
  document.getElementById('confirm-msg').textContent = `Delete database monitor "${name}"?`;
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    const res = await fetch(`${API}/api/db-monitors/${id}`, {method:'DELETE', credentials:'include'});
    if (res.ok) { toast('Deleted','success'); loadDatabases(); }
    else toast('Error deleting','error');
  };
  openModal('modal-confirm');
}
// ── PUBLIC DB STATUS PAGE ─────────────────────

async function loadDbStatusPage() {
  // Hide app shell, hide service status view, show DB status view
  const appShell = document.getElementById('app-shell');
  const spView   = document.getElementById('status-page-view');
  const dbView   = document.getElementById('db-status-view');

  if (appShell) appShell.style.display = 'none';
  if (spView)   spView.classList.remove('open');
  if (dbView)   dbView.style.display = 'block';

  try {
    const res  = await fetch('/api/db-status/public');
    if (!res.ok) throw new Error('API returned ' + res.status);
    const dbs  = await res.json();
    renderDbStatusPage(dbs);
    const upd = document.getElementById('db-status-updated');
    if (upd) upd.textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch(e) {
    const grp = document.getElementById('db-status-groups');
    if (grp) grp.innerHTML = `<div style="color:var(--red);padding:20px;text-align:center">Error loading status: ${e.message}</div>`;
  }
}

function renderDbStatusPage(dbs) {
  const down = dbs.filter(d => d.enabled && d.last_check?.status === 0).length;
  const overall = document.getElementById('db-status-overall');
  const overallText = document.getElementById('db-status-overall-text');
  if (down > 0) {
    overall.className = 'sp-overall has-down';
    overallText.textContent = `${down} Database${down>1?'s':''} Offline`;
  } else {
    overall.className = 'sp-overall all-up';
    overallText.textContent = 'All Databases Operational';
  }

  const groups = {};
  dbs.forEach(d => {
    const g = d.group_name || 'General';
    if (!groups[g]) groups[g] = [];
    groups[g].push(d);
  });

  const dbTypeIcon = t => t==='mssql'?'🗄️':t==='postgres'?'🐘':'🔌';
  const dbTypeName = t => t==='mssql'?'SQL Server':t==='postgres'?'PostgreSQL':'TCP';

  let html = '';
  Object.keys(groups).sort().forEach(g => {
    const gDbs  = groups[g];
    const gDown = gDbs.filter(d => d.enabled && d.last_check?.status === 0).length;
    const gColor = gDown > 0 ? 'var(--red)' : 'var(--green)';

    html += `<div style="margin-bottom:28px">
      <div style="display:flex;align-items:center;gap:10px;padding:8px 4px;border-bottom:2px solid var(--border);margin-bottom:14px">
        <span style="font-size:12px;font-weight:800;color:var(--text);text-transform:uppercase;letter-spacing:.08em">${g}</span>
        <span style="font-size:11px;color:${gColor};font-weight:600">${gDown>0?gDown+' offline':'All operational'}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px">`;

    gDbs.forEach(db => {
      const last    = db.last_check;
      const isDown  = db.enabled && last?.status === 0;
      const isPaused = !db.enabled;
      const statusColor = isPaused ? 'var(--text3)' : isDown ? 'var(--red)' : 'var(--green)';
      const statusLabel = isPaused ? 'PAUSED' : isDown ? 'OFFLINE' : 'NORMAL';
      const statusCls   = isPaused ? 'badge-paused' : isDown ? 'badge-down' : 'badge-up';
      const lat   = last?.latency_ms != null ? last.latency_ms+'ms' : '–';
      const conn  = last?.connections != null ? last.connections : '–';
      const uptime = db.uptime_24h != null ? db.uptime_24h.toFixed(2)+'%' : '–';
      const msg   = last?.msg || '';
      const borderColor = isDown ? 'var(--red)' : isPaused ? 'var(--border)' : 'var(--green)';

      html += `
        <div style="background:var(--surface);border:1px solid var(--border);border-left:4px solid ${borderColor};border-radius:var(--radius);padding:16px;box-shadow:var(--shadow)">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
            <span style="font-size:20px">${dbTypeIcon(db.db_type)}</span>
            <div style="flex:1;min-width:0">
              <div style="font-size:14px;font-weight:700;color:var(--text)">${db.name}</div>
              <div style="font-size:11px;color:var(--text3)">${db.host}:${db.port}${db.database?' / '+db.database:''}</div>
            </div>
            <span class="badge ${statusCls}">${statusLabel}</span>
          </div>
          <div style="display:flex;gap:0;border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:${isDown&&msg?'10px':'0'}">
            <div style="flex:1;text-align:center;padding:8px 4px;border-right:1px solid var(--border)">
              <div style="font-size:14px;font-weight:700;color:${statusColor}">${lat}</div>
              <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">Latency</div>
            </div>
            <div style="flex:1;text-align:center;padding:8px 4px;border-right:1px solid var(--border)">
              <div style="font-size:14px;font-weight:700;color:var(--blue)">${conn}</div>
              <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">Connections</div>
            </div>
            <div style="flex:1;text-align:center;padding:8px 4px">
              <div style="font-size:14px;font-weight:700;color:${db.uptime_24h>=99?'var(--green)':db.uptime_24h>=90?'var(--yellow)':'var(--red)'}">${uptime}</div>
              <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">24h Uptime</div>
            </div>
          </div>
          ${isDown && msg ? `
          <div style="display:flex;align-items:flex-start;gap:6px;padding:8px 10px;background:var(--red-dim);border:1px solid var(--red);border-radius:6px;margin-top:10px">
            <span style="color:var(--red);font-size:13px;flex-shrink:0">⚠</span>
            <div style="font-size:11px;color:var(--red);word-break:break-word">${msg}</div>
          </div>` : ''}
        </div>`;
    });

    html += `</div></div>`;
  });

  document.getElementById('db-status-groups').innerHTML = html || '<div style="text-align:center;padding:40px;color:var(--text3)">No databases configured yet.</div>';
}

// Auto-refresh handled by app.js init