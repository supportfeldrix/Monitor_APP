# Implementation Plan: Monitor Export/Import

## Overview

Implement disaster recovery export/import functionality for the CROIT Monitor APP. Two new API endpoints (`GET /api/export`, `POST /api/import`) in `app.py` and a corresponding UI section in the Settings page (`frontend/dist/app.js`). The export produces a JSON backup of all configuration tables; the import validates and restores from that backup in either "clean" (wipe-and-restore) or "merge" (skip duplicates) mode.

## Tasks

- [x] 1. Implement the Export API endpoint
  - [x] 1.1 Add `GET /api/export` route in `app.py`
    - Add route with `@role_required(['admin'])` decorator
    - Read all configuration tables inside `with DB_LOCK, get_db() as conn:` block
    - Build the export JSON structure with metadata section (exported_at ISO 8601 UTC, app_version, format_version "1.0", warning about sensitive credentials)
    - Read monitors, db_monitors, status_pages (with their monitor assignments from status_page_monitors), settings, maintenance_windows, servers, software (software_inventory), software_catalogue, dependencies (as service_dependencies), topology_layout (as topology_positions), version_trackers
    - For status pages: join status_page_monitors to get monitor_name, monitor_url, sort_order per page
    - For maintenance_windows: include monitor_name and monitor_url references
    - For service_dependencies: map from `dependencies` table columns to export schema
    - For topology_positions: map from `topology_layout` table columns to export schema
    - Return response with `Content-Type: application/json`, `Content-Disposition: attachment; filename="croit-monitor-backup-YYYY-MM-DD.json"` using current UTC date
    - Handle database read errors with 500 status and error message
    - Empty tables produce empty arrays in the output
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 6.1, 6.2, 6.3, 6.4_

  - [ ]* 1.2 Write property test for export round-trip consistency
    - **Property 1: Export/Import Round-Trip Preserves Configuration**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.14, 2.1–2.10, 6.5**

  - [ ]* 1.3 Write property test for sensitive data handling in export
    - **Property 5: Export Includes DB Passwords But Excludes User Password Hashes**
    - **Validates: Requirements 6.1, 6.3**

- [x] 2. Implement the Import API endpoint — validation layer
  - [x] 2.1 Add `POST /api/import` route in `app.py` with validation logic
    - Add route with `@role_required(['admin'])` decorator
    - Accept `multipart/form-data` with `file` and `mode` fields
    - Validate file is present, reject with 400 if missing
    - Validate file size does not exceed 50 MB, reject with 400 if exceeded
    - Parse JSON content, reject with 400 and parse error detail if invalid
    - Validate metadata section exists and contains `format_version`
    - Validate `format_version` is "1.0" (supported list), reject unsupported versions with 400
    - Validate all required top-level sections are present: monitors, db_monitors, settings, status_pages, maintenance_windows, servers, software_inventory, software_catalogue, service_dependencies, version_trackers
    - Validate each monitor entry has required fields: name, url, type — report invalid entry by array index
    - Validate each db_monitor entry has required fields: name, db_type, host — report invalid entry by array index
    - Validate mode is "clean" or "merge" (default "clean"), reject invalid modes with 400
    - All validation completes before any database writes
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 4.4, 4.5_

  - [ ]* 2.2 Write property test for structural validation
    - **Property 2: Structural Validation Rejects Invalid Backups and Identifies Violations**
    - **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 3.8**

- [x] 3. Implement the Import API endpoint — clean mode insert logic
  - [x] 3.1 Implement clean mode database operations in `app.py`
    - After validation passes, acquire `DB_LOCK` and begin explicit transaction
    - In "clean" mode: DELETE all rows from monitors, db_monitors, status_pages, status_page_monitors, settings, maintenance_windows, servers, software, software_catalogue, dependencies, topology_layout, version_trackers — but NOT users table
    - INSERT all records from backup into respective tables
    - For status_pages: insert page first, then look up the page id and insert status_page_monitors entries (resolve monitor references by name+url to get monitor id)
    - For software_inventory: resolve server_hostname to server id during insert
    - For service_dependencies: resolve monitor references by name+url to get monitor ids, insert into dependencies table
    - For topology_positions: resolve monitor references by name+url, insert into topology_layout table
    - For maintenance_windows: resolve monitor references by name+url if present
    - COMMIT on success, ROLLBACK on any error
    - Return 200 with summary counts per category (monitors, db_monitors, status_pages, settings, maintenance_windows, servers, software_inventory, software_catalogue, service_dependencies, version_trackers)
    - Return 500 with error detail and rollback confirmation on transaction failure
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 4.1, 4.3, 4.4, 6.5_

  - [ ]* 3.2 Write property test for clean mode user preservation
    - **Property 3: Clean Mode Replaces All Configuration But Preserves Users**
    - **Validates: Requirements 4.1, 4.3**

  - [ ]* 3.3 Write property test for transaction atomicity
    - **Property 6: Transaction Atomicity on Import Failure**
    - **Validates: Requirements 2.11, 2.13**

  - [ ]* 3.4 Write property test for import summary accuracy
    - **Property 7: Import Summary Counts Match Actual Records**
    - **Validates: Requirements 2.12**

