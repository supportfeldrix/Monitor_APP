# Requirements Document

## Introduction

This feature adds CSV export/download capability to the Software Inventory section of the CROIT Monitor APP. Users will be able to export the software inventory for a specific server (or all servers) as a downloadable CSV file directly from the dashboard UI. This supports compliance reporting, auditing, and offline analysis workflows.

## Glossary

- **CSV_Export_API**: The backend API endpoint that generates and returns a CSV file containing software inventory data
- **Export_Button**: The UI control in the Software Inventory panel that triggers the CSV download
- **Software_Inventory**: The database table (`software_inventory`) storing discovered and manually-added software records per server
- **Server**: A monitored server registered in the CROIT Monitor APP
- **Dashboard**: The web-based frontend interface of the CROIT Monitor APP

## Requirements

### Requirement 1: CSV Export API Endpoint

**User Story:** As an operations engineer, I want a backend API endpoint that returns software inventory data as a CSV file, so that I can download structured data for reporting and compliance purposes.

#### Acceptance Criteria

1. WHEN a GET request is made to the CSV export endpoint with a valid server ID, THE CSV_Export_API SHALL return a CSV file containing all software inventory records for that server
2. WHEN a GET request is made to the CSV export endpoint without a server ID, THE CSV_Export_API SHALL return a CSV file containing all software inventory records across all servers
3. THE CSV_Export_API SHALL include the following columns in the CSV output: Server Hostname, Environment, Software Name, Version, Vendor, License Type, Support Status, Risk Rating, Install Path, Discovered By, Created At
4. THE CSV_Export_API SHALL set the HTTP response Content-Type header to `text/csv`
5. THE CSV_Export_API SHALL set the Content-Disposition header to `attachment` with a filename that includes the server hostname (when filtered) and the current date in ISO format
6. WHEN a request is made without valid authentication, THE CSV_Export_API SHALL return HTTP 401 Unauthorized

### Requirement 2: CSV Content Formatting

**User Story:** As an operations engineer, I want the CSV output to be well-formatted and compatible with standard spreadsheet tools, so that I can open it in Excel or LibreOffice without manual cleanup.

#### Acceptance Criteria

1. THE CSV_Export_API SHALL include a header row as the first line of the CSV file with human-readable column names
2. THE CSV_Export_API SHALL properly escape field values that contain commas, double quotes, or newline characters according to RFC 4180
3. THE CSV_Export_API SHALL use UTF-8 encoding for the CSV output
4. WHEN a field value is empty or null, THE CSV_Export_API SHALL output an empty field (two consecutive delimiters)

### Requirement 3: Frontend Export Button

**User Story:** As a dashboard user, I want a clearly visible export button in the Software Inventory panel, so that I can download the CSV with a single click.

#### Acceptance Criteria

1. THE Dashboard SHALL display an Export CSV button in the Software Inventory tab action area
2. WHEN a server is selected in the server filter dropdown, THE Export_Button SHALL download the CSV for that specific server
3. WHEN no server is selected and other filters are active, THE Export_Button SHALL download the CSV for all servers
4. WHILE the CSV file is being generated and downloaded, THE Export_Button SHALL display a loading state to indicate the operation is in progress
5. WHEN the download completes successfully, THE Dashboard SHALL display a success toast notification
6. IF the CSV download fails due to a network or server error, THEN THE Dashboard SHALL display an error toast notification with a descriptive message

### Requirement 4: Export Filename Convention

**User Story:** As an operations engineer, I want downloaded CSV files to have descriptive filenames, so that I can identify them easily in my downloads folder.

#### Acceptance Criteria

1. WHEN exporting software for a specific server, THE CSV_Export_API SHALL use the filename format `software-inventory_{hostname}_{YYYY-MM-DD}.csv`
2. WHEN exporting software for all servers, THE CSV_Export_API SHALL use the filename format `software-inventory_all-servers_{YYYY-MM-DD}.csv`
3. THE CSV_Export_API SHALL sanitize the hostname in the filename by replacing non-alphanumeric characters (except hyphens and underscores) with underscores
