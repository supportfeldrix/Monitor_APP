# Requirements Document

## Introduction

This feature introduces a new `dba` (Database Administrator) role to the CROIT Monitor APP's role-based access control system. Currently the app supports `admin` (full access) and `viewer` (read-only access to all sections). The `dba` role restricts a user's access to ONLY the Databases tab and its associated API endpoints (`/api/db-monitors/*`), while granting full CRUD permissions within that scope. All other sections (Monitors, Servers, Software, Settings, User Management) are inaccessible to DBA users.

## Glossary

- **CROIT_Monitor_APP**: The Flask-based uptime and database monitoring application serving a vanilla JS frontend
- **Auth_System**: The authentication and authorization layer using flask_login with session-based auth, `auth_required` and `admin_required` decorators
- **DBA_User**: A user with the `dba` role value in the `users` table, restricted to database monitoring functionality
- **Admin_User**: A user with the `admin` role, having full unrestricted access to all features
- **Viewer_User**: A user with the `viewer` role, having read-only access to all sections
- **Database_Tab**: The frontend page displaying database monitors, accessible via the sidebar navigation item "Databases"
- **Restricted_Sections**: Monitors, Servers, Software, Settings, and User Management — sections that DBA users cannot access
- **DB_Monitor_API**: The set of backend endpoints under `/api/db-monitors/*` that handle database monitor CRUD operations
- **Navigation_Sidebar**: The left-hand sidebar containing navigation items for all application tabs/pages
- **Role_Guard**: A backend decorator or middleware that checks a user's role before allowing access to a route

## Requirements

### Requirement 1: DBA Role Definition

**User Story:** As an administrator, I want to assign a `dba` role to users, so that I can grant database-only access without exposing other system sections.

#### Acceptance Criteria

1. THE Auth_System SHALL accept only `admin`, `viewer`, and `dba` as valid values for the `role` column in the `users` table, rejecting any other value with a validation error
2. WHEN a DBA_User authenticates successfully, THE Auth_System SHALL return the role value `dba` in the `role` field of the JSON login response payload
3. WHEN an Admin_User creates or edits a user, THE CROIT_Monitor_APP SHALL present `admin`, `viewer`, and `dba` as the complete set of selectable role options in the role dropdown
4. IF a request to create or update a user specifies a role value other than `admin`, `viewer`, or `dba`, THEN THE Auth_System SHALL reject the request and return an error message indicating an invalid role value
5. WHEN a new user is auto-provisioned via LDAP authentication, THE Auth_System SHALL assign the `viewer` role by default until an Admin_User explicitly changes it

### Requirement 2: Backend Route Restriction for DBA Users

**User Story:** As a system owner, I want DBA users to be blocked from accessing non-database API endpoints, so that the principle of least privilege is enforced at the API layer.

#### Acceptance Criteria

1. WHEN a DBA_User sends a request using any HTTP method to any `/api/db-monitors/*` endpoint, THE Auth_System SHALL allow the request to proceed to the route handler
2. WHEN a DBA_User sends a request using any HTTP method to any endpoint NOT matching `/api/db-monitors/*` or `/api/auth/me`, THE Auth_System SHALL return HTTP 403 with a JSON response body containing an "error" key and a message indicating access is denied
3. WHEN a DBA_User sends a GET request to `/api/auth/me`, THE Auth_System SHALL allow the request and return a JSON response containing `"role": "dba"` along with the username and authentication status
4. IF a new API route is added to the CROIT_Monitor_APP without explicitly granting DBA_User access, THEN THE Auth_System SHALL deny DBA_User access to that route by default with HTTP 403

### Requirement 3: DBA Full CRUD Access to Database Monitors

**User Story:** As a DBA user, I want full create, read, update, and delete access to database monitors, so that I can manage database monitoring independently.

#### Acceptance Criteria

1. WHEN a DBA_User sends a POST request to create a database monitor, THE DB_Monitor_API SHALL create the monitor and return a success response
2. WHEN a DBA_User sends a GET request to list or view database monitors, THE DB_Monitor_API SHALL return the requested data
3. WHEN a DBA_User sends a PUT request to update an existing database monitor, THE DB_Monitor_API SHALL update the monitor and return a success response
4. WHEN a DBA_User sends a DELETE request to remove a database monitor, THE DB_Monitor_API SHALL delete the monitor and return a success response
5. WHEN a DBA_User requests extended metrics for a database monitor, THE DB_Monitor_API SHALL return the metrics data

### Requirement 4: Frontend Navigation Restriction for DBA Users

**User Story:** As a system owner, I want the frontend to hide non-database navigation items for DBA users, so that the restricted access is reflected in the user interface.

#### Acceptance Criteria

1. WHILE a DBA_User is logged in, THE Navigation_Sidebar SHALL display only the "Databases" navigation item and hide all other navigation items including Dashboard, Status Pages, Settings, SSL Certificates, Service Topology, Server Inventory, Software Inventory, and the Monitors section
2. WHILE a DBA_User is logged in, THE Navigation_Sidebar SHALL not render clickable links or interactive elements for any hidden navigation items in the DOM
3. IF a DBA_User invokes the navigate function with a page value other than "databases" (via browser console or programmatic call), THEN THE CROIT_Monitor_APP SHALL prevent the page from displaying and redirect the user to the Database_Tab within 1 second
4. WHEN a DBA_User session is established after login, THE CROIT_Monitor_APP SHALL apply the navigation restrictions before rendering the Navigation_Sidebar, so that restricted items are never visible even momentarily
5. IF the role value in the stored session becomes unavailable or cannot be read, THEN THE CROIT_Monitor_APP SHALL treat the user as unauthenticated and redirect to the login page

### Requirement 5: DBA Login Redirect

**User Story:** As a DBA user, I want to be automatically directed to the Databases page after login, so that I land on the only section I have access to.

#### Acceptance Criteria

1. WHEN a DBA_User successfully authenticates, THE CROIT_Monitor_APP SHALL navigate the user to the Database_Tab
2. WHEN a DBA_User refreshes the application or opens a new session, THE CROIT_Monitor_APP SHALL load the Database_Tab as the default landing page

### Requirement 6: Role Guard Decorator

**User Story:** As a developer, I want a reusable role-based access control decorator, so that route restrictions can be enforced consistently across the backend.

#### Acceptance Criteria

1. THE Role_Guard SHALL accept a list of 1 to 10 allowed role strings as a parameter
2. WHEN a user with a role not in the allowed list accesses a guarded route, THE Role_Guard SHALL return HTTP 403 with a JSON response body `{"error": "Access denied"}`
3. WHEN a user with a role in the allowed list accesses a guarded route, THE Role_Guard SHALL allow the request to proceed to the route handler without modifying the request
4. IF an unauthenticated user accesses a guarded route, THEN THE Role_Guard SHALL return HTTP 401 with a JSON response body `{"error": "Not authenticated"}` before evaluating role authorization
5. IF the allowed roles list provided to the decorator is empty, THEN THE Role_Guard SHALL deny all requests with HTTP 403 and a JSON response body `{"error": "Access denied"}`
6. THE Role_Guard SHALL be usable as a standalone decorator that includes its own authentication check, and SHALL be stackable with the existing `@auth_required` decorator without conflicting behavior
