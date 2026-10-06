# Critical Process/Service Monitoring — Implementation Review

Detects the shell-launched Fircosoft processes (AlertReview, AlertController-Orchestrator, AlertController-CoreEngine, AppDynamics-AppAgent) that `systemctl` never lists, by command-line pattern in both collectors, ships them in the heartbeat under `discovered_services.process_services`, stores them as `category='process'`, alerts on watched-service down/recovery transitions, and surfaces them in the server detail UI with an admin-only Watch toggle and per-service transition history. The implementation follows the plan step-for-step and reuses the existing alert/SMTP and role-model machinery rather than inventing new settings. Verification evidence (ast.parse, node --check, a JSON-validated 4-service sample, a throwaway-DB migration trace, and a backward-compat trace) is recorded in the commit message and is sufficient.

**Watch for:** nothing blocking. One informational divergence between collectors on the AppDynamics pattern breadth (shell matches on `appdynamics` only, agent requires `appdynamics`+`appagent`), which has no alerting impact because AppDynamics is `critical:false` and alerting is gated on the watched set, not the critical flag.

**Verdict:** APPROVED

## High-level view

Detection works without root in both collectors. The Python agent scans `/proc/*/cmdline`, matching each `PROCESS_SERVICE_CONFIG` entry by substring (plus optional `pattern2` for AppDynamics), resolves ports by cross-referencing matched PIDs against the already-collected `listening_ports` list unioned with configured expected ports, and wraps the whole body in try/except returning `[]`. The shell collector uses an editable `name|pattern|expected_ports|critical` heredoc block, counts matches with `ps -eo pid,args | grep -F`, and hand-builds the `process_services` JSON in the same string-concatenation style as the existing `PORTS`/`SERVICES`, emitting it into `discovered_services`. Both emit the exact contract object shape.

The `watched` flag is kept in a dedicated `watched_services` table so it survives the heartbeat's per-cycle `DELETE FROM server_services`. Migrations are idempotent try/except blocks consistent with the file's existing style, adding a tolerant `watched` column, the `watched_services` and `service_events` tables, and the events index.

Heartbeat ingest reuses the existing DELETE/reinsert with `category='process'` rows and the same dict→list / isinstance guards as the other three categories, so a heartbeat with no `process_services` key resolves to `[]` and inserts nothing. The GET services endpoint computes `watched` per process row from `watched_services` and adds `summary.processes`.

Alerting (`_check_service_alerts`) fires only on a status transition recorded in `service_events`, de-duping repeated heartbeats, and gates the email (not the event row) behind a per-(server,service) 24h cooldown. It reuses the exact SMTP keys and send pattern of `_check_agent_thresholds` with no invented settings. Routes use the correct scopes: watch toggle is admin-only, reads are admin+viewer.

The frontend renders a Critical Services section first with status badges, ports, an admin-only Watch toggle, a viewer read-only armed indicator, and a collapsible recent-events list, matching the existing style and role model. `index.html` and `app.js` were correctly left untouched.

<details>
<summary>Issues (1)</summary>

1. **AppDynamics pattern breadth (informational)** — the shell collector matches AppDynamics on `appdynamics` alone while the agent requires both `appdynamics` and `appagent`, so the shell `pids`/`status` may count extra AppDynamics-related java processes. No action required: AppDynamics is `critical:false` and alerting is gated on the watched set, not the critical flag, so there is no functional impact. Mentioned only for parity awareness.

</details>

<details>
<summary>Details</summary>

### Detection without root — both collectors

`discover_process_services(listening_ports)` in `agent.py` iterates `/proc/*/cmdline`, decodes null-separated bytes with `errors="replace"`, matches each config entry by `pattern` (and `pattern2` when present, both required), sets `status = "running" if matched_pids else "down"`, and resolves ports as the union of configured expected ports and any `listening_ports` entry whose `pid` is in the matched set. The whole body is wrapped in `try/except` returning `[]`, and `collect_discovered_services()` calls `discover_listening_ports()` once into a local and passes it in, avoiding a double scan. No root is required — `/proc/<pid>/cmdline` is world-readable for the owning user's own processes, and per-PID open errors are swallowed. The emitted dict carries `name/status/pattern/pids/ports(sorted)/critical`, matching the contract.

The shell collector defines the editable config as a newline-delimited heredoc of `name|pattern|expected_ports|critical`, parses it with `IFS='|'`, counts matches via `ps -eo pid,args --no-headers | grep -F -- "$pattern" | grep -v grep`, builds the `pids` and `ports` JSON arrays by hand, JSON-escapes the pattern with `sed`, and emits objects of the identical shape. Expected ports are the display source of truth (no root for a reliable PID→port map), with a best-effort `ss` supplement noted. The `{EMPTY}` sentinel for AppDynamics ports is handled: the port loop is skipped and `PORTS_JSON` closes to `[]`.

### JSON validity of the shell output

The final heredoc line was extended to add `"process_services":$PROCESS_SERVICES` inside the existing `discovered_services` object after `"containers":[]`, preserving the hand-built string-concatenation style. The coder validated a representative 4-service sample through `json.load` (recorded in the commit); the object/array delimiters balance on inspection and `critical` flows through as the raw JSON literal `true`/`false`.

