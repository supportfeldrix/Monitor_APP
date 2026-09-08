# Implementation Plan: DB Extended Metrics

## Overview

Extend the CROIT Monitor APP to collect active request counts, running queries, and database lists from Microsoft SQL Server instances via DMVs. The implementation adds a new SQLite table (`db_extended_metrics`), a collection function integrated into the existing `db_monitor_loop`, a REST API endpoint, and frontend UI components in the DB detail view. The backend is Python/Flask and the frontend is vanilla JavaScript.

## Tasks

- [x] 1. Create database schema and storage layer
  - [x] 1.1 Add `db_extended_metrics` table creation to `init_db()`
    - Add `CREATE TABLE IF NOT EXISTS db_extended_metrics` with columns: id (INTEGER PRIMARY KEY AUTOINCREMENT), db_id (INTEGER NOT NULL), active_requests (INTEGER), running_queries (TEXT), databases_list (TEXT), collected_at (TEXT NOT NULL DEFAULT datetime('now'))
    - Add foreign key referencing `db_monitors(id)`
    - Add `CREATE INDEX IF NOT EXISTS idx_dbext_id_time ON db_extended_metrics (db_id, collected_at)`
    - Place alongside existing table definitions in the `init_db()` function
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 1.2 Add cascade delete for extended metrics in `api_delete_db_monitor`
    - In the existing `api_delete_db_monitor(did)` function, add `conn.execute("DELETE FROM db_extended_metrics WHERE db_id=?", (did,))` before the existing heartbeat delete
    - _Requirements: 8.6_

