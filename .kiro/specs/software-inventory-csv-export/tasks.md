# Implementation Plan: Software Inventory CSV Export

## Overview

This plan implements a CSV export feature for the Software Inventory module. It adds a Flask backend endpoint (`GET /api/software/export-csv`) that generates RFC 4180-compliant CSV files, and a frontend Export button in the Software Inventory tab that triggers a browser download. The implementation follows existing patterns: `DB_LOCK` + `get_db()` for database access, `@auth_required` for authentication, and `fetch()` with `credentials:'include'` on the frontend.

## Tasks

- [ ] 1. Implement backend CSV export endpoint
  - [x] 1.1 Add the filename helper function `_csv_export_filename` to `app.py`
    - Create a helper that accepts an optional hostname string
    - Sanitize hostname by replacing non-alphanumeric characters (except hyphens/underscores) with underscores
    - Return filename in format `software-inventory_{sanitized}_{YYYY-MM-DD}.csv` or `software-inventory_all-servers_{YYYY-MM-DD}.csv` when hostname is None
    - _Requirements: 4.1, 4.2, 4.3_

  - [ ] 1.2 Add the `GET /api/software/export-csv` route to `app.py`
    - Decorate with `@app.route` and `@auth_required`
    - Read optional `server_id` query parameter
    - If `server_id` is provided, validate the server exists (return 404 if not)
    - Query `software_inventory JOIN servers` with optional `server_id` filter, ordered by environment, hostname, name
    - Use `csv.writer` with `io.StringIO` to generate CSV content
    - Write header row: Server Hostname, Environment, Software Name, Version, Vendor, License Type, Support Status, Risk Rating, Install Path, Discovered By, Created At
    - Write data rows, outputting empty string for None/null values
    - Return Flask `Response` with `Content-Type: text/csv; charset=utf-8` and `Content-Disposition: attachment; filename="..."` using the filename helper
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.3, 2.4_

  - [ ]* 1.3 Write property test for server filtering completeness
    - **Property 1: Server filtering completeness**
    - Use `hypothesis` to generate random software inventory records assigned to random servers
    - Export with and without `server_id` filter
    - Assert CSV output contains exactly the matching records (all present, no extras)
    - **Validates: Requirements 1.1, 1.2**

  - [ ]* 1.4 Write property test for CSV field value round-trip
    - **Property 2: CSV field value round-trip**
    - Use `hypothesis` to generate records with arbitrary Unicode text including commas, double quotes, newlines
    - Serialize to CSV via the endpoint logic, parse back with `csv.reader`
    - Assert parsed values are identical to originals
    - **Validates: Requirements 2.2, 2.3**

  - [ ]* 1.5 Write property test for null fields producing empty CSV fields
    - **Property 3: Null fields produce empty CSV fields**
    - Use `hypothesis` to generate records with random nullable fields set to None
    - Export to CSV, parse back, verify empty strings and consistent column count per row
    - **Validates: Requirements 2.4**

  - [ ]* 1.6 Write property test for filename generation with hostname sanitization
    - **Property 4: Filename generation with hostname sanitization**
    - Use `hypothesis` to generate random hostname strings with special characters
    - Call `_csv_export_filename`, verify regex match `software-inventory_[a-zA-Z0-9_-]+_\d{4}-\d{2}-\d{2}\.csv`
    - Verify alphanumeric chars, hyphens, and underscores from original are preserved in position
    - **Validates: Requirements 1.5, 4.1, 4.3**

- [ ] 2. Implement frontend export button and download logic
  - [ ] 2.1 Add the `exportSwCsv()` function to `software.js`
    - Read `swServerFilter` to determine if a server is selected
    - Construct API URL: `${API}/api/software/export-csv` with optional `?server_id=${swServerFilter}`
    - Fetch the response with `credentials: 'include'`
    - On success: create a Blob from response, generate a blob URL, create a temporary `<a>` element with `download` attribute, trigger click, revoke blob URL
    - Extract filename from `Content-Disposition` header if available, otherwise use a default
    - On error: show error toast with descriptive message
    - _Requirements: 3.2, 3.3, 3.5, 3.6_

  - [ ] 2.2 Add the Export CSV button to the inventory tab actions area in `software.js`
    - Insert an "Export CSV" button into `#sw-tab-actions-inventory` alongside existing action buttons
    - Wire the button's `onclick` to call `exportSwCsv()`
    - Implement loading state: disable button and change text to "Exporting..." while the fetch is in progress
    - Reset button state after completion (success or failure)
    - _Requirements: 3.1, 3.4_

  - [ ]* 2.3 Write unit tests for frontend export logic
    - Test that button disables during export and re-enables after
    - Test that success toast appears on successful download
    - Test that error toast appears on failed download
    - Test that `server_id` query param is included when a server is selected
    - _Requirements: 3.4, 3.5, 3.6, 3.2_

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Integration wiring and end-to-end validation
  - [ ] 4.1 Add integration test for the full export flow
    - Seed the test database with servers and software inventory records
    - Make an authenticated GET request to `/api/software/export-csv`
    - Verify response status 200, Content-Type `text/csv; charset=utf-8`, Content-Disposition header with correct filename format
    - Parse CSV body and verify header row matches the 11 specified columns
    - Verify data rows match seeded records
    - Test with `server_id` filter and without
    - Test 404 response for non-existent `server_id`
    - Test 401 response for unauthenticated request
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 4.1, 4.2_

- [ ] 5. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document using Python's `hypothesis` library
- Unit tests validate specific examples and edge cases
- The backend uses Python (`csv`, `io.StringIO`, Flask `Response`) and the frontend uses vanilla JavaScript (`fetch`, Blob API)
- All backend code goes in `app.py` following existing patterns (`DB_LOCK`, `get_db()`, `@auth_required`)
- All frontend code goes in `frontend/dist/software.js` following existing patterns (`fetch` with `credentials:'include'`, `toast()` for notifications)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "1.4", "1.5", "1.6", "2.1"] },
    { "id": 3, "tasks": ["2.2"] },
    { "id": 4, "tasks": ["2.3", "4.1"] }
  ]
}
```
