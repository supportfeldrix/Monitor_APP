// ═══════════════════════════════════════════
// SERVER INVENTORY
// ═══════════════════════════════════════════
let allServers   = [];
let srvEnvFilter = '';

function srvSetEnv(env) {
  srvEnvFilter = env;
  document.querySelectorAll('#srv-env-filter .tf-btn').forEach(b => b.classList.toggle('active', b.dataset.env === env));
  loadServers();
}

function srvFilterCards() {
  const q = (document.getElementById('srv-search')?.value || '').toLowerCase();
  document.querySelectorAll('.srv-card').forEach(card => {
    const text = card.dataset.search || '';
    card.style.display = (!q || text.includes(q)) ? '' : 'none';
  });
}

function renderServerSummary(servers) {
  document.getElementById('srv-total').textContent    = servers.length;
  document.getElementById('srv-healthy').textContent  = servers.filter(s=>s.health==='healthy').length;
  document.getElementById('srv-degraded').textContent = servers.filter(s=>s.health==='degraded').length;
  document.getElementById('srv-critical').textContent = servers.filter(s=>s.health==='critical').length;
  document.getElementById('srv-prod').textContent     = servers.filter(s=>s.environment==='PROD').length;
  document.getElementById('srv-uat').textContent      = servers.filter(s=>s.environment==='UAT').length;
}