- [x] 2. Implement extended metrics collection
  - [x] 2.1 Create `collect_extended_metrics(conn, db_id)` function
    - Add a new function in `app.py` that accepts an open pyodbc connection and db_id
    - Query active request count: `SELECT COUNT(*) FROM sys.dm_exec_requests WHERE session_id > 50 AND session_id != @@SPID`
    - Query running queries (top 50 by elapsed_time DESC): join `sys.dm_exec_requests` with `sys.dm_exec_sql_text`, retrieving sql_text (truncated to 500 chars via LEFT), status, wait_type, elapsed_time_ms, database_name — excluding own session
    - Query database list: `SELECT name, state_desc, compatibility_level FROM sys.databases ORDER BY name`
    - Each query wrapped in independent try/except — failure stores NULL for that field, logs warning, does not raise
    - Store results as JSON in `db_extended_metrics` using `DB_LOCK` and `get_db()`
    - After INSERT, execute retention purge: delete records for that db_id whose id is NOT IN the 100 most recent by collected_at
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3, 3.4, 3.5, 8.4, 8.5_

  - [x] 2.2 Integrate `collect_extended_metrics` into `check_db_query` for MSSQL
    - In the `check_db_query` function, after the existing session count query succeeds, call `collect_extended_metrics(conn, db_id)` while the pyodbc connection is still open inside the `with` block
    - Pass the db_id through to `check_db_query` (add parameter) or call from `db_monitor_loop` after getting the connection result
    - Ensure collection only runs for MSSQL monitors with both username and password configured
    - Use the same 5-second connection timeout as the existing heartbeat
    - _Requirements: 1.4, 1.5_

  - [ ]* 2.3 Write property test for query text truncation (Property 3)
    - **Property 3: Query Text Truncation**
    - For any SQL text string, after truncation the result length ≤ 500 chars; if original ≤ 500 chars, result is identical to original
    - Use `hypothesis` with `@settings(max_examples=100)`
    - **Validates: Requirements 2.3**

  - [ ]* 2.4 Write property test for running queries bounded and sorted (Property 4)
    - **Property 4: Running Queries Bounded and Sorted**
    - For any set of active requests (0 to N), stored snapshot has ≤ 50 entries ordered by elapsed_time_ms descending
    - Use `hypothesis` with `@settings(max_examples=100)`
    - **Validates: Requirements 2.4**

  - [ ]* 2.5 Write property test for retention invariant (Property 5)
    - **Property 5: Retention Invariant**
    - For any db_id, after any number of insertions, record count never exceeds 100 and retained records are the 100 most recent
    - Use `hypothesis` with `@settings(max_examples=100)` and in-memory SQLite
    - **Validates: Requirements 8.4, 8.5**

  - [ ]* 2.6 Write property test for error resilience (Property 2)
    - **Property 2: Error Resilience — Graceful Degradation**
    - For any exception during collection, NULL is stored for the failed field, no exception propagates, heartbeat loop continues
    - Mock pyodbc cursor to raise on specific queries, verify behavior
    - **Validates: Requirements 1.3, 2.6, 3.4**

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement API endpoint
  - [x] 4.1 Create `GET /api/db-monitors/<id>/extended-metrics` endpoint
    - Add a new Flask route with `@auth_required` decorator
    - Look up the db_monitor by id — return 404 if not found
    - If monitor has no username configured — return 200 with `message` field and null metric values
    - Query `db_extended_metrics` for the most recent record (ORDER BY collected_at DESC LIMIT 1) for that db_id
    - If no record exists — return 200 with `message` indicating no data available and null values
    - On success — return 200 with `active_requests`, `running_queries` (parsed JSON array), `databases_list` (parsed JSON array), and `collected_at`
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 4.2 Write unit tests for the extended metrics API endpoint
    - Test 404 for nonexistent monitor
    - Test 200 with message when monitor has no credentials
    - Test 200 with message when no extended metrics records exist
    - Test 200 with correct data when records exist
    - Test 401 when not authenticated
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 4.3 Write property test for serialization round-trip (Property 1)
    - **Property 1: Extended Metrics Serialization Round-Trip**
    - For any valid extended metrics record, storing and retrieving via the API produces equivalent values
    - Use `hypothesis` with `@settings(max_examples=100)` and in-memory SQLite
    - **Validates: Requirements 1.2, 2.2, 3.2, 3.5, 4.1**

  - [ ]* 4.4 Write property test for cascade delete (Property 6)
    - **Property 6: Cascade Delete — No Orphan Records**
    - After deleting a db_monitor, count of extended metrics for that db_id is zero
    - Use `hypothesis` with `@settings(max_examples=100)` and in-memory SQLite
    - **Validates: Requirements 8.6**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement frontend - Active Requests stat box
  - [x] 6.1 Add Active Requests stat box to the DB detail view
    - In `db.js`, within the `openDbDetail` function (or equivalent detail rendering), add a fetch call to `GET /api/db-monitors/<id>/extended-metrics`
    - Display `active_requests` value in a stat box labeled "Active Requests" positioned after the existing "Total Checks" stat box
    - Use the same HTML structure as existing stat boxes: `<div class="stat-box"><div class="sv val-blue">VALUE</div><div class="sl">Active Requests</div></div>`
    - Display dash character (–) if data is unavailable or monitor lacks credentials
    - Only show for MSSQL monitors with credentials configured
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 7. Implement frontend - Running Queries table
  - [x] 7.1 Add Running Queries table to the DB detail view
    - Render a table below the stat boxes with columns: SQL Text, Status, Wait Type, Elapsed Time (ms), Database
    - Sort rows by elapsed_time_ms descending, show max 50 rows
    - Apply monospace font (`font-family: monospace`) to the SQL Text column
    - Truncate displayed SQL text to 200 characters with an expand/collapse button to show full 500-char text
    - Display "No active queries" message when the array is empty
    - Display error message if the fetch fails or times out (10s), preserving other detail view content
    - Only show for MSSQL monitors with credentials
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 8. Implement frontend - Database List table
  - [x] 8.1 Add Database List table to the DB detail view
    - Render a table with columns: Name, State, Compatibility Level, sorted alphabetically by name
    - Color-code the state: green text/badge for ONLINE, red for OFFLINE, yellow for RESTORING/RECOVERING
    - Display "No database list available — credentials may be required" when data is null or empty
    - Only show for MSSQL monitors with credentials
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 8.2 Write property test for database state color mapping (Property 7)
    - **Property 7: Database State Color Mapping**
    - For any state string from the expected set, the color mapping returns green for ONLINE, red for OFFLINE, yellow for RESTORING/RECOVERING, neutral for others
    - Implement as a simple JS unit test or Python test for the mapping logic
    - **Validates: Requirements 7.3**

