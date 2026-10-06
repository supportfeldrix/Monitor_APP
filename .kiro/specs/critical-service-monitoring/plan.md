# Implementation Plan — Critical Process/Service Monitoring

Adds a "critical process/service" monitoring capability to the CROIT Monitor APP. The Fircosoft application processes (AlertReview, AlertController-Orchestrator, AlertController-CoreEngine, AppDynamics-AppAgent) are shell-launched java/FKRUN processes under the `fircosoft` user, so `systemctl list-units` never lists them. We detect them by command-line pattern on the box, ship them in the heartbeat under `discovered_services.process_services`, store them, alert on watched critical services going down, and surface them in the server detail UI with a per-service Watch toggle and transition history.

## Design decisions (brief rationale)

- **Port mapping reuses existing discovery output, not a new scanner.** `discover_listening_ports()` (agent.py) already returns a list where each entry carries `pid` and `port`. The new `discover_process_services()` cross-references matched PIDs against that list to resolve ports, so we add no new `/proc/net/tcp` parsing. The shell collector has no reliable PID→port map without root, so it uses the configured *expected* ports plus a best-effort `ss -tlnp` scan.
- **The `watched` flag lives in its own table, not on `server_services`.** The heartbeat does `DELETE FROM server_services WHERE server_id=?` then reinserts every cycle, so any flag on those rows is volatile. A separate `watched_services(server_id, service_name)` table survives the delete/reinsert; the GET endpoint joins it in.
- **Alert state uses `service_events` transitions, not a cooldown-only model.** We alert only on a status *transition* (last recorded status differs from current). This naturally de-dupes repeated "down" heartbeats. A per-(server,service) 24h cooldown via the `settings` table (identical to `_check_agent_thresholds`) guards against event-table churn/flapping, matching the existing alert pattern.
- **AppDynamics is `critical:false` and never alerts.** Only watched services are considered for alerting, and the default config marks AppDynamics non-critical so it is informational-only even if an operator never watches it.
- **Backward compatible.** Missing `process_services` key resolves to `[]` everywhere; older heartbeats and older collectors keep working with no errors.

---

