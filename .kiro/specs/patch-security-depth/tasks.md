# Implementation Plan: patch-security-depth

## Overview

Enrich the Server Inventory with pending update count, reboot-required flag, and a patch status badge (`up_to_date` / `updates_pending` / `critical`). The data flows from both the Linux agent and the Windows agent through the existing heartbeat pipeline to the Flask backend, which stores it, derives a `patch_info` object, and triggers email alerts on critical transitions. The frontend renders a colour-coded badge on each Server Card.

Implementation order: Linux agent → Windows agent → backend schema + heartbeat + alert → backend API enrichment → frontend badge → property-based tests.

---

## Tasks

- [ ] 1. Add patch metric collection to the Linux agent (`LINUX_SETUP/agent.py`)
  - [ ] 1.1 Implement `collect_patch_metrics_linux()` function
    - Detect distro family from `/etc/os-release` (`ID_LIKE` or `ID` field)
    - **Debian/Ubuntu path:** run `apt list --upgradable 2>/dev/null` and count lines containing "upgradable" for `pending_updates`; detect security updates via `grep -i security` on the same output
    - **RHEL/CentOS path:** run `yum check-update --quiet 2>/dev/null` and count lines matching `^[a-zA-Z]` for `pending_updates`; detect security updates via `yum updateinfo list security 2>/dev/null`
    - Classify `patch_status`: `"up_to_date"` if count == 0, `"critical"` if any security updates detected, `"updates_pending"` otherwise
    - Detect `reboot_required` by checking existence of `/var/run/reboot-required` (Debian/Ubuntu) or `/var/run/reboot-required` equivalent; fall back to `False` if file absent
    - Return `{"pending_updates": int|None, "reboot_required": bool|None, "patch_status": str|None}`
    - Wrap entire function in try/except; on any failure return all-`None` dict and log warning
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5 (Linux scope)_

  - [ ] 1.2 Add patch interval scheduling state and `--patch-interval` CLI argument to `main()` in `LINUX_SETUP/agent.py`
    - Add `parser.add_argument("--patch-interval", type=int, default=60)` alongside existing `--interval`
    - Initialise `last_patch_time = 0` and `cached_patch = {"pending_updates": None, "reboot_required": None, "patch_status": None}` before the main loop
    - Inside the loop, before calling `collect_metrics()`, check `if time.time() - last_patch_time >= patch_interval_s:` and refresh `cached_patch`; otherwise reuse cached values
    - Call `metrics.update(cached_patch)` so all three keys are always present in the heartbeat payload
    - _Requirements: 6.1, 6.2, 6.3, 6.4 (Linux scope)_

  - [ ]* 1.3 Write property test — Linux patch payload always contains patch keys (Property 3)
    - **Property 3: Heartbeat payload always contains patch keys**
    - **Validates: Requirements 1.5**
    - Use `hypothesis` to generate arbitrary outcomes (success dict, all-None dict, exception) and assert `pending_updates`, `reboot_required`, `patch_status` keys are always present in the result of `collect_metrics()`

- [ ] 2. Add patch metric collection to the Windows agent (`WINDOWS_AGENT/agent_windows.py`)
  - [ ] 2.1 Implement `collect_patch_metrics()` with WUA COM primary path
    - Import `win32com.client` and `pythoncom` inside the function (guarded by try/except `ImportError`)
    - Create `Microsoft.Update.Session`, call `CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0")`
    - Build a list of dicts `[{"severity": u.MsrcSeverity or ""}]` from the results
    - Pass the list to `classify_patch_status()` (implemented in 2.2) to derive `patch_status`
    - Set `pending_updates` to `len(updates)`
    - _Requirements: 1.1, 1.3_

  - [ ] 2.2 Implement `classify_patch_status(updates)` pure function
    - Accept a list of update dicts with a `"severity"` key
    - Return `"up_to_date"` if list is empty
    - Return `"critical"` if any entry has severity `"Critical"` or `"Important"`
    - Return `"updates_pending"` otherwise
    - No I/O; no side effects
    - _Requirements: 1.3_

  - [ ] 2.3 Implement `get_reboot_required()` function using `winreg`
    - Check `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired` key exists → return `True`
    - Check `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\PendingFileRenameOperations` value is non-empty → return `True`
    - Neither condition → return `False`
    - `winreg` unavailable or any exception → return `None`
    - _Requirements: 1.2_

  - [ ] 2.4 Implement PowerShell fallback paths inside `collect_patch_metrics()`
    - **First fallback** (triggered by `com_error` or `ImportError`): run `Get-WindowsUpdate -NotInstalled` via `subprocess`; parse output to count updates and detect severity keywords `Critical`/`Important`
    - **Second fallback** (triggered when PSWindowsUpdate not installed): run `(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher().Search('IsInstalled=0').Updates` via `powershell.exe`; parse count from output
    - On all-fallback failure: return `{"pending_updates": None, "reboot_required": None, "patch_status": None}` and log warning
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ] 2.5 Wire `collect_patch_metrics()` and `get_reboot_required()` into the scheduling loop in `main()`
    - Add `parser.add_argument("--patch-interval", type=int, default=60)` to the argument parser
    - Initialise `last_patch_time = 0` and `cached_patch = {"pending_updates": None, "reboot_required": None, "patch_status": None}` before the main loop
    - Inside the loop, refresh `cached_patch` when interval elapsed; merge reboot result into cached dict
    - Call `metrics.update(cached_patch)` before `post_metrics()`
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ]* 2.6 Write property test — `classify_patch_status` is exhaustive and correct (Property 1)
    - **Property 1: Patch status classification is exhaustive and correct**
    - **Validates: Requirements 1.3**
    - Use `hypothesis` with `st.lists(st.fixed_dictionaries({"severity": st.text()}))` to generate random update lists; assert return value is always one of the three valid strings and satisfies the classification invariants

  - [ ]* 2.7 Write property test — WUA failure produces all-null patch fields (Property 2)
    - **Property 2: WUA failure produces all-null patch fields**
    - **Validates: Requirements 1.4, 2.3**
    - Use `hypothesis` with `st.from_type(Exception)` (or a sampled set of exception types) to generate arbitrary exceptions; mock the COM import to raise them; assert all three returned fields are `None`

  - [ ]* 2.8 Write property test — patch values cached between collection intervals (Property 4)
    - **Property 4: Patch values are cached between collection intervals**
    - **Validates: Requirements 6.3**
    - Use `hypothesis` to generate a cached patch dict and an elapsed time `< patch_interval_s`; assert the heartbeat payload contains the cached values unchanged without invoking the collection function