- [x] 9. Implement frontend - Auto-refresh timer
  - [x] 9.1 Add 30-second auto-refresh for extended metrics in the detail view
    - When the detail panel opens for an MSSQL monitor with credentials, start a `setInterval` that calls the extended metrics endpoint every 30 seconds
    - Update the Active Requests stat box, Running Queries table, and Database List table on each refresh
    - Clear the interval when the detail panel is closed
    - Store the interval reference (e.g., `extMetricsInterval`) and ensure proper cleanup to avoid memory leaks
    - _Requirements: 6.6_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Add blocking queries collection
  - [x] 11.1 Add `blocking_queries` column to `db_extended_metrics` table
    - Add migration in `init_db()`: `ALTER TABLE db_extended_metrics ADD COLUMN blocking_queries TEXT`
    - The column stores a JSON array of blocking chain objects
    - Use the same try/except migration pattern as existing column additions
    - _Requirements: 9.4, 9.5_

  - [x] 11.2 Implement blocking queries collection in `collect_extended_metrics`
    - Add a new try/except block in `collect_extended_metrics` that queries `sys.dm_exec_requests` joined with `sys.dm_os_waiting_tasks` and `sys.dm_exec_sessions` to identify blocking relationships
    - Identify Head_Blockers: sessions that have other sessions waiting on them but are not themselves waiting on another session
    - For each Head_Blocker, construct a Blocking_Chain: head blocker session_id, head blocker SQL text (via `sys.dm_exec_sql_text`, truncated to 500 chars), and a list of blocked sessions with their session_id, SQL text, wait_type, wait_resource, wait_time_ms
    - Traverse blocking chains to a maximum depth of 10 levels
    - Store empty string for SQL text when `sys.dm_exec_sql_text` returns NULL
    - Store results as JSON array in the `blocking_queries` field; empty array `[]` when no blocking exists
    - On failure: log error, store NULL for `blocking_queries`, do not fail the heartbeat
    - Update the INSERT statement to include `blocking_queries` column
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

  - [x] 11.3 Update API endpoint to include `blocking_queries` in response
    - In `api_get_extended_metrics`, add `blocking_queries` to the returned JSON (parsed from TEXT to JSON array)
    - Return `null` for `blocking_queries` when no data or no credentials
    - _Requirements: 9.4, 4.1_

- [x] 12. Add long-running queries threshold configuration
  - [x] 12.1 Add `long_running_threshold` column to `db_monitors` table
    - Add migration in `init_db()`: `ALTER TABLE db_monitors ADD COLUMN long_running_threshold INTEGER`
    - Default is NULL (meaning use global setting of 5 seconds)
    - Accepts integer values 1-3600 (seconds)
    - _Requirements: 11.2_

  - [x] 12.2 Add global Long_Running_Threshold setting support
    - Use the existing `settings` table to store a global `long_running_threshold` key (default 5 seconds)
    - On app startup, seed the default if not present: `INSERT OR IGNORE INTO settings (key, value) VALUES ('long_running_threshold', '5')`
    - _Requirements: 11.3_

  - [x] 12.3 Update `PATCH /api/db-monitors/<id>` to accept `long_running_threshold_seconds`
    - In the existing PATCH/PUT handler for db_monitors, accept `long_running_threshold_seconds` field
    - Validate: must be integer between 1 and 3600 inclusive; reject with error message if invalid
    - Store in the `long_running_threshold` column of `db_monitors`
    - _Requirements: 11.2, 11.7, 11.9, 11.10_

  - [x] 12.4 Update API endpoint to include threshold in extended-metrics response
    - In `api_get_extended_metrics`, include `long_running_threshold_seconds` in the response
    - Resolve the active threshold: per-monitor value if configured, otherwise global value, otherwise 5
    - _Requirements: 11.1, 11.9_

