# CROIT Monitor APP — Project Knowledge Base

## Project Overview

CRO IT custom uptime and database monitoring dashboard. Provides HTTP/HTTPS/TCP monitoring, MSSQL database monitoring with extended metrics (active requests, running queries, blocking queries, long-running queries, database inventory), server inventory, software inventory, service topology, and role-based access control.

## Architecture

### Stack
- **Backend**: Python 3, Flask 3.0.3, SQLite (single file `uptime.db`), flask-login (session auth)
- **Frontend**: Vanilla JavaScript (no framework), served as static files from `frontend/dist/`
- **Auth**: flask-login with session cookies, bcrypt password hashing (`hashlib` SHA256 currently), RBAC via `@role_required` decorator
- **Deployment**: Standalone Python app (`python app.py` or `start.bat`), no container

### Key Files
| File | Purpose |
|------|---------|
| `app.py` | Entire Flask backend — routes, monitoring loops, DB schema, decorators |
| `frontend/dist/app.js` | Main frontend — navigation, dashboard, monitors, settings, topology |
| `frontend/dist/db.js` | Database monitoring frontend — detail view, extended metrics, charts |
| `frontend/dist/servers.js` | Server inventory frontend |
| `frontend/dist/software.js` | Software inventory frontend |
| `frontend/dist/index.html` | Main SPA shell (sidebar, modals, pages) |
| `frontend/dist/login.html` | Login page |
| `uptime.db` | SQLite database (auto-created on first run) |
| `requirements.txt` | Python dependencies |
| `start.bat` | Windows launcher script |

### Backend Architecture (Single File)
Everything lives in `app.py`:
- **Imports & constants** (lines 1-50)
- **Flask app setup** (lines 33-55)
- **Database functions** (`get_db()`, `init_db()`, `DB_LOCK`) (lines 55-650)
- **User model** (`class User(UserMixin)`) 
- **Auth decorators** (`auth_required`, `admin_required`, `role_required`)
- **Monitoring loops** (`monitor_loop`, `db_monitor_loop`, background threads)
- **Extended metrics collection** (`collect_extended_metrics`) — MSSQL DMV queries
- **API routes** — grouped by resource (`/api/monitors/*`, `/api/db-monitors/*`, `/api/servers/*`, etc.)
- **Static file serving** (catch-all route for SPA)

### Frontend Architecture
- **State**: Global variables (`currentUserInfo`, `monitors`, etc.)
- **Navigation**: Hash-less SPA — `navigate(page)` shows/hides `.page` divs
- **API client**: `fetch()` with `credentials:'include'` for session cookies
- **Auto-refresh**: `setInterval` every 30s for dashboard data
- **Extended metrics refresh**: `setInterval` every 30s when detail panel is open

## Role-Based Access Control

### Roles
| Role | Access |
|------|--------|
| `admin` | Full access — all sections, user management, settings |
| `viewer` | Read-only access to all monitoring sections (no settings/user management) |
| `dba` | Database tab only — full CRUD on `/api/db-monitors/*`, blocked from everything else |

### How It Works
- **Backend**: `@role_required(['admin', 'dba'])` decorator on each route (replaces old `@auth_required`)
- **Frontend**: `applyRoleRestrictions(role)` removes sidebar items from DOM; `navigate()` guard redirects DBA to databases
- **Session**: `currentUserInfo.role` stored after `checkAuth()` call to `/api/auth/me`

### Route Protection Matrix
| Route Group | Allowed Roles |
|-------------|---------------|
| `/api/auth/*` | All (no decorator) |
| `/api/db-monitors/*` | admin, dba |
| `/api/monitors/*` | admin, viewer |
| `/api/servers/*` | admin, viewer |
| `/api/software/*` | admin, viewer |
| `/api/settings/*` | admin only |
| `/api/users/*` | admin only |

## Database Monitoring — Extended Metrics

### What It Collects (from MSSQL DMVs)
1. **Active request count** — `sys.dm_exec_requests` (session_id > 50, excluding own session)
2. **Running queries** (top 50 by elapsed time) — `sys.dm_exec_requests` + `sys.dm_exec_sql_text`
3. **Database list** — `sys.databases`
4. **Blocking queries** — head blocker detection via blocking_session_id, chain traversal (max depth 10)
5. **Long-running queries** — client-side filter of running_queries using configurable threshold

