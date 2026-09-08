# Requirements Document

## Introduction

The Podman Dashboard UAT application currently displays a "last patched date" for each monitored Windows server in the Server Inventory section. This feature enriches the patch and security section of each server card with three additional data points:

1. **Pending updates count** — how many Windows updates are waiting to be installed
2. **Reboot required flag** — whether the server is pending a reboot to complete an update
3. **CVE / severity indicator** — a high-level patch status badge (✅ Up-to-date / ⚠ Updates pending / 🔴 Critical security updates)

The Windows Agent (`agent_windows.py`) collects and reports these values to the Flask backend (`app.py`) via the existing `/api/agent/heartbeat` endpoint. The dashboard frontend renders the enriched patch status on each server card.

---

## Glossary

- **Agent**: The `agent_windows.py` Python script that runs on each monitored Windows host and posts metrics to the dashboard.
- **Dashboard**: The Flask web application (`app.py`) and its frontend (`frontend/dist/index.html`) that displays server health and inventory.
- **Heartbeat**: A single metrics payload POSTed by the Agent to `/api/agent/heartbeat`.
- **Patch_Status**: A computed severity label derived from pending update count and update classification. One of: `up_to_date`, `updates_pending`, or `critical`.
- **Pending_Updates**: The count of Windows updates that are available but not yet installed on a host.
- **Reboot_Required**: A boolean flag indicating that at least one installed update requires a system restart to take effect.
- **Server_Card**: The UI component in the Server Inventory view that displays summary information for a single monitored Windows host.
- **WUA**: Windows Update Agent — the Windows COM API (`Microsoft.Update.Session`) used to query update state.
- **WSUS**: Windows Server Update Services — the corporate update distribution point that WUA queries.

---

## Requirements

### Requirement 1: Agent Collects Patch Metrics

**User Story:** As a dashboard operator, I want the Windows Agent to collect pending update count, reboot-required flag, and update severity from each monitored host, so that the dashboard can display accurate patch status without manual data entry.

#### Acceptance Criteria

1. WHEN the Agent runs a collection cycle, THE Agent SHALL query the Windows Update Agent (WUA) COM API to determine the count of updates that are available but not yet installed on the host.
2. WHEN the Agent runs a collection cycle, THE Agent SHALL query the Windows registry key `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\PendingFileRenameOperations` and the `RebootRequired` value under `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired` to determine whether a reboot is required.
3. WHEN the Agent runs a collection cycle, THE Agent SHALL classify the Patch_Status as `critical` if one or more available updates carry a MsrcSeverity of `Critical` or `Important`, as `updates_pending` if updates are available but none are `Critical` or `Important`, and as `up_to_date` if no updates are available.
4. IF the WUA COM API is unavailable or raises an exception, THEN THE Agent SHALL set `pending_updates` to `null`, `reboot_required` to `null`, and `patch_status` to `null` in the Heartbeat payload, and SHALL log the exception message to the agent log file.
5. WHEN the Agent runs a collection cycle, THE Agent SHALL include `pending_updates` (integer or null), `reboot_required` (boolean or null), and `patch_status` (string or null) in the JSON Heartbeat payload alongside existing metrics.

---

### Requirement 2: Agent Fallback via PowerShell

**User Story:** As a dashboard operator, I want the Agent to fall back to a PowerShell-based query when the WUA COM API is unavailable, so that patch metrics are collected on hosts where the COM API is restricted.

#### Acceptance Criteria

1. IF the WUA COM API raises a `pythoncom.com_error` or `ImportError`, THEN THE Agent SHALL execute the PowerShell command `Get-WindowsUpdate` (from the `PSWindowsUpdate` module) to retrieve pending update count and severity.
2. IF the `PSWindowsUpdate` module is not installed, THEN THE Agent SHALL execute `(New-Object -ComObject Microsoft.Update.Session).CreateUpdateSearcher().Search('IsInstalled=0').Updates.Count` via PowerShell as a secondary fallback to obtain the pending update count.
3. IF all fallback methods fail, THEN THE Agent SHALL set `pending_updates`, `reboot_required`, and `patch_status` to `null` and SHALL log a warning to the agent log file.

---

### Requirement 3: Backend Stores Patch Metrics

**User Story:** As a dashboard operator, I want the backend to persist patch metrics received from the Agent, so that the dashboard can display current and historical patch status for each server.

#### Acceptance Criteria

1. THE Dashboard SHALL add the columns `pending_updates` (INTEGER), `reboot_required` (INTEGER), and `patch_status` (TEXT) to the `agent_metrics` table via a schema migration that executes `ALTER TABLE agent_metrics ADD COLUMN` for each column if it does not already exist.
2. WHEN the `/api/agent/heartbeat` endpoint receives a Heartbeat payload, THE Dashboard SHALL store the values of `pending_updates`, `reboot_required`, and `patch_status` from the payload into the corresponding columns of the new `agent_metrics` row.
3. WHEN the `/api/agent/metrics/<server_id>` endpoint is called, THE Dashboard SHALL include `pending_updates`, `reboot_required`, and `patch_status` in the `latest` object of the JSON response.
4. IF the Heartbeat payload omits `pending_updates`, `reboot_required`, or `patch_status`, THEN THE Dashboard SHALL store `NULL` for the missing fields without returning an error.

