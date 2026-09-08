# Implementation Plan: DBA Role Access Control

## Overview

Implement a `dba` role in the CROIT Monitor APP that restricts users to only the Databases section. The implementation follows a backend-first approach: a reusable `@role_required` decorator enforces API-level access control, routes are decorated per the protection matrix, and the frontend filters navigation and guards page transitions for DBA users.

## Tasks

- [x] 1. Implement the `role_required` decorator and role validation constants
  - [x] 1.1 Create the `role_required` decorator factory in `app.py`
    - Add `VALID_ROLES = frozenset({'admin', 'viewer', 'dba'})` constant near the top of `app.py`
    - Implement `role_required(allowed_roles)` decorator factory that:
      - Returns 401 `{"error": "Not authenticated"}` if user is not authenticated
      - Returns 403 `{"error": "Access denied"}` if user's role is not in `allowed_roles`
      - Proceeds to the route handler if role is allowed
    - Ensure it works standalone (includes its own auth check) and is stackable with `@auth_required`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 1.2 Add role validation to user create/update endpoints
    - In the user creation endpoint (`POST /api/users`), validate that the `role` field is in `VALID_ROLES`
    - In the user update endpoint (`PUT /api/users/<id>`), validate that the `role` field is in `VALID_ROLES`
    - Return 400 with `{"error": "Invalid role: <value>. Must be one of: admin, viewer, dba"}` for invalid values
    - Ensure LDAP auto-provisioned users default to `viewer` role
    - _Requirements: 1.1, 1.4, 1.5_

  - [ ]* 1.3 Write property test for role validation (Property 1)
    - **Property 1: Role Validation Rejects Invalid Values**
    - Use Hypothesis to generate arbitrary strings; verify that only `admin`, `viewer`, `dba` are accepted and all others are rejected with an error response
    - **Validates: Requirements 1.1, 1.4**

  - [ ]* 1.4 Write property test for role guard access decision (Property 5)
    - **Property 5: Role Guard Access Decision**
    - Use Hypothesis to generate (user_role, allowed_roles_list) pairs; verify the decorator allows access iff `user_role` is in `allowed_roles_list`, otherwise returns 403
    - **Validates: Requirements 6.2, 6.3**

- [x] 2. Apply route protection matrix to all backend API endpoints
  - [x] 2.1 Decorate `/api/db-monitors/*` routes with `@role_required(['admin', 'dba'])`
    - Apply the decorator to all db-monitor endpoints (GET list, GET single, POST create, PUT update, DELETE remove, GET metrics)
    - Verify DBA users get full CRUD access to database monitors
    - _Requirements: 2.1, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 2.2 Decorate remaining API routes per the protection matrix
    - `/api/monitors/*` → `@role_required(['admin', 'viewer'])`
    - `/api/servers/*` → `@role_required(['admin', 'viewer'])`
    - `/api/software/*` → `@role_required(['admin', 'viewer'])`
    - `/api/software-catalogue/*` → `@role_required(['admin', 'viewer'])`
    - `/api/topology/*` → `@role_required(['admin', 'viewer'])`
    - `/api/status/*` → `@role_required(['admin', 'viewer'])`
    - `/api/ssl/*` → `@role_required(['admin', 'viewer'])`
    - `/api/maintenance/*` → `@role_required(['admin', 'viewer'])`
    - `/api/settings/*` → `@role_required(['admin'])`
    - `/api/users/*` → `@role_required(['admin'])` (replaces `@admin_required`)
    - `/api/version-tracker/*` → `@role_required(['admin', 'viewer'])`
    - `/api/version-findings/*` → `@role_required(['admin', 'viewer'])`
    - `/api/agent/*` → `@role_required(['admin', 'viewer'])`
    - `/api/reports/*` → `@role_required(['admin'])`
    - Leave `/api/auth/*` undecorated (public/session endpoints)
    - _Requirements: 2.2, 2.4_

  - [ ]* 2.3 Write property test for DBA db-monitor access (Property 2)
    - **Property 2: DBA Users Can Access All DB-Monitor Endpoints**
    - Use Hypothesis to generate db-monitor paths × HTTP methods; verify DBA user gets access (not 403)
    - **Validates: Requirements 2.1**

  - [ ]* 2.4 Write property test for DBA restricted route denial (Property 3)
    - **Property 3: DBA Users Are Denied Access to Non-Allowed Endpoints**
    - Use Hypothesis to generate non-db-monitor, non-auth API paths; verify DBA user gets 403
    - **Validates: Requirements 2.2, 2.4**

