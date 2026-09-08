# Requirements Document

## Introduction

This feature extends the CROIT Monitor APP's database monitoring capabilities for Microsoft SQL Server instances when credentials are provided. Currently, the monitor only performs a connectivity check (`SELECT 1`) and counts active user sessions. This enhancement adds real-time visibility into active queries/requests ("hits"), the actual SQL commands currently executing, a list of all databases on the server, blocking query detection with chain visualization, and a dedicated long-running queries view with configurable thresholds. These extended metrics are collected during the periodic monitoring loop and exposed via new API endpoints and frontend UI panels in the detail view.

## Glossary

- **Monitor_App**: The CROIT Monitor APP Flask backend that runs background monitoring loops and serves API endpoints
- **Extended_Metrics_Collector**: The component within the Monitor_App responsible for querying SQL Server DMVs to gather active requests, running queries, and database listings
- **DB_Detail_View**: The frontend panel displayed when a user clicks on a database card, showing statistics and charts for a specific monitored database
- **Active_Request**: A currently executing request on SQL Server as reported by `sys.dm_exec_requests`
- **Running_Query**: The SQL text of an Active_Request, retrieved via `sys.dm_exec_sql_text`
- **Database_List**: The collection of databases present on the monitored SQL Server instance as reported by `sys.databases`
- **DMV**: Dynamic Management View — SQL Server system views that expose server state and performance data
- **Heartbeat**: A single monitoring check result stored in the `db_heartbeats` table
- **Blocking_Query**: A session holding a lock that prevents one or more other sessions from proceeding, identified via `sys.dm_exec_requests` and `sys.dm_os_waiting_tasks`
- **Head_Blocker**: The root session in a blocking chain that is not itself blocked by another session, causing a cascade of blocked sessions
- **Blocked_Session**: A session that is waiting to acquire a resource held by a Blocking_Query
- **Blocking_Chain**: A tree of sessions where the Head_Blocker is the root, intermediate nodes are both blocked and blocking, and leaf nodes are only blocked
- **Wait_Resource**: The specific resource (lock, latch, or page) that a Blocked_Session is waiting to acquire, as reported by `sys.dm_exec_requests.wait_resource`
- **Long_Running_Query**: A Running_Query whose elapsed time exceeds the configured Long_Running_Threshold
- **Long_Running_Threshold**: A configurable duration (in seconds) above which a Running_Query is classified as a Long_Running_Query; defaults to 5 seconds

## Requirements

### Requirement 1: Collect Active Request Count

**User Story:** As a DevOps engineer, I want to see how many active queries/requests are currently running on my SQL Server, so that I can identify periods of high database load.

#### Acceptance Criteria

1. WHEN a monitoring heartbeat is executed for an MSSQL database where both username and password are configured, THE Extended_Metrics_Collector SHALL query `sys.dm_exec_requests` to count the number of currently executing user requests, excluding system session IDs (session_id > 50)
2. THE Extended_Metrics_Collector SHALL store the active request count as a non-negative integer in the `db_extended_metrics` record associated with the same db_id and collection timestamp as the heartbeat
3. IF the active request count query fails due to insufficient permissions or any query execution error, THEN THE Extended_Metrics_Collector SHALL log the error message, store NULL for the active request count, and continue the heartbeat without failing the overall connectivity check
4. WHEN username or password is not configured for a database monitor, THE Extended_Metrics_Collector SHALL skip extended metrics collection entirely and perform only the TCP connectivity check
5. THE Extended_Metrics_Collector SHALL execute the active request count query using the same connection timeout (5 seconds) as the existing heartbeat connectivity check

### Requirement 2: Collect Running Queries

**User Story:** As a DevOps engineer, I want to see what SQL commands are currently executing on my SQL Server, so that I can diagnose performance bottlenecks and identify long-running queries.

#### Acceptance Criteria

1. WHEN a monitoring heartbeat is executed for an MSSQL database with valid credentials, THE Extended_Metrics_Collector SHALL query `sys.dm_exec_requests` joined with `sys.dm_exec_sql_text` to retrieve the SQL text, status, wait type, elapsed time (in milliseconds), and database name for each Active_Request, excluding the monitoring session's own request
2. THE Extended_Metrics_Collector SHALL store the running queries snapshot as a JSON array associated with the heartbeat timestamp, where each element contains the fields: sql_text (string), status (string), wait_type (string or null), elapsed_time_ms (integer), and database_name (string)
3. THE Extended_Metrics_Collector SHALL truncate individual query text to a maximum of 500 characters to limit storage consumption
4. THE Extended_Metrics_Collector SHALL store at most 50 running queries per snapshot, ordered by elapsed time descending, to bound storage size
5. WHEN no active requests are found on the server, THE Extended_Metrics_Collector SHALL store an empty JSON array for the running queries snapshot
6. IF the running queries query fails due to insufficient permissions, connection timeout, or any other error, THEN THE Extended_Metrics_Collector SHALL log the error and continue without failing the overall heartbeat check

