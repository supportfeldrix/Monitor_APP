# Requirements Document

## Introduction

The Monitor Audit Report feature enables users to generate and download comprehensive CSV reports detailing monitor uptime, downtime incidents, and performance metrics for a specified time period. This feature supports compliance audits by providing a structured, downloadable record of monitoring data.

## Glossary

- **Report_Generator**: The backend component responsible for compiling monitor statistics and downtime incidents into a structured CSV report.
- **Audit_Report**: A CSV file containing monitor metadata, uptime statistics, and downtime incident details for a specified time period.
- **Downtime_Incident**: A contiguous sequence of one or more heartbeat checks with status 0 (down), bounded by checks with status 1 (up) or the edges of the reporting period.
- **Monitor**: A configured endpoint check stored in the monitors table, identified by id, name, url, and type.
- **Heartbeat**: A single check result stored in the heartbeats table, recording status (1=up, 0=down), latency, message, and timestamp.
- **Time_Period**: The date/time range for which the report is generated, specified as a preset (7d, 30d, 90d) or custom from/to dates.
- **Frontend_Report_Panel**: The UI component that allows users to select a monitor, choose a time period, and trigger the report download.

## Requirements

### Requirement 1: Generate Audit Report via API

**User Story:** As a compliance officer, I want to request an audit report for a specific monitor and time period via an API endpoint, so that I can obtain structured uptime/downtime data for audit purposes.

#### Acceptance Criteria

1. WHEN a GET request is made to `/api/monitors/<mid>/audit-report` with valid timeframe parameters, THE Report_Generator SHALL return a CSV file as an attachment with Content-Type `text/csv`.
2. WHEN a GET request is made to `/api/monitors/<mid>/audit-report` with a preset parameter (7d, 30d, 90d), THE Report_Generator SHALL generate the report for the corresponding time period relative to the current UTC time.
3. WHEN a GET request is made to `/api/monitors/<mid>/audit-report` with from_dt and to_dt parameters, THE Report_Generator SHALL generate the report for the specified custom date range.
4. WHEN a GET request is made to `/api/monitors/<mid>/audit-report` for a monitor that does not exist, THE Report_Generator SHALL return HTTP 404 with an error message.
5. THE Report_Generator SHALL require authentication via the @auth_required decorator before processing any audit report request.
6. THE Report_Generator SHALL name the downloaded CSV file using the pattern `{monitor_name}_audit_{from_date}_to_{to_date}.csv`.

### Requirement 2: Report Content — Summary Section

**User Story:** As a compliance officer, I want the audit report to include a summary of monitor metadata and uptime statistics, so that I can quickly assess overall service availability.

#### Acceptance Criteria

1. THE Report_Generator SHALL include the following monitor metadata in the report summary: monitor name, URL, type, and check interval.
2. THE Report_Generator SHALL include the following statistics in the report summary: uptime percentage, total checks, up count, down count, and average latency in milliseconds.
3. THE Report_Generator SHALL include the reporting period start and end timestamps in ISO 8601 format in the report summary.
4. WHEN no heartbeat data exists for the specified time period, THE Report_Generator SHALL set uptime percentage, average latency, total checks, up count, and down count to zero in the summary.

### Requirement 3: Report Content — Downtime Incidents Section

**User Story:** As a compliance officer, I want the audit report to list each downtime incident with start time, end time, duration, and error messages, so that I can investigate service disruptions.

#### Acceptance Criteria

1. THE Report_Generator SHALL identify downtime incidents by grouping consecutive heartbeats with status 0 (down) into a single incident.
2. FOR EACH downtime incident, THE Report_Generator SHALL record the incident start time (first down heartbeat timestamp), end time (last down heartbeat timestamp), duration in seconds, number of failed checks, and the error message from the first failed check.
3. WHEN a downtime incident extends to the end of the reporting period without a recovery, THE Report_Generator SHALL use the reporting period end time as the incident end time and mark the incident as ongoing.
4. WHEN no downtime incidents exist in the specified time period, THE Report_Generator SHALL include an empty incidents section with headers only.

### Requirement 4: CSV Format Structure

**User Story:** As a compliance officer, I want the CSV report to follow a consistent, parseable structure, so that I can import it into audit tools and spreadsheets.

#### Acceptance Criteria

1. THE Report_Generator SHALL structure the CSV with a summary section followed by a blank separator row followed by an incidents section.
2. THE Report_Generator SHALL format the summary section as key-value rows with columns: Field, Value.
3. THE Report_Generator SHALL format the incidents section with columns: Incident_Number, Start_Time, End_Time, Duration_Seconds, Failed_Checks, Status, Error_Message.
4. THE Report_Generator SHALL format all timestamps in the CSV using ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
5. THE Report_Generator SHALL use UTF-8 encoding for the CSV file.

### Requirement 5: Frontend Report Download Interface

**User Story:** As a user, I want a UI panel to select a monitor and time period and download the audit report, so that I can generate reports without using the API directly.

#### Acceptance Criteria

1. WHEN the user navigates to a monitor's detail view, THE Frontend_Report_Panel SHALL display an "Audit Report" download option.
2. THE Frontend_Report_Panel SHALL provide time period selection with preset options (Last 7 Days, Last 30 Days, Last 90 Days) and a custom date range picker.
3. WHEN the user selects a time period and clicks the download button, THE Frontend_Report_Panel SHALL initiate a file download by calling the audit report API endpoint with the selected parameters.
4. WHILE the report is being generated, THE Frontend_Report_Panel SHALL display a loading indicator to inform the user that the download is in progress.
5. IF the API returns an error, THEN THE Frontend_Report_Panel SHALL display an error notification with the error message.

### Requirement 6: Performance and Data Handling

**User Story:** As a system administrator, I want the report generation to handle large datasets without degrading application performance, so that the monitoring system remains responsive during report generation.

#### Acceptance Criteria

1. THE Report_Generator SHALL acquire the DB_LOCK for the minimum duration required to read data, then release it before CSV formatting.
2. WHEN the reporting period contains more than 100,000 heartbeat records, THE Report_Generator SHALL stream the CSV response instead of buffering the entire file in memory.
3. IF a database error occurs during report generation, THEN THE Report_Generator SHALL return HTTP 500 with a descriptive error message and log the error.
