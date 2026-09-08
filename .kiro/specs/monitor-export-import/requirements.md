# Requirements Document

## Introduction

Export/Import feature for the CROIT Monitor APP that enables disaster recovery by allowing administrators to export all monitor configurations to a JSON backup file and re-import them when the `uptime.db` SQLite database is corrupted or deleted. The feature covers HTTP/HTTPS/TCP monitors, database monitors, status pages, notification settings, server inventory, software inventory, and all associated configuration that would be time-consuming to recreate manually.

## Glossary

- **Export_Service**: The backend component responsible for reading all configuration data from the SQLite database and producing a structured JSON file.
- **Import_Service**: The backend component responsible for reading a JSON backup file, validating its structure, and inserting the configuration data into the SQLite database.
- **Backup_File**: A JSON file containing a complete snapshot of all monitor configurations, settings, and associated data exported from the application.
- **Admin_User**: A user with the `admin` role who has permission to perform export and import operations.
- **Monitor_Configuration**: The complete set of attributes for an HTTP/HTTPS/TCP/keyword monitor including name, URL, type, interval, retries, timeout, keyword, accepted codes, description, tags, group, and enabled state.
- **DB_Monitor_Configuration**: The complete set of attributes for a database monitor including name, db_type, host, port, database, username, password, interval, enabled state, description, group, and long_running_threshold.
- **Status_Page_Configuration**: A status page definition including slug, title, description, theme, show_tags, custom_css, and its assigned monitor list with sort order.

## Requirements

### Requirement 1: Export All Configuration Data

**User Story:** As an admin, I want to export all monitor configurations and settings to a JSON backup file, so that I can restore my setup if the database is lost or corrupted.

#### Acceptance Criteria

1. WHEN an Admin_User sends a GET request to the export endpoint, THE Export_Service SHALL return an HTTP 200 response with Content-Type `application/json` containing a JSON Backup_File with all Monitor_Configurations from the monitors table.
2. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all DB_Monitor_Configurations from the db_monitors table in the Backup_File.
3. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all Status_Page_Configurations with their monitor assignments and sort order in the Backup_File.
4. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all key-value pairs from the settings table in the Backup_File.
5. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all maintenance windows in the Backup_File.
6. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all server inventory records in the Backup_File.
7. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all software inventory records in the Backup_File.
8. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all software catalogue entries in the Backup_File.
9. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all service dependencies and topology layout positions in the Backup_File.
10. WHEN an Admin_User triggers an export, THE Export_Service SHALL include all software version tracker definitions in the Backup_File.
11. WHEN an Admin_User triggers an export, THE Export_Service SHALL include a metadata section containing the export timestamp in ISO 8601 UTC format, application version, and export format version in the Backup_File.
12. WHEN an Admin_User triggers an export, THE Export_Service SHALL set the HTTP response Content-Disposition header to trigger a file download with the filename pattern `croit-monitor-backup-YYYY-MM-DD.json` where YYYY-MM-DD is the current UTC date.
13. IF a database read error occurs during export, THEN THE Export_Service SHALL return an HTTP 500 status with an error message indicating the export failed due to a database read error.
14. WHEN an Admin_User triggers an export and a data category contains no records, THE Export_Service SHALL represent that category as an empty array in the Backup_File.
15. WHEN an Admin_User triggers an export, THE Export_Service SHALL complete the response within 30 seconds.

### Requirement 2: Import Configuration From Backup File

**User Story:** As an admin, I want to import a previously exported JSON backup file, so that I can restore my monitor configurations after a database loss.

#### Acceptance Criteria

1. WHEN an Admin_User uploads a valid Backup_File to the import endpoint, THE Import_Service SHALL insert all Monitor_Configurations from the file into the monitors table.
2. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL insert all DB_Monitor_Configurations from the file into the db_monitors table.
3. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL recreate all Status_Page_Configurations with their monitor assignments and sort order.
4. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL restore all settings key-value pairs from the file.
5. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL restore all maintenance windows from the file.
6. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL restore all server inventory records from the file.
7. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL restore all software inventory records from the file.
8. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL restore all software catalogue entries from the file.
9. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL restore all service dependencies and topology layout positions from the file.
10. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL restore all software version tracker definitions from the file.
11. WHEN an Admin_User uploads a valid Backup_File, THE Import_Service SHALL execute all inserts within a single database transaction so that a failure at any point rolls back all changes, leaving the database in its pre-import state.
12. WHEN the import completes successfully, THE Import_Service SHALL return a summary indicating the count of records imported for each category: monitors, db_monitors, status_pages, settings, maintenance_windows, servers, software_inventory, software_catalogue, service_dependencies, and version_trackers.
13. IF the database transaction fails during import, THEN THE Import_Service SHALL roll back all changes and return an error response indicating the failure reason and confirming that no data was modified.
14. IF the uploaded Backup_File exceeds 50 MB in size, THEN THE Import_Service SHALL reject the request with an error message indicating the maximum allowed file size.

### Requirement 3: Validate Backup File Before Import

**User Story:** As an admin, I want the system to validate the backup file before importing, so that I do not accidentally corrupt my database with malformed data.

#### Acceptance Criteria