function srvHealthColor(h) {
  return h==='healthy'?'var(--green)':h==='degraded'?'var(--yellow)':h==='critical'?'var(--red)':'var(--text3)';
}
function srvHealthBadge(h) {
  const cls = h==='healthy'?'badge-up':h==='degraded'?'badge-pending':h==='critical'?'badge-down':'badge-paused';
  const lbl = (h||'unknown').toUpperCase();
  return `<span class="badge ${cls}">${lbl}</span>`;
}
function srvEnvBadge(env) {
  const color = env==='PROD'?'var(--blue)':env==='UAT'?'var(--yellow)':env==='INT'?'#8b5cf6':env==='PRE'?'#f97316':'var(--text3)';
  return `<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;background:rgba(43,125,233,.1);color:${color};border:1px solid ${color}">${env||'?'}</span>`;
}
function srvOsIcon(os) {
  if (!os) return '🖥️';
  const o = os.toLowerCase();
  if (o.includes('red hat')||o.includes('rhel')||o.includes('enterprise')) return '🎩';
  if (o.includes('ubuntu')||o.includes('debian')) return '🐧';
  if (o.includes('windows')) return '🪟';
  if (o.includes('centos')) return '⚙️';
  return '🖥️';
}
function fmtUptime(sec) {
  if (!sec) return '–';
  const d = Math.floor(sec/86400), h = Math.floor((sec%86400)/3600), m = Math.floor((sec%3600)/60);
  if (d>0) return `${d}d ${h}h`;
  if (h>0) return `${h}h ${m}m`;
  return `${m}m`;
}
function gauge(pct, warn=70, crit=90) {
  if (pct==null) return '–';
  const color = pct>=crit?'var(--red)':pct>=warn?'var(--yellow)':'var(--green)';
  return `<span style="color:${color};font-weight:700">${pct}%</span>`;
}
function renderServerCards(servers) {
  const grid = document.getElementById('srv-cards-grid');
  if (!servers.length) {
    grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:60px 20px;color:var(--text3)">
      <div style="font-size:48px;margin-bottom:16px">🖥️</div>
      <p style="font-size:15px;font-weight:600;margin-bottom:8px">No servers yet</p>
      <p style="font-size:13px;margin-bottom:20px">Add your servers to start tracking inventory</p>
      <button class="btn btn-primary" onclick="openAddServerModal()">+ Add Server</button>
    </div>`;
    return;
  }
  let html = '';
  servers.forEach(s => {
    const hColor = srvHealthColor(s.health);
    const m = s.latest_metrics;
    const cpuVal  = m ? gauge(m.cpu_pct,70,90)  : '–';
    const ramVal  = m ? gauge(m.ram_pct,70,90)  : '–';
    const diskVal = m ? gauge(m.disk_pct,80,95) : '–';
    const uptime  = m ? fmtUptime(m.uptime_sec) : '–';
    const agentOnline = m && m.collected_at ?
      (new Date() - new Date(m.collected_at+'Z')) < 180000 : false;
    const agentDot = agentOnline
      ? `<span style="width:7px;height:7px;border-radius:50%;background:var(--green);display:inline-block;margin-right:4px" title="Agent online"></span>`
      : `<span style="width:7px;height:7px;border-radius:50%;background:var(--border);display:inline-block;margin-right:4px" title="No agent data"></span>`;
    const searchText = `${s.hostname} ${s.ip_address||''} ${s.role||''} ${s.os||''} ${s.environment}`.toLowerCase();
    html += `
      <div class="card srv-card" data-search="${esc(searchText)}"
           style="border-left:4px solid ${hColor};cursor:pointer;transition:box-shadow .15s"
           onclick="openServerDetail(${s.id})"
           onmouseover="this.style.boxShadow='var(--shadow-md)'"
           onmouseout="this.style.boxShadow=''">
        <div class="card-header" style="background:var(--surface)">
          <div style="display:flex;align-items:center;gap:10px;flex:1;min-width:0">
            <span style="font-size:22px">${srvOsIcon(s.os)}</span>
            <div style="min-width:0;flex:1">
              <div style="font-size:14px;font-weight:700;color:var(--text)">${esc(s.hostname)}</div>
              <div style="font-size:11px;color:var(--text3)">${esc(s.ip_address||'')} ${s.os?'· '+esc(s.os):''}</div>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;flex-shrink:0;flex-wrap:wrap">
            ${srvEnvBadge(s.environment)}
            ${srvHealthBadge(s.health)}
            <button class="btn btn-secondary btn-sm btn-icon" onclick="event.stopPropagation();openEditServerModal(${s.id})" title="Edit"><svg width="12" height="12"><use href="#ic-edit"/></svg></button>
            <button class="btn btn-danger btn-sm btn-icon" onclick="event.stopPropagation();confirmDeleteServer(${s.id},'${esc(s.hostname)}')" title="Delete"><svg width="12" height="12"><use href="#ic-trash"/></svg></button>
          </div>
        </div>
        <div class="card-body" style="padding:12px 18px">
          ${s.role ? `<div style="font-size:12px;color:var(--text2);margin-bottom:10px">📋 ${esc(s.role)}</div>` : ''}
          <div style="display:flex;gap:0;border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:10px">
            <div style="flex:1;text-align:center;padding:8px 4px;border-right:1px solid var(--border)">
              <div style="font-size:13px;font-weight:700">${cpuVal}</div>
              <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">CPU</div>
            </div>
            <div style="flex:1;text-align:center;padding:8px 4px;border-right:1px solid var(--border)">
              <div style="font-size:13px;font-weight:700">${ramVal}</div>
              <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">RAM</div>
            </div>
            <div style="flex:1;text-align:center;padding:8px 4px;border-right:1px solid var(--border)">
              <div style="font-size:13px;font-weight:700">${diskVal}</div>
              <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">Disk</div>
            </div>
            <div style="flex:1;text-align:center;padding:8px 4px">
              <div style="font-size:13px;font-weight:700;color:var(--text2)">${s.total_monitors}</div>
              <div style="font-size:9px;color:var(--text3);text-transform:uppercase;margin-top:2px">Services</div>
            </div>
          </div>
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text3)">
            <span>${agentDot}${agentOnline?'Agent: '+uptime+' uptime':'No agent'}</span>
            <span style="color:${s.down_count>0?'var(--red)':'var(--green)'}">${s.up_count}/${s.total_monitors} up</span>
          </div>
          <div style="margin-top:6px">${alertsBadge(getServerAlerts(s, s.latest_metrics))}</div>
        </div>
      </div>`;
  });
  grid.innerHTML = html;
}
async function openServerDetail(id) {
  const panel = document.getElementById('srv-detail-panel');
  const title = document.getElementById('srv-detail-title');
  const body  = document.getElementById('srv-detail-body');
  panel.style.display = '';
  panel.scrollIntoView({behavior:'smooth',block:'start'});
  title.textContent = 'Loading...';
  body.innerHTML = '<div class="loading-center" style="padding:20px"><div class="spinner"></div></div>';
  try {
    const [srvRes, metRes] = await Promise.all([
      fetch(`${API}/api/servers/${id}`, {credentials:'include'}),
      fetch(`${API}/api/agent/metrics/${id}?limit=60`, {credentials:'include'})
    ]);
    const s   = await srvRes.json();
    const met = await metRes.json();
    title.textContent = s.hostname + ' — Detail';
    const m = met.latest;
    const agentOnline = m && m.collected_at ? (new Date()-new Date(m.collected_at+'Z'))<180000 : false;
    const osStr = m ? `${m.os_name||''} ${m.os_version||''}`.trim() : (s.os||'–');
    const kernelStr = m?.kernel || '–';
    const cpuVal  = m ? gauge(m.cpu_pct,70,90)  : '–';
    const ramVal  = m ? `${gauge(m.ram_pct,70,90)} (${m.ram_used_gb}/${m.ram_total_gb} GB)` : '–';
    const diskVal = m ? `${gauge(m.disk_pct,80,95)} (${m.disk_used_gb}/${m.disk_total_gb} GB)` : '–';
    const loadVal = m ? `${m.load_1m} / ${m.load_5m} / ${m.load_15m}` : '–';
    const uptimeVal = m ? fmtUptime(m.uptime_sec) : '–';
    const procVal = m?.process_count || '–';
    const lastSeen = met.last_seen ? new Date(met.last_seen+'Z').toLocaleString() : 'Never';

    // OS version check
    let osWarning = '';
    if (osStr) {
      const ol = osStr.toLowerCase();
      if (ol.includes('rhel 7')||ol.includes('red hat enterprise linux 7')||ol.includes('centos 7'))
        osWarning = `<div style="padding:8px 12px;background:var(--red-dim);border:1px solid var(--red);border-radius:6px;font-size:12px;color:var(--red);margin-bottom:12px">⚠ OS is end-of-life: ${esc(osStr)} — upgrade to RHEL 9 recommended</div>`;
      else if (ol.includes('rhel 8')||ol.includes('red hat enterprise linux 8'))
        osWarning = `<div style="padding:8px 12px;background:var(--yellow-dim);border:1px solid var(--yellow);border-radius:6px;font-size:12px;color:var(--yellow);margin-bottom:12px">⚠ ${esc(osStr)} — RHEL 9 available, consider upgrading</div>`;
    }

    body.innerHTML = `
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap">
        <span style="font-size:36px">${srvOsIcon(s.os)}</span>
        <div style="flex:1">
          <div style="font-size:16px;font-weight:700">${esc(s.hostname)}</div>
          <div style="font-size:12px;color:var(--text3)">${esc(s.ip_address||'')} · ${esc(osStr)} · Kernel: ${esc(kernelStr)}</div>
          ${s.role?`<div style="font-size:12px;color:var(--text2);margin-top:2px">📋 ${esc(s.role)}</div>`:''}
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          ${srvEnvBadge(s.environment)}
          ${srvHealthBadge(s.health)}
          <span style="font-size:11px;color:${agentOnline?'var(--green)':'var(--text3)'}">
            ${agentOnline?'● Agent online':'○ No agent'}
          </span>
        </div>
      </div>
      ${osWarning}
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:20px">
        <div class="stat-box"><div class="sv">${cpuVal}</div><div class="sl">CPU Usage</div></div>
        <div class="stat-box"><div class="sv" style="font-size:13px">${ramVal}</div><div class="sl">RAM</div></div>
        <div class="stat-box"><div class="sv" style="font-size:13px">${diskVal}</div><div class="sl">Disk (/)</div></div>
        <div class="stat-box"><div class="sv val-blue">${uptimeVal}</div><div class="sl">Uptime</div></div>
        <div class="stat-box"><div class="sv" style="font-size:13px">${loadVal}</div><div class="sl">Load 1/5/15m</div></div>
        <div class="stat-box"><div class="sv">${procVal}</div><div class="sl">Processes</div></div>
      </div>
      ${(() => {
        const alerts = getServerAlerts(s, m);
        if (!alerts.length) return '';
        return `<div style="padding:10px 14px;background:${alerts.some(a=>a.level==='critical')?'var(--red-dim)':'var(--yellow-dim)'};border:1px solid ${alerts.some(a=>a.level==='critical')?'var(--red)':'var(--yellow)'};border-radius:var(--radius);margin-bottom:16px">
          <div style="font-size:11px;font-weight:700;color:${alerts.some(a=>a.level==='critical')?'var(--red)':'var(--yellow)'};margin-bottom:6px">⚠ ${alerts.length} Active Alert${alerts.length>1?'s':''}</div>
          ${alerts.map(a=>`<div style="font-size:12px;color:var(--text2);padding:2px 0">${a.level==='critical'?'🔴':'🟡'} ${esc(a.msg)}</div>`).join('')}
        </div>`;
      })()}
      ${met.history.length>1?`
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">CPU & RAM History (last ${met.history.length} checks)</div>
      <canvas id="srv-metrics-chart" height="80" style="width:100%;display:block;border-radius:6px;margin-bottom:16px"></canvas>`:''}
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Specs</div>
      <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--text2);margin-bottom:16px;padding:12px 16px;background:var(--surface2);border-radius:var(--radius)">
        <span>💻 CPU: ${m?.cpu_cores ? m.cpu_cores+' cores' : s.cpu_cores ? s.cpu_cores+' cores' : '–'}${m?.cpu_threads?' / '+m.cpu_threads+' threads':''}</span>
        <span>🧠 RAM: ${m?.ram_total_gb ? m.ram_total_gb+' GB' : s.ram_gb ? s.ram_gb+' GB' : '–'}</span>
        <span>💾 Disk: ${s.disk_gb?s.disk_gb+' GB':'–'}</span>
        <span>📍 Location: ${esc(s.location||'–')}</span>
        <span>🛡️ Last Patched: ${patchBadge(s.last_patched)}</span>
        ${renderPatchBadge(s.patch_info)}
        <span>🕐 Agent last seen: ${lastSeen}</span>
      </div>
      ${m?.disk_mounts?.length ? `
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Disk Mount Breakdown</div>
      <div style="margin-bottom:16px">${renderDiskMounts(m.disk_mounts)}</div>` : ''}
      ${s.notes?`<div style="font-size:12px;color:var(--text2);padding:10px 14px;background:var(--surface2);border-radius:var(--radius);margin-bottom:16px;border-left:3px solid var(--fnb-teal)">📝 ${esc(s.notes)}</div>`:''}
      <div style="font-size:11px;font-weight:700;color:var(--text3);text-transform:uppercase;margin-bottom:8px">Linked Services (${s.monitors.length})</div>
      ${s.monitors.length?`
      <div class="table-wrap"><table>
        <thead><tr><th>Service</th><th>URL / Host</th><th>Status</th><th>Latency</th><th>Last Check</th></tr></thead>
        <tbody>${s.monitors.map(mon=>{
          const stColor = mon.status==='up'?'var(--green)':mon.status==='down'?'var(--red)':'var(--text3)';
          const icon = mon.type==='database'?(mon.db_type==='postgres'?'🐘':'🗄️'):'🌐';
          return `<tr>
            <td>${icon} <strong>${esc(mon.name)}</strong></td>
            <td style="font-size:11px;color:var(--text3)">${esc(mon.url)}</td>
            <td><span style="color:${stColor};font-weight:700;text-transform:uppercase">${mon.status}</span></td>
            <td>${mon.latency_ms!=null?mon.latency_ms+'ms':'–'}</td>
            <td style="font-size:11px;color:var(--text3)">${mon.checked_at?new Date(mon.checked_at+'Z').toLocaleTimeString():'–'}</td>
          </tr>`;
        }).join('')}</tbody>
      </table></div>`:'<div style="font-size:12px;color:var(--text3);padding:8px">No services linked. Edit this server to add monitors.</div>'}

      <div style="margin-top:16px;display:flex;flex-direction:column;gap:8px">
        <div class="srv-collapse-section" style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden">
          <div onclick="toggleSrvSection(this)" style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);cursor:pointer;user-select:none">
            <span style="font-size:12px;font-weight:700;color:var(--text2)">📦 Software Inventory</span>
            <span class="srv-collapse-arrow" style="font-size:10px;color:var(--text3);transition:transform .2s">▼</span>
          </div>
          <div class="srv-collapse-body" style="display:none;padding:12px 14px" id="srv-sw-section-${s.id}">
            <div class="loading-center" style="padding:12px"><div class="spinner" style="width:14px;height:14px"></div></div>
          </div>
        </div>

        <div class="srv-collapse-section" style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden">
          <div onclick="toggleSrvSection(this)" style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);cursor:pointer;user-select:none">
            <span style="font-size:12px;font-weight:700;color:var(--text2)">🔍 Discovered Services</span>
            <span class="srv-collapse-arrow" style="font-size:10px;color:var(--text3);transition:transform .2s">▼</span>
          </div>
          <div class="srv-collapse-body" style="display:none;padding:12px 14px" id="srv-services-section-${s.id}">
            <div class="loading-center" style="padding:12px"><div class="spinner" style="width:14px;height:14px"></div></div>
          </div>
        </div>

        <div class="srv-collapse-section" style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden">
          <div onclick="toggleSrvSection(this)" style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--surface2);cursor:pointer;user-select:none">
            <span style="font-size:12px;font-weight:700;color:var(--text2)">📂 Folder Sizes</span>
            <span class="srv-collapse-arrow" style="font-size:10px;color:var(--text3);transition:transform .2s">▼</span>
          </div>
          <div class="srv-collapse-body" style="display:none;padding:12px 14px" id="srv-folders-section-${s.id}">
          </div>
        </div>
      </div>

      <div style="margin-top:16px;display:flex;gap:8px">
        <button class="btn btn-primary btn-sm" onclick="openEditServerModal(${s.id})">✏️ Edit Server</button>
        <button class="btn btn-secondary btn-sm" onclick="showAgentSetup(${s.id},'${esc(s.hostname)}')">🤖 Agent Setup</button>
      </div>`;

    if (met.history.length > 1) {
      requestAnimationFrame(() => drawSrvMetricsChart('srv-metrics-chart', met.history));
    }
    // Load software section asynchronously
    renderServerSoftwareSection(s.id).then(html => {
      const swEl = document.getElementById(`srv-sw-section-${s.id}`);
      if (swEl) swEl.innerHTML = html;
    });
    // Load discovered services section asynchronously
    renderServerServicesSection(s.id).then(html => {
      const svcEl = document.getElementById(`srv-services-section-${s.id}`);
      if (svcEl) svcEl.innerHTML = html;
    });
    // Load folder sizes section asynchronously
    renderFolderSizesSection(s.id).then(html => {
      const fldEl = document.getElementById(`srv-folders-section-${s.id}`);
      if (fldEl) fldEl.innerHTML = html;
    });
  } catch(e) {
    body.innerHTML = `<div style="color:var(--red)">Error: ${esc(e.message)}</div>`;
  }
}

function drawSrvMetricsChart(canvasId, history) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.width  = canvas.offsetWidth || 800;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  const PAD = {top:8,right:8,bottom:20,left:36};
  const cW = W-PAD.left-PAD.right, cH = H-PAD.top-PAD.bottom;
  ctx.fillStyle='#f8fffe'; ctx.fillRect(0,0,W,H);
  ctx.strokeStyle='#eaecef'; ctx.lineWidth=1;
  [0,25,50,75,100].forEach(v=>{
    const y=PAD.top+cH-(v/100)*cH;
    ctx.beginPath();ctx.moveTo(PAD.left,y);ctx.lineTo(W-PAD.right,y);ctx.stroke();
    ctx.fillStyle='#8a94a6';ctx.font='9px sans-serif';ctx.textAlign='right';
    ctx.fillText(v+'%',PAD.left-4,y+3);
  });
  const n=history.length;
  const tx=i=>PAD.left+(i/(n-1))*cW;
  const ty=v=>PAD.top+cH-((v||0)/100)*cH;
  // RAM line (blue)
  ctx.beginPath();ctx.strokeStyle='rgba(43,125,233,.8)';ctx.lineWidth=2;ctx.lineJoin='round';
  history.forEach((h,i)=>i===0?ctx.moveTo(tx(i),ty(h.ram_pct)):ctx.lineTo(tx(i),ty(h.ram_pct)));
  ctx.stroke();
  // CPU line (teal)
  ctx.beginPath();ctx.strokeStyle='rgba(0,169,157,.9)';ctx.lineWidth=2;ctx.lineJoin='round';
  history.forEach((h,i)=>i===0?ctx.moveTo(tx(i),ty(h.cpu_pct)):ctx.lineTo(tx(i),ty(h.cpu_pct)));
  ctx.stroke();
  // Legend
  ctx.fillStyle='rgba(0,169,157,.9)';ctx.fillRect(PAD.left,H-14,12,8);
  ctx.fillStyle='#4a5568';ctx.font='9px sans-serif';ctx.textAlign='left';ctx.fillText('CPU',PAD.left+15,H-7);
  ctx.fillStyle='rgba(43,125,233,.8)';ctx.fillRect(PAD.left+45,H-14,12,8);
  ctx.fillStyle='#4a5568';ctx.fillText('RAM',PAD.left+60,H-7);
}
async function showAgentSetup(serverId, hostname) {
  const token_res = await fetch(`${API}/api/agent/token/${serverId}`, {credentials:'include'});
  const token_data = await token_res.json();
  let token = token_data.token;
  if (!token) {
    const gen = await fetch(`${API}/api/agent/token/${serverId}`, {method:'POST',credentials:'include'});
    const gd  = await gen.json();
    token = gd.token;
  }
  document.getElementById('confirm-msg').innerHTML = `
    <div style="font-size:13px">
      <p style="margin-bottom:12px">Run this on <strong>${hostname}</strong> to install the agent:</p>
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:12px;font-family:monospace;font-size:11px;word-break:break-all;margin-bottom:12px">
        cp /home/f5151422/Podman_Dashboard_UAT/LINUX_SETUP/agent.py ~/agent.py<br><br>
        python3 ~/agent.py --url https://frm-rbautodev01:9443 --token ${token} --once
      </div>
      <p style="font-size:12px;color:var(--text3);margin-bottom:8px">Then add to crontab for every-minute collection:</p>
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:10px;font-family:monospace;font-size:11px;word-break:break-all">
        (crontab -l 2>/dev/null; echo "* * * * * python3 ~/agent.py --url https://frm-rbautodev01:9443 --token ${token} --once >> ~/agent.log 2>&1") | crontab -
      </div>
      <p style="font-size:11px;color:var(--text3);margin-top:10px">Token: <code style="background:var(--surface2);padding:2px 6px;border-radius:4px">${token.substring(0,16)}...</code></p>
    </div>`;
  document.getElementById('confirm-ok-btn').textContent = 'Regenerate Token';
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    await fetch(`${API}/api/agent/token/${serverId}`, {method:'POST',credentials:'include'});
    toast('Token regenerated — update your agent command','info');
  };
  openModal('modal-confirm');
}

async function openAddServerModal() {
  document.getElementById('modal-server-title').textContent = 'Add Server';
  document.getElementById('srv-id').value = '';
  ['srv-hostname','srv-ip','srv-os','srv-role','srv-location','srv-notes'].forEach(id => {
    const el = document.getElementById(id); if(el) el.value='';
  });
  ['srv-cpu','srv-ram','srv-disk'].forEach(id => {
    const el = document.getElementById(id); if(el) el.value='';
  });
  document.getElementById('srv-env').value = 'PROD';
  const lp = document.getElementById('srv-last-patched');
  if (lp) lp.value = '';
  await renderServerMonitorCheckboxes([], []);
  openModal('modal-server');
}

async function openEditServerModal(id) {
  const s = allServers.find(sv => sv.id === id);
  if (!s) return;
  document.getElementById('modal-server-title').textContent = 'Edit Server';
  document.getElementById('srv-id').value       = s.id;
  document.getElementById('srv-hostname').value = s.hostname;
  document.getElementById('srv-ip').value       = s.ip_address || '';
  document.getElementById('srv-os').value       = s.os || '';
  document.getElementById('srv-env').value      = s.environment || 'PROD';
  document.getElementById('srv-role').value     = s.role || '';
  document.getElementById('srv-cpu').value      = s.cpu_cores || '';
  document.getElementById('srv-ram').value      = s.ram_gb || '';
  document.getElementById('srv-disk').value     = s.disk_gb || '';
  document.getElementById('srv-location').value = s.location || '';
  document.getElementById('srv-notes').value    = s.notes || '';
  const lp = document.getElementById('srv-last-patched');
  if (lp) lp.value = s.last_patched || '';
  const linkedMonIds = s.monitors.filter(m=>m.type==='monitor').map(m=>m.id);
  const linkedDbIds  = s.monitors.filter(m=>m.type==='database').map(m=>m.id);
  await renderServerMonitorCheckboxes(linkedMonIds, linkedDbIds);
  openModal('modal-server');
}

async function renderServerMonitorCheckboxes(selectedMonIds, selectedDbIds) {
  const monWrap = document.getElementById('srv-monitor-checkboxes');
  const dbWrap  = document.getElementById('srv-db-checkboxes');
  monWrap.innerHTML = '<div style="font-size:12px;color:var(--text3);padding:4px">Loading...</div>';
  dbWrap.innerHTML  = '<div style="font-size:12px;color:var(--text3);padding:4px">Loading...</div>';
  try {
    const [monRes, dbRes] = await Promise.all([
      fetch(`${API}/api/monitors`, {credentials:'include'}),
      fetch(`${API}/api/db-monitors`, {credentials:'include'})
    ]);
    const monitors   = monRes.ok ? await monRes.json() : [];
    const dbMonitors = dbRes.ok  ? await dbRes.json()  : [];

    if (!monitors.length) {
      monWrap.innerHTML = '<div style="font-size:12px;color:var(--text3);padding:4px">No monitors yet.</div>';
    } else {
      const groups = {};
      monitors.forEach(m => { const g=m.group_name||'General'; if(!groups[g])groups[g]=[]; groups[g].push(m); });
      let html = '';
      Object.keys(groups).sort().forEach(g => {
        html += `<div style="font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase;padding:6px 0 3px">${esc(g)}</div>`;
        groups[g].forEach(m => {
          const chk = selectedMonIds.includes(m.id)?'checked':'';
          const st  = m.enabled?(m.current_status?.status===1?'var(--green)':'var(--red)'):'var(--text3)';
          html += `<label class="form-check" style="padding:5px 4px;border-bottom:1px solid var(--border2)">
            <input type="checkbox" value="${m.id}" ${chk}/>
            <span style="display:inline-flex;align-items:center;gap:5px;flex:1;font-size:12px">
              <span style="width:7px;height:7px;border-radius:50%;background:${st};flex-shrink:0;display:inline-block"></span>
              ${esc(m.name)}
            </span>
          </label>`;
        });
      });
      monWrap.innerHTML = html;
    }

    if (!dbMonitors.length) {
      dbWrap.innerHTML = '<div style="font-size:12px;color:var(--text3);padding:4px">No DB monitors yet.</div>';
    } else {
      const dbTypeIcon = t=>t==='mssql'?'🗄️':t==='postgres'?'🐘':'🔌';
      let html = '';
      dbMonitors.forEach(d => {
        const chk = selectedDbIds.includes(d.id)?'checked':'';
        const last = d.last_check;
        const st   = d.enabled&&last?.status===0?'var(--red)':d.enabled&&last?.status===1?'var(--green)':'var(--text3)';
        html += `<label class="form-check" style="padding:5px 4px;border-bottom:1px solid var(--border2)">
          <input type="checkbox" data-db="1" value="${d.id}" ${chk}/>
          <span style="display:inline-flex;align-items:center;gap:5px;flex:1;font-size:12px">
            <span style="width:7px;height:7px;border-radius:50%;background:${st};flex-shrink:0;display:inline-block"></span>
            ${dbTypeIcon(d.db_type)} ${esc(d.name)}
          </span>
          <span style="font-size:10px;color:var(--text3)">${esc(d.host)}:${d.port}</span>
        </label>`;
      });
      dbWrap.innerHTML = html;
    }
  } catch(e) {
    monWrap.innerHTML = `<div style="color:var(--red);font-size:12px">Error: ${esc(e.message)}</div>`;
  }
}

async function saveServer() {
  const id = document.getElementById('srv-id').value;
  const payload = {
    hostname:     document.getElementById('srv-hostname').value.trim(),
    ip_address:   document.getElementById('srv-ip').value.trim(),
    os:           document.getElementById('srv-os').value.trim(),
    environment:  document.getElementById('srv-env').value,
    role:         document.getElementById('srv-role').value.trim(),
    cpu_cores:    parseInt(document.getElementById('srv-cpu').value)||null,
    ram_gb:       parseInt(document.getElementById('srv-ram').value)||null,
    disk_gb:      parseInt(document.getElementById('srv-disk').value)||null,
    location:     document.getElementById('srv-location').value.trim(),
    last_patched: document.getElementById('srv-last-patched')?.value || null,
    notes:        document.getElementById('srv-notes').value.trim(),
  };
  if (!payload.hostname) { toast('Hostname is required','error'); return; }
  const monitorIds = [...document.querySelectorAll('#srv-monitor-checkboxes input:checked')].map(i=>parseInt(i.value));
  const dbIds      = [...document.querySelectorAll('#srv-db-checkboxes input[data-db]:checked')].map(i=>parseInt(i.value));
  try {
    const method = id ? 'PUT' : 'POST';
    const url    = id ? `${API}/api/servers/${id}` : `${API}/api/servers`;
    const res    = await fetch(url, {method, headers:{'Content-Type':'application/json'}, credentials:'include', body:JSON.stringify(payload)});
    if (!res.ok) { const e=await res.json(); toast(e.error||'Error','error'); return; }
    const saved = await res.json();
    await fetch(`${API}/api/servers/${saved.id}/monitors`, {
      method:'POST', headers:{'Content-Type':'application/json'}, credentials:'include',
      body: JSON.stringify({monitor_ids: monitorIds, db_ids: dbIds})
    });
    closeModal('modal-server');
    toast(id?'Server updated':'Server added','success');
    loadServers();
  } catch(e) { toast('Error: '+e.message,'error'); }
}

function confirmDeleteServer(id, hostname) {
  document.getElementById('confirm-msg').textContent = `Delete server "${hostname}" from inventory? This will not affect your monitors.`;
  document.getElementById('confirm-ok-btn').textContent = 'Delete';
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    const res = await fetch(`${API}/api/servers/${id}`, {method:'DELETE',credentials:'include'});
    if (res.ok) { toast('Server removed','success'); loadServers(); }
    else toast('Error deleting server','error');
  };
  openModal('modal-confirm');
}

// Enrich servers with latest agent metrics on load
async function loadServers() {
  const grid = document.getElementById('srv-cards-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="loading-center" style="grid-column:1/-1;padding:40px"><div class="spinner"></div>&nbsp; Loading...</div>';
  try {
    const url = srvEnvFilter ? `${API}/api/servers?environment=${srvEnvFilter}` : `${API}/api/servers`;
    const res = await fetch(url, {credentials:'include'});
    allServers = await res.json();
    // Fetch latest agent metrics for each server in parallel
    await Promise.all(allServers.map(async s => {
      try {
        const mr = await fetch(`${API}/api/agent/metrics/${s.id}?limit=1`, {credentials:'include'});
        if (mr.ok) { const md = await mr.json(); s.latest_metrics = md.latest; }
      } catch(e) { s.latest_metrics = null; }
    }));
    renderServerSummary(allServers);
    renderServerCards(allServers);
  } catch(e) {
    grid.innerHTML = `<div style="color:var(--red);padding:20px;grid-column:1/-1">Error: ${esc(e.message)}</div>`;
  }
}
// ── PATCH DATE HELPERS ───────────────────────
function renderPatchBadge(patchInfo) {
  const { patch_status, pending_updates, reboot_required, collected_at } = patchInfo || {};
  const tooltip = collected_at ? `Patch data collected: ${collected_at}` : '';

  let badge = '';
  if (patch_status === 'up_to_date') {
    badge = `<span class="badge badge-green" title="${tooltip}">\u2705 Up-to-date</span>`;
  } else if (patch_status === 'updates_pending') {
    badge = `<span class="badge badge-amber" title="${tooltip}">\u26a0 Updates pending</span>` +
            `<span class="badge-count">(${pending_updates} updates)</span>`;
  } else if (patch_status === 'critical') {
    badge = `<span class="badge badge-red" title="${tooltip}">\uD83D\uDD34 Critical updates</span>` +
            `<span class="badge-count">(${pending_updates} updates)</span>`;
  } else {
    badge = `<span class="badge badge-grey" title="${tooltip}">\u2014 Patch status unknown</span>`;
  }

  const rebootHtml = reboot_required === true
    ? `<span class="badge badge-amber badge-reboot">\uD83D\uDD01 Reboot required</span>`
    : '';

  return `<div class="patch-status">${badge}${rebootHtml}</div>`;
}

function patchAge(dateStr) {
  if (!dateStr) return null;
  const days = Math.floor((new Date() - new Date(dateStr)) / 86400000);
  return days;
}
function patchBadge(dateStr) {
  if (!dateStr) return '<span style="font-size:11px;color:var(--text3)">Never recorded</span>';
  const days = patchAge(dateStr);
  const d = new Date(dateStr).toLocaleDateString();
  if (days <= 30)  return `<span style="color:var(--green);font-size:11px;font-weight:600">✓ ${d} (${days}d ago)</span>`;
  if (days <= 90)  return `<span style="color:var(--yellow);font-size:11px;font-weight:600">⚠ ${d} (${days}d ago)</span>`;
  return `<span style="color:var(--red);font-size:11px;font-weight:600">⚠ ${d} (${days}d ago — overdue)</span>`;
}
function patchWarning(dateStr) {
  if (!dateStr) return '';
  const days = patchAge(dateStr);
  if (days > 90) return `<div style="padding:8px 12px;background:var(--red-dim);border:1px solid var(--red);border-radius:6px;font-size:12px;color:var(--red);margin-bottom:12px">⚠ Last patched ${days} days ago — security updates may be overdue</div>`;
  if (days > 30) return `<div style="padding:8px 12px;background:var(--yellow-dim);border:1px solid var(--yellow);border-radius:6px;font-size:12px;color:var(--yellow);margin-bottom:12px">⚠ Last patched ${days} days ago — consider scheduling updates</div>`;
  return '';
}
// ── AGENT SETUP WITH ALTERNATIVES ────────────
async function showAgentSetup(serverId, hostname) {
  const token_res = await fetch(`${API}/api/agent/token/${serverId}`, {credentials:'include'});
  const token_data = await token_res.json();
  let token = token_data.token;
  if (!token) {
    const gen = await fetch(`${API}/api/agent/token/${serverId}`, {method:'POST',credentials:'include'});
    const gd  = await gen.json();
    token = gd.token;
  }
  const appUrl = 'https://frm-rbautodev01:9443';
  document.getElementById('confirm-msg').innerHTML = `
    <div style="font-size:12px;line-height:1.7">
      <p style="font-weight:700;margin-bottom:8px">Install agent on <strong>${hostname}</strong>:</p>
      <p style="color:var(--text3);margin-bottom:6px">1. Copy agent to server:</p>
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-family:monospace;font-size:10px;word-break:break-all;margin-bottom:10px">
        scp /home/f5151422/agent.py f5151422@${hostname}:/home/f5151422/agent.py
      </div>
      <p style="color:var(--text3);margin-bottom:6px">2. Test once:</p>
      <div style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-family:monospace;font-size:10px;word-break:break-all;margin-bottom:10px">
        python3 ~/agent.py --url ${appUrl} --token ${token} --once
      </div>
      <p style="color:var(--text3);margin-bottom:4px">3. Schedule — choose one option:</p>
      <div style="border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:8px">
        <div style="padding:6px 10px;background:var(--surface2);font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase">Option A — Crontab (if available)</div>
        <div style="padding:8px 10px;font-family:monospace;font-size:10px;word-break:break-all;background:var(--surface)">
          (crontab -l 2>/dev/null; echo "* * * * * python3 ~/agent.py --url ${appUrl} --token ${token} --once >> ~/agent.log 2>&1") | crontab -
        </div>
      </div>
      <div style="border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:8px">
        <div style="padding:6px 10px;background:var(--surface2);font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase">Option B — systemd user service (no sudo)</div>
        <div style="padding:8px 10px;font-family:monospace;font-size:10px;word-break:break-all;background:var(--surface)">
          mkdir -p ~/.config/systemd/user<br>
          cat > ~/.config/systemd/user/croit-agent.service &lt;&lt;'EOF'<br>
          [Unit]<br>Description=CROIT Agent<br>After=network.target<br>
          [Service]<br>ExecStart=python3 /home/f5151422/agent.py --url ${appUrl} --token ${token}<br>Restart=always<br>RestartSec=60<br>
          [Install]<br>WantedBy=default.target<br>EOF<br>
          systemctl --user daemon-reload<br>
          systemctl --user enable --now croit-agent
        </div>
      </div>
      <div style="border:1px solid var(--border);border-radius:6px;overflow:hidden">
        <div style="padding:6px 10px;background:var(--surface2);font-size:10px;font-weight:700;color:var(--text3);text-transform:uppercase">Option C — nohup background (no crontab, no systemd)</div>
        <div style="padding:8px 10px;font-family:monospace;font-size:10px;word-break:break-all;background:var(--surface)">
          nohup python3 ~/agent.py --url ${appUrl} --token ${token} --interval 60 >> ~/agent.log 2>&1 &<br>
          echo $! > ~/agent.pid<br>
          echo "Agent PID: $(cat ~/agent.pid)"
        </div>
      </div>
    </div>`;
  document.getElementById('confirm-ok-btn').textContent = 'Regenerate Token';
  document.getElementById('confirm-ok-btn').onclick = async () => {
    closeModal('modal-confirm');
    await fetch(`${API}/api/agent/token/${serverId}`, {method:'POST',credentials:'include'});
    toast('Token regenerated — update your agent command','info');
  };
  openModal('modal-confirm');
}
// ── ACTIVE ALERTS + HEALTH REASON ────────────────────────────────────────────

// Environment-aware thresholds
const ENV_THRESHOLDS = {
  PROD: { cpu_warn:70, cpu_crit:90, ram_warn:80, ram_crit:90, disk_warn:70, disk_crit:85 },
  UAT:  { cpu_warn:80, cpu_crit:95, ram_warn:85, ram_crit:95, disk_warn:80, disk_crit:90 },
  DEV:  { cpu_warn:85, cpu_crit:95, ram_warn:85, ram_crit:95, disk_warn:85, disk_crit:95 },
};
function getThresholds(env) {
  return ENV_THRESHOLDS[env] || ENV_THRESHOLDS.PROD;
}

function getServerAlerts(s, m) {
  const alerts = [];
  if (!m) return alerts;
  const t = getThresholds(s.environment);

  if (m.cpu_pct >= t.cpu_crit)       alerts.push({level:'critical', msg:`CPU critical: ${m.cpu_pct}% (threshold ${t.cpu_crit}%)`});
  else if (m.cpu_pct >= t.cpu_warn)  alerts.push({level:'warning',  msg:`CPU high: ${m.cpu_pct}% (threshold ${t.cpu_warn}%)`});

  if (m.ram_pct >= t.ram_crit)       alerts.push({level:'critical', msg:`RAM critical: ${m.ram_pct}% (threshold ${t.ram_crit}%)`});
  else if (m.ram_pct >= t.ram_warn)  alerts.push({level:'warning',  msg:`RAM high: ${m.ram_pct}% (threshold ${t.ram_warn}%)`});

  if (m.disk_mounts && m.disk_mounts.length) {
    m.disk_mounts.forEach(d => {
      if (d.pct >= t.disk_crit)      alerts.push({level:'critical', msg:`Disk ${d.mount} critical: ${d.pct}% (threshold ${t.disk_crit}%)`});
      else if (d.pct >= t.disk_warn) alerts.push({level:'warning',  msg:`Disk ${d.mount} high: ${d.pct}% (threshold ${t.disk_warn}%)`});
    });
  } else if (m.disk_pct != null) {
    if (m.disk_pct >= t.disk_crit)      alerts.push({level:'critical', msg:`Disk critical: ${m.disk_pct}% (threshold ${t.disk_crit}%)`});
    else if (m.disk_pct >= t.disk_warn) alerts.push({level:'warning',  msg:`Disk high: ${m.disk_pct}% (threshold ${t.disk_warn}%)`});
  }

  if (m.load_1m && m.cpu_cores && m.load_1m > m.cpu_cores * 1.5)
    alerts.push({level:'warning', msg:`Load high: ${m.load_1m} (${m.cpu_cores} cores)`});

  if (s.down_count > 0)
    alerts.push({level:'critical', msg:`${s.down_count} linked service${s.down_count>1?'s':''} DOWN`});

  return alerts;
}

function alertsBadge(alerts) {
  if (!alerts.length) return `<span style="font-size:10px;color:var(--green);font-weight:600">✓ No alerts</span>`;
  const crits = alerts.filter(a=>a.level==='critical').length;
  const warns = alerts.filter(a=>a.level==='warning').length;
  const color = crits > 0 ? 'var(--red)' : 'var(--yellow)';
  const count = crits + warns;
  const tip   = alerts.map(a=>`${a.level==='critical'?'🔴':'🟡'} ${a.msg}`).join('\n');
  return `<span style="font-size:10px;font-weight:700;color:${color};cursor:help" title="${tip}">⚠ ${count} alert${count>1?'s':''}</span>`;
}

// ── DISK MOUNT TABLE ──────────────────────────────────────────────────────────

function renderDiskMounts(mounts) {
  if (!mounts || !mounts.length) return '<div style="font-size:12px;color:var(--text3)">No disk data</div>';
  return `<div class="table-wrap"><table style="font-size:12px">
    <thead><tr>
      <th>Mount</th><th>Device</th><th>Type</th>
      <th>Total</th><th>Used</th><th>Free</th><th>Usage</th>
    </tr></thead>
    <tbody>${mounts.map(d => {
      const color = d.pct>=95?'var(--red)':d.pct>=85?'var(--yellow)':'var(--green)';
      const typeColor = d.disk_type==='SSD'?'var(--blue)':d.disk_type==='HDD'?'var(--text2)':'var(--text3)';
      return `<tr>
        <td><strong>${esc(d.mount)}</strong></td>
        <td style="color:var(--text3);font-size:11px">${esc(d.device)}</td>
        <td><span style="color:${typeColor};font-weight:600;font-size:11px">${esc(d.disk_type)}</span></td>
        <td>${d.total_gb} GB</td>
        <td>${d.used_gb} GB</td>
        <td>${d.free_gb} GB</td>
        <td>
          <div style="display:flex;align-items:center;gap:6px">
            <div style="flex:1;height:6px;background:var(--border);border-radius:3px;min-width:60px">
              <div style="width:${d.pct}%;height:100%;background:${color};border-radius:3px"></div>
            </div>
            <span style="color:${color};font-weight:700;font-size:11px;white-space:nowrap">${d.pct}%</span>
          </div>
        </td>
      </tr>`;
    }).join('')}</tbody>
  </table></div>`;
}


// ═══════════════════════════════════════════
// DISCOVERED SERVICES (Auto-Discovery)
// ═══════════════════════════════════════════

async function renderServerServicesSection(serverId) {
  try {
    const res = await fetch(`${API}/api/servers/${serverId}/services`, {credentials:'include'});
    if (!res.ok) return '';
    const data = await res.json();
    const { services, summary } = data;

    if (!services.length) {
      return `
        <div style="font-size:12px;color:var(--text3);padding:8px;border:1px dashed var(--border);border-radius:var(--radius)">
          No services discovered yet. The agent will auto-detect listening ports, systemd services, and containers on the next scan (every 5 minutes).
        </div>`;
    }

    const ports      = services.filter(s => s.category === 'port');
    const svcList    = services.filter(s => s.category === 'service');
    const containers = services.filter(s => s.category === 'container');

    let html = `
      <div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap">
        <span style="font-size:11px;padding:3px 10px;border-radius:12px;background:rgba(43,125,233,.1);color:var(--blue);border:1px solid var(--blue)">🔌 ${summary.ports} Ports</span>
        <span style="font-size:11px;padding:3px 10px;border-radius:12px;background:rgba(0,169,157,.1);color:var(--green);border:1px solid var(--green)">⚙️ ${summary.services} Services</span>
        <span style="font-size:11px;padding:3px 10px;border-radius:12px;background:rgba(139,92,246,.1);color:#8b5cf6;border:1px solid #8b5cf6">🐳 ${summary.containers} Containers</span>
      </div>`;

    // Listening Ports Table
    if (ports.length) {
      html += `
        <div style="font-size:11px;font-weight:600;color:var(--text2);margin-bottom:6px;margin-top:12px">🔌 Listening Ports</div>
        <div class="table-wrap" style="margin-bottom:12px"><table>
          <thead><tr><th>Port</th><th>Process</th><th>PID</th><th>Address</th><th>Protocol</th></tr></thead>
          <tbody>`;
      // Sort by port number
      ports.sort((a,b) => (a.port||0) - (b.port||0));
      ports.forEach(p => {
        const portColor = p.port < 1024 ? 'var(--blue)' : 'var(--text2)';
        const processIcon = getProcessIcon(p.process);
        html += `<tr>
          <td><strong style="color:${portColor}">${p.port}</strong></td>
          <td>${processIcon} ${esc(p.process || '–')}</td>
          <td style="font-size:11px;color:var(--text3)">${p.pid || '–'}</td>
          <td style="font-size:11px;color:var(--text3)">${esc(p.address || '*')}</td>
          <td style="font-size:11px">${(p.protocol||'tcp').toUpperCase()}</td>
        </tr>`;
      });
      html += `</tbody></table></div>`;
    }

    // Systemd / Windows Services Table
    if (svcList.length) {
      html += `
        <div style="font-size:11px;font-weight:600;color:var(--text2);margin-bottom:6px;margin-top:12px">⚙️ Active Services</div>
        <div class="table-wrap" style="margin-bottom:12px"><table>
          <thead><tr><th>Service</th><th>Status</th><th>Description</th><th>Type</th></tr></thead>
          <tbody>`;
      svcList.forEach(s => {
        const stColor = s.status === 'running' ? 'var(--green)' : s.status === 'failed' ? 'var(--red)' : 'var(--yellow)';
        const stDot = `<span style="width:7px;height:7px;border-radius:50%;background:${stColor};display:inline-block;margin-right:5px"></span>`;
        html += `<tr>
          <td><strong>${esc(s.name)}</strong></td>
          <td>${stDot}<span style="color:${stColor};font-weight:600;font-size:11px;text-transform:uppercase">${esc(s.status||'–')}</span></td>
          <td style="font-size:11px;color:var(--text3);max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.description || '–')}</td>
          <td style="font-size:11px">${esc(s.service_type || '–')}</td>
        </tr>`;
      });
      html += `</tbody></table></div>`;
    }

    // Containers Table
    if (containers.length) {
      html += `
        <div style="font-size:11px;font-weight:600;color:var(--text2);margin-bottom:6px;margin-top:12px">🐳 Containers</div>
        <div class="table-wrap" style="margin-bottom:12px"><table>
          <thead><tr><th>Name</th><th>Image</th><th>Status</th><th>Ports</th><th>Runtime</th></tr></thead>
          <tbody>`;
      containers.forEach(c => {
        const isUp = (c.status||'').toLowerCase().includes('up');
        const stColor = isUp ? 'var(--green)' : 'var(--red)';
        html += `<tr>
          <td><strong>${esc(c.name || c.container_id || '–')}</strong></td>
          <td style="font-size:11px;color:var(--text3);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.image || '–')}</td>
          <td><span style="color:${stColor};font-weight:600;font-size:11px">${esc(c.status || '–')}</span></td>
          <td style="font-size:11px;color:var(--text3)">${esc(c.ports_info || '–')}</td>
          <td style="font-size:11px">${esc(c.service_type || '–')}</td>
        </tr>`;
      });
      html += `</tbody></table></div>`;
    }

    // Last seen timestamp
    if (services.length && services[0].last_seen) {
      html += `<div style="font-size:10px;color:var(--text3);text-align:right;margin-top:4px">Last scanned: ${new Date(services[0].last_seen+'Z').toLocaleString()}</div>`;
    }

    return html;
  } catch(e) {
    return `<div style="font-size:12px;color:var(--text3)">Could not load discovered services.</div>`;
  }
}

function getProcessIcon(process) {
  if (!process) return '📡';
  const p = process.toLowerCase();
  if (p.includes('java') || p.includes('jvm')) return '☕';
  if (p.includes('python')) return '🐍';
  if (p.includes('node')) return '🟢';
  if (p.includes('nginx')) return '🌐';
  if (p.includes('httpd') || p.includes('apache')) return '🌐';
  if (p.includes('postgres')) return '🐘';
  if (p.includes('mysql') || p.includes('mariadb')) return '🐬';
  if (p.includes('redis')) return '🔴';
  if (p.includes('mongo')) return '🍃';
  if (p.includes('docker') || p.includes('containerd')) return '🐳';
  if (p.includes('podman')) return '🦭';
  if (p.includes('sshd')) return '🔐';
  if (p.includes('kafka')) return '📨';
  if (p.includes('rabbit')) return '🐰';
  if (p.includes('elastic')) return '🔍';
  if (p.includes('grafana')) return '📊';
  if (p.includes('prometheus')) return '🔥';
  if (p.includes('jenkins')) return '🏗️';
  if (p.includes('wso2')) return '🔗';
  return '📡';
}


// ═══════════════════════════════════════════
// FOLDER SIZE BREAKDOWN
// ═══════════════════════════════════════════

async function renderFolderSizesSection(serverId) {
  try {
    const res = await fetch(`${API}/api/servers/${serverId}/folder-sizes`, {credentials:'include'});
    if (!res.ok) return '';
    const data = await res.json();
    const folders = data.folders || [];

    if (!folders.length) return '';

    let html = `
      <div class="table-wrap"><table>
        <thead><tr><th>Folder</th><th>Size</th><th style="width:200px">Usage</th></tr></thead>
        <tbody>`;

    const maxSize = folders.length > 0 ? folders[0].size_gb : 1;

    folders.forEach(f => {
      const sizeStr = f.size_gb >= 1 ? `${f.size_gb} GB` : `${f.size_mb || 0} MB`;
      const pct = maxSize > 0 ? Math.round((f.size_gb / maxSize) * 100) : 0;
      const barColor = f.size_gb > 20 ? 'var(--red)' : f.size_gb > 5 ? 'var(--yellow)' : 'var(--green)';
      html += `<tr>
        <td style="font-size:12px;font-family:monospace">${esc(f.path)}</td>
        <td style="font-size:12px;font-weight:700;white-space:nowrap">${sizeStr}</td>
        <td><div style="background:var(--surface2);border-radius:4px;height:14px;overflow:hidden"><div style="width:${pct}%;height:100%;background:${barColor};border-radius:4px"></div></div></td>
      </tr>`;
    });

    html += `</tbody></table></div>`;
    return html;
  } catch(e) {
    return '';
  }
}


// ═══════════════════════════════════════════
// COLLAPSIBLE SECTIONS
// ═══════════════════════════════════════════

function toggleSrvSection(headerEl) {
  const section = headerEl.closest('.srv-collapse-section');
  const body = section.querySelector('.srv-collapse-body');
  const arrow = headerEl.querySelector('.srv-collapse-arrow');
  if (body.style.display === 'none') {
    body.style.display = '';
    arrow.style.transform = 'rotate(180deg)';
  } else {
    body.style.display = 'none';
    arrow.style.transform = 'rotate(0deg)';
  }
}