- [x] 13. Implement frontend - Blocking Queries section
  - [x] 13.1 Add Blocking Queries section to the DB detail view
    - Render a "Blocking Queries" section below the existing Running Queries table
    - Display each Blocking_Chain as a tree: Head_Blocker at root level, Blocked_Sessions indented below
    - For each Head_Blocker: show session_id, SQL text (truncated to 200 chars with expand), count of blocked sessions
    - For each Blocked_Session: show session_id, SQL text (truncated to 200 chars with expand), wait_type, wait_resource, wait_time_ms
    - Display "No blocking queries detected" when the array is empty
    - Cap display at 50 blocked sessions per head blocker with overflow indication
    - Only show for MSSQL monitors with credentials
    - Include in the existing 30-second auto-refresh cycle
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9_

- [x] 14. Implement frontend - Long-Running Queries section
  - [x] 14.1 Add Long-Running Queries section to the DB detail view
    - Render a "Long-Running Queries" section that filters `running_queries` from the API response
    - Show only queries where `elapsed_time_ms > (threshold * 1000)`
    - Use the `long_running_threshold_seconds` value from the API response to determine threshold
    - Display same columns as running queries table: SQL Text, Status, Wait Type, Elapsed Time (ms), Database
    - Apply colored row background to distinguish long-running queries
    - Display "No long-running queries (threshold: X seconds)" when none exceed threshold
    - Only show for MSSQL monitors with credentials
    - Include in the existing 30-second auto-refresh cycle
    - _Requirements: 11.1, 11.4, 11.5, 11.6_

  - [x] 14.2 Add threshold configuration control in the detail view
    - Add an input control (number input + save button) to set the Long_Running_Threshold
    - Pre-populate with the current threshold from the API response
    - On submit: validate (integer 1-3600), call `PATCH /api/db-monitors/<id>` with `long_running_threshold_seconds`
    - On success: re-filter displayed queries immediately without page refresh
    - On validation failure: show error message indicating accepted range (1-3600 seconds)
    - _Requirements: 11.7, 11.8, 11.10_

- [x] 15. Final checkpoint - Verify new features
  - Ensure all new blocking queries and long-running queries features work end-to-end
  - Verify the 30-second refresh includes blocking queries data
  - Ask the user if questions arise

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend uses Python/Flask with SQLite (via `get_db()` and `DB_LOCK` pattern)
- The frontend uses vanilla JavaScript in `db.js` with direct DOM manipulation
- All extended metrics collection is fail-safe: errors never break the heartbeat loop
- The `collect_extended_metrics` function must be called inside the pyodbc `with` block while the connection is still open
- Blocking queries use `sys.dm_exec_requests` + `sys.dm_os_waiting_tasks` + `sys.dm_exec_sessions` DMVs
- Long-running queries are a client-side filter of the existing running_queries data — no additional DMV queries needed
- The Long_Running_Threshold is per-monitor (stored in `db_monitors`) with a global fallback (stored in `settings` table)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.5", "2.6"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4"] },
    { "id": 5, "tasks": ["6.1", "7.1", "8.1", "8.2"] },
    { "id": 6, "tasks": ["9.1"] },
    { "id": 7, "tasks": ["11.1", "12.1", "12.2"] },
    { "id": 8, "tasks": ["11.2", "12.3"] },
    { "id": 9, "tasks": ["11.3", "12.4"] },
    { "id": 10, "tasks": ["13.1", "14.1", "14.2"] },
    { "id": 11, "tasks": ["15"] }
  ]
}
```