### Config block editability and the four defaults

Both collectors place a clearly-commented config block at the top. AlertReview, AlertController-Orchestrator, and AlertController-CoreEngine are `critical=true`; AppDynamics-AppAgent is `critical=false`. Alerting is driven by the watched set, and AppDynamics being non-critical plus never watched by default keeps it informational-only — it never alerts.

### Backward compatibility

The heartbeat ingest reads `discovered_services.get("process_services", [])` with dict→list coercion and an `isinstance` list guard, so a legacy heartbeat with no key inserts no process rows. `_check_service_alerts` guards `isinstance(process_services, list)` and returns early otherwise, and the call site passes `(discovered_services or {}).get("process_services", [])`. The agent's `collect_discovered_services` always includes the key going forward. No error path for the missing key.

### Backend storage, watched persistence, and migrations

Process rows are stored through the existing `DELETE FROM server_services WHERE server_id=?` + reinsert, so they refresh each cycle without duplicating. The `watched` flag is kept in the separate `watched_services` table and is therefore not lost by that per-heartbeat delete; `GET services` recomputes `watched` for process rows from `watched_services` and reports `summary.processes`. Migrations are three idempotent try/except blocks (tolerant `watched` column; `CREATE TABLE IF NOT EXISTS` for `watched_services` and `service_events`; `CREATE INDEX IF NOT EXISTS`), consistent with the file's existing migration style. The coder's throwaway-DB trace confirms table/index/column creation, a caught second ALTER, and the watched flag surviving the DELETE/reinsert.

### Alert transitions, SMTP reuse, and cooldown

`_check_service_alerts` records a `service_events` row only on a real transition (running/none→down, down→running), which de-dupes repeated down heartbeats, and emails on those transitions. The SMTP path is a verbatim reuse of `_check_agent_thresholds`: settings keys `smtp_host`, `smtp_to_servers` with `smtp_to` fallback, `smtp_from`, `smtp_port` defaulting to `"25"`, `MIMEText` with `Subject`/`From`/`To`, and `smtplib.SMTP(host, port, timeout=10)`. No invented settings. The 24h cooldown reuses the same `_last_alert_sent` module dict and `threshold_alert_{key[0]}_{key[1]}` settings-persistence helpers with `ALERT_COOLDOWN=86400`; the key namespace `("service", f"{server_id}_{name}")` does not collide with the metric alert keys. The event row is inserted on every transition (complete history); only the email is cooldown-gated, as specified.

### Route scopes

`POST /api/servers/<sid>/services/watch` is `@role_required(['admin'])` and validates a non-empty `service_name` (400 otherwise), using `INSERT OR IGNORE` / `DELETE` against `watched_services`. `GET /api/servers/<sid>/service-events` is `@role_required(['admin','viewer'])` with an optional `service_name` filter and a `limit` clamped to 1..500. Scopes match the contract. The auth/role model is otherwise unchanged.

### Frontend

`renderServerServicesSection` filters `category === 'process'`, renders a "🚨 Critical Services" sub-section before the Listening Ports table, and adds a red Critical summary pill from `summary.processes`. Each service shows a green/red status dot + RUNNING/DOWN label, a critical/informational label, and `ports_info`. The Watch toggle button renders only when `currentUserInfo.role === 'admin'`; viewers get a read-only armed/not-watched indicator. `toggleServiceWatch` POSTs with `credentials:'include'` and JSON content type, toasts on success, and re-renders by swapping the existing `#srv-services-section-${serverId}` innerHTML — the same container and return-value pattern the initial async load uses. `loadServiceEvents` fetches `service-events?...&limit=10` and renders a collapsible color-coded table. Values are escaped via `esc()` and single-quote-escaped in inline handlers.

### Scope hygiene

`index.html` and `app.js` were not modified; the section renders inside the pre-existing `#srv-services-section` container, matching step 9's "only if required" guidance. The README carries the operator note to add a manual TCP backstop monitor on `:8443` for both UAT (`cro-r1fxacruat:8443`) and PROD, with no hostnames hard-coded into app logic.

</details>

<details>
<summary>File map</summary>

- `LINUX_SETUP/agent.py` — `PROCESS_SERVICE_CONFIG` block + `discover_process_services()`; `collect_discovered_services()` now scans ports once and includes `process_services`.
- `LINUX_SETUP/collect_metrics_linux.sh` — editable config heredoc + hand-built `process_services` JSON emitted into `discovered_services`.
- `app.py` — idempotent migrations (watched column, `watched_services`, `service_events`, index); heartbeat ingest of `process_services` as `category='process'`; `_check_service_alerts()`; GET services computed `watched` + `summary.processes`; watch-toggle and service-events routes.
- `frontend/dist/servers.js` — Critical Services section, admin Watch toggle, viewer read-only indicator, collapsible recent-events, summary pill, `toggleServiceWatch()`/`loadServiceEvents()`.
- `LINUX_SETUP/README.md` — operator TCP-backstop note (:8443, UAT/PROD).
- `.kiro/specs/critical-service-monitoring/plan.md` — the plan this review is measured against.

Full diff: `git show 898e0aa`.

</details>