---

### Requirement 4: Backend Computes Patch Status Badge

**User Story:** As a dashboard operator, I want the backend to derive a consistent Patch_Status label for each server, so that the frontend can render a uniform badge without duplicating classification logic.

#### Acceptance Criteria

1. WHEN the `/api/servers` or `/api/servers/<server_id>` endpoint builds a server response, THE Dashboard SHALL include a `patch_info` object containing `pending_updates`, `reboot_required`, `patch_status`, and `last_patched` sourced from the most recent `agent_metrics` row for that server.
2. WHEN `patch_status` stored in `agent_metrics` is `null` and `last_patched` is set on the server record, THE Dashboard SHALL set `patch_info.patch_status` to `up_to_date` in the response.
3. WHEN `patch_status` stored in `agent_metrics` is `null` and `last_patched` is also `null`, THE Dashboard SHALL set `patch_info.patch_status` to `null` in the response.
4. THE Dashboard SHALL NOT modify the `last_patched` field on the `servers` table as part of this feature; `last_patched` remains a manually entered value.

---

### Requirement 5: Frontend Displays Patch Status Badge

**User Story:** As a dashboard user, I want each Server Card to show a colour-coded patch status badge alongside the last patched date, so that I can immediately identify servers that need attention.

#### Acceptance Criteria

1. WHEN `patch_info.patch_status` is `up_to_date`, THE Server_Card SHALL display a green badge labelled "✅ Up-to-date".
2. WHEN `patch_info.patch_status` is `updates_pending`, THE Server_Card SHALL display an amber badge labelled "⚠ Updates pending" and SHALL display the pending update count in the format "(N updates)".
3. WHEN `patch_info.patch_status` is `critical`, THE Server_Card SHALL display a red badge labelled "🔴 Critical updates" and SHALL display the pending update count in the format "(N updates)".
4. WHEN `patch_info.reboot_required` is `true`, THE Server_Card SHALL display a secondary amber indicator labelled "🔁 Reboot required" beneath the patch status badge.
5. WHEN `patch_info.patch_status` is `null`, THE Server_Card SHALL display a grey badge labelled "— Patch status unknown".
6. THE Server_Card SHALL continue to display the existing `last_patched` date field alongside the new patch status badge.
7. WHEN the user hovers over the patch status badge, THE Server_Card SHALL display a tooltip showing the last time patch metrics were collected by the Agent (sourced from `agent_metrics.collected_at`).

---

### Requirement 6: Agent Collection Interval for Patch Metrics

**User Story:** As a dashboard operator, I want patch metric collection to run on a configurable schedule that is less frequent than the main metrics loop, so that the Agent does not overload the Windows Update API on every heartbeat.

#### Acceptance Criteria

1. THE Agent SHALL collect patch metrics (pending updates, reboot required, patch status) once every 60 minutes by default, independent of the main metrics collection interval.
2. WHERE the `--patch-interval` command-line argument is provided, THE Agent SHALL use the supplied value (in minutes) as the patch collection interval instead of the default 60 minutes.
3. WHEN the patch collection interval has not yet elapsed since the last patch collection, THE Agent SHALL include the most recently collected patch values in the Heartbeat payload rather than re-querying the Windows Update API.
4. WHEN the Agent starts for the first time in a session, THE Agent SHALL perform an immediate patch metrics collection before waiting for the first interval to elapse.

---

### Requirement 7: Dashboard Alert on Critical Patch Status

**User Story:** As a dashboard operator, I want to receive an email alert when a server transitions to `critical` patch status, so that I can act on critical security updates promptly.

#### Acceptance Criteria

1. WHEN the Dashboard receives a Heartbeat with `patch_status` equal to `critical` for a server whose previous stored `patch_status` was not `critical`, THE Dashboard SHALL send an email alert to the configured SMTP recipient(s) with the server hostname, pending update count, and the timestamp of the transition.
2. WHEN the Dashboard has already sent a `critical` patch alert for a server within the preceding 24 hours, THE Dashboard SHALL NOT send a duplicate alert for the same server.
3. IF SMTP is not configured in the Dashboard settings, THEN THE Dashboard SHALL log the alert condition to the application log instead of sending an email.
4. WHEN a server's `patch_status` transitions from `critical` to `up_to_date` or `updates_pending`, THE Dashboard SHALL reset the 24-hour alert suppression timer for that server so that a future `critical` transition triggers a new alert.