1. WHEN an Admin_User uploads a file to the import endpoint, THE Import_Service SHALL verify that the file contains valid JSON and that the file size does not exceed 50 MB.
2. IF the uploaded file is missing the required metadata section or the metadata section does not contain a format_version field, THEN THE Import_Service SHALL reject the file with a 400 HTTP status and an error message indicating which element is missing (metadata section or format_version field).
3. WHEN the Backup_File contains a format_version that the Import_Service does not support, THE Import_Service SHALL reject the file with a 400 HTTP status and an error message indicating the unsupported version value and the list of supported versions.
4. WHEN the Backup_File is missing required top-level sections (monitors, db_monitors, settings, status_pages, maintenance_windows, servers, software, software_catalogue, service_dependencies, version_trackers), THE Import_Service SHALL reject the file with a 400 HTTP status and an error message listing all missing section names.
5. WHEN any monitor entry in the Backup_File is missing required fields (name, url, type), THE Import_Service SHALL reject the file with a 400 HTTP status and an error message identifying the invalid entry by its array index position.
6. WHEN any db_monitor entry in the Backup_File is missing required fields (name, db_type, host), THE Import_Service SHALL reject the file with a 400 HTTP status and an error message identifying the invalid entry by its array index position.
7. IF a JSON parsing error occurs during import, THEN THE Import_Service SHALL return a 400 HTTP status with an error message indicating the parse failure reason.
8. THE Import_Service SHALL complete all validation checks before performing any database write operations.

### Requirement 4: Import Mode Selection

**User Story:** As an admin, I want to choose whether to merge or replace data during import, so that I can either add to existing configuration or do a clean restore.

#### Acceptance Criteria

1. WHEN an Admin_User specifies mode "clean" in the import request, THE Import_Service SHALL delete all existing configuration data (monitors, db_monitors, status_pages, status_page_monitor_assignments, settings, maintenance_windows, servers, software_inventory, software_catalogue, service_dependencies, topology_positions, and version_trackers) from the database before inserting the backup data.
2. WHEN an Admin_User specifies mode "merge" in the import request, THE Import_Service SHALL skip inserting records that would create duplicate entries based on unique identifiers (monitor: name + url, db_monitor: name + host + port + database, status page: slug, server: hostname, software_inventory: server + software_name, software_catalogue: name + vendor, service_dependency: source + target, version_tracker: name + url) and SHALL insert all non-duplicate records from the Backup_File.
3. WHILE the import mode is "clean", THE Import_Service SHALL preserve the existing users table and not delete user accounts.
4. WHEN no import mode is specified in the import request, THE Import_Service SHALL default to "clean" mode.
5. IF an Admin_User specifies a mode value other than "clean" or "merge", THEN THE Import_Service SHALL reject the request with a 400 HTTP status and an error message indicating the valid mode options.
6. WHEN the import completes in "merge" mode, THE Import_Service SHALL include in the response summary the count of records skipped due to duplicates per category alongside the count of records inserted.

### Requirement 5: Access Control for Export and Import

**User Story:** As a system administrator, I want export and import operations restricted to admin users only, so that unauthorized users cannot access sensitive configuration data or overwrite system state.

#### Acceptance Criteria

1. THE Export_Service SHALL require the requesting user to have the admin role.
2. THE Import_Service SHALL require the requesting user to have the admin role.
3. WHEN a non-admin user attempts to access the export endpoint, THE Export_Service SHALL return a 403 HTTP status with an error message indicating insufficient permissions.
4. WHEN a non-admin user attempts to access the import endpoint, THE Import_Service SHALL return a 403 HTTP status with an error message indicating insufficient permissions.
5. IF an unauthenticated request is received at the export or import endpoint, THEN THE system SHALL return a 401 HTTP status before evaluating role-based access.

### Requirement 6: Sensitive Data Handling in Export

**User Story:** As an admin, I want database monitor passwords included in the export so I can do a full restore, but I want to be aware of the security implications.

#### Acceptance Criteria

1. WHEN an Admin_User triggers an export, THE Export_Service SHALL include the password field from each DB_Monitor_Configuration in the Backup_File in the same format as stored in the database, to enable full disaster recovery without manual re-entry.
2. THE Export_Service SHALL include a warning field in the metadata section indicating that the file contains sensitive credentials and should be stored securely.
3. THE Export_Service SHALL exclude user password hashes from the Backup_File, ensuring no user authentication credentials from the users table are present in the exported data.
4. WHEN an Admin_User triggers an export, THE Export_Service SHALL include any credential values stored in the settings table (such as SMTP passwords or API keys) in the Backup_File to enable complete configuration restore.
5. IF the Backup_File contains sensitive credentials, THEN THE Import_Service SHALL restore those credential values to their original database fields without transformation, preserving the ability to use them immediately after import.

### Requirement 7: Frontend Export and Import Interface

**User Story:** As an admin, I want a user interface in the Settings page to trigger export and import operations, so that I do not need to use the API directly.

#### Acceptance Criteria

1. WHILE the current user has the admin role, THE Settings page SHALL display an "Export/Import" section with an Export button and an Import file upload area that accepts only `.json` files.
2. WHEN an Admin_User clicks the Export button, THE frontend SHALL trigger a download of the Backup_File from the export endpoint.
3. WHEN an Admin_User selects a file in the Import upload area, THE frontend SHALL display the filename and provide a mode selector (Clean Restore / Merge) with "Clean Restore" selected by default, and an Import button.
4. WHEN an Admin_User clicks the Import button, THE frontend SHALL upload the selected file to the import endpoint with the chosen mode.
5. WHEN the import completes successfully, THE frontend SHALL display a success notification showing the import summary counts that auto-dismisses after 5 seconds.
6. IF the import fails, THEN THE frontend SHALL display an error notification with the error message from the backend that persists until the user manually dismisses it.
7. WHILE an import operation is in progress, THE frontend SHALL disable the Import button and the Export button and show a loading indicator.
8. IF the export request fails, THEN THE frontend SHALL display an error notification indicating the export could not be completed that persists until the user manually dismisses it.