- [ ] 3. Checkpoint — verify both agents run without errors
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Backend schema migration (`app.py`)
  - [ ] 4.1 Add three `ALTER TABLE` migrations to `init_db()`
    - After the existing `cpu_cores`/`cpu_threads`/`disk_mounts` migration block, add a new loop:
      ```python
      for col, defn in [
          ("pending_updates", "INTEGER"),
          ("reboot_required", "INTEGER"),
          ("patch_status",    "TEXT"),
      ]:
          try:
              conn.execute(f"ALTER TABLE agent_metrics ADD COLUMN {col} {defn}")
              print(f"[DB] Migrated: added {col} to agent_metrics.")
          except Exception:
              pass
      ```
    - Running `init_db()` twice on an existing database must not raise an error
    - _Requirements: 3.1_

- [ ] 5. Backend heartbeat endpoint and alert logic (`app.py`)
  - [ ] 5.1 Extend `api_agent_heartbeat()` to store the three new fields
    - Read `d.get("pending_updates")`, `d.get("reboot_required")`, `d.get("patch_status")` from the JSON payload
    - Add the three values to the existing `INSERT INTO agent_metrics` statement (new columns at the end)
    - Missing fields in the payload must store `NULL` without error
    - After the INSERT, call `_check_patch_alert(server_id, d)`
    - _Requirements: 3.2, 3.4_

  - [ ] 5.2 Implement `_patch_alert_sent` dict and `_check_patch_alert(server_id, payload)` function
    - Add module-level `_patch_alert_sent: dict = {}` (keyed by `server_id`, value = epoch float)
    - Implement the function per the design: skip if `new_status != "critical"` (and clear suppression); fetch previous stored `patch_status` via `OFFSET 1` query; send alert on first critical or after 24 h window expires; update `_patch_alert_sent[server_id]`
    - _Requirements: 7.1, 7.2, 7.4_

  - [ ] 5.3 Implement `_send_patch_alert(server_id, payload)` function
    - Look up server hostname from `servers` table
    - Build email body with hostname, `pending_updates`, and transition timestamp
    - Reuse existing `get_setting()` / `smtplib` pattern from `send_alert_email()`
    - If SMTP not configured, log the alert condition to stdout instead of raising
    - _Requirements: 7.1, 7.3_

  - [ ]* 5.4 Write property test — heartbeat storage round-trip preserves patch fields (Property 5)
    - **Property 5: Heartbeat storage round-trip preserves patch fields**
    - **Validates: Requirements 3.2, 3.4**
    - Use `hypothesis` + Flask test client to generate random combinations of `pending_updates` (int or None), `reboot_required` (bool or None), `patch_status` (str or None); POST to `/api/agent/heartbeat`; query `agent_metrics`; assert stored values equal submitted values and endpoint returns HTTP 200

  - [ ]* 5.5 Write property test — critical transition alert fires for all non-critical prior states (Property 10)
    - **Property 10: Critical transition alert fires for all non-critical prior states**
    - **Validates: Requirements 7.1**
    - Use `hypothesis` to generate prior states from `{None, "up_to_date", "updates_pending"}`; mock SMTP; assert alert is attempted for each

  - [ ]* 5.6 Write property test — alert suppression holds within 24-hour window (Property 11)
    - **Property 11: Alert suppression holds within 24-hour window**
    - **Validates: Requirements 7.2**
    - Use `hypothesis` to generate N repeated critical heartbeats (N ≥ 2) within a 24 h window; mock SMTP; assert `sendmail` called exactly once

  - [ ]* 5.7 Write property test — suppression timer resets on non-critical transition (Property 12)
    - **Property 12: Suppression timer resets on non-critical transition**
    - **Validates: Requirements 7.4**
    - Use `hypothesis` to generate a non-critical status (`"up_to_date"` or `"updates_pending"`); assert that after the non-critical heartbeat the next critical heartbeat triggers a new alert