### Requirement 3: Collect Database List

**User Story:** As a DevOps engineer, I want to see all databases that exist on my SQL Server instance, so that I can verify expected databases are present and monitor the server inventory.

#### Acceptance Criteria

1. WHEN a monitoring heartbeat is executed for an MSSQL database with valid credentials, THE Extended_Metrics_Collector SHALL query `sys.databases` to retrieve the name, state description, and compatibility level of each database
2. THE Extended_Metrics_Collector SHALL store the database list as a JSON array in the `databases_list` column of the extended metrics record associated with the database monitor
3. WHEN a monitoring heartbeat is executed for an MSSQL database with valid credentials, THE Extended_Metrics_Collector SHALL replace the previously stored database list with the current query result on each heartbeat cycle
4. IF the database list query fails due to insufficient permissions or a query execution error, THEN THE Extended_Metrics_Collector SHALL log the error including the failure reason, store a null value for the databases_list field, and continue without failing the overall heartbeat check
5. WHEN the database list query succeeds, THE Extended_Metrics_Collector SHALL store each database entry as a JSON object containing exactly three fields: name (string), state_desc (string), and compatibility_level (integer)

### Requirement 4: Extended Metrics API Endpoints

**User Story:** As a frontend developer, I want API endpoints that expose the extended metrics data, so that I can render them in the detail view.

#### Acceptance Criteria

1. WHEN an authenticated user requests `GET /api/db-monitors/<id>/extended-metrics` for an existing monitor with credentials and collected data, THE Monitor_App SHALL return HTTP 200 with a JSON object containing `active_requests` (integer), `running_queries` (JSON array), `databases_list` (JSON array), and `collected_at` (timestamp string) from the most recent `db_extended_metrics` record for that monitor
2. IF the specified database monitor `<id>` does not exist, THEN THE Monitor_App SHALL return HTTP 404 with a JSON object containing an error message indicating the monitor was not found
3. IF the specified database monitor does not have a username configured, THEN THE Monitor_App SHALL return HTTP 200 with a JSON object containing a `message` field indicating extended metrics require credentials and null values for `active_requests`, `running_queries`, and `databases_list`
4. IF the specified database monitor has zero records in the `db_extended_metrics` table, THEN THE Monitor_App SHALL return HTTP 200 with a JSON object containing a `message` field indicating no data is available yet and null values for `active_requests`, `running_queries`, and `databases_list`
5. THE Monitor_App SHALL require authentication via the `@auth_required` decorator for the extended metrics endpoint, returning HTTP 401 for unauthenticated requests

### Requirement 5: Display Active Request Count in Detail View

**User Story:** As a DevOps engineer, I want to see the active request count ("hits") in the database detail panel, so that I can monitor real-time load at a glance.

#### Acceptance Criteria

1. WHEN a user opens the DB_Detail_View for an MSSQL monitor with credentials, THE DB_Detail_View SHALL fetch the `GET /api/db-monitors/<id>/extended-metrics` endpoint and display the `active_requests` value in a stat box labeled "Active Requests", positioned after the existing "Total Checks" stat box
2. IF the extended-metrics endpoint returns a response indicating no data is available or the monitor lacks credentials, THEN THE DB_Detail_View SHALL display a dash character (–) in the Active Requests stat box value area
3. THE DB_Detail_View SHALL render the Active Requests stat box using the same HTML structure as existing stat boxes (`<div class="stat-box"><div class="sv val-COLOR">VALUE</div><div class="sl">LABEL</div></div>`) with the `val-blue` color class for the value
4. WHEN a user opens the DB_Detail_View for a non-MSSQL monitor or a monitor without credentials configured, THE DB_Detail_View SHALL not display the Active Requests stat box

### Requirement 6: Display Running Queries Table in Detail View

**User Story:** As a DevOps engineer, I want to see a table of currently running queries in the detail panel, so that I can identify what is consuming database resources.

#### Acceptance Criteria

1. WHEN a user opens the DB_Detail_View for an MSSQL monitor with credentials, THE DB_Detail_View SHALL display a table showing running queries with columns: SQL Text, Status, Wait Type, Elapsed Time (ms), and Database, sorted by Elapsed Time descending, displaying a maximum of 50 rows
2. IF the running queries array returned from the API is empty, THEN THE DB_Detail_View SHALL display a message stating "No active queries" in place of the table
3. THE DB_Detail_View SHALL truncate displayed SQL text to 200 characters with an expand option to view the full 500-character stored text
4. THE DB_Detail_View SHALL apply a monospace font to the SQL Text column
5. IF the API call to retrieve running queries fails or times out within 10 seconds, THEN THE DB_Detail_View SHALL display an error message indicating the queries could not be loaded, and SHALL preserve any previously displayed content in other sections of the detail view
6. WHEN the DB_Detail_View is open, THE DB_Detail_View SHALL refresh the running queries table every 30 seconds without requiring a full page reload