- [x] 3. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Update login response and `/api/auth/me` to include role
  - [x] 4.1 Ensure login and auth/me endpoints return the `role` field
    - Verify `POST /api/auth/login` response includes `"role": "dba"` for DBA users
    - Verify `GET /api/auth/me` response includes `"role": "dba"` along with username and authenticated status
    - Add `role` to the response payload if not already present
    - _Requirements: 1.2, 2.3_

  - [ ]* 4.2 Write unit tests for DBA login and auth/me responses
    - Test that login as DBA returns `role: "dba"` in JSON response
    - Test that `/api/auth/me` as DBA returns `role: "dba"`, username, and authenticated=true
    - _Requirements: 1.2, 2.3_

- [ ] 5. Implement frontend navigation restrictions and role-based filtering
  - [x] 5.1 Add role-based navigation filtering in `frontend/dist/app.js`
    - Define `ROLE_ALLOWED_PAGES` map: `dba: ['databases']`, `viewer: [all non-admin pages]`, `admin: null`
    - Implement `applyRoleRestrictions(role)` function that removes disallowed sidebar items from the DOM entirely (not CSS hide)
    - Call `applyRoleRestrictions()` in `checkAuth()` after fetching `/api/auth/me` and storing `currentUserInfo`
    - Ensure restrictions are applied before sidebar is visible (no momentary flash of restricted items)
    - _Requirements: 4.1, 4.2, 4.4_

  - [x] 5.2 Implement the navigate guard in `frontend/dist/app.js`
    - Wrap the existing `navigate()` function to check `currentUserInfo.role`
    - If role is `dba` and page is not `databases`, redirect to `databases` page
    - Handle edge case: if `currentUserInfo` is null or role is missing, treat as unauthenticated and redirect to login
    - _Requirements: 4.3, 4.5_

  - [ ]* 5.3 Write property test for navigate guard (Property 4)
    - **Property 4: Navigate Guard Redirects DBA to Databases**
    - Use Hypothesis to generate arbitrary page name strings ≠ "databases"; verify the DBA user is always redirected to the databases page
    - **Validates: Requirements 4.3**

- [x] 6. Implement DBA login redirect and init page selection
  - [x] 6.1 Update login handler to redirect DBA users to databases page
    - In `frontend/dist/login.html` (or login JS), after successful login response:
      - If `data.role === 'dba'`, redirect to `/#databases`
      - Otherwise, redirect to `/` (default dashboard)
    - _Requirements: 5.1_

  - [x] 6.2 Update `init()` function in `frontend/dist/app.js` for DBA default page
    - After `checkAuth()` succeeds, check `currentUserInfo.role`
    - If role is `dba`, call `navigate('databases')` instead of loading the dashboard
    - On page refresh, DBA users should always land on the databases page
    - _Requirements: 5.2_

- [x] 7. Update the user management UI role dropdown
  - [x] 7.1 Add `dba` option to the role select dropdown in user management
    - Update the role `<select>` element to include `<option value="dba">dba</option>`
    - Ensure admin users see all three options: `viewer`, `admin`, `dba` when creating or editing users
    - _Requirements: 1.3_

- [x] 8. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties using Hypothesis
- The `role` column already exists in the `users` table — no database migration needed
- The `@role_required` decorator replaces `@admin_required` on user management routes
- Frontend restriction is UX convenience — backend enforcement is the security boundary

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "4.1"] },
    { "id": 2, "tasks": ["1.3", "1.4", "2.1", "2.2"] },
    { "id": 3, "tasks": ["2.3", "2.4", "4.2"] },
    { "id": 4, "tasks": ["5.1", "6.1", "7.1"] },
    { "id": 5, "tasks": ["5.2", "6.2"] },
    { "id": 6, "tasks": ["5.3"] }
  ]
}
```