- [ ] 6. Checkpoint — verify backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Backend API enrichment (`app.py`)
  - [ ] 7.1 Implement `_build_patch_info(server_id, last_patched, conn)` helper
    - Query most recent `agent_metrics` row for `pending_updates`, `reboot_required`, `patch_status`, `collected_at`
    - Apply fallback: if `patch_status` is `None` and `last_patched` is set → return `"up_to_date"`
    - If no metrics row exists and `last_patched` is set → return `"up_to_date"`
    - If no metrics row and `last_patched` is `None` → return `patch_status: None`
    - Always return a dict with all five keys: `pending_updates`, `reboot_required`, `patch_status`, `last_patched`, `collected_at`
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 7.2 Call `_build_patch_info()` from `_server_with_health()` and attach result to server response
    - Pass `server["id"]`, `server["last_patched"]`, and the open `conn` to `_build_patch_info()`
    - Attach the returned dict as `result["patch_info"]`
    - Confirm `last_patched` on the `servers` row is not modified by this call
    - _Requirements: 4.1, 4.4_

  - [ ]* 7.3 Write property test — server API response always includes `patch_info` (Property 6)
    - **Property 6: Server API response always includes patch_info**
    - **Validates: Requirements 4.1**
    - Use `hypothesis` + Flask test client to generate servers with varying `agent_metrics` states (no rows, rows with null fields, rows with all fields populated); call `/api/servers`; assert every item contains `patch_info` with all five required keys

  - [ ]* 7.4 Write property test — null `patch_status` with `last_patched` resolves to `up_to_date` (Property 7)
    - **Property 7: Null patch_status with last_patched resolves to up_to_date**
    - **Validates: Requirements 4.2**
    - Use `hypothesis` to generate non-null `last_patched` date strings with null stored `patch_status`; assert API response sets `patch_info.patch_status` to `"up_to_date"`

  - [ ]* 7.5 Write property test — heartbeat never modifies `last_patched` (Property 8)
    - **Property 8: Heartbeat never modifies last_patched**
    - **Validates: Requirements 4.4**
    - Use `hypothesis` to generate arbitrary heartbeat payloads (with and without patch fields); POST to `/api/agent/heartbeat`; assert `last_patched` on the `servers` row is identical before and after

- [ ] 8. Frontend badge rendering (`frontend/dist/index.html` / `servers.js`)
  - [ ] 8.1 Implement `renderPatchBadge(patchInfo)` JavaScript function
    - Destructure `patch_status`, `pending_updates`, `reboot_required`, `collected_at` from `patchInfo` (or `{}` if null)
    - Render green `badge-green` span for `"up_to_date"`, amber `badge-amber` + count span for `"updates_pending"`, red `badge-red` + count span for `"critical"`, grey `badge-grey` for null/unknown
    - Append `badge-reboot` amber span when `reboot_required === true`
    - Set `title` attribute on the badge span to `collected_at` value for tooltip
    - Return a `<div class="patch-status">` wrapping all generated HTML
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.7_

  - [ ] 8.2 Insert `renderPatchBadge()` output into each Server Card below the existing `last_patched` field
    - Locate the section of the server card template that renders `last_patched`
    - Call `renderPatchBadge(server.patch_info)` and append the returned HTML immediately after the `last_patched` line
    - Ensure the existing `last_patched` display is preserved unchanged
    - _Requirements: 5.6_

  - [ ] 8.3 Add CSS classes for patch badge styling
    - Add `.badge-green`, `.badge-amber`, `.badge-red`, `.badge-grey`, `.badge-reboot`, `.badge-count`, `.patch-status` to the stylesheet section of `index.html`
    - Green: `#22c55e` background; Amber: `#f59e0b`; Red: `#ef4444`; Grey: `#6b7280`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [ ]* 8.4 Write property test — badge count display for non-up-to-date statuses (Property 9)
    - **Property 9: Badge count display for non-up-to-date statuses**
    - **Validates: Requirements 5.2, 5.3**
    - Use `fast-check` to generate random integers N ≥ 0 paired with `"updates_pending"` or `"critical"` status; call `renderPatchBadge()`; assert the rendered HTML contains the string `(${N} updates)`

- [ ] 9. Final checkpoint — full integration verification
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP delivery
- Each task references specific requirements for traceability
- Checkpoints (tasks 3, 6, 9) ensure incremental validation at each layer boundary
- Property tests use **Hypothesis** (Python) for backend/agent properties and **fast-check** (JavaScript) for frontend rendering properties; minimum 100 iterations each
- The Linux agent changes (task 1) are new scope not in the original design; they follow the same patterns as the Windows agent and share the same backend/frontend pipeline
- `last_patched` on the `servers` table is never modified by this feature — it remains a manually entered value