### Requirement 7: Display Database List in Detail View

**User Story:** As a DevOps engineer, I want to see a list of all databases on the server in the detail panel, so that I can verify the server inventory without connecting separately.

#### Acceptance Criteria

1. WHEN a user opens the DB_Detail_View for an MSSQL monitor with credentials, THE DB_Detail_View SHALL display a table of databases with columns: Name, State, and Compatibility Level, sorted alphabetically by name
2. WHEN no database list data is available, THE DB_Detail_View SHALL display a message stating "No database list available — credentials may be required"
3. THE DB_Detail_View SHALL visually distinguish databases in an ONLINE state (green text or badge) from those in OFFLINE state (red) or RESTORING/RECOVERING state (yellow)
4. WHEN a user opens the DB_Detail_View for a non-MSSQL monitor or a monitor without credentials configured, THE DB_Detail_View SHALL not display the database list section

### Requirement 8: Extended Metrics Storage Schema

**User Story:** As a developer, I want the extended metrics to be stored persistently, so that the data survives application restarts and can be retrieved by the API.

#### Acceptance Criteria

1. THE Monitor_App SHALL create a `db_extended_metrics` table with columns: id (INTEGER PRIMARY KEY AUTOINCREMENT), db_id (INTEGER NOT NULL, foreign key referencing db_monitors(id)), active_requests (INTEGER), running_queries (TEXT storing JSON), databases_list (TEXT storing JSON), and collected_at (TEXT NOT NULL, defaulting to current UTC timestamp)
2. THE Monitor_App SHALL create an index on the `db_extended_metrics` table covering (db_id, collected_at) to support efficient retention queries and time-range lookups
3. THE Monitor_App SHALL create the `db_extended_metrics` table and its index on application startup using IF NOT EXISTS, within the init_db() function alongside existing table definitions
4. THE Monitor_App SHALL retain only the most recent 100 extended metrics records per db_id, ordered by collected_at descending
5. WHEN inserting a new extended metrics record, THE Monitor_App SHALL delete records for that db_id whose id is not among the 100 most recent (by collected_at descending), within the same database transaction as the insert
6. WHEN a db_monitor is deleted, THE Monitor_App SHALL delete all associated records from the `db_extended_metrics` table for that db_id

### Requirement 9: Collect Blocking Query Information

**User Story:** As a DBA, I want to see which sessions are blocking other sessions on my SQL Server, so that I can quickly identify and resolve lock contention issues causing application slowdowns.

#### Acceptance Criteria

1. WHEN a monitoring heartbeat is executed for an MSSQL database with valid credentials, THE Extended_Metrics_Collector SHALL query `sys.dm_exec_requests` joined with `sys.dm_os_waiting_tasks` and `sys.dm_exec_sessions` to identify sessions that are blocking other sessions
2. WHEN blocking sessions are identified, THE Extended_Metrics_Collector SHALL identify each Head_Blocker by finding sessions that have other sessions waiting on them but are not themselves waiting on another session
3. WHEN a Head_Blocker is identified, THE Extended_Metrics_Collector SHALL construct a Blocking_Chain capturing: the head blocker session_id, head blocker SQL text, each blocked session_id, each blocked session SQL text, wait_type, wait_resource, and wait_time_ms for each blocked session, traversing a maximum depth of 10 levels from the head blocker
4. THE Extended_Metrics_Collector SHALL store blocking query data as a JSON array in a `blocking_queries` field within the `db_extended_metrics` record, where each element represents one Blocking_Chain containing the head blocker and its list of blocked sessions
5. WHEN no blocking relationships exist on the server, THE Extended_Metrics_Collector SHALL store an empty JSON array for the blocking_queries field
6. THE Extended_Metrics_Collector SHALL truncate SQL text for both blocking and blocked sessions to a maximum of 500 characters, consistent with the running queries truncation
7. IF the SQL text cannot be retrieved for a blocking or blocked session (NULL from the DMV), THEN THE Extended_Metrics_Collector SHALL store an empty string for that session's SQL text field in the Blocking_Chain
8. IF the blocking queries query fails due to insufficient permissions or any query execution error, THEN THE Extended_Metrics_Collector SHALL log the error, store NULL for the blocking_queries field, and continue without failing the overall heartbeat check

