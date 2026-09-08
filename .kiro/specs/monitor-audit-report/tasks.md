# Implementation Plan: Monitor Audit Report

## Overview

Implement a backend API endpoint and frontend download panel that allow users to generate and download CSV audit reports containing monitor uptime statistics and downtime incident details. The implementation follows the existing CSV export pattern (csv + io.StringIO + Flask Response) and reuses `build_monitor_stats()` and `parse_timeframe()` helpers.

## Tasks

- [ ] 1. Implement backend audit report endpoint and helpers
  - [ ] 1.1 Create the `compute_downtime_incidents` helper function in `app.py`
    - Add a function that takes an ordered list of heartbeat rows and a period_end datetime
    - Group consecutive heartbeats with status=0 into incident dicts
    - Each incident contains: incident_number, start_time, end_time, duration_seconds, failed_checks, status ("Resolved"/"Ongoing"), error_message
    - Mark incidents that extend to period end as "Ongoing"
    - Return an empty list when no down heartbeats exist
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [ ] 1.2 Create the `sanitize_monitor_name` helper function in `app.py`
    - Replace non-alphanumeric characters (except hyphens and underscores) with underscores
    - Used for generating safe CSV filenames
    - _Requirements: 1.6_

  - [ ] 1.3 Implement the `GET /api/monitors/<int:mid>/audit-report` endpoint in `app.py`
    - Decorate with `@auth_required`
    - Parse timeframe using `parse_timeframe(request.args)` supporting presets (7d, 30d, 90d) and custom from_dt/to_dt
    - Acquire `DB_LOCK`, fetch monitor row (return 404 if not found), fetch heartbeats for period, release lock
    - Call `build_monitor_stats()` for summary statistics
    - Call `compute_downtime_incidents()` for incident data
    - Format CSV using `csv.writer` + `io.StringIO` with summary section (key-value rows), blank separator row, and incidents section (7-column header + data rows)
    - Handle zero-heartbeat case: produce report with zero stats and empty incidents section (headers only)
    - Return response with `Content-Type: text/csv; charset=utf-8` and `Content-Disposition` attachment header using sanitized filename pattern `{name}_audit_{from}_to_{to}.csv`
    - Catch `ValueError` for invalid date formats (return 400), `sqlite3.Error` for DB errors (return 500 with logged traceback)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4, 4.1, 4.2, 4.3, 4.4, 4.5, 6.1, 6.3_

  - [ ] 1.4 Add streaming response support for large datasets in the audit report endpoint
    - When heartbeat count exceeds 100,000 rows, use Flask `Response` with a generator function that yields CSV rows incrementally
    - Avoid full in-memory buffering for large reports
    - _Requirements: 6.2_

- [ ] 2. Checkpoint - Verify backend endpoint
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Implement frontend audit report panel
  - [ ] 3.1 Add the Audit Report UI panel to the monitor detail view in `frontend/dist/app.js`
    - Add an "Audit Report" section within the existing monitor detail rendering function
    - Include preset time period buttons: "Last 7 Days", "Last 30 Days", "Last 90 Days"
    - Include custom date range inputs (from/to date pickers)
    - Add a "Download Audit Report" button
    - _Requirements: 5.1, 5.2_

  - [ ] 3.2 Implement the download logic and UX feedback in `frontend/dist/app.js`
    - On button click, call `GET /api/monitors/<mid>/audit-report` with selected preset or from_dt/to_dt params
    - Show a loading spinner/indicator while the request is in progress
    - On success, create a blob URL from the response and trigger download via a dynamically created `<a>` element (same pattern as software CSV export)
    - On error, display an error toast/notification with the error message from the API
    - _Requirements: 5.3, 5.4, 5.5_

- [ ] 4. Checkpoint - Verify full feature integration
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Write tests for audit report feature
  - [ ]* 5.1 Write property test for filename sanitization
    - **Property 1: Filename sanitization preserves structure**
    - Test that for any monitor name (special chars, spaces, unicode) and valid date range, the filename matches `{sanitized_name}_audit_{YYYY-MM-DD}_to_{YYYY-MM-DD}.csv` with only alphanumeric, hyphens, and underscores in the name portion
    - **Validates: Requirements 1.6**

  - [ ]* 5.2 Write property test for summary section completeness
    - **Property 2: Summary section completeness and correctness**
    - Test that for any monitor metadata and heartbeat sequence: up_count + down_count == total_checks, uptime_pct == round(up_count/total_checks*100, 2) when total > 0, and all stats are zero when no heartbeats exist
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4**

  - [ ]* 5.3 Write property test for downtime incident grouping
    - **Property 3: Downtime incident grouping correctness**
    - Test that for any ordered heartbeat sequence: (a) every status=0 heartbeat belongs to exactly one incident, (b) no status=1 heartbeat belongs to any incident, (c) incidents are non-overlapping and chronological, (d) failed_checks equals count of down heartbeats per incident, (e) duration_seconds equals end_time minus start_time
    - **Validates: Requirements 3.1, 3.2, 3.3**

  - [ ]* 5.4 Write property test for CSV structural invariant
    - **Property 4: CSV structural invariant**
    - Test that for any report data, the CSV has: summary section with 2-column key-value rows, exactly one blank separator row, incidents section with 7-column header and 7-column data rows
    - **Validates: Requirements 4.1, 4.2, 4.3**

  - [ ]* 5.5 Write property test for timestamp format invariant
    - **Property 5: Timestamp format invariant**
    - Test that all timestamps in the CSV output match ISO 8601 pattern `YYYY-MM-DDTHH:MM:SS`
    - **Validates: Requirements 4.4**

  - [ ]* 5.6 Write unit tests for the audit report endpoint
    - Test GET with valid preset returns 200 + CSV content-type
    - Test GET for non-existent monitor returns 404
    - Test unauthenticated GET returns 401
    - Test report with no heartbeats has zero stats
    - Test report with all-up heartbeats has empty incidents (headers only)
    - Test ongoing incident at period end marked correctly
    - Test database error returns 500
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 2.4, 3.3, 3.4, 6.3_

- [ ] 6. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using Hypothesis (Python)
- The backend follows the same csv + io.StringIO + Flask Response pattern as the existing software CSV export
- Existing helpers `build_monitor_stats()` and `parse_timeframe()` are reused — no duplication
- The frontend follows the same blob download pattern as the software CSV export

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3"] },
    { "id": 2, "tasks": ["1.4", "3.1"] },
    { "id": 3, "tasks": ["3.2"] },
    { "id": 4, "tasks": ["5.1", "5.2", "5.3", "5.4", "5.5", "5.6"] }
  ]
}
```