- [x] 4. Checkpoint - Verify backend export and clean import
  - Ensure all tests pass, ask the user if questions arise.
  - Run syntax check: `python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"`

- [x] 5. Implement the Import API endpoint — merge mode logic
  - [x] 5.1 Add merge mode duplicate detection and insert logic in `app.py`
    - Extend the import route to handle `mode="merge"`
    - Before inserting each record, check for existing duplicates using the unique keys:
      - monitors: `name` + `url`
      - db_monitors: `name` + `host` + `port` + `database`
      - status_pages: `slug`
      - servers: `hostname`
      - software_inventory: `server_hostname` + `name`
      - software_catalogue: `name_pattern` + `vendor`
      - service_dependencies: `monitor_name` + `monitor_url` + `depends_on_name` + `depends_on_url`
      - version_trackers: `name_match` + `check_source`
      - settings: `key` (upsert — always overwrite value)
      - maintenance_windows: always insert (no duplicate check)
    - Skip records that match existing duplicates
    - Insert non-duplicate records
    - Track and return counts of inserted and skipped per category
    - Wrap in transaction with COMMIT/ROLLBACK
    - _Requirements: 4.2, 4.6_

  - [ ]* 5.2 Write property test for merge mode duplicate handling
    - **Property 4: Merge Mode Skips Duplicates and Reports Accurately**
    - **Validates: Requirements 4.2, 4.6**

- [x] 6. Checkpoint - Verify backend merge mode
  - Ensure all tests pass, ask the user if questions arise.
  - Run syntax check: `python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"`

- [x] 7. Implement frontend Export/Import UI
  - [x] 7.1 Add Export/Import section to the Settings page in `frontend/dist/app.js`
    - Add an "Export / Import" section in the settings page HTML (rendered within `loadSettings()` or equivalent settings rendering function)
    - Only display when `currentUserInfo.role === 'admin'`
    - Add Export button that triggers `fetch('/api/export', {credentials:'include'})`, converts response to blob, and initiates download via temporary anchor element
    - Add file input that accepts only `.json` files, displays selected filename
    - Add mode selector: radio buttons for "Clean Restore" (default selected) and "Merge"
    - Add Import button that uploads file via `FormData` to `POST /api/import` with selected mode
    - Implement loading state: disable both Export and Import buttons during any operation, show spinner/indicator
    - On import success: display green notification with summary counts, auto-dismiss after 5 seconds
    - On import error: display red/persistent error notification with backend error message, dismiss on user click
    - On export error: display persistent error notification
    - Handle network errors ("Could not connect to server") and timeout (30s)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

- [x] 8. Checkpoint - Verify frontend syntax and full integration
  - Ensure all tests pass, ask the user if questions arise.
  - Run syntax check: `node --check frontend/dist/app.js`
  - Verify export button triggers download, import button uploads file with correct mode

- [x] 9. Wire together and verify access control
  - [x] 9.1 Verify access control and end-to-end flow
    - Confirm `@role_required(['admin'])` is on both `/api/export` and `/api/import` routes
    - Verify 401 returned for unauthenticated requests (handled by flask-login)
    - Verify 403 returned for non-admin users (viewer, dba)
    - Verify frontend only shows Export/Import section for admin role
    - Test full round-trip: export → clear database → import (clean) → verify data restored
    - Test merge mode: import into populated database → verify duplicates skipped, new records added
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - Run syntax checks for both backend and frontend
  - Verify no regressions in existing functionality

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- The project has no automated test framework — property tests would require `pytest` + `hypothesis` setup
- All backend changes go into `app.py` (single-file Flask pattern)
- All frontend changes go into `frontend/dist/app.js` (vanilla JS, no build step)
- Database table name mapping: `dependencies` → `service_dependencies` in export, `topology_layout` → `topology_positions` in export
- Use `DB_LOCK` for all database operations to prevent conflicts with monitoring loops

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "1.2", "1.3"] },
    { "id": 2, "tasks": ["3.1", "2.2"] },
    { "id": 3, "tasks": ["5.1", "3.2", "3.3", "3.4"] },
    { "id": 4, "tasks": ["7.1", "5.2"] },
    { "id": 5, "tasks": ["9.1"] }
  ]
}
```