### Requirement 10: Display Blocking Queries in Detail View

**User Story:** As a DBA, I want to see blocking relationships in the detail panel with a clear visual hierarchy, so that I can immediately identify the root cause of lock contention and take corrective action.

#### Acceptance Criteria

1. WHEN a user opens the DB_Detail_View for an MSSQL monitor with credentials, THE DB_Detail_View SHALL display a "Blocking Queries" section showing each Blocking_Chain as a tree structure where each Head_Blocker is a root node and its direct Blocked_Sessions are rendered as indented child nodes beneath it
2. THE DB_Detail_View SHALL visually distinguish Head_Blocker sessions from Blocked_Sessions using a tree-style indented layout where Head_Blocker rows are displayed at the root level and Blocked_Session rows are indented by at least one level to communicate the blocker → blocked relationship
3. THE DB_Detail_View SHALL display for each Head_Blocker: the session_id, SQL text (truncated to 200 characters with an expand option to reveal the full text), and the count of sessions it is blocking
4. THE DB_Detail_View SHALL display for each Blocked_Session: the session_id, SQL text (truncated to 200 characters with an expand option to reveal the full text), wait_type, wait_resource, and wait_time_ms displayed as a numeric value in milliseconds
5. WHEN the blocking_queries array returned from the API is empty, THE DB_Detail_View SHALL display a message stating "No blocking queries detected" in place of the blocking section content
6. IF the API request for blocking queries fails or returns an error, THEN THE DB_Detail_View SHALL display an error indication within the Blocking Queries section and retain any previously displayed blocking data until the next successful refresh
7. WHEN the DB_Detail_View is open, THE DB_Detail_View SHALL refresh the blocking queries data using the same 30-second setInterval timer as the existing extended metrics refresh, executing both fetches within the same refresh cycle
8. WHEN a user opens the DB_Detail_View for a non-MSSQL monitor or a monitor without credentials configured, THE DB_Detail_View SHALL not render the Blocking Queries section in the DOM
9. IF a Blocking_Chain contains more than 50 Blocked_Sessions under a single Head_Blocker, THEN THE DB_Detail_View SHALL display the first 50 Blocked_Sessions and provide an indication that additional blocked sessions exist

### Requirement 11: Long-Running Queries View with Configurable Threshold

**User Story:** As a DBA, I want a dedicated section that highlights queries running longer than a configurable threshold, so that I can quickly identify problematic queries without scanning through all active queries.

#### Acceptance Criteria

1. WHEN a user opens the DB_Detail_View for an MSSQL monitor with credentials, THE DB_Detail_View SHALL display a "Long-Running Queries" section that filters the running queries snapshot to show only queries whose elapsed_time_ms exceeds the active Long_Running_Threshold for that monitor (resolved as: per-monitor value if configured, otherwise global value, otherwise 5 seconds)
2. THE Monitor_App SHALL store a configurable Long_Running_Threshold value (in seconds) per database monitor in the `db_monitors` table, accepting integer values between 1 and 3600 inclusive, defaulting to 5 seconds when not explicitly configured
3. THE Monitor_App SHALL support a global Long_Running_Threshold setting that applies to all monitors where no per-monitor threshold is configured, with the global setting defaulting to 5 seconds
4. WHEN the per-monitor Long_Running_Threshold is configured, THE DB_Detail_View SHALL use the per-monitor value, overriding the global setting
5. THE DB_Detail_View SHALL display the Long-Running Queries section with the same table columns as the running queries table (SQL Text, Status, Wait Type, Elapsed Time, Database), with a colored row background distinguishing long-running query rows from standard query rows
6. WHEN no running queries exceed the Long_Running_Threshold, THE DB_Detail_View SHALL display a message stating "No long-running queries (threshold: X seconds)" where X is the active threshold value for that monitor
7. THE DB_Detail_View SHALL provide an input control to view and modify the Long_Running_Threshold for the current monitor directly from the detail view, accepting only integer values between 1 and 3600 inclusive, with changes persisted via the API
8. WHEN a user submits a valid Long_Running_Threshold value via the detail view control, THE Monitor_App SHALL update the stored threshold for that monitor and re-filter the displayed running queries against the new threshold within 1 second of successful API response, without requiring a page refresh
9. THE Monitor_App SHALL expose the Long_Running_Threshold configuration via `GET /api/db-monitors/<id>/extended-metrics` (included in the response) and allow updates via `PATCH /api/db-monitors/<id>` with a `long_running_threshold_seconds` field
10. IF a user submits a Long_Running_Threshold value that is not an integer or is outside the range of 1 to 3600, THEN THE Monitor_App SHALL reject the update, retain the previous threshold value, and display an error message indicating the accepted range