- [ ] 1. Add the `process_services` config block and `discover_process_services()` to the full Python agent.
      In `LINUX_SETUP/agent.py`, add a clearly-commented module-level config list `PROCESS_SERVICE_CONFIG` (near the top, after imports, before `get_os_info`) with the four services:
      `{"name":"AlertReview","pattern":"tierName=AlertReview","ports":[6902,8443],"critical":True}`,
      `{"name":"AlertController-Orchestrator","pattern":"tierName=AlertControllerOrchestrator","ports":[6080,6081],"critical":True}`,
      `{"name":"AlertController-CoreEngine","pattern":"/opt/fircosoft/BackEnds/bin/AlertController/CoreEngine/FKRUN","ports":[6450,6500,6900],"critical":True}`,
      `{"name":"AppDynamics-AppAgent","pattern":"appdynamics","pattern2":"appagent","ports":[],"critical":False}` (AppDynamics match requires BOTH substrings present in the cmdline).
      Add `discover_process_services(listening_ports)` placed next to `discover_containers()` / `collect_discovered_services()` (~line 1070). It: iterates `/proc/*/cmdline` (null-separated bytes, decode replacing errors, replace `\0` with space); for each config entry, collects PIDs whose cmdline contains the `pattern` substring (and `pattern2` if present); `status = "running" if pids else "down"`; resolves `ports` by scanning the passed-in `listening_ports` list for entries whose `pid` is in the matched PID set, unioned with the configured expected `ports` (so 8443/etc still show when PID→port can't be resolved without root); returns a list of `{"name","status","pattern","pids":[...],"ports":[sorted ints],"critical":bool}`. Wrap the whole body in `try/except` returning `[]` on failure.
      Then modify `collect_discovered_services()` to call `discover_listening_ports()` once into a local var, pass it to `discover_process_services(...)`, and add `"process_services": <result>` to the returned dict (keep `listening_ports` set to that same local var to avoid double-scanning).
      Files: `LINUX_SETUP/agent.py`
      Verify: `python -c "import ast,io; ast.parse(open(r'LINUX_SETUP/agent.py',encoding='utf-8').read()); print('OK')"` prints OK. Then a focused runtime check on any Linux-like `/proc` is not available on Windows — instead run `python -c "import importlib.util,sys; spec=importlib.util.spec_from_file_location('a',r'LINUX_SETUP/agent.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.discover_process_services([]))"` and confirm it returns a list of 4 dicts all with status `down` (no fircosoft procs on dev box) and no exception.

- [ ] 2. Add equivalent `process_services` detection to the SSH-pull shell collector.
      In `LINUX_SETUP/collect_metrics_linux.sh`, add a clearly-commented, easily-editable config block near the top (after the shebang/header) defining the four services as parallel bash arrays or a newline-delimited heredoc of `name|pattern|expected_ports|critical` (one per line; AppDynamics uses `appdynamics` as pattern and `critical=false`). Before the final `cat << ENDJSON`, build a `PROCESS_SERVICES="["` JSON string by hand (same string-concatenation style as `PORTS`/`SERVICES`): for each configured service, count matches with `ps -eo pid,args --no-headers 2>/dev/null | grep -F "<pattern>" | grep -v grep`; collect matching PIDs into a JSON array; `status` = `running` if match count ≥ 1 else `down`; `ports` = the configured expected list (JSON array of ints), optionally supplemented by any port from `ss -tlnp 2>/dev/null` whose PID is in the matched set (best-effort; skip if `ss` lacks `-p` permission). Escape the pattern string for JSON (`sed 's/"/\\"/g'`). Emit valid JSON objects `{"name":"...","status":"...","pattern":"...","pids":[...],"ports":[...],"critical":true|false}`. Append `,"process_services":$PROCESS_SERVICES` inside the existing `discovered_services` object in the final heredoc (after `"containers":[]`).
      Files: `LINUX_SETUP/collect_metrics_linux.sh`
      Verify: `bash -n LINUX_SETUP/collect_metrics_linux.sh` (via Git Bash/WSL if available) reports no syntax errors. If no bash is available on the dev box, at minimum confirm the heredoc still contains a single valid JSON line by visual check that every `{` has a matching `}` and the `discovered_services` object ends with `"process_services":$PROCESS_SERVICES}`. The emitted JSON contract must match step 1's object shape exactly.

- [ ] 3. Add DB schema migrations for watched flag, watched_services, and service_events in `init_db()`.
      In `app.py` `init_db()`, in the migration section (the series of `try: conn.execute("ALTER TABLE ...") except: pass` blocks after the `executescript`, ~line 403+), add:
      (a) `ALTER TABLE server_services ADD COLUMN watched INTEGER DEFAULT 0` wrapped in try/except (harmless; the live `watched` value is computed from the table below, but the column keeps older read paths tolerant).
      (b) a second `executescript` (or `conn.execute` calls) creating `CREATE TABLE IF NOT EXISTS watched_services (server_id INTEGER NOT NULL, service_name TEXT NOT NULL, PRIMARY KEY (server_id, service_name))` and `CREATE TABLE IF NOT EXISTS service_events (id INTEGER PRIMARY KEY AUTOINCREMENT, server_id INTEGER NOT NULL, service_name TEXT NOT NULL, status TEXT, changed_at TEXT NOT NULL DEFAULT (datetime('now')))` and `CREATE INDEX IF NOT EXISTS idx_svc_events_server_name ON service_events (server_id, service_name)`.
      Match the existing style (the file already creates `server_services` twice via two `executescript` blocks, so adding a new one is consistent).
      Files: `app.py`
      Verify: delete/rename any local `uptime.db` then run `python -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('OK')"` for syntax, then `python app.py` briefly (or import + call `init_db()`) and confirm startup logs show no migration exception and `sqlite3 uptime.db ".tables"` lists `watched_services` and `service_events`.

- [ ] 4. Ingest `process_services` from the heartbeat into `server_services` with category='process'.
      In `app.py` `api_agent_heartbeat()` (~line 4017), inside the existing `if discovered_services and isinstance(discovered_services, dict):` block, after the containers insert loop and before the block closes, add a `process_services` insert loop. Normalize `discovered_services.get("process_services", [])` to a list (same dict→list / non-list guards used for the other three categories). For each dict entry with a `name`, insert into `server_services` reusing columns: `category='process'`, `name=entry["name"]`, `status=entry.get("status")`, `process=entry.get("pattern")`, `ports_info=` comma-joined `entry.get("ports")` ints (e.g. `"6902,8443"`; empty string if none), `service_type='process'`, `last_seen=now_str_svc`. (The `critical` flag and `pids` are carried for the alert helper in step 6 — pass the raw `process_services` list to that helper; they do not need their own columns.) The existing `DELETE FROM server_services WHERE server_id=?` already clears old rows, so process rows refresh each cycle.
      Files: `app.py`
      Verify: `python -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('OK')"`. Then POST a crafted heartbeat (see step 8 test) and query `sqlite3 uptime.db "SELECT name,status,ports_info,service_type FROM server_services WHERE category='process'"` — rows appear with the expected names/ports and refresh (not duplicate) on a second POST.

- [ ] 5. Extend `GET /api/servers/<int:sid>/services` so process rows include computed `watched` and update the summary.
      In `app.py` `api_server_services(sid)` (~line 4149), after building `services = [dict(r) for r in rows]`, load the watched set once: `SELECT service_name FROM watched_services WHERE server_id=?` into a Python set, and set `s["watched"] = (s["name"] in watched_set)` for rows where `s["category"] == "process"` (default `False`/0 otherwise). `ports_info` is already selected by `SELECT *`. Add `"processes": len([s for s in services if s["category"] == "process"])` to the `summary` dict. Keep the existing `@role_required(['admin','viewer'])`.
      Files: `app.py`
      Verify: `python -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('OK')"`. Then `curl -ks --cookie <session> https://localhost:5000/api/servers/<id>/services` (or the running port) returns process-category entries each with a `watched` boolean and `ports_info`, and `summary.processes` is present.

- [ ] 6. Add `_check_service_alerts(server_id, process_services)` and call it from the heartbeat.
      In `app.py`, define `_check_service_alerts(server_id, process_services)` immediately after `_check_agent_thresholds` (~line 3430, same module region). Behavior:
      - Guard: if not a list, return. Look up `hostname`/`environment` from `servers` like `_check_agent_thresholds` does.
      - Load the watched set: `SELECT service_name FROM watched_services WHERE server_id=?`.
      - For each watched service name: determine current status from `process_services` (status of the matching entry, or `"down"` if the watched service is entirely absent from the list). Read the last recorded status: `SELECT status FROM service_events WHERE server_id=? AND service_name=? ORDER BY id DESC LIMIT 1`.
      - On transition **running/none → down**: INSERT a `service_events` row `(server_id, service_name, 'down')` and send a DOWN email; on transition **down → running**: INSERT `(server_id, service_name, 'running')` and send a RECOVERY email. No event/email when status is unchanged.
      - Reuse the EXACT SMTP pattern from `_check_agent_thresholds`: settings keys `smtp_host`, `smtp_to_servers` (fallback `smtp_to`), `smtp_from`, `smtp_port` (default `"25"`), `MIMEText` body + `Subject`/`From`/`To`, `smtplib.SMTP(host, port, timeout=10)`. Subjects e.g. `f"[CROIT Service Alert] {hostname} — {service_name} DOWN"` and `... — {service_name} RECOVERED"`. Body includes hostname, env, service name, ports, and timestamp.
      - Apply a per-(server,service) 24h cooldown using the same `settings`-table + `_last_alert_sent`-style mechanism as `_check_agent_thresholds` (reuse a module-level dict and the `threshold_alert_`-style key, e.g. key `("service", f"{server_id}_{service_name}")`), so repeated transitions don't spam. The event row is still inserted on every real transition (history is complete); only the email respects cooldown.
      Then call `_check_service_alerts(server_id, discovered_services.get("process_services", []))` right next to the existing `_check_agent_thresholds(server_id, d)` call (~line 4100), guarded so a missing key passes `[]`.
      Files: `app.py`
      Verify: `python -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('OK')"`. Functional: with SMTP unset, POST a heartbeat where a watched service is `down` and confirm a `service_events` row is inserted (`sqlite3 uptime.db "SELECT * FROM service_events"`) and no exception is logged; POST again with it `running` and confirm a recovery row is added. (Email send is skipped gracefully when `smtp_host`/`smtp_to` are empty, exactly like `_check_agent_thresholds`.)

- [ ] 7. Add the watch-toggle and service-events routes.
      In `app.py`, near `api_server_services` (~line 4173), add:
      (a) `POST /api/servers/<int:sid>/services/watch` with `@role_required(['admin'])`, body `{"service_name": "...", "watched": true|false}`. On `watched=true`: `INSERT OR IGNORE INTO watched_services (server_id, service_name) VALUES (?,?)`. On `watched=false`: `DELETE FROM watched_services WHERE server_id=? AND service_name=?`. Validate `service_name` non-empty (400 if missing). Return `jsonify({"ok": True, "service_name": name, "watched": bool})`. Use `with DB_LOCK, get_db() as conn:`.
      (b) `GET /api/servers/<int:sid>/service-events` with `@role_required(['admin','viewer'])`, query params `service_name` (optional filter) and `limit` (default 50, cap at 500). `SELECT id, service_name, status, changed_at FROM service_events WHERE server_id=? [AND service_name=?] ORDER BY id DESC LIMIT ?`. Return `jsonify({"events": [dict(r) for r in rows]})`.
      Files: `app.py`
      Verify: `python -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('OK')"`. Then as an admin session: `POST .../services/watch {"service_name":"AlertReview","watched":true}` returns `ok`, the service row from the GET services endpoint now shows `watched:true`, and `GET .../service-events?service_name=AlertReview` returns recent transitions. As a viewer session the POST returns 403; the GET events returns 200.

- [ ] 8. Add the "Critical Services" section to the server detail view (process category) with Watch toggle and history.
      In `frontend/dist/servers.js`, inside `renderServerServicesSection(serverId)` (~line 727): compute `const processes = services.filter(s => s.category === 'process');`. Render a new "🚨 Critical Services" sub-section BEFORE the Listening Ports table (most important first). For each process entry render a row/card with: a status badge (green dot + "RUNNING" when `status==='running'`, red dot + "DOWN" otherwise), the ports held (`esc(p.ports_info || '–')`), a `critical`-aware label, and — only when `currentUserInfo && currentUserInfo.role === 'admin'` — a Watch toggle button showing armed/disarmed state (`p.watched` truthy = "🔔 Watching" else "🔕 Watch") wired to a new `toggleServiceWatch(serverId, name, nextState)` function; viewers see an "Alerts armed/—" read-only indicator instead. Below each service add a small collapsible "recent events" area populated by a new `loadServiceEvents(serverId, name, elId)` that fetches `GET /api/servers/${serverId}/service-events?service_name=${encodeURIComponent(name)}&limit=10` and lists `status` + `changed_at` (color-coded). Add `toggleServiceWatch()` which POSTs to `/api/servers/${serverId}/services/watch` with `{service_name, watched}` (`credentials:'include'`, `Content-Type: application/json`), on success calls `toast(...)` and re-renders the services section (reuse the existing `renderServerServicesSection(...).then(...)` refresh pattern, or re-call it and swap `#srv-services-section-${serverId}` innerHTML). Add `'process'` to the summary pills row (e.g. a red "🚨 N Critical" pill using `summary.processes`). Match the exact visual style (`var(--green)`, `var(--red)`, `esc()`, table-wrap) already used in the function. Reuse `getProcessIcon()` for the service process icon where helpful.
      Files: `frontend/dist/servers.js`
      Verify: `node --check frontend/dist/servers.js` passes. Manual: open a server detail with process rows — the Critical Services section shows status badges and ports; as admin the Watch toggle flips `watched` and persists across refresh; as viewer the toggle is absent but status shows; the recent-events list renders transitions.

- [ ] 9. (Only if a modal/markup change is actually required) wire any shell/index.html hooks.
      Review `frontend/dist/index.html` and `frontend/dist/app.js`: the Critical Services section renders inside the existing `#srv-services-section-${s.id}` container that `servers.js` already populates, so NO new `.page`/modal is expected. If step 8's toggle/history needs a shared helper that lives in `app.js` (e.g. a confirm modal) use the existing `toast`/modal helpers rather than adding markup. Only touch `index.html` if a new static container is genuinely needed; otherwise leave it unchanged and note that in the implementation.
      Files: `frontend/dist/app.js` and/or `frontend/dist/index.html` (only if required)
      Verify: `node --check frontend/dist/app.js` passes (if edited). Confirm no duplicate element IDs introduced (`grep` for any new id in index.html).

- [ ] 10. Add the TCP-backstop operator note (no code behavior change).
      Append a short note to this spec folder or the project README (`LINUX_SETUP/README.md`) stating: an operator should manually add a TCP monitor against `cro-r1fxacruat:8443` (UAT) and the prod box `:8443` as a network-reachability backstop for the frontend-facing AlertReview port. Do NOT auto-create a monitor in code and do NOT hard-code hostnames into app logic.
      Files: `LINUX_SETUP/README.md` (or a `NOTES.md` in `.kiro/specs/critical-service-monitoring/`)
      Verify: the note exists and names port 8443 and both environments; no code paths reference the hostnames.

- [ ] 11. Final syntax/compat gate.
      Run the project's documented checks: `python -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('OK')"`, `python -c "import ast; ast.parse(open(r'LINUX_SETUP/agent.py',encoding='utf-8').read()); print('OK')"`, `node --check frontend/dist/servers.js`, and (if edited) `node --check frontend/dist/app.js`. Confirm a heartbeat WITHOUT `process_services` still succeeds (backward-compat): POST a legacy-shaped heartbeat and confirm `{"ok":true}` with no process rows and no exception.
      Files: none (verification only)
      Verify: all four checks pass; legacy heartbeat returns ok.

## End-to-end data contract (must stay identical across collectors and backend)

```json
"discovered_services": {
  "listening_ports": [...],
  "systemd_services": [...],
  "containers": [...],
  "process_services": [
    {"name":"AlertReview","status":"running","pattern":"tierName=AlertReview","pids":[3195567],"ports":[6902,8443],"critical":true},
    {"name":"AlertController-Orchestrator","status":"running","pattern":"tierName=AlertControllerOrchestrator","pids":[3194786],"ports":[6080,6081],"critical":true},
    {"name":"AlertController-CoreEngine","status":"running","pattern":"/opt/fircosoft/BackEnds/bin/AlertController/CoreEngine/FKRUN","pids":[3192979],"ports":[6450,6500,6900],"critical":true},
    {"name":"AppDynamics-AppAgent","status":"running","pattern":"appdynamics","pids":[3192993],"ports":[],"critical":false}
  ]
}
```

## Notes / assumptions

- The reviewer loop's gate file is `.kiro/specs/critical-service-monitoring/review.json` (jsonPath `verdict` → `APPROVED`); this plan does not create or modify it.
- No automated test suite exists; verification uses the project's documented `ast.parse` / `node --check` syntax checks plus crafted heartbeat POSTs, consistent with the steering doc's testing section.
- `collect_metrics_linux.sh` port resolution is best-effort (no root); expected ports from the config block are the source of truth for display, which is acceptable since the status (running/down) is what drives alerts.