### Storage
- Table: `db_extended_metrics` (columns: id, db_id, active_requests, running_queries, databases_list, blocking_queries, collected_at)
- Retention: 100 records per db_id
- JSON storage: running_queries and blocking_queries as TEXT columns with JSON arrays
- Long-running threshold: `long_running_threshold` INTEGER column on `db_monitors` table + global setting in `settings` table

### API Endpoint
`GET /api/db-monitors/<id>/extended-metrics` returns:
```json
{
  "active_requests": 12,
  "running_queries": [...],
  "databases_list": [...],
  "blocking_queries": [...],
  "long_running_threshold_seconds": 5,
  "collected_at": "2026-06-09 14:30:00"
}
```

### Key Implementation Details
- `collect_extended_metrics(conn, db_id)` is called inside `check_db_query` while the pyodbc connection is open
- Each DMV query is wrapped in independent try/except — failure stores NULL, doesn't break the heartbeat
- Blocking query detection: find sessions with `blocking_session_id > 0`, identify head blockers (not themselves blocked), traverse chain with BFS
- SQL text truncated to 500 chars in SQL (`LEFT(..., 500)`), displayed at 200 chars with expand/collapse

## Common Development Patterns

### Adding a New API Endpoint
1. Add the route in `app.py` with `@role_required(['admin', 'viewer'])` (or appropriate roles)
2. Use `with DB_LOCK, get_db() as conn:` for all database access
3. Return `jsonify(...)` with appropriate HTTP status codes

### Adding a New Frontend Section
1. Add a `.page` div in `index.html`
2. Add a `.sidebar-item` with `id="nav-<page>"` in the sidebar
3. Add `if (page === '<page>') load<Page>();` in the `navigate()` function in `app.js`
4. Add the page to `ROLE_ALLOWED_PAGES` if needed

### Database Migrations
- Use `ALTER TABLE ... ADD COLUMN` wrapped in try/except at the end of `init_db()`
- Pattern: `try: conn.execute("ALTER TABLE x ADD COLUMN y TYPE"); except: pass`
- No external migration tool — all handled in `init_db()` on app startup

### Session/Auth Pattern
```python
@app.route("/api/something", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_something():
    # current_user is available from flask-login
    ...
```

## Known Issues & Fixes

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| `VALID_ROLES` must include `dba` | New role added June 2026 | Already in code as `frozenset({'admin', 'viewer', 'dba'})` |
| Old `@auth_required` still defined | Was replaced by `@role_required` | Unused but harmless — left in for backward compat |
| DBA user sees flash of all nav items | `applyRoleRestrictions()` runs after DOM paint | Called inside `checkAuth()` before page content loads — mitigated |
| Extended metrics NULL on first heartbeat | No data collected yet | API returns message "No extended metrics data available yet" |
| Blocking queries NULL after upgrade | `blocking_queries` column didn't exist | Migration in `init_db()` adds it on restart |
| pyodbc not in requirements.txt | Installed separately on machines with MSSQL | Only needed when monitoring MSSQL databases |

## Testing

```bash
# Syntax check backend
python -c "import ast; ast.parse(open('app.py', encoding='utf-8').read()); print('OK')"

# Syntax check frontend
node --check frontend/dist/app.js
node --check frontend/dist/db.js
```

No automated test suite currently. Property tests defined in specs but marked optional.

## Deployment

### Local Development (Windows)
```bash
# Start directly
python app.py
# Or use the batch file
start.bat
```
App runs on `http://localhost:5000` by default.

### Files to Deploy for Updates
When copying changes to production/other machines:
- `app.py` — if backend changes were made
- `frontend/dist/app.js` — if navigation/dashboard/settings changed
- `frontend/dist/db.js` — if database monitoring UI changed
- `frontend/dist/index.html` — if modals/layout changed
- `frontend/dist/login.html` — if login page changed

Always restart the app after deploying `app.py` changes (schema migrations run on startup).

## Feature Specs

Active specs in `.kiro/specs/`:
- `db-extended-metrics` — Active requests, running queries, blocking queries, long-running queries, database list
- `dba-role-access-control` — DBA role with restricted access to databases only
- `monitor-audit-report` — Audit reporting
- `patch-security-depth` — Security patching depth
- `software-inventory-csv-export` — CSV export for software inventory
