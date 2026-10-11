"""
Uptime Monitor - Flask Backend (KUMA-compatible feature set)
- HTTP/HTTPS, TCP port, keyword monitoring
- Multiple named status pages with custom slugs
- Heartbeat history with timeframe filtering
- Notification config (SMTP)
- SQLite storage
"""

import sqlite3
import threading
import time
import socket
import smtplib
import requests
import json
import re
import hashlib
import secrets
from functools import wraps
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from flask import Flask, jsonify, request, send_from_directory, session, redirect
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os

# ─────────────────────────────────────────────
# Valid roles
# ─────────────────────────────────────────────
VALID_ROLES = frozenset({'admin', 'viewer', 'dba'})

app = Flask(__name__, static_folder="frontend/dist", static_url_path="")
app.url_map.strict_slashes = False

# Load secret key from file (production) or generate one (development)
_secret_key_file = os.path.join(os.path.dirname(__file__), "secret.key")
if os.path.exists(_secret_key_file):
    with open(_secret_key_file) as _f:
        app.secret_key = _f.read().strip()
else:
    app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

CORS(app, supports_credentials=True)

# Session cookie config — ensures Chrome accepts the cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
app.config["REMEMBER_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_HTTPONLY"] = True

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = None  # We handle redirects manually

DB_PATH       = "uptime.db"
MONITORS_FILE = "monitors.json"

# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

DB_LOCK = threading.Lock()

# ─────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id       = str(id)
        self.username = username
        self.role     = role  # 'admin' or 'viewer'

@login_manager.user_loader
def load_user(user_id):
    with DB_LOCK, get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row:
        return User(row["id"], row["username"], row["role"])
    return None

def init_db():
    with DB_LOCK, get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS monitors (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL,
                url             TEXT    NOT NULL,
                type            TEXT    NOT NULL DEFAULT 'http',
                interval        INTEGER NOT NULL DEFAULT 60,
                retries         INTEGER NOT NULL DEFAULT 3,
                timeout         INTEGER NOT NULL DEFAULT 10,
                keyword         TEXT,
                accepted_codes  TEXT    NOT NULL DEFAULT '200-299',
                enabled         INTEGER NOT NULL DEFAULT 1,
                notify_email    INTEGER NOT NULL DEFAULT 0,
                description     TEXT,
                tags            TEXT,
                group_name      TEXT    NOT NULL DEFAULT '',
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS heartbeats (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id  INTEGER NOT NULL,
                status      INTEGER NOT NULL,
                latency_ms  INTEGER,
                msg         TEXT,
                checked_at  TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (monitor_id) REFERENCES monitors(id)
            );

            CREATE INDEX IF NOT EXISTS idx_hb_mid_time
                ON heartbeats (monitor_id, checked_at);

            CREATE TABLE IF NOT EXISTS status_pages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                slug        TEXT NOT NULL UNIQUE,
                title       TEXT NOT NULL,
                description TEXT,
                theme       TEXT NOT NULL DEFAULT 'dark',
                show_tags   INTEGER NOT NULL DEFAULT 0,
                custom_css  TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS status_page_monitors (
                page_id     INTEGER NOT NULL,
                monitor_id  INTEGER NOT NULL,
                sort_order  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (page_id, monitor_id),
                FOREIGN KEY (page_id)    REFERENCES status_pages(id),
                FOREIGN KEY (monitor_id) REFERENCES monitors(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS maintenance_windows (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id  INTEGER,
                title       TEXT NOT NULL,
                start_dt    TEXT NOT NULL,
                end_dt      TEXT NOT NULL,
                repeat_weekly INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (monitor_id) REFERENCES monitors(id)
            );

            CREATE TABLE IF NOT EXISTS ssl_checks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id  INTEGER NOT NULL UNIQUE,
                days_left   INTEGER,
                expiry_date TEXT,
                issuer      TEXT,
                last_checked TEXT,
                FOREIGN KEY (monitor_id) REFERENCES monitors(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL UNIQUE,
                password   TEXT NOT NULL,
                role       TEXT NOT NULL DEFAULT 'viewer',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS dependencies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                monitor_id  INTEGER NOT NULL,
                depends_on  INTEGER NOT NULL,
                label       TEXT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (monitor_id, depends_on),
                FOREIGN KEY (monitor_id) REFERENCES monitors(id),
                FOREIGN KEY (depends_on)  REFERENCES monitors(id)
            );

            CREATE TABLE IF NOT EXISTS topology_layout (
                monitor_id  INTEGER PRIMARY KEY,
                pos_x       REAL NOT NULL DEFAULT 0,
                pos_y       REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (monitor_id) REFERENCES monitors(id)
            );

            CREATE TABLE IF NOT EXISTS db_monitors (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT    NOT NULL,
                db_type      TEXT    NOT NULL DEFAULT 'mssql',
                host         TEXT    NOT NULL,
                port         INTEGER NOT NULL DEFAULT 1433,
                database     TEXT,
                username     TEXT,
                password     TEXT,
                interval     INTEGER NOT NULL DEFAULT 60,
                enabled      INTEGER NOT NULL DEFAULT 1,
                notify_email INTEGER NOT NULL DEFAULT 0,
                description  TEXT,
                group_name   TEXT    NOT NULL DEFAULT '',
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS db_heartbeats (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                db_id        INTEGER NOT NULL,
                status       INTEGER NOT NULL,
                latency_ms   INTEGER,
                connections  INTEGER,
                msg          TEXT,
                checked_at   TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (db_id) REFERENCES db_monitors(id)
            );

            CREATE INDEX IF NOT EXISTS idx_dbhb_id_time
                ON db_heartbeats (db_id, checked_at);

            CREATE TABLE IF NOT EXISTS db_extended_metrics (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                db_id           INTEGER NOT NULL,
                active_requests INTEGER,
                running_queries TEXT,
                databases_list  TEXT,
                collected_at    TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (db_id) REFERENCES db_monitors(id)
            );

            CREATE INDEX IF NOT EXISTS idx_dbext_id_time
                ON db_extended_metrics (db_id, collected_at);

            CREATE TABLE IF NOT EXISTS agent_tokens (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id   INTEGER NOT NULL UNIQUE,
                token       TEXT    NOT NULL UNIQUE,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                last_seen   TEXT,
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE TABLE IF NOT EXISTS agent_metrics (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id    INTEGER NOT NULL,
                os_name      TEXT,
                os_version   TEXT,
                kernel       TEXT,
                cpu_pct      REAL,
                cpu_cores    INTEGER,
                cpu_threads  INTEGER,
                ram_total_gb REAL,
                ram_used_gb  REAL,
                ram_pct      REAL,
                disk_total_gb REAL,
                disk_used_gb  REAL,
                disk_pct     REAL,
                disk_mounts  TEXT,
                uptime_sec   INTEGER,
                load_1m      REAL,
                load_5m      REAL,
                load_15m     REAL,
                process_count INTEGER,
                collected_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_agent_metrics_sid_time
                ON agent_metrics (server_id, collected_at);

            CREATE TABLE IF NOT EXISTS servers (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname     TEXT    NOT NULL,
                ip_address   TEXT,
                os           TEXT,
                environment  TEXT    NOT NULL DEFAULT 'PROD',
                role         TEXT,
                cpu_cores    INTEGER,
                ram_gb       INTEGER,
                disk_gb      INTEGER,
                location     TEXT,
                last_patched TEXT,
                notes        TEXT,
                created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS server_monitors (
                server_id   INTEGER NOT NULL,
                monitor_id  INTEGER NOT NULL,
                PRIMARY KEY (server_id, monitor_id),
                FOREIGN KEY (server_id)  REFERENCES servers(id),
                FOREIGN KEY (monitor_id) REFERENCES monitors(id)
            );

            CREATE TABLE IF NOT EXISTS server_db_monitors (
                server_id   INTEGER NOT NULL,
                db_id       INTEGER NOT NULL,
                PRIMARY KEY (server_id, db_id),
                FOREIGN KEY (server_id) REFERENCES servers(id),
                FOREIGN KEY (db_id)     REFERENCES db_monitors(id)
            );

            CREATE TABLE IF NOT EXISTS software_inventory (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id      INTEGER NOT NULL,
                name           TEXT    NOT NULL,
                version        TEXT,
                vendor         TEXT,
                license_type   TEXT,
                support_status TEXT,
                risk_rating    TEXT,
                install_path   TEXT,
                discovered_by  TEXT    NOT NULL DEFAULT 'manual',
                created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_sw_server_id
                ON software_inventory (server_id);

            CREATE TABLE IF NOT EXISTS software_catalogue (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name_pattern   TEXT    NOT NULL,
                vendor         TEXT,
                license_type   TEXT,
                support_status TEXT    NOT NULL DEFAULT 'Supported',
                risk_rating    TEXT    NOT NULL DEFAULT 'Low',
                notes          TEXT,
                created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_sw_cat_pattern
                ON software_catalogue (name_pattern);

            -- ── Software Version Tracker ──────────────────────────────────
            -- Defines how to fetch the latest version for a known software product.
            -- check_type: 'github_release' | 'jenkins_update_center' | 'url_regex'
            CREATE TABLE IF NOT EXISTS software_version_tracker (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name_match      TEXT    NOT NULL,
                display_name    TEXT    NOT NULL,
                check_type      TEXT    NOT NULL,
                check_source    TEXT    NOT NULL,
                regex_pattern   TEXT,
                latest_version  TEXT,
                last_checked    TEXT,
                enabled         INTEGER NOT NULL DEFAULT 1,
                notes           TEXT,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS software_version_findings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id       INTEGER NOT NULL,
                tracker_id      INTEGER NOT NULL,
                sw_name         TEXT    NOT NULL,
                installed_ver   TEXT,
                latest_ver      TEXT,
                status          TEXT    NOT NULL DEFAULT 'outdated',
                alerted         INTEGER NOT NULL DEFAULT 0,
                last_seen       TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id)  REFERENCES servers(id),
                FOREIGN KEY (tracker_id) REFERENCES software_version_tracker(id)
            );

            CREATE INDEX IF NOT EXISTS idx_svf_server
                ON software_version_findings (server_id);

            -- ── Discovered Services ───────────────────────────────────────
            CREATE TABLE IF NOT EXISTS server_services (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id   INTEGER NOT NULL,
                category    TEXT    NOT NULL,
                name        TEXT    NOT NULL,
                port        INTEGER,
                protocol    TEXT,
                address     TEXT,
                pid         INTEGER,
                process     TEXT,
                status      TEXT,
                description TEXT,
                image       TEXT,
                ports_info  TEXT,
                container_id TEXT,
                service_type TEXT,
                last_seen   TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );

            CREATE INDEX IF NOT EXISTS idx_svc_server_id
                ON server_services (server_id);
        """)
    # Migration: add msg column if upgrading from old schema
    try:
        conn.execute("ALTER TABLE heartbeats ADD COLUMN msg TEXT")
        print("[DB] Migrated: added msg column to heartbeats.")
    except Exception:
        pass  # column already exists
    # Migration: add group_name column if upgrading from old schema
    try:
        conn.execute("ALTER TABLE monitors ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")
        print("[DB] Migrated: added group_name column to monitors.")
    except Exception:
        pass  # column already exists
    # Migration: add last_patched column to servers
    try:
        conn.execute("ALTER TABLE servers ADD COLUMN last_patched TEXT")
        print("[DB] Migrated: added last_patched column to servers.")
    except Exception:
        pass  # column already exists
    # Migration: add cpu_cores/threads and disk_mounts to agent_metrics
    for col, defn in [
        ("cpu_cores",   "INTEGER"),
        ("cpu_threads", "INTEGER"),
        ("disk_mounts", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE agent_metrics ADD COLUMN {col} {defn}")
            print(f"[DB] Migrated: added {col} to agent_metrics.")
        except Exception:
            pass
    # Migration: add patch metric columns to agent_metrics
    for col, defn in [
        ("pending_updates", "INTEGER"),
        ("reboot_required", "INTEGER"),
        ("patch_status",    "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE agent_metrics ADD COLUMN {col} {defn}")
            print(f"[DB] Migrated: added {col} to agent_metrics.")
        except Exception:
            pass
    # Migration: add request_body and request_headers columns to monitors (for http-post type)
    for col, defn in [
        ("request_body",    "TEXT"),
        ("request_headers", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE monitors ADD COLUMN {col} {defn}")
            print(f"[DB] Migrated: added {col} to monitors.")
        except Exception:
            pass
    # Migration: create software_inventory table if upgrading from old schema
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS software_inventory (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id      INTEGER NOT NULL,
                name           TEXT    NOT NULL,
                version        TEXT,
                vendor         TEXT,
                license_type   TEXT,
                support_status TEXT,
                risk_rating    TEXT,
                install_path   TEXT,
                discovered_by  TEXT    NOT NULL DEFAULT 'manual',
                created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id) REFERENCES servers(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sw_server_id ON software_inventory (server_id)")
        print("[DB] Migrated: software_inventory table ensured.")
    except Exception:
        pass
    # Migration: create software_catalogue table
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS software_catalogue (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                name_pattern   TEXT    NOT NULL,
                vendor         TEXT,
                license_type   TEXT,
                support_status TEXT    NOT NULL DEFAULT 'Supported',
                risk_rating    TEXT    NOT NULL DEFAULT 'Low',
                notes          TEXT,
                created_at     TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sw_cat_pattern ON software_catalogue (name_pattern)")
        print("[DB] Migrated: software_catalogue table ensured.")
    except Exception:
        pass
    # Seed default catalogue entries if empty
    cat_count = conn.execute("SELECT COUNT(*) FROM software_catalogue").fetchone()[0]
    if cat_count == 0:
        default_catalogue = [
            # WSO2
            ("wso2%",           "WSO2",              "Commercial",   "Supported",       "High",     "WSO2 middleware platform"),
            # Java / JDK / JRE
            ("java%",           "Oracle / OpenJDK",  "Commercial",   "Supported",       "Medium",   "Java runtime"),
            ("jdk%",            "Oracle",             "Commercial",   "Supported",       "Medium",   "Java Development Kit"),
            ("jre%",            "Oracle",             "Commercial",   "Supported",       "Medium",   "Java Runtime Environment"),
            ("openjdk%",        "Red Hat / OpenJDK",  "Open Source",  "Supported",       "Low",      "OpenJDK runtime"),
            # PostgreSQL
            ("postgresql%",     "PostgreSQL Global",  "Open Source",  "Supported",       "Low",      "PostgreSQL database"),
            ("postgres%",       "PostgreSQL Global",  "Open Source",  "Supported",       "Low",      "PostgreSQL database"),
            # Microsoft SQL Server
            ("mssql%",          "Microsoft",          "Commercial",   "Supported",       "High",     "Microsoft SQL Server"),
            # Red Hat / RHEL packages
            ("rhel%",           "Red Hat",            "Commercial",   "Supported",       "Low",      "Red Hat Enterprise Linux"),
            ("redhat%",         "Red Hat",            "Commercial",   "Supported",       "Low",      "Red Hat package"),
            # Veritas
            ("vrts%",           "Veritas",            "Commercial",   "Supported",       "Medium",   "Veritas storage software"),
            ("veritas%",        "Veritas",            "Commercial",   "Supported",       "Medium",   "Veritas software"),
            # Apache
            ("httpd%",          "Apache",             "Open Source",  "Supported",       "Low",      "Apache HTTP Server"),
            ("apache%",         "Apache",             "Open Source",  "Supported",       "Low",      "Apache software"),
            # Nginx
            ("nginx%",          "Nginx Inc",          "Open Source",  "Supported",       "Low",      "Nginx web server"),
            # OpenSSL
            ("openssl%",        "OpenSSL Project",    "Open Source",  "Supported",       "Medium",   "OpenSSL cryptography library"),
            # Python
            ("python%",         "Python Software",    "Open Source",  "Supported",       "Low",      "Python runtime"),
            # Node.js
            ("nodejs%",         "OpenJS Foundation",  "Open Source",  "Supported",       "Low",      "Node.js runtime"),
            ("node%",           "OpenJS Foundation",  "Open Source",  "Supported",       "Low",      "Node.js runtime"),
            # Docker / Podman / Containers
            ("docker%",         "Docker Inc",         "Commercial",   "Supported",       "Medium",   "Docker container runtime"),
            ("podman%",         "Red Hat",            "Open Source",  "Supported",       "Low",      "Podman container runtime"),
            # Jenkins
            ("jenkins%",        "CloudBees",          "Open Source",  "Supported",       "Medium",   "Jenkins CI/CD"),
            # Ansible
            ("ansible%",        "Red Hat",            "Open Source",  "Supported",       "Low",      "Ansible automation"),
            # Kernel / OS core
            ("kernel%",         "Red Hat / Linux",    "Open Source",  "Supported",       "Low",      "Linux kernel"),
            ("glibc%",          "GNU",                "Open Source",  "Supported",       "Low",      "GNU C Library"),
            # CentOS 7 / RHEL 7 — EOL
            ("centos-release%", "CentOS",             "Open Source",  "End of Life",     "Critical", "CentOS 7 is EOL"),
            # Graylog
            ("graylog%",        "Graylog",            "Commercial",   "Supported",       "Medium",   "Graylog log management"),
            # Microsoft Defender
            ("mdatp%",          "Microsoft",          "Commercial",   "Supported",       "Low",      "Microsoft Defender ATP"),
        ]
        for row in default_catalogue:
            conn.execute(
                "INSERT INTO software_catalogue (name_pattern, vendor, license_type, support_status, risk_rating, notes) VALUES (?,?,?,?,?,?)",
                row
            )
        print(f"[DB] Seeded {len(default_catalogue)} default software catalogue entries.")
    # Migration: create software_version_tracker tables if upgrading from old schema
    with DB_LOCK, get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS software_version_tracker (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name_match      TEXT    NOT NULL,
                display_name    TEXT    NOT NULL,
                check_type      TEXT    NOT NULL,
                check_source    TEXT    NOT NULL,
                regex_pattern   TEXT,
                latest_version  TEXT,
                last_checked    TEXT,
                enabled         INTEGER NOT NULL DEFAULT 1,
                notes           TEXT,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS software_version_findings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id       INTEGER NOT NULL,
                tracker_id      INTEGER NOT NULL,
                sw_name         TEXT    NOT NULL,
                installed_ver   TEXT,
                latest_ver      TEXT,
                status          TEXT    NOT NULL DEFAULT 'outdated',
                alerted         INTEGER NOT NULL DEFAULT 0,
                last_seen       TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id)  REFERENCES servers(id),
                FOREIGN KEY (tracker_id) REFERENCES software_version_tracker(id)
            );
            CREATE INDEX IF NOT EXISTS idx_svf_server ON software_version_findings (server_id);
        """)
        # Seed default version trackers if table is empty
        tr_count = conn.execute("SELECT COUNT(*) FROM software_version_tracker").fetchone()[0]
        if tr_count == 0:
            default_trackers = [
                # (name_match, display_name, check_type, check_source, regex_pattern, notes)
                ("jenkins",          "Jenkins",                "jenkins_update_center", "https://updates.jenkins.io/stable/latestCore.txt",  None,                    "Jenkins LTS latest version"),
                ("chef",             "Chef Infra Client",      "github_release",        "chef/chef",                                          None,                    "Chef Infra Client"),
                ("graylog-sidecar",  "Graylog Sidecar",        "github_release",        "Graylog2/collector-sidecar",                         None,                    "Graylog Sidecar agent"),
                ("graylog",          "Graylog Server",         "github_release",        "Graylog2/graylog2-server",                           None,                    "Graylog log management"),
                ("mdatp",            "Microsoft Defender ATP",  "url_regex",             "https://packages.microsoft.com/config/rhel/8/prod.repo", r"mdatp-([0-9]+\.[0-9]+\.[0-9]+)", "MS Defender for Endpoint"),
                ("check-mk-agent",   "Checkmk Agent",          "github_release",        "tribe29/checkmk",                                    None,                    "Checkmk monitoring agent"),
                ("ansible",          "Ansible",                "github_release",        "ansible/ansible",                                    None,                    "Ansible automation"),
                ("docker-ce",        "Docker CE",              "github_release",        "moby/moby",                                          None,                    "Docker Community Edition"),
                ("podman",           "Podman",                 "github_release",        "containers/podman",                                  None,                    "Podman container runtime"),
                ("postgresql",       "PostgreSQL",             "url_regex",             "https://www.postgresql.org/ftp/latest/",              r"v([0-9]+\.[0-9]+)",    "PostgreSQL database"),
                ("nginx",            "Nginx",                  "github_release",        "nginx/nginx",                                        None,                    "Nginx web server"),
                ("python3",          "Python 3",               "url_regex",             "https://www.python.org/downloads/",                  r"Python ([3-9]\.[0-9]+\.[0-9]+)", "Python 3 runtime"),
                ("node",             "Node.js",                "github_release",        "nodejs/node",                                        None,                    "Node.js runtime"),
                ("wso2",             "WSO2",                   "github_release",        "wso2/product-apim",                                  None,                    "WSO2 API Manager"),
            ]
            for row in default_trackers:
                conn.execute(
                    """INSERT INTO software_version_tracker
                       (name_match, display_name, check_type, check_source, regex_pattern, notes)
                       VALUES (?,?,?,?,?,?)""",
                    row
                )
            print(f"[DB] Seeded {len(default_trackers)} default software version trackers.")
    # Migration: create server_services table for auto-discovery
    with DB_LOCK, get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS server_services (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id   INTEGER NOT NULL,
                category    TEXT    NOT NULL,
                name        TEXT    NOT NULL,
                port        INTEGER,
                protocol    TEXT,
                address     TEXT,
                pid         INTEGER,
                process     TEXT,
                status      TEXT,
                description TEXT,
                image       TEXT,
                ports_info  TEXT,
                container_id TEXT,
                service_type TEXT,
                last_seen   TEXT    NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (server_id) REFERENCES servers(id)
            );
            CREATE INDEX IF NOT EXISTS idx_svc_server_id ON server_services (server_id);
        """)

    # Migration: critical process/service monitoring (watched flag, events, watched_services)
    # (a) 'watched' column keeps older read paths tolerant; the live value is
    #     computed from watched_services (below), which survives the heartbeat's
    #     DELETE/reinsert of server_services rows.
    try:
        conn.execute("ALTER TABLE server_services ADD COLUMN watched INTEGER DEFAULT 0")
        print("[DB] Migrated: added watched column to server_services.")
    except Exception:
        pass  # column already exists
    # (b) stable watched flag + transition history
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watched_services (
                server_id    INTEGER NOT NULL,
                service_name TEXT    NOT NULL,
                PRIMARY KEY (server_id, service_name)
            );
            CREATE TABLE IF NOT EXISTS service_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id    INTEGER NOT NULL,
                service_name TEXT    NOT NULL,
                status       TEXT,
                changed_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_svc_events_server_name
                ON service_events (server_id, service_name);
        """)
    except Exception:
        pass

    # Migration: add blocking_queries column to db_extended_metrics
    try:
        conn.execute("ALTER TABLE db_extended_metrics ADD COLUMN blocking_queries TEXT")
        print("[DB] Migrated: added blocking_queries column to db_extended_metrics.")
    except Exception:
        pass  # column already exists

    # Migration: add long_running_threshold column to db_monitors
    try:
        conn.execute("ALTER TABLE db_monitors ADD COLUMN long_running_threshold INTEGER")
        print("[DB] Migrated: added long_running_threshold column to db_monitors.")
    except Exception:
        pass  # column already exists

    # Seed global long_running_threshold setting if not present
    try:
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('long_running_threshold', '5')")
    except Exception:
        pass

    # Seed default admin user if no users exist
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("croitadmin", hash_password("N03ntry#_PCR3m0T#"), "admin")
        )
        print("[DB] Default admin user created: croitadmin")
    print("[DB] Initialized.")


def load_default_monitors():
    if not os.path.exists(MONITORS_FILE):
        return
    with DB_LOCK, get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM monitors").fetchone()[0]
        if count > 0:
            return
        with open(MONITORS_FILE) as f:
            data = json.load(f)
        for m in data.get("monitors", []):
            conn.execute(
                """INSERT INTO monitors (name, url, type, interval, description)
                   VALUES (?, ?, ?, ?, ?)""",
                (m["name"], m["url"], m.get("type","http"),
                 m.get("interval", 60), m.get("description",""))
            )
        # Create a default status page
        conn.execute(
            """INSERT OR IGNORE INTO status_pages (slug, title, description)
               VALUES ('default', 'System Status', 'Live status of all monitored services')"""
        )
        page_id = conn.execute("SELECT id FROM status_pages WHERE slug='default'").fetchone()["id"]
        monitors = conn.execute("SELECT id FROM monitors").fetchall()
        for i, mon in enumerate(monitors):
            conn.execute(
                "INSERT OR IGNORE INTO status_page_monitors VALUES (?,?,?)",
                (page_id, mon["id"], i)
            )
    print("[DB] Default monitors + status page loaded.")


# ─────────────────────────────────────────────
# Monitor checks
# ─────────────────────────────────────────────

def _get_proxies(url: str) -> dict:
    """
    Return proxy settings for a given URL.
    - Internal hostnames / RFC-1918 IPs bypass the proxy entirely.
    - External URLs use the system proxy so they can reach the internet.
    """
    import re
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""

    # Patterns that should bypass the proxy (internal)
    bypass_patterns = [
        r"^localhost$",
        r"^127\.",
        r"^10\.",
        r"^172\.(1[6-9]|2[0-9]|3[01])\.",   # RFC-1918 172.16-31.x
        r"^172\.20\.",                         # TOM servers
        r"^192\.168\.",
        r"\.local$",
        r"\.fnb\.co\.za$",                     # all internal FNB domains
        r"frm-",                               # frm-rbautodev01, frm-rbtomprd, frm-rbclapprd1 etc.
        r"frb-",
        r"\.ocp\.fnb\.co\.za$",               # OpenShift clusters (UAT + PROD)
        r"apps\.(dev|uat|prod|stg)-",         # OpenShift app routes
    ]
    for pattern in bypass_patterns:
        if re.search(pattern, host, re.IGNORECASE):
            return {"http": "", "https": ""}  # direct, no proxy

    # External URLs (e.g. actimizecloud.com) — use system proxy
    return {}  # lets requests pick up HTTP_PROXY / HTTPS_PROXY env vars


def check_http(url, timeout, keyword=None, accepted_codes="200-299", verify_ssl=False,
               method="GET", request_body=None, request_headers=None):
    try:
        start = time.monotonic()
        headers = {"Content-Type": "application/json"}
        if request_headers:
            try:
                extra = json.loads(request_headers) if isinstance(request_headers, str) else request_headers
                headers.update(extra)
            except Exception:
                pass

        if method == "POST" and request_body:
            # Check if this is a multipart/form-data request
            content_type = headers.get("Content-Type", "").lower()
            if "multipart/form-data" in content_type:
                # Parse form fields from JSON body: {"field1": "value1", "field2": "value2"}
                headers.pop("Content-Type", None)  # Let requests set the boundary
                try:
                    form_data = json.loads(request_body) if isinstance(request_body, str) else request_body
                    # Build multipart form fields
                    files = {k: (None, v) for k, v in form_data.items()}
                    resp = requests.post(url, files=files, headers=headers,
                                         timeout=timeout, verify=verify_ssl,
                                         allow_redirects=True, proxies=_get_proxies(url))
                except (json.JSONDecodeError, TypeError):
                    body_bytes = request_body.encode("utf-8") if isinstance(request_body, str) else request_body
                    resp = requests.post(url, data=body_bytes, headers=headers,
                                         timeout=timeout, verify=verify_ssl,
                                         allow_redirects=True, proxies=_get_proxies(url))
            else:
                body_bytes = request_body.encode("utf-8") if isinstance(request_body, str) else request_body
                resp = requests.post(url, data=body_bytes, headers=headers,
                                     timeout=timeout, verify=verify_ssl,
                                     allow_redirects=True, proxies=_get_proxies(url))
        else:
            resp = requests.get(url, timeout=timeout, verify=verify_ssl,
                                allow_redirects=True, proxies=_get_proxies(url))
        latency = int((time.monotonic() - start) * 1000)
        code    = resp.status_code

        # Check accepted status codes (e.g. "200-299,403")
        ok = False
        for part in accepted_codes.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-")
                if int(lo) <= code <= int(hi):
                    ok = True; break
            else:
                if code == int(part):
                    ok = True; break

        if not ok:
            return 0, latency, f"HTTP {code}"

        if keyword:
            if keyword.lower() not in resp.text.lower():
                return 0, latency, f"Keyword '{keyword}' not found"

        return 1, latency, f"HTTP {code}"
    except requests.exceptions.Timeout:
        return 0, None, "Timeout"
    except Exception as e:
        return 0, None, str(e)[:120]


def check_tcp(host, port, timeout):
    try:
        # Extract host/port from url-style strings like tcp://host:port
        if "://" in host:
            host = host.split("://")[1]
        if ":" in host:
            host, port = host.rsplit(":", 1)
            port = int(port)
        start = time.monotonic()
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
        latency = int((time.monotonic() - start) * 1000)
        return 1, latency, "TCP OK"
    except Exception as e:
        return 0, None, str(e)[:120]


def check_ssl(hostname, port=443, timeout=10):
    """Check SSL certificate expiry. Returns (days_left, expiry_date_str, issuer).
    For external hosts, tunnels through the corporate proxy via HTTP CONNECT."""
    import ssl as ssl_lib
    try:
        # Decide whether to go direct or through proxy
        proxies  = _get_proxies(f"https://{hostname}")
        proxy_url = proxies.get("https") or proxies.get("http")

        if proxy_url:
            # Connect via HTTP CONNECT tunnel through the proxy
            # Use unverified context just for the tunnel socket, then re-wrap
            from urllib.parse import urlparse
            p          = urlparse(proxy_url)
            proxy_host = p.hostname
            proxy_port = p.port or 8080
            raw = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
            connect_req = f"CONNECT {hostname}:{port} HTTP/1.1\r\nHost: {hostname}:{port}\r\n\r\n"
            raw.sendall(connect_req.encode())
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = raw.recv(4096)
                if not chunk:
                    break
                resp += chunk
            status_line = resp.split(b"\r\n")[0].decode()
            if "200" not in status_line:
                return None, None, f"Proxy CONNECT failed: {status_line.strip()}"
            # Now wrap with a context that retrieves the cert
            ctx = ssl_lib.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl_lib.CERT_OPTIONAL
            ssock = ctx.wrap_socket(raw, server_hostname=hostname)
        else:
            # Direct connection for internal hosts
            ctx = ssl_lib.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl_lib.CERT_OPTIONAL
            raw   = socket.create_connection((hostname, port), timeout=timeout)
            ssock = ctx.wrap_socket(raw, server_hostname=hostname)

        cert = ssock.getpeercert()
        ssock.close()

        if not cert:
            return None, None, "No certificate returned"

        expiry_str = cert.get("notAfter", "")
        if not expiry_str:
            return None, None, "No expiry date in certificate"

        expiry_dt    = datetime.strptime(expiry_str, "%b %d %H:%M:%S %Y %Z")
        days_left    = (expiry_dt - datetime.utcnow()).days
        issuer_parts = dict(x[0] for x in cert.get("issuer", []))
        issuer       = issuer_parts.get("organizationName", issuer_parts.get("commonName", "Unknown"))
        return days_left, expiry_dt.strftime("%Y-%m-%d"), issuer

    except ssl_lib.SSLCertVerificationError as e:
        return -1, None, f"Cert error: {str(e)[:80]}"
    except Exception as e:
        return None, None, str(e)[:80]


def is_in_maintenance(monitor_id):
    """Return True if the monitor is currently in a maintenance window."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    now_dt  = datetime.utcnow()
    with DB_LOCK, get_db() as conn:
        windows = conn.execute(
            "SELECT * FROM maintenance_windows WHERE monitor_id=? OR monitor_id IS NULL",
            (monitor_id,)
        ).fetchall()
    for w in windows:
        start = datetime.fromisoformat(w["start_dt"])
        end   = datetime.fromisoformat(w["end_dt"])
        if w["repeat_weekly"]:
            # Shift to current week
            days_since = (now_dt.weekday() - start.weekday()) % 7
            start_this = now_dt.replace(
                hour=start.hour, minute=start.minute, second=0, microsecond=0
            ) - timedelta(days=days_since)
            end_this = start_this + (end - start)
            if start_this <= now_dt <= end_this:
                return True, w["title"]
        else:
            if start <= now_dt <= end:
                return True, w["title"]
    return False, None


def do_check(monitor):
    mtype   = monitor["type"]
    url     = monitor["url"]
    timeout = monitor["timeout"] or 10

    if mtype in ("http", "https", "keyword"):
        kw = monitor["keyword"] if mtype == "keyword" else None
        return check_http(url, timeout, keyword=kw,
                          accepted_codes=monitor["accepted_codes"] or "200-299")
    elif mtype == "http-post":
        return check_http(url, timeout,
                          keyword=monitor.get("keyword") or None,
                          accepted_codes=monitor["accepted_codes"] or "200-299",
                          method="POST",
                          request_body=monitor.get("request_body") or None,
                          request_headers=monitor.get("request_headers") or None)
    elif mtype == "tcp":
        # url field holds host:port for TCP
        host = url
        port = 80
        if "://" in url:
            host = url.split("://")[1]
        if ":" in host:
            host, p = host.rsplit(":", 1)
            port = int(p)
        return check_tcp(host, port, timeout)
    else:
        return check_http(url, timeout)


# ─────────────────────────────────────────────
# Notification
# ─────────────────────────────────────────────

def get_setting(key, default=None):
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def send_alert_email(monitor_name, url, status, msg):
    smtp_host = get_setting("smtp_host", "")
    smtp_port = int(get_setting("smtp_port", "25"))
    smtp_from = get_setting("smtp_from", "")
    # Use monitor-specific recipients, fall back to default
    smtp_to   = get_setting("smtp_to_monitors", "") or get_setting("smtp_to", "")
    if not smtp_host or not smtp_to:
        return
    # Support multiple recipients separated by commas
    recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]
    try:
        if status == 0:
            state = "🔴 DOWN"
        elif status == "ssl_warning":
            state = "🟡 Certificate Expiring Soon"
        else:
            state = "🟢 UP"
        body  = f"Monitor: {monitor_name}\nURL: {url}\nStatus: {state}\nMessage: {msg}\nTime: {datetime.now()}"
        m = MIMEText(body)
        if status == "ssl_warning":
            m["Subject"] = f"[SSL Warning] {monitor_name} - Certificate Expiring Soon"
        else:
            m["Subject"] = f"[Uptime Monitor] {monitor_name} is {state}"
        m["From"]    = smtp_from
        m["To"]      = ", ".join(recipients)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(smtp_from, recipients, m.as_string())
        print(f"[Email] Alert sent for {monitor_name}")
    except Exception as e:
        print(f"[Email] Failed: {e}")


# ─────────────────────────────────────────────
# Monitor loop
# ─────────────────────────────────────────────

prev_status   = {}   # monitor_id -> last status
retry_counts  = {}   # monitor_id -> consecutive failures

def monitor_loop():
    last_checked = {}
    print("[Monitor] Background loop started.")

    # Initialize prev_status from last heartbeat in DB so alerts work after restart
    try:
        with DB_LOCK, get_db() as conn:
            monitors = conn.execute("SELECT id FROM monitors WHERE enabled=1").fetchall()
            for m in monitors:
                mid = m["id"]
                last_hb = conn.execute(
                    "SELECT status FROM heartbeats WHERE monitor_id=? ORDER BY checked_at DESC LIMIT 1",
                    (mid,)
                ).fetchone()
                if last_hb:
                    prev_status[mid] = last_hb["status"]
        print(f"[Monitor] Initialized prev_status for {len(prev_status)} monitors from DB.")
    except Exception as e:
        print(f"[Monitor] WARNING: Could not init prev_status: {e}")

    while True:
        now = time.time()
        with DB_LOCK, get_db() as conn:
            monitors = conn.execute(
                "SELECT * FROM monitors WHERE enabled=1"
            ).fetchall()
            monitors = [dict(m) for m in monitors]

        for m in monitors:
            mid      = m["id"]
            interval = m["interval"]
            if now - last_checked.get(mid, 0) < interval:
                continue

            status, latency, msg = do_check(m)

            # Skip recording if in maintenance window
            in_maint, maint_title = is_in_maintenance(mid)
            if in_maint:
                last_checked[mid] = now
                print(f"[MAINT] {m['name']} — skipping (maintenance: {maint_title})")
                continue

            # Retry logic
            if status == 0:
                retry_counts[mid] = retry_counts.get(mid, 0) + 1
                if retry_counts[mid] < m["retries"]:
                    last_checked[mid] = now
                    continue  # don't record yet, retry next cycle
            else:
                retry_counts[mid] = 0

            with DB_LOCK, get_db() as conn:
                conn.execute(
                    "INSERT INTO heartbeats (monitor_id, status, latency_ms, msg) VALUES (?,?,?,?)",
                    (mid, status, latency, msg)
                )

            # Alert on state change
            if m["notify_email"]:
                prev = prev_status.get(mid)
                if prev is not None and prev != status:
                    send_alert_email(m["name"], m["url"], status, msg or "")

            prev_status[mid] = status
            last_checked[mid] = now
            state = "UP" if status else "DOWN"
            print(f"[{state}] {m['name']} ({m['url']}) — {latency}ms — {msg}")

        time.sleep(5)


# ─────────────────────────────────────────────
# SSL Certificate checker loop
# ─────────────────────────────────────────────

def ssl_check_loop():
    """Check SSL certs every 6 hours. Alert if expiry < 30 days."""
    print("[SSL] Certificate checker started.")
    while True:
        try:
            with DB_LOCK, get_db() as conn:
                monitors = conn.execute(
                    "SELECT id, name, url FROM monitors WHERE enabled=1 AND url LIKE 'https://%'"
                ).fetchall()
                monitors = [dict(m) for m in monitors]

            for m in monitors:
                try:
                    from urllib.parse import urlparse
                    parsed   = urlparse(m["url"])
                    hostname = parsed.hostname
                    port     = parsed.port or 443
                    if not hostname:
                        continue
                    days_left, expiry_date, issuer = check_ssl(hostname, port)
                    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    with DB_LOCK, get_db() as conn:
                        conn.execute(
                            """INSERT INTO ssl_checks (monitor_id, days_left, expiry_date, issuer, last_checked)
                               VALUES (?,?,?,?,?)
                               ON CONFLICT(monitor_id) DO UPDATE SET
                               days_left=excluded.days_left, expiry_date=excluded.expiry_date,
                               issuer=excluded.issuer, last_checked=excluded.last_checked""",
                            (m["id"], days_left, expiry_date, issuer, now_str)
                        )
                    if days_left is not None and days_left <= 30:
                        print(f"[SSL] WARNING: {m['name']} cert expires in {days_left} days ({expiry_date})")
                        # Send alert email
                        smtp_host = get_setting("smtp_host", "")
                        smtp_to   = get_setting("smtp_to", "")
                        if smtp_host and smtp_to and days_left in (30, 14, 7, 3, 1):
                            send_alert_email(
                                m["name"], m["url"], "ssl_warning",
                                f"SSL certificate expires in {days_left} days on {expiry_date}"
                            )
                except Exception as e:
                    print(f"[SSL] Error checking {m['name']}: {e}")
        except Exception as e:
            print(f"[SSL] Loop error: {e}")
        time.sleep(6 * 3600)  # every 6 hours


# ─────────────────────────────────────────────
# Database Monitor — check + loop
# ─────────────────────────────────────────────

def check_db_tcp(host, port, timeout=5):
    """TCP reachability check for database servers."""
    try:
        start = time.monotonic()
        with socket.create_connection((host, int(port)), timeout=timeout):
            pass
        latency = int((time.monotonic() - start) * 1000)
        return 1, latency, "TCP OK", None
    except Exception as e:
        return 0, None, str(e)[:120], None


def check_db_query(db_type, host, port, database, username, password, timeout=5, db_id=None):
    """Run SELECT 1 and get connection count. Falls back to TCP if driver not installed."""
    current_query = "connect"
    try:
        start = time.monotonic()
        connections = None

        if db_type == "mssql":
            try:
                import pymssql
                conn = pymssql.connect(
                    server=host, port=int(port), database=database or 'master',
                    user=username, password=password, login_timeout=timeout,
                    timeout=timeout, as_dict=False
                )
                try:
                    cur = conn.cursor()
                    current_query = "SELECT 1"
                    cur.execute("SELECT 1")
                    cur.fetchone()
                    try:
                        current_query = "SELECT COUNT(*) FROM sys.dm_exec_sessions"
                        cur.execute("SELECT COUNT(*) FROM sys.dm_exec_sessions WHERE is_user_process=1")
                        connections = cur.fetchone()[0]
                    except Exception as qe:
                        print(f"[DB] Connection count query failed: {qe}")
                    # Collect extended metrics while connection is still open
                    if db_id is not None:
                        try:
                            collect_extended_metrics(conn, db_id)
                        except Exception as ext_e:
                            print(f"[DB EXT] Extended metrics collection failed for db_id={db_id}: {ext_e}")
                finally:
                    conn.close()
            except ImportError:
                return check_db_tcp(host, port, timeout)

        elif db_type == "postgres":
            try:
                import psycopg2
                with psycopg2.connect(
                    host=host, port=port, dbname=database or "postgres",
                    user=username, password=password, connect_timeout=timeout
                ) as conn:
                    with conn.cursor() as cur:
                        current_query = "SELECT 1"
                        cur.execute("SELECT 1")
                        cur.fetchone()
                        try:
                            current_query = "SELECT COUNT(*) FROM pg_stat_activity"
                            cur.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE state='active'")
                            connections = cur.fetchone()[0]
                        except Exception as qe:
                            print(f"[DB] Connection count query failed: {qe}")
            except ImportError:
                return check_db_tcp(host, port, timeout)

        else:
            return check_db_tcp(host, port, timeout)

        latency = int((time.monotonic() - start) * 1000)
        return 1, latency, "Query OK", connections

    except Exception as e:
        err_msg = f"[{current_query}] {str(e)}"
        print(f"[DB ERROR] {host}:{port} — {err_msg}")
        return 0, None, err_msg[:200], None


def collect_extended_metrics(conn, db_id):
    """Collect extended metrics (active requests, running queries, database list, blocking queries) from MSSQL.
    Each query is independent — failure stores NULL for that field and logs a warning."""
    active_requests = None
    running_queries = None
    databases_list = None

    # 1. Active request count
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sys.dm_exec_requests WHERE session_id > 50 AND session_id != @@SPID")
        active_requests = cur.fetchone()[0]
    except Exception as e:
        print(f"[DB EXT] active_requests failed for db_id={db_id}: {e}")

    # 2. Running queries (top 50 by elapsed time)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT TOP 50
                r.session_id,
                LEFT(CAST(t.text AS NVARCHAR(MAX)), 500) AS sql_text,
                r.status,
                r.wait_type,
                r.total_elapsed_time AS elapsed_time_ms,
                DB_NAME(r.database_id) AS database_name
            FROM sys.dm_exec_requests r
            CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
            WHERE r.session_id > 50 AND r.session_id != @@SPID
            ORDER BY r.total_elapsed_time DESC
        """)
        rows = cur.fetchall()
        running_queries = []
        for row in rows:
            running_queries.append({
                "session_id": row[0],
                "sql_text": row[1],
                "status": row[2],
                "wait_type": row[3],
                "elapsed_time_ms": row[4],
                "database_name": row[5]
            })
    except Exception as e:
        print(f"[DB EXT] running_queries failed for db_id={db_id}: {e}")

    # 3. Database list
    try:
        cur = conn.cursor()
        cur.execute("SELECT name, state_desc, compatibility_level FROM sys.databases ORDER BY name")
        rows = cur.fetchall()
        databases_list = []
        for row in rows:
            databases_list.append({
                "name": row[0],
                "state_desc": row[1],
                "compatibility_level": row[2]
            })
    except Exception as e:
        print(f"[DB EXT] databases_list failed for db_id={db_id}: {e}")

    # 4. Blocking queries
    blocking_queries = None
    try:
        cur = conn.cursor()
        # Get all blocked sessions with their blocker
        cur.execute("""
            SELECT 
                r.session_id AS blocked_session_id,
                r.blocking_session_id,
                r.wait_type,
                r.wait_resource,
                r.wait_time AS wait_time_ms,
                LEFT(ISNULL(CAST(t.text AS NVARCHAR(MAX)), ''), 500) AS blocked_sql_text,
                DB_NAME(r.database_id) AS database_name
            FROM sys.dm_exec_requests r
            CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t
            WHERE r.blocking_session_id > 0
              AND r.session_id > 50
            ORDER BY r.blocking_session_id, r.wait_time DESC
        """)
        blocked_rows = cur.fetchall()

        if not blocked_rows:
            blocking_queries = []
        else:
            # Build a map of blocker_session_id -> list of blocked sessions
            blocker_map = {}
            all_blocked_ids = set()
            for row in blocked_rows:
                blocked_sid = row[0]
                blocker_sid = row[1]
                all_blocked_ids.add(blocked_sid)
                if blocker_sid not in blocker_map:
                    blocker_map[blocker_sid] = []
                blocker_map[blocker_sid].append({
                    "session_id": blocked_sid,
                    "sql_text": row[5] or "",
                    "wait_type": row[2],
                    "wait_resource": row[3],
                    "wait_time_ms": row[4],
                    "database_name": row[6]
                })

            # Head blockers are those that block others but are not themselves blocked
            head_blockers = [sid for sid in blocker_map.keys() if sid not in all_blocked_ids]

            blocking_queries = []
            for head_sid in head_blockers:
                # Get head blocker's SQL text
                head_sql = ""
                try:
                    cur2 = conn.cursor()
                    cur2.execute("""
                        SELECT LEFT(ISNULL(CAST(t.text AS NVARCHAR(MAX)), ''), 500) AS sql_text
                        FROM sys.dm_exec_connections c
                        CROSS APPLY sys.dm_exec_sql_text(c.most_recent_sql_handle) t
                        WHERE c.session_id = ?
                    """, (head_sid,))
                    hrow = cur2.fetchone()
                    if hrow:
                        head_sql = hrow[0] or ""
                except Exception:
                    pass

                # Collect all blocked sessions under this head blocker (traverse chain, max depth 10)
                all_blocked = []
                queue = [head_sid]
                visited = {head_sid}
                depth = 0
                while queue and depth < 10:
                    next_queue = []
                    for sid in queue:
                        if sid in blocker_map:
                            for blocked in blocker_map[sid]:
                                if blocked["session_id"] not in visited:
                                    visited.add(blocked["session_id"])
                                    all_blocked.append(blocked)
                                    next_queue.append(blocked["session_id"])
                    queue = next_queue
                    depth += 1

                blocking_queries.append({
                    "head_blocker": {
                        "session_id": head_sid,
                        "sql_text": head_sql
                    },
                    "blocked_sessions": all_blocked,
                    "blocked_count": len(all_blocked)
                })
    except Exception as e:
        print(f"[DB EXT] blocking_queries failed for db_id={db_id}: {e}")

    # 5. Store results in SQLite
    try:
        with DB_LOCK, get_db() as local_conn:
            local_conn.execute(
                "INSERT INTO db_extended_metrics (db_id, active_requests, running_queries, databases_list, blocking_queries) VALUES (?,?,?,?,?)",
                (db_id, active_requests,
                 json.dumps(running_queries) if running_queries is not None else None,
                 json.dumps(databases_list) if databases_list is not None else None,
                 json.dumps(blocking_queries) if blocking_queries is not None else None)
            )
            # Retention purge: keep only the 100 most recent records per db_id
            local_conn.execute("""
                DELETE FROM db_extended_metrics
                WHERE db_id = ? AND id NOT IN (
                    SELECT id FROM db_extended_metrics
                    WHERE db_id = ?
                    ORDER BY collected_at DESC
                    LIMIT 100
                )
            """, (db_id, db_id))
    except Exception as e:
        print(f"[DB EXT] Storage failed for db_id={db_id}: {e}")


def db_monitor_loop():
    """Background loop that checks all enabled DB monitors."""
    last_checked = {}
    print("[DB Monitor] Background loop started.")
    while True:
        now = time.time()
        with DB_LOCK, get_db() as conn:
            dbs = conn.execute("SELECT * FROM db_monitors WHERE enabled=1").fetchall()
            dbs = [dict(d) for d in dbs]

        for db in dbs:
            did      = db["id"]
            interval = db["interval"]
            if now - last_checked.get(did, 0) < interval:
                continue

            if db.get("username") and db.get("password"):
                status, latency, msg, connections = check_db_query(
                    db["db_type"], db["host"], db["port"],
                    db.get("database"), db["username"], db["password"],
                    db_id=did
                )
            else:
                status, latency, msg, connections = check_db_tcp(db["host"], db["port"])

            with DB_LOCK, get_db() as conn:
                conn.execute(
                    "INSERT INTO db_heartbeats (db_id, status, latency_ms, connections, msg) VALUES (?,?,?,?,?)",
                    (did, status, latency, connections, msg)
                )

            last_checked[did] = now
            state = "UP" if status else "DOWN"
            lat_str  = f"{latency}ms" if latency is not None else "None"
            conn_str = f"conns={connections}" if connections is not None else "conns=N/A"
            if status == 0:
                print(f"[DB DOWN] {db['name']} ({db['host']}:{db['port']}) — {lat_str} — ERROR: {msg}")
            else:
                print(f"[DB UP]   {db['name']} ({db['host']}:{db['port']}) — {lat_str} — {conn_str} — {msg}")

        time.sleep(5)


# ─────────────────────────────────────────────
# Weekly report scheduler
# ─────────────────────────────────────────────

def weekly_report_loop():
    """Send weekly uptime report every Monday at 08:00 UTC."""
    print("[Report] Weekly report scheduler started.")
    last_sent_week = None
    while True:
        now = datetime.utcnow()
        # Monday = 0, send at 08:00
        if now.weekday() == 0 and now.hour == 8 and last_sent_week != now.isocalendar()[1]:
            try:
                send_weekly_report()
                last_sent_week = now.isocalendar()[1]
                print(f"[Report] Weekly report sent for week {last_sent_week}")
            except Exception as e:
                print(f"[Report] Failed to send: {e}")
        time.sleep(60)  # check every minute


def send_weekly_report():
    smtp_host = get_setting("smtp_host", "")
    smtp_port = int(get_setting("smtp_port", "25"))
    smtp_from = get_setting("smtp_from", "")
    smtp_to   = get_setting("smtp_to", "")
    if not smtp_host or not smtp_to:
        print("[Report] SMTP not configured, skipping.")
        return

    now    = datetime.utcnow()
    week_start = now - timedelta(days=7)

    with DB_LOCK, get_db() as conn:
        monitors = conn.execute("SELECT * FROM monitors ORDER BY group_name, name").fetchall()
        monitors = [dict(m) for m in monitors]

    # Build stats per monitor for last 7 days
    groups = {}
    for m in monitors:
        g = m["group_name"] or "General"
        if g not in groups:
            groups[g] = []
        with DB_LOCK, get_db() as conn:
            stats = build_monitor_stats(
                m["id"],
                week_start,
                now,
                conn
            )
        groups[g].append({**m, **stats})

    # Build HTML email
    rows_html = ""
    overall_uptimes = []
    for group_name, mons in sorted(groups.items()):
        rows_html += f"""
        <tr style="background:#f0f2f5">
          <td colspan="4" style="padding:8px 12px;font-weight:700;font-size:12px;
              text-transform:uppercase;letter-spacing:.06em;color:#4a5568">{group_name}</td>
        </tr>"""
        for m in mons:
            pct   = m["uptime_pct"]
            color = "#1a9e5c" if pct is None or pct >= 99 else "#d97706" if pct >= 90 else "#e53e3e"
            pct_s = f"{pct:.2f}%" if pct is not None else "No data"
            lat_s = f"{m['avg_latency']}ms" if m["avg_latency"] else "–"
            overall_uptimes.append(pct) if pct is not None else None
            rows_html += f"""
        <tr>
          <td style="padding:8px 12px;font-size:13px">{m['name']}</td>
          <td style="padding:8px 12px;font-size:13px;font-weight:700;color:{color}">{pct_s}</td>
          <td style="padding:8px 12px;font-size:13px;color:#4a5568">{lat_s}</td>
          <td style="padding:8px 12px;font-size:13px;color:#4a5568">{m['total_checks']}</td>
        </tr>"""

    avg_overall = f"{sum(overall_uptimes)/len(overall_uptimes):.2f}%" if overall_uptimes else "N/A"
    week_label  = f"{week_start.strftime('%d %b')} – {now.strftime('%d %b %Y')}"

    html_body = f"""
<html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f4f6f8;margin:0;padding:20px">
<div style="max-width:680px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08)">
  <div style="background:linear-gradient(135deg,#1a6eb5,#1a9e5c);padding:28px 32px;color:#fff">
    <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;opacity:.8">CROIT</div>
    <div style="font-size:22px;font-weight:800;margin-top:4px">Weekly Uptime Report</div>
    <div style="font-size:13px;opacity:.8;margin-top:6px">{week_label}</div>
  </div>
  <div style="padding:24px 32px">
    <div style="display:flex;gap:20px;margin-bottom:24px">
      <div style="flex:1;background:#f0f2f5;border-radius:8px;padding:16px;text-align:center">
        <div style="font-size:28px;font-weight:800;color:#1a9e5c">{avg_overall}</div>
        <div style="font-size:11px;color:#8a94a6;text-transform:uppercase;margin-top:4px">Overall Uptime</div>
      </div>
      <div style="flex:1;background:#f0f2f5;border-radius:8px;padding:16px;text-align:center">
        <div style="font-size:28px;font-weight:800;color:#2b7de9">{len(monitors)}</div>
        <div style="font-size:11px;color:#8a94a6;text-transform:uppercase;margin-top:4px">Monitors</div>
      </div>
    </div>
    <table style="width:100%;border-collapse:collapse;border:1px solid #dde1e7;border-radius:8px;overflow:hidden">
      <thead>
        <tr style="background:#f0f2f5">
          <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:700;color:#8a94a6;text-transform:uppercase">Service</th>
          <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:700;color:#8a94a6;text-transform:uppercase">Uptime</th>
          <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:700;color:#8a94a6;text-transform:uppercase">Avg Latency</th>
          <th style="padding:10px 12px;text-align:left;font-size:11px;font-weight:700;color:#8a94a6;text-transform:uppercase">Checks</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
  <div style="padding:16px 32px;border-top:1px solid #dde1e7;font-size:11px;color:#8a94a6;text-align:center">
    CROIT Uptime Monitoring &nbsp;·&nbsp; Auto-generated report &nbsp;·&nbsp; {now.strftime('%d %b %Y %H:%M')} UTC
  </div>
</div>
</body></html>"""

    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText as _MIMEText
    recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[CROIT] Weekly Uptime Report — {week_label}"
    msg["From"]    = smtp_from
    msg["To"]      = ", ".join(recipients)
    msg.attach(_MIMEText(html_body, "html"))
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as s:
        s.sendmail(smtp_from, recipients, msg.as_string())


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def build_monitor_stats(mid, dt_from, dt_to, conn):
    from_str = dt_from.strftime("%Y-%m-%d %H:%M:%S")
    to_str   = dt_to.strftime("%Y-%m-%d %H:%M:%S")

    rows = conn.execute(
        """SELECT status, latency_ms, checked_at FROM heartbeats
           WHERE monitor_id=? AND checked_at BETWEEN ? AND ?
           ORDER BY checked_at ASC""",
        (mid, from_str, to_str)
    ).fetchall()

    total = len(rows)
    up    = sum(1 for r in rows if r["status"] == 1)
    uptime_pct = round(up / total * 100, 2) if total else None

    latencies   = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else None

    last = conn.execute(
        """SELECT status, latency_ms, msg, checked_at FROM heartbeats
           WHERE monitor_id=? ORDER BY checked_at DESC LIMIT 1""",
        (mid,)
    ).fetchone()

    # 50-bucket timeline
    BUCKETS = 50
    buckets = []
    if total > 0:
        span = (dt_to - dt_from).total_seconds()
        bsize = max(span / BUCKETS, 1)
        for i in range(BUCKETS):
            b_start = (dt_from + timedelta(seconds=i * bsize)).strftime("%Y-%m-%d %H:%M:%S")
            b_end   = (dt_from + timedelta(seconds=(i+1) * bsize)).strftime("%Y-%m-%d %H:%M:%S")
            b_rows  = [r for r in rows if b_start <= r["checked_at"] <= b_end]
            if b_rows:
                b_up = sum(1 for r in b_rows if r["status"] == 1)
                buckets.append(1 if b_up / len(b_rows) >= 0.5 else 0)
            else:
                buckets.append(None)
    else:
        buckets = [None] * BUCKETS

    return {
        "uptime_pct":   uptime_pct,
        "avg_latency":  avg_latency,
        "total_checks": total,
        "up_checks":    up,
        "timeline":     buckets,
        "current_status": dict(last) if last else None,
        "from_dt": from_str,
        "to_dt":   to_str,
    }


def parse_timeframe(args):
    preset  = args.get("preset", "24h")
    from_dt = args.get("from_dt")
    to_dt   = args.get("to_dt")
    now     = datetime.utcnow()
    preset_map = {
        "1h":  now - timedelta(hours=1),
        "3h":  now - timedelta(hours=3),
        "6h":  now - timedelta(hours=6),
        "9h":  now - timedelta(hours=9),
        "24h": now - timedelta(hours=24),
        "7d":  now - timedelta(days=7),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
    }
    if from_dt and to_dt:
        return datetime.fromisoformat(from_dt), datetime.fromisoformat(to_dt)
    return preset_map.get(preset, now - timedelta(hours=24)), now


# ─────────────────────────────────────────────
# API — Auth
# ─────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    d        = request.get_json()
    username = (d.get("username") or "").strip()
    password = (d.get("password") or "")
    with DB_LOCK, get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, hash_password(password))
        ).fetchone()
    if not row:
        return jsonify({"error": "Invalid username or password"}), 401
    user = User(row["id"], row["username"], row["role"])
    login_user(user, remember=True)
    return jsonify({"ok": True, "username": user.username, "role": user.role})

@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    logout_user()
    return jsonify({"ok": True})

@app.route("/api/auth/me", methods=["GET"])
def api_me():
    if current_user.is_authenticated:
        return jsonify({"authenticated": True, "username": current_user.username, "role": current_user.role})
    return jsonify({"authenticated": False}), 401

# ─────────────────────────────────────────────
# API — Users (admin only)
# ─────────────────────────────────────────────

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Not authenticated"}), 401
        if current_user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated

def auth_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Not authenticated"}), 401
        return f(*args, **kwargs)
    return decorated

def role_required(allowed_roles):
    """Decorator factory that restricts route access to users with specific roles.

    Args:
        allowed_roles: list/set of role strings.
                       Valid roles: 'admin', 'viewer', 'dba'

    Returns:
        - 401 if user is not authenticated
        - 403 if user's role is not in allowed_roles
        - Proceeds to route handler if role is allowed
    """
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({"error": "Not authenticated"}), 401
            if current_user.role not in allowed_roles:
                return jsonify({"error": "Access denied"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

@app.route("/api/users", methods=["GET"])
@role_required(['admin'])
def api_get_users():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/users", methods=["POST"])
@role_required(['admin'])
def api_create_user():
    d        = request.get_json()
    username = (d.get("username") or "").strip()
    password = (d.get("password") or "")
    role     = d.get("role", "viewer")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": f"Invalid role: {role}. Must be one of: admin, viewer, dba"}), 400
    try:
        with DB_LOCK, get_db() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, hash_password(password), role)
            )
            row = conn.execute("SELECT id, username, role, created_at FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except Exception:
        return jsonify({"error": "Username already exists"}), 409

@app.route("/api/users/<int:uid>", methods=["PUT"])
@role_required(['admin'])
def api_update_user(uid):
    d = request.get_json()
    if "password" in d and d["password"]:
        with DB_LOCK, get_db() as conn:
            conn.execute("UPDATE users SET password=? WHERE id=?", (hash_password(d["password"]), uid))
    if "role" in d:
        if d["role"] not in VALID_ROLES:
            return jsonify({"error": f"Invalid role: {d['role']}. Must be one of: admin, viewer, dba"}), 400
        with DB_LOCK, get_db() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=?", (d["role"], uid))
    with DB_LOCK, get_db() as conn:
        row = conn.execute("SELECT id, username, role, created_at FROM users WHERE id=?", (uid,)).fetchone()
    return jsonify(dict(row))

@app.route("/api/users/<int:uid>", methods=["DELETE"])
@role_required(['admin'])
def api_delete_user(uid):
    if str(uid) == current_user.id:
        return jsonify({"error": "Cannot delete your own account"}), 400
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
    return jsonify({"deleted": uid})

# ─────────────────────────────────────────────
# API — Monitors
# ─────────────────────────────────────────────

@app.route("/api/monitors", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_monitors():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute("SELECT * FROM monitors ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/monitors", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_add_monitor():
    d = request.get_json()
    name     = d.get("name","").strip()
    url      = d.get("url","").strip()
    mtype    = d.get("type","http")
    interval = int(d.get("interval", 60))
    retries  = int(d.get("retries", 3))
    timeout  = int(d.get("timeout", 10))
    keyword  = d.get("keyword","") or None
    accepted = d.get("accepted_codes","200-299")
    notify   = int(d.get("notify_email", 0))
    desc     = d.get("description","")
    tags     = d.get("tags","")
    group    = d.get("group_name","").strip()
    req_body    = d.get("request_body","") or None
    req_headers = d.get("request_headers","") or None
    if not name or not url:
        return jsonify({"error": "name and url required"}), 400
    with DB_LOCK, get_db() as conn:
        cur = conn.execute(
            """INSERT INTO monitors
               (name,url,type,interval,retries,timeout,keyword,accepted_codes,notify_email,description,tags,group_name,request_body,request_headers)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name,url,mtype,interval,retries,timeout,keyword,accepted,notify,desc,tags,group,req_body,req_headers)
        )
        row = conn.execute("SELECT * FROM monitors WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/monitors/<int:mid>", methods=["PUT"])
@role_required(['admin', 'viewer'])
def api_update_monitor(mid):
    d = request.get_json()
    fields = []
    vals   = []
    for col in ["name","url","type","interval","retries","timeout",
                "keyword","accepted_codes","notify_email","description","tags","enabled","group_name",
                "request_body","request_headers"]:
        if col in d:
            fields.append(f"{col}=?")
            vals.append(d[col])
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    vals.append(mid)
    with DB_LOCK, get_db() as conn:
        conn.execute(f"UPDATE monitors SET {','.join(fields)} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM monitors WHERE id=?", (mid,)).fetchone()
    return jsonify(dict(row))


@app.route("/api/monitors/<int:mid>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_delete_monitor(mid):
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM heartbeats WHERE monitor_id=?", (mid,))
        conn.execute("DELETE FROM status_page_monitors WHERE monitor_id=?", (mid,))
        conn.execute("DELETE FROM monitors WHERE id=?", (mid,))
    return jsonify({"deleted": mid})


@app.route("/api/monitors/<int:mid>/toggle", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_toggle_monitor(mid):
    with DB_LOCK, get_db() as conn:
        row = conn.execute("SELECT enabled FROM monitors WHERE id=?", (mid,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        new = 0 if row["enabled"] else 1
        conn.execute("UPDATE monitors SET enabled=? WHERE id=?", (new, mid))
    return jsonify({"id": mid, "enabled": bool(new)})


@app.route("/api/monitors/<int:mid>/stats", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_monitor_stats(mid):
    dt_from, dt_to = parse_timeframe(request.args)
    with DB_LOCK, get_db() as conn:
        mon = conn.execute("SELECT * FROM monitors WHERE id=?", (mid,)).fetchone()
        if not mon:
            return jsonify({"error": "not found"}), 404
        stats = build_monitor_stats(mid, dt_from, dt_to, conn)
    return jsonify({**dict(mon), **stats})


@app.route("/api/monitors/<int:mid>/heartbeats", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_heartbeats(mid):
    limit   = int(request.args.get("limit", 200))
    from_dt = request.args.get("from_dt")
    to_dt   = request.args.get("to_dt")
    preset  = request.args.get("preset")

    if from_dt and to_dt:
        dt_from = datetime.fromisoformat(from_dt)
        dt_to   = datetime.fromisoformat(to_dt)
    elif preset:
        now = datetime.utcnow()
        preset_map = {
            "1h": now - timedelta(hours=1), "3h": now - timedelta(hours=3),
            "6h": now - timedelta(hours=6), "9h": now - timedelta(hours=9),
            "24h": now - timedelta(hours=24), "7d": now - timedelta(days=7),
            "30d": now - timedelta(days=30), "90d": now - timedelta(days=90),
        }
        dt_from = preset_map.get(preset, now - timedelta(hours=24))
        dt_to   = now
    else:
        dt_from = None
        dt_to   = None

    with DB_LOCK, get_db() as conn:
        if dt_from and dt_to:
            rows = conn.execute(
                """SELECT status, latency_ms, msg, checked_at FROM heartbeats
                   WHERE monitor_id=? AND checked_at BETWEEN ? AND ?
                   ORDER BY checked_at ASC LIMIT ?""",
                (mid, dt_from.strftime("%Y-%m-%d %H:%M:%S"),
                 dt_to.strftime("%Y-%m-%d %H:%M:%S"), limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT status, latency_ms, msg, checked_at FROM heartbeats
                   WHERE monitor_id=? ORDER BY checked_at DESC LIMIT ?""",
                (mid, limit)
            ).fetchall()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────
# API — Monitor Audit Report (CSV Export)
# ─────────────────────────────────────────────

def _sanitize_monitor_name(name):
    """Sanitize monitor name for use in filenames."""
    return re.sub(r'[^a-zA-Z0-9\-_]', '_', name or 'unknown')


def _compute_downtime_incidents(heartbeats, period_end):
    """
    Group consecutive down heartbeats into downtime incidents.
    Returns list of incident dicts.
    """
    incidents = []
    current_incident = None
    incident_num = 0

    for hb in heartbeats:
        if hb["status"] == 0:
            if current_incident is None:
                incident_num += 1
                current_incident = {
                    "incident_number": incident_num,
                    "start_time": hb["checked_at"],
                    "end_time": hb["checked_at"],
                    "failed_checks": 1,
                    "error_message": hb.get("msg") or "",
                }
            else:
                current_incident["end_time"] = hb["checked_at"]
                current_incident["failed_checks"] += 1
        else:
            if current_incident is not None:
                # Incident resolved
                current_incident["status"] = "Resolved"
                start = datetime.strptime(current_incident["start_time"], "%Y-%m-%d %H:%M:%S")
                end = datetime.strptime(current_incident["end_time"], "%Y-%m-%d %H:%M:%S")
                current_incident["duration_seconds"] = int((end - start).total_seconds())
                # Format timestamps as ISO 8601
                current_incident["start_time"] = start.strftime("%Y-%m-%dT%H:%M:%S")
                current_incident["end_time"] = end.strftime("%Y-%m-%dT%H:%M:%S")
                incidents.append(current_incident)
                current_incident = None

    # Handle ongoing incident at end of period
    if current_incident is not None:
        current_incident["status"] = "Ongoing"
        start = datetime.strptime(current_incident["start_time"], "%Y-%m-%d %H:%M:%S")
        end_time = period_end if isinstance(period_end, datetime) else datetime.strptime(current_incident["end_time"], "%Y-%m-%d %H:%M:%S")
        current_incident["duration_seconds"] = int((end_time - start).total_seconds())
        current_incident["start_time"] = start.strftime("%Y-%m-%dT%H:%M:%S")
        current_incident["end_time"] = end_time.strftime("%Y-%m-%dT%H:%M:%S")
        incidents.append(current_incident)

    return incidents


@app.route("/api/monitors/<int:mid>/audit-report", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_monitor_audit_report(mid):
    """Generate and download a CSV audit report for a monitor."""
    import csv
    import io

    # Parse timeframe
    try:
        dt_from, dt_to = parse_timeframe(request.args)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    # Fetch data under lock
    with DB_LOCK, get_db() as conn:
        mon = conn.execute("SELECT * FROM monitors WHERE id=?", (mid,)).fetchone()
        if not mon:
            return jsonify({"error": "Monitor not found"}), 404

        from_str = dt_from.strftime("%Y-%m-%d %H:%M:%S")
        to_str = dt_to.strftime("%Y-%m-%d %H:%M:%S")

        heartbeats = conn.execute(
            """SELECT status, latency_ms, msg, checked_at FROM heartbeats
               WHERE monitor_id=? AND checked_at BETWEEN ? AND ?
               ORDER BY checked_at ASC""",
            (mid, from_str, to_str)
        ).fetchall()

    # Compute stats (outside lock)
    heartbeats_list = [dict(hb) for hb in heartbeats]
    total = len(heartbeats_list)
    up = sum(1 for hb in heartbeats_list if hb["status"] == 1)
    down = total - up
    uptime_pct = round(up / total * 100, 2) if total else 0
    latencies = [hb["latency_ms"] for hb in heartbeats_list if hb["latency_ms"] is not None]
    avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0

    # Compute downtime incidents
    incidents = _compute_downtime_incidents(heartbeats_list, dt_to)

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Summary section (key-value rows)
    writer.writerow(["Field", "Value"])
    writer.writerow(["Monitor Name", mon["name"]])
    writer.writerow(["URL", mon["url"]])
    writer.writerow(["Type", mon["type"]])
    writer.writerow(["Check Interval (s)", mon["interval"]])
    writer.writerow(["Report Period Start", dt_from.strftime("%Y-%m-%dT%H:%M:%S")])
    writer.writerow(["Report Period End", dt_to.strftime("%Y-%m-%dT%H:%M:%S")])
    writer.writerow(["Uptime (%)", uptime_pct])
    writer.writerow(["Total Checks", total])
    writer.writerow(["Up Count", up])
    writer.writerow(["Down Count", down])
    writer.writerow(["Average Latency (ms)", avg_latency])

    # Blank separator row
    writer.writerow([])

    # Incidents section
    writer.writerow(["Incident_Number", "Start_Time", "End_Time", "Duration_Seconds", "Failed_Checks", "Status", "Error_Message"])
    for inc in incidents:
        writer.writerow([
            inc["incident_number"],
            inc["start_time"],
            inc["end_time"],
            inc["duration_seconds"],
            inc["failed_checks"],
            inc["status"],
            inc["error_message"],
        ])

    # Build filename
    sanitized_name = _sanitize_monitor_name(mon["name"])
    from_date = dt_from.strftime("%Y-%m-%d")
    to_date = dt_to.strftime("%Y-%m-%d")
    filename = f"{sanitized_name}_audit_{from_date}_to_{to_date}.csv"

    response = app.response_class(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
    return response


# ─────────────────────────────────────────────
# API — Dashboard status (all monitors)
# ─────────────────────────────────────────────

@app.route("/api/status", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_status():
    dt_from, dt_to = parse_timeframe(request.args)
    with DB_LOCK, get_db() as conn:
        monitors = conn.execute("SELECT * FROM monitors ORDER BY id").fetchall()
        result = []
        for m in monitors:
            stats = build_monitor_stats(m["id"], dt_from, dt_to, conn)
            result.append({**dict(m), **stats})
    return jsonify(result)


# ─────────────────────────────────────────────
# API — Status Pages
# ─────────────────────────────────────────────

@app.route("/api/status-pages", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_list_status_pages():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute("SELECT * FROM status_pages ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/status-pages", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_create_status_page():
    d     = request.get_json()
    slug  = re.sub(r"[^a-z0-9\-]", "", d.get("slug","").lower().replace(" ","-"))
    title = d.get("title","").strip()
    desc  = d.get("description","")
    theme = d.get("theme","dark")
    css   = d.get("custom_css","")
    if not slug or not title:
        return jsonify({"error": "slug and title required"}), 400
    with DB_LOCK, get_db() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO status_pages (slug,title,description,theme,custom_css) VALUES (?,?,?,?,?)",
                (slug, title, desc, theme, css)
            )
            row = conn.execute("SELECT * FROM status_pages WHERE id=?", (cur.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            return jsonify({"error": "slug already exists"}), 409
    return jsonify(dict(row)), 201


@app.route("/api/status-pages/<int:pid>", methods=["PUT"])
@role_required(['admin', 'viewer'])
def api_update_status_page(pid):
    d = request.get_json()
    fields, vals = [], []
    for col in ["title","description","theme","custom_css","show_tags"]:
        if col in d:
            fields.append(f"{col}=?")
            vals.append(d[col])
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    vals.append(pid)
    with DB_LOCK, get_db() as conn:
        conn.execute(f"UPDATE status_pages SET {','.join(fields)} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM status_pages WHERE id=?", (pid,)).fetchone()
    return jsonify(dict(row))


@app.route("/api/status-pages/<int:pid>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_delete_status_page(pid):
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM status_page_monitors WHERE page_id=?", (pid,))
        conn.execute("DELETE FROM status_pages WHERE id=?", (pid,))
    return jsonify({"deleted": pid})


@app.route("/api/status-pages/<int:pid>/monitors", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_page_monitors(pid):
    with DB_LOCK, get_db() as conn:
        rows = conn.execute(
            """SELECT m.* FROM monitors m
               JOIN status_page_monitors spm ON spm.monitor_id=m.id
               WHERE spm.page_id=? ORDER BY spm.sort_order""",
            (pid,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/status-pages/<int:pid>/monitors", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_page_add_monitor(pid):
    d   = request.get_json()
    mid = d.get("monitor_id")
    if not mid:
        return jsonify({"error": "monitor_id required"}), 400
    with DB_LOCK, get_db() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) FROM status_page_monitors WHERE page_id=?", (pid,)
        ).fetchone()[0]
        conn.execute(
            "INSERT OR IGNORE INTO status_page_monitors VALUES (?,?,?)",
            (pid, mid, max_order + 1)
        )
    return jsonify({"ok": True})


@app.route("/api/status-pages/<int:pid>/monitors/<int:mid>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_page_remove_monitor(pid, mid):
    with DB_LOCK, get_db() as conn:
        conn.execute(
            "DELETE FROM status_page_monitors WHERE page_id=? AND monitor_id=?",
            (pid, mid)
        )
    return jsonify({"ok": True})


@app.route("/api/status-pages/slug/<path:slug>", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_page_by_slug(slug):
    # Strip any trailing dots or slashes that browsers may append
    slug = slug.rstrip('./')
    dt_from, dt_to = parse_timeframe(request.args)
    with DB_LOCK, get_db() as conn:
        page = conn.execute(
            "SELECT * FROM status_pages WHERE slug=?", (slug,)
        ).fetchone()
        if not page:
            return jsonify({"error": "not found"}), 404
        monitors = conn.execute(
            """SELECT m.* FROM monitors m
               JOIN status_page_monitors spm ON spm.monitor_id=m.id
               WHERE spm.page_id=? ORDER BY spm.sort_order""",
            (page["id"],)
        ).fetchall()
        result = []
        for m in monitors:
            stats = build_monitor_stats(m["id"], dt_from, dt_to, conn)
            result.append({**dict(m), **stats})
    return jsonify({"page": dict(page), "monitors": result})


# ─────────────────────────────────────────────
# API — Settings
# ─────────────────────────────────────────────

@app.route("/api/settings", methods=["GET"])
@role_required(['admin'])
def api_get_settings():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return jsonify({r["key"]: r["value"] for r in rows})


@app.route("/api/settings", methods=["POST"])
@role_required(['admin'])
def api_save_settings():
    d = request.get_json()
    with DB_LOCK, get_db() as conn:
        for k, v in d.items():
            conn.execute(
                "INSERT INTO settings (key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v))
            )
    return jsonify({"ok": True})


@app.route("/api/settings/test-email", methods=["POST"])
@role_required(['admin'])
def api_test_email():
    d         = request.get_json()
    smtp_host = d.get("smtp_host","")
    smtp_port = int(d.get("smtp_port", 25))
    smtp_from = d.get("smtp_from","")
    smtp_to   = d.get("smtp_to","")
    # Support multiple recipients separated by commas
    recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]
    try:
        msg = MIMEText("This is a test email from Uptime Monitor.")
        msg["Subject"] = "[Uptime Monitor] Test Email"
        msg["From"]    = smtp_from
        msg["To"]      = ", ".join(recipients)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(smtp_from, recipients, msg.as_string())
        return jsonify({"ok": True, "message": "Test email sent successfully."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ─────────────────────────────────────────────
# API — SSL Certificates
# ─────────────────────────────────────────────

@app.route("/api/ssl", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_ssl_status():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute(
            """SELECT s.*, m.name, m.url FROM ssl_checks s
               JOIN monitors m ON m.id = s.monitor_id
               ORDER BY s.days_left ASC"""
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/ssl/refresh", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_ssl_refresh():
    def run():
        from urllib.parse import urlparse
        with DB_LOCK, get_db() as conn:
            monitors = conn.execute(
                "SELECT id, name, url FROM monitors WHERE enabled=1 AND url LIKE 'https://%'"
            ).fetchall()
            monitors = [dict(m) for m in monitors]
        for m in monitors:
            try:
                parsed   = urlparse(m["url"])
                hostname = parsed.hostname
                port     = parsed.port or 443
                if not hostname:
                    continue
                days_left, expiry_date, issuer = check_ssl(hostname, port)
                now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                with DB_LOCK, get_db() as conn:
                    conn.execute(
                        """INSERT INTO ssl_checks (monitor_id, days_left, expiry_date, issuer, last_checked)
                           VALUES (?,?,?,?,?)
                           ON CONFLICT(monitor_id) DO UPDATE SET
                           days_left=excluded.days_left, expiry_date=excluded.expiry_date,
                           issuer=excluded.issuer, last_checked=excluded.last_checked""",
                        (m["id"], days_left, expiry_date, issuer, now_str)
                    )
            except Exception as e:
                print(f"[SSL] Refresh error {m['name']}: {e}")
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"ok": True, "message": "SSL refresh started."})


# ─────────────────────────────────────────────
# API — Maintenance Windows
# ─────────────────────────────────────────────

@app.route("/api/maintenance", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_maintenance():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute(
            """SELECT mw.*, m.name as monitor_name FROM maintenance_windows mw
               LEFT JOIN monitors m ON m.id = mw.monitor_id
               ORDER BY mw.start_dt DESC"""
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/maintenance", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_create_maintenance():
    d             = request.get_json()
    title         = d.get("title","").strip()
    monitor_id    = d.get("monitor_id") or None
    start_dt      = d.get("start_dt","").strip()
    end_dt        = d.get("end_dt","").strip()
    repeat_weekly = int(d.get("repeat_weekly", 0))
    if not title or not start_dt or not end_dt:
        return jsonify({"error": "title, start_dt and end_dt required"}), 400
    with DB_LOCK, get_db() as conn:
        cur = conn.execute(
            "INSERT INTO maintenance_windows (monitor_id, title, start_dt, end_dt, repeat_weekly) VALUES (?,?,?,?,?)",
            (monitor_id, title, start_dt, end_dt, repeat_weekly)
        )
        row = conn.execute(
            """SELECT mw.*, m.name as monitor_name FROM maintenance_windows mw
               LEFT JOIN monitors m ON m.id = mw.monitor_id WHERE mw.id=?""",
            (cur.lastrowid,)
        ).fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/maintenance/<int:wid>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_delete_maintenance(wid):
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM maintenance_windows WHERE id=?", (wid,))
    return jsonify({"deleted": wid})


# ─────────────────────────────────────────────
# API — Weekly Report (manual trigger)
# ─────────────────────────────────────────────

@app.route("/api/reports/weekly/send", methods=["POST"])
@role_required(['admin'])
def api_send_weekly_report():
    try:
        threading.Thread(target=send_weekly_report, daemon=True).start()
        return jsonify({"ok": True, "message": "Weekly report is being sent."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ─────────────────────────────────────────────
# API — Topology & Dependencies
# ─────────────────────────────────────────────

@app.route("/api/topology", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_topology():
    """Return all monitors with their dependencies and current status."""
    with DB_LOCK, get_db() as conn:
        monitors = conn.execute("SELECT * FROM monitors ORDER BY id").fetchall()
        deps = conn.execute("SELECT * FROM dependencies ORDER BY id").fetchall()
        layout = conn.execute("SELECT * FROM topology_layout").fetchall()
    
    layout_map = {r["monitor_id"]: {"x": r["pos_x"], "y": r["pos_y"]} for r in layout}
    
    nodes = []
    for m in monitors:
        # Get current status
        with DB_LOCK, get_db() as conn:
            last = conn.execute(
                "SELECT status FROM heartbeats WHERE monitor_id=? ORDER BY checked_at DESC LIMIT 1",
                (m["id"],)
            ).fetchone()
        status = "pending"
        if not m["enabled"]:
            status = "paused"
        elif last:
            status = "up" if last["status"] == 1 else "down"
        
        pos = layout_map.get(m["id"], {"x": 0, "y": 0})
        nodes.append({
            "id": m["id"],
            "name": m["name"],
            "group": m["group_name"] or "General",
            "status": status,
            "x": pos["x"],
            "y": pos["y"]
        })
    
    edges = [{"id": d["id"], "from": d["monitor_id"], "to": d["depends_on"], "label": d["label"]} for d in deps]
    
    return jsonify({"nodes": nodes, "edges": edges})


@app.route("/api/topology/dependencies", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_list_dependencies():
    """List all dependencies with monitor names."""
    with DB_LOCK, get_db() as conn:
        rows = conn.execute("""
            SELECT d.id, d.monitor_id, d.depends_on, d.label,
                   m1.name as monitor_name, m2.name as depends_on_name
            FROM dependencies d
            JOIN monitors m1 ON m1.id = d.monitor_id
            JOIN monitors m2 ON m2.id = d.depends_on
            ORDER BY d.id
        """).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/topology/dependencies", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_add_dependency():
    """Add a dependency link: monitor_id depends on depends_on."""
    d = request.get_json()
    monitor_id = d.get("monitor_id")
    depends_on = d.get("depends_on")
    label = d.get("label", "")
    
    if not monitor_id or not depends_on:
        return jsonify({"error": "monitor_id and depends_on required"}), 400
    if monitor_id == depends_on:
        return jsonify({"error": "Cannot depend on itself"}), 400
    
    try:
        with DB_LOCK, get_db() as conn:
            cur = conn.execute(
                "INSERT INTO dependencies (monitor_id, depends_on, label) VALUES (?, ?, ?)",
                (monitor_id, depends_on, label)
            )
            row = conn.execute("SELECT * FROM dependencies WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify(dict(row)), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Dependency already exists"}), 409


@app.route("/api/topology/dependencies/<int:did>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_delete_dependency(did):
    """Delete a dependency link."""
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM dependencies WHERE id=?", (did,))
    return jsonify({"deleted": did})


@app.route("/api/topology/impact/<int:mid>", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_impact(mid):
    """Get impact analysis: what services depend on this one (directly or indirectly)."""
    with DB_LOCK, get_db() as conn:
        # Get all dependencies
        deps = conn.execute("SELECT monitor_id, depends_on FROM dependencies").fetchall()
        monitors = conn.execute("SELECT id, name FROM monitors").fetchall()
    
    # Build dependency graph (reverse: depends_on -> [monitor_ids])
    graph = {}
    for d in deps:
        if d["depends_on"] not in graph:
            graph[d["depends_on"]] = []
        graph[d["depends_on"]].append(d["monitor_id"])
    
    # BFS to find all impacted services
    impacted = set()
    queue = [mid]
    visited = set()
    
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        if current != mid:
            impacted.add(current)
        if current in graph:
            queue.extend(graph[current])
    
    # Get monitor names
    monitor_map = {m["id"]: m["name"] for m in monitors}
    result = [{"id": i, "name": monitor_map.get(i, "Unknown")} for i in impacted]
    
    return jsonify({"monitor_id": mid, "impacted": result})


@app.route("/api/topology/layout", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_save_layout():
    """Save node positions for topology map."""
    positions = request.get_json()  # [{monitor_id, x, y}, ...]
    if not isinstance(positions, list):
        return jsonify({"error": "Expected array of positions"}), 400
    
    with DB_LOCK, get_db() as conn:
        for pos in positions:
            mid = pos.get("monitor_id")
            x = pos.get("x", 0)
            y = pos.get("y", 0)
            if mid:
                conn.execute("""
                    INSERT INTO topology_layout (monitor_id, pos_x, pos_y)
                    VALUES (?, ?, ?)
                    ON CONFLICT(monitor_id) DO UPDATE SET pos_x=excluded.pos_x, pos_y=excluded.pos_y
                """, (mid, x, y))
    
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# API — Database Monitors
# ─────────────────────────────────────────────

@app.route("/api/db-monitors", methods=["GET"])
@role_required(['admin', 'dba'])
def api_get_db_monitors():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute("SELECT * FROM db_monitors ORDER BY group_name, name").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d.pop("password", None)  # never expose password
        # Get latest heartbeat
        with DB_LOCK, get_db() as conn:
            last = conn.execute(
                "SELECT * FROM db_heartbeats WHERE db_id=? ORDER BY checked_at DESC LIMIT 1",
                (d["id"],)
            ).fetchone()
        d["last_check"] = dict(last) if last else None
        result.append(d)
    return jsonify(result)


@app.route("/api/db-monitors", methods=["POST"])
@role_required(['admin', 'dba'])
def api_add_db_monitor():
    d = request.get_json()
    name     = d.get("name","").strip()
    db_type  = d.get("db_type","mssql")
    host     = d.get("host","").strip()
    port     = int(d.get("port", 1433 if db_type=="mssql" else 5432))
    database = d.get("database","").strip() or None
    username = d.get("username","").strip() or None
    password = d.get("password","") or None
    interval = int(d.get("interval", 60))
    notify   = int(d.get("notify_email", 0))
    desc     = d.get("description","")
    group    = d.get("group_name","").strip()
    if not name or not host:
        return jsonify({"error": "name and host required"}), 400
    with DB_LOCK, get_db() as conn:
        cur = conn.execute(
            """INSERT INTO db_monitors (name,db_type,host,port,database,username,password,
               interval,notify_email,description,group_name)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (name,db_type,host,port,database,username,password,interval,notify,desc,group)
        )
        db_id = cur.lastrowid
        row = conn.execute("SELECT * FROM db_monitors WHERE id=?", (db_id,)).fetchone()

        # Also create a mirror TCP monitor so it appears in Status Pages & Dashboard
        tcp_url = f"tcp://{host}:{port}"
        db_type_label = {"mssql":"SQL Server","postgres":"PostgreSQL"}.get(db_type,"Database")
        mirror_desc = f"[DB Monitor] {db_type_label} — {database or host}"
        conn.execute(
            """INSERT INTO monitors (name,url,type,interval,notify_email,description,group_name,tags)
               VALUES (?,?,?,?,?,?,?,?)""",
            (name, tcp_url, "tcp", interval, notify, mirror_desc, group, "database")
        )

    result = dict(row)
    result.pop("password", None)
    return jsonify(result), 201


@app.route("/api/db-monitors/<int:did>", methods=["PUT", "PATCH"])
@role_required(['admin', 'dba'])
def api_update_db_monitor(did):
    d = request.get_json()
    fields, vals = [], []
    for col in ["name","db_type","host","port","database","username","interval",
                "notify_email","description","group_name","enabled"]:
        if col in d:
            fields.append(f"{col}=?")
            vals.append(d[col])
    if "password" in d and d["password"]:
        fields.append("password=?")
        vals.append(d["password"])
    if "long_running_threshold_seconds" in d:
        val = d["long_running_threshold_seconds"]
        if val is not None:
            try:
                val = int(val)
                if val < 1 or val > 3600:
                    return jsonify({"error": "long_running_threshold_seconds must be between 1 and 3600"}), 400
            except (ValueError, TypeError):
                return jsonify({"error": "long_running_threshold_seconds must be an integer between 1 and 3600"}), 400
            fields.append("long_running_threshold=?")
            vals.append(val)
        else:
            # Allow setting to NULL (revert to global default)
            fields.append("long_running_threshold=?")
            vals.append(None)
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    vals.append(did)
    with DB_LOCK, get_db() as conn:
        conn.execute(f"UPDATE db_monitors SET {','.join(fields)} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM db_monitors WHERE id=?", (did,)).fetchone()
    result = dict(row)
    result.pop("password", None)
    return jsonify(result)


@app.route("/api/db-monitors/<int:did>", methods=["DELETE"])
@role_required(['admin', 'dba'])
def api_delete_db_monitor(did):
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM db_extended_metrics WHERE db_id=?", (did,))
        conn.execute("DELETE FROM db_heartbeats WHERE db_id=?", (did,))
        conn.execute("DELETE FROM db_monitors WHERE id=?", (did,))
    return jsonify({"deleted": did})


@app.route("/api/db-monitors/<int:did>/toggle", methods=["POST"])
@role_required(['admin', 'dba'])
def api_toggle_db_monitor(did):
    with DB_LOCK, get_db() as conn:
        row = conn.execute("SELECT enabled FROM db_monitors WHERE id=?", (did,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        new = 0 if row["enabled"] else 1
        conn.execute("UPDATE db_monitors SET enabled=? WHERE id=?", (new, did))
    return jsonify({"id": did, "enabled": bool(new)})


@app.route("/api/db-monitors/<int:did>/heartbeats", methods=["GET"])
@role_required(['admin', 'dba'])
def api_db_heartbeats(did):
    limit  = int(request.args.get("limit", 500))
    preset = request.args.get("preset", "24h")
    now    = datetime.utcnow()
    preset_map = {
        "1h": now - timedelta(hours=1), "3h": now - timedelta(hours=3),
        "6h": now - timedelta(hours=6), "9h": now - timedelta(hours=9),
        "24h": now - timedelta(hours=24), "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
    }
    dt_from = preset_map.get(preset, now - timedelta(hours=24))
    with DB_LOCK, get_db() as conn:
        rows = conn.execute(
            """SELECT status, latency_ms, connections, msg, checked_at
               FROM db_heartbeats WHERE db_id=?
               AND checked_at BETWEEN ? AND ?
               ORDER BY checked_at ASC LIMIT ?""",
            (did, dt_from.strftime("%Y-%m-%d %H:%M:%S"),
             now.strftime("%Y-%m-%d %H:%M:%S"), limit)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/db-monitors/<int:did>/stats", methods=["GET"])
@role_required(['admin', 'dba'])
def api_db_stats(did):
    preset = request.args.get("preset", "24h")
    now    = datetime.utcnow()
    preset_map = {
        "1h": now - timedelta(hours=1), "3h": now - timedelta(hours=3),
        "6h": now - timedelta(hours=6), "9h": now - timedelta(hours=9),
        "24h": now - timedelta(hours=24), "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
    }
    dt_from = preset_map.get(preset, now - timedelta(hours=24))
    with DB_LOCK, get_db() as conn:
        db = conn.execute("SELECT * FROM db_monitors WHERE id=?", (did,)).fetchone()
        if not db:
            return jsonify({"error": "not found"}), 404
        rows = conn.execute(
            """SELECT status, latency_ms, connections, checked_at
               FROM db_heartbeats WHERE db_id=?
               AND checked_at BETWEEN ? AND ?
               ORDER BY checked_at ASC""",
            (did, dt_from.strftime("%Y-%m-%d %H:%M:%S"),
             now.strftime("%Y-%m-%d %H:%M:%S"))
        ).fetchall()
        last = conn.execute(
            "SELECT * FROM db_heartbeats WHERE db_id=? ORDER BY checked_at DESC LIMIT 1",
            (did,)
        ).fetchone()

    total   = len(rows)
    up      = sum(1 for r in rows if r["status"] == 1)
    uptime  = round(up / total * 100, 2) if total else None
    lats    = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    avg_lat = round(sum(lats) / len(lats)) if lats else None
    conns   = [r["connections"] for r in rows if r["connections"] is not None]
    avg_conn = round(sum(conns) / len(conns), 1) if conns else None
    max_conn = max(conns) if conns else None

    result = dict(db)
    result.pop("password", None)
    result.update({
        "uptime_pct":   uptime,
        "avg_latency":  avg_lat,
        "total_checks": total,
        "avg_connections": avg_conn,
        "max_connections": max_conn,
        "last_check":   dict(last) if last else None,
    })
    return jsonify(result)


@app.route("/api/db-monitors/<int:did>/extended-metrics", methods=["GET"])
@role_required(['admin', 'dba'])
def api_get_extended_metrics(did):
    with DB_LOCK, get_db() as conn:
        db = conn.execute("SELECT * FROM db_monitors WHERE id=?", (did,)).fetchone()
        if not db:
            return jsonify({"error": "Monitor not found"}), 404

        # Resolve long_running_threshold: per-monitor > global > default 5
        threshold = db["long_running_threshold"]
        if threshold is None:
            global_row = conn.execute("SELECT value FROM settings WHERE key='long_running_threshold'").fetchone()
            threshold = int(global_row["value"]) if global_row else 5

        # If no credentials configured, return message with null values
        if not db["username"]:
            return jsonify({
                "message": "Extended metrics require database credentials (username and password)",
                "active_requests": None,
                "running_queries": None,
                "databases_list": None,
                "blocking_queries": None,
                "long_running_threshold_seconds": threshold
            })

        # Query the most recent extended metrics record
        row = conn.execute(
            """SELECT active_requests, running_queries, databases_list, blocking_queries, collected_at
               FROM db_extended_metrics WHERE db_id=?
               ORDER BY collected_at DESC LIMIT 1""",
            (did,)
        ).fetchone()

        if not row:
            return jsonify({
                "message": "No extended metrics data available yet",
                "active_requests": None,
                "running_queries": None,
                "databases_list": None,
                "blocking_queries": None,
                "long_running_threshold_seconds": threshold
            })

        return jsonify({
            "active_requests": row["active_requests"],
            "running_queries": json.loads(row["running_queries"]) if row["running_queries"] else None,
            "databases_list": json.loads(row["databases_list"]) if row["databases_list"] else None,
            "blocking_queries": json.loads(row["blocking_queries"]) if row["blocking_queries"] else None,
            "long_running_threshold_seconds": threshold,
            "collected_at": row["collected_at"]
        })


# ─────────────────────────────────────────────
# API — Server Inventory
# ─────────────────────────────────────────────

def _build_patch_info(server_id, last_patched, conn):
    """Build the patch_info dict for a server from the most recent agent_metrics row."""
    row = conn.execute(
        "SELECT pending_updates, reboot_required, patch_status, collected_at "
        "FROM agent_metrics WHERE server_id=? ORDER BY collected_at DESC LIMIT 1",
        (server_id,)
    ).fetchone()

    if row:
        status = row["patch_status"]
        if status is None and last_patched:
            status = "up_to_date"
        return {
            "pending_updates": row["pending_updates"],
            "reboot_required": bool(row["reboot_required"]) if row["reboot_required"] is not None else None,
            "patch_status":    status,
            "last_patched":    last_patched,
            "collected_at":    row["collected_at"],
        }
    return {
        "pending_updates": None,
        "reboot_required": None,
        "patch_status":    "up_to_date" if last_patched else None,
        "last_patched":    last_patched,
        "collected_at":    None,
    }


def _server_with_health(server, conn):
    """Enrich a server dict with live health from linked monitors."""
    sid = server["id"]

    # Get linked monitors
    mons = conn.execute("""
        SELECT m.id, m.name, m.url, m.enabled, m.group_name
        FROM monitors m
        JOIN server_monitors sm ON sm.monitor_id = m.id
        WHERE sm.server_id = ?
        ORDER BY m.name
    """, (sid,)).fetchall()

    # Get linked DB monitors
    dbs = conn.execute("""
        SELECT d.id, d.name, d.db_type, d.host, d.port, d.enabled
        FROM db_monitors d
        JOIN server_db_monitors sdm ON sdm.db_id = d.id
        WHERE sdm.server_id = ?
        ORDER BY d.name
    """, (sid,)).fetchall()

    monitor_list = []
    for m in mons:
        last = conn.execute(
            "SELECT status, latency_ms, msg, checked_at FROM heartbeats WHERE monitor_id=? ORDER BY checked_at DESC LIMIT 1",
            (m["id"],)
        ).fetchone()
        status = "pending"
        if not m["enabled"]:   status = "paused"
        elif last:             status = "up" if last["status"] == 1 else "down"
        monitor_list.append({
            "id": m["id"], "name": m["name"], "url": m["url"],
            "type": "monitor", "status": status,
            "group_name": m["group_name"],
            "latency_ms": last["latency_ms"] if last else None,
            "msg": last["msg"] if last else None,
            "checked_at": last["checked_at"] if last else None,
        })

    for d in dbs:
        last = conn.execute(
            "SELECT status, latency_ms, connections, msg, checked_at FROM db_heartbeats WHERE db_id=? ORDER BY checked_at DESC LIMIT 1",
            (d["id"],)
        ).fetchone()
        status = "pending"
        if not d["enabled"]:   status = "paused"
        elif last:             status = "up" if last["status"] == 1 else "down"
        monitor_list.append({
            "id": d["id"], "name": d["name"],
            "url": f"{d['host']}:{d['port']}",
            "type": "database", "db_type": d["db_type"],
            "status": status,
            "latency_ms": last["latency_ms"] if last else None,
            "connections": last["connections"] if last else None,
            "msg": last["msg"] if last else None,
            "checked_at": last["checked_at"] if last else None,
        })

    # Aggregate health
    enabled = [m for m in monitor_list if m["status"] != "paused"]
    down    = [m for m in enabled if m["status"] == "down"]
    up      = [m for m in enabled if m["status"] == "up"]

    if not enabled:
        health = "unknown"
    elif down:
        health = "critical" if len(down) > len(enabled) / 2 else "degraded"
    elif any(m["status"] == "pending" for m in enabled):
        health = "pending"
    else:
        health = "healthy"

    result = dict(server)
    result["monitors"]     = monitor_list
    result["health"]       = health
    result["total_monitors"] = len(monitor_list)
    result["up_count"]     = len(up)
    result["down_count"]   = len(down)
    result["patch_info"]   = _build_patch_info(sid, server.get("last_patched"), conn)
    return result


@app.route("/api/servers", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_servers():
    env_filter = request.args.get("environment")
    with DB_LOCK, get_db() as conn:
        if env_filter:
            rows = conn.execute(
                "SELECT * FROM servers WHERE environment=? ORDER BY environment, hostname",
                (env_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM servers ORDER BY environment, hostname"
            ).fetchall()
        result = [_server_with_health(dict(r), conn) for r in rows]
    return jsonify(result)


@app.route("/api/servers/<int:sid>", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_server(sid):
    with DB_LOCK, get_db() as conn:
        row = conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
        if not row:
            return jsonify({"error": "not found"}), 404
        result = _server_with_health(dict(row), conn)
    return jsonify(result)


@app.route("/api/servers", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_add_server():
    d = request.get_json()
    hostname    = d.get("hostname","").strip()
    ip_address  = d.get("ip_address","").strip() or None
    os_name     = d.get("os","").strip() or None
    environment = d.get("environment","PROD").strip()
    role        = d.get("role","").strip() or None
    cpu_cores   = d.get("cpu_cores") or None
    ram_gb      = d.get("ram_gb") or None
    disk_gb     = d.get("disk_gb") or None
    location    = d.get("location","").strip() or None
    last_patched = (d.get("last_patched") or "").strip() or None
    notes       = (d.get("notes") or "").strip() or None
    if not hostname:
        return jsonify({"error": "hostname required"}), 400
    with DB_LOCK, get_db() as conn:
        cur = conn.execute(
            """INSERT INTO servers (hostname,ip_address,os,environment,role,cpu_cores,ram_gb,disk_gb,location,last_patched,notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (hostname,ip_address,os_name,environment,role,cpu_cores,ram_gb,disk_gb,location,last_patched,notes)
        )
        row = conn.execute("SELECT * FROM servers WHERE id=?", (cur.lastrowid,)).fetchone()
        result = _server_with_health(dict(row), conn)
    return jsonify(result), 201


@app.route("/api/servers/<int:sid>", methods=["PUT"])
@role_required(['admin', 'viewer'])
def api_update_server(sid):
    d = request.get_json()
    fields, vals = [], []
    for col in ["hostname","ip_address","os","environment","role",
                "cpu_cores","ram_gb","disk_gb","location","last_patched","notes"]:
        if col in d:
            fields.append(f"{col}=?")
            vals.append(d[col] or None)
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    vals.append(sid)
    with DB_LOCK, get_db() as conn:
        conn.execute(f"UPDATE servers SET {','.join(fields)} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
        result = _server_with_health(dict(row), conn)
    return jsonify(result)


@app.route("/api/servers/<int:sid>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_delete_server(sid):
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM server_monitors WHERE server_id=?", (sid,))
        conn.execute("DELETE FROM server_db_monitors WHERE server_id=?", (sid,))
        conn.execute("DELETE FROM servers WHERE id=?", (sid,))
    return jsonify({"deleted": sid})


@app.route("/api/servers/<int:sid>/monitors", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_server_set_monitors(sid):
    """Set all monitors for a server (replaces existing)."""
    d           = request.get_json()
    monitor_ids = d.get("monitor_ids", [])
    db_ids      = d.get("db_ids", [])
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM server_monitors WHERE server_id=?", (sid,))
        conn.execute("DELETE FROM server_db_monitors WHERE server_id=?", (sid,))
        for mid in monitor_ids:
            conn.execute("INSERT OR IGNORE INTO server_monitors VALUES (?,?)", (sid, mid))
        for did in db_ids:
            conn.execute("INSERT OR IGNORE INTO server_db_monitors VALUES (?,?)", (sid, did))
        row = conn.execute("SELECT * FROM servers WHERE id=?", (sid,)).fetchone()
        result = _server_with_health(dict(row), conn)
    return jsonify(result)


# ─────────────────────────────────────────────
# API — Software Inventory
# ─────────────────────────────────────────────

@app.route("/api/software", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_software():
    server_id = request.args.get("server_id")
    with DB_LOCK, get_db() as conn:
        if server_id:
            rows = conn.execute(
                """SELECT sw.*, s.hostname, s.environment
                   FROM software_inventory sw
                   JOIN servers s ON s.id = sw.server_id
                   WHERE sw.server_id=?
                   ORDER BY sw.name""",
                (server_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT sw.*, s.hostname, s.environment
                   FROM software_inventory sw
                   JOIN servers s ON s.id = sw.server_id
                   ORDER BY s.environment, s.hostname, sw.name"""
            ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/software", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_add_software():
    d = request.get_json()
    server_id      = d.get("server_id")
    name           = (d.get("name") or "").strip()
    version        = (d.get("version") or "").strip() or None
    vendor         = (d.get("vendor") or "").strip() or None
    license_type   = (d.get("license_type") or "").strip() or None
    support_status = (d.get("support_status") or "").strip() or None
    risk_rating    = (d.get("risk_rating") or "").strip() or None
    install_path   = (d.get("install_path") or "").strip() or None
    discovered_by  = d.get("discovered_by", "manual")
    if not server_id or not name:
        return jsonify({"error": "server_id and name required"}), 400
    with DB_LOCK, get_db() as conn:
        cur = conn.execute(
            """INSERT INTO software_inventory
               (server_id, name, version, vendor, license_type, support_status, risk_rating, install_path, discovered_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (server_id, name, version, vendor, license_type, support_status, risk_rating, install_path, discovered_by)
        )
        row = conn.execute(
            """SELECT sw.*, s.hostname, s.environment
               FROM software_inventory sw JOIN servers s ON s.id=sw.server_id
               WHERE sw.id=?""",
            (cur.lastrowid,)
        ).fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/software/<int:swid>", methods=["PUT"])
@role_required(['admin', 'viewer'])
def api_update_software(swid):
    d = request.get_json()
    fields, vals = [], []
    for col in ["name", "version", "vendor", "license_type", "support_status",
                "risk_rating", "install_path", "discovered_by"]:
        if col in d:
            fields.append(f"{col}=?")
            vals.append(d[col] or None)
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    vals.append(swid)
    with DB_LOCK, get_db() as conn:
        conn.execute(f"UPDATE software_inventory SET {','.join(fields)} WHERE id=?", vals)
        row = conn.execute(
            """SELECT sw.*, s.hostname, s.environment
               FROM software_inventory sw JOIN servers s ON s.id=sw.server_id
               WHERE sw.id=?""",
            (swid,)
        ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


@app.route("/api/software/<int:swid>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_delete_software(swid):
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM software_inventory WHERE id=?", (swid,))
    return jsonify({"deleted": swid})


@app.route("/api/servers/<int:sid>/software", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_server_software(sid):
    with DB_LOCK, get_db() as conn:
        rows = conn.execute(
            """SELECT sw.*, s.hostname, s.environment
               FROM software_inventory sw
               JOIN servers s ON s.id = sw.server_id
               WHERE sw.server_id=?
               ORDER BY sw.name""",
            (sid,)
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/software/export-csv", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_export_software_csv():
    """Export software inventory as a downloadable CSV file."""
    import csv
    import io

    server_id = request.args.get("server_id")

    with DB_LOCK, get_db() as conn:
        if server_id:
            # Validate server exists
            srv = conn.execute("SELECT hostname FROM servers WHERE id=?", (server_id,)).fetchone()
            if not srv:
                return jsonify({"error": "Server not found"}), 404
            hostname = srv["hostname"]
            rows = conn.execute(
                """SELECT sw.name, sw.version, sw.vendor, sw.license_type,
                          sw.support_status, sw.risk_rating, sw.install_path,
                          sw.discovered_by, sw.created_at,
                          s.hostname, s.environment
                   FROM software_inventory sw
                   JOIN servers s ON s.id = sw.server_id
                   WHERE sw.server_id=?
                   ORDER BY s.environment, s.hostname, sw.name""",
                (server_id,)
            ).fetchall()
        else:
            hostname = None
            rows = conn.execute(
                """SELECT sw.name, sw.version, sw.vendor, sw.license_type,
                          sw.support_status, sw.risk_rating, sw.install_path,
                          sw.discovered_by, sw.created_at,
                          s.hostname, s.environment
                   FROM software_inventory sw
                   JOIN servers s ON s.id = sw.server_id
                   ORDER BY s.environment, s.hostname, sw.name"""
            ).fetchall()

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow([
        "Server Hostname", "Environment", "Software Name", "Version",
        "Vendor", "License Type", "Support Status", "Risk Rating",
        "Install Path", "Discovered By", "Created At"
    ])

    # Data rows
    for row in rows:
        writer.writerow([
            row["hostname"] or "",
            row["environment"] or "",
            row["name"] or "",
            row["version"] or "",
            row["vendor"] or "",
            row["license_type"] or "",
            row["support_status"] or "",
            row["risk_rating"] or "",
            row["install_path"] or "",
            row["discovered_by"] or "",
            row["created_at"] or "",
        ])

    # Build filename
    filename = _csv_export_filename(hostname)

    # Return CSV response
    response = app.response_class(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
    return response


def _csv_export_filename(hostname):
    """Generate a sanitized CSV export filename."""
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    if hostname:
        # Sanitize: replace non-alphanumeric (except - and _) with _
        sanitized = re.sub(r'[^a-zA-Z0-9\-_]', '_', hostname)
        return f"software-inventory_{sanitized}_{date_str}.csv"
    else:
        return f"software-inventory_all-servers_{date_str}.csv"


# ─────────────────────────────────────────────
# Software Catalogue — enrichment helper
# ─────────────────────────────────────────────

def _enrich_from_catalogue(sw_name, conn):
    """
    Look up sw_name against software_catalogue name_pattern (SQL LIKE).
    Returns dict with vendor/license_type/support_status/risk_rating or None.
    Patterns are matched case-insensitively, most specific (longest) match wins.
    """
    rows = conn.execute(
        """SELECT * FROM software_catalogue
           WHERE lower(?) LIKE lower(name_pattern)
           ORDER BY length(name_pattern) DESC
           LIMIT 1""",
        (sw_name,)
    ).fetchone()
    return dict(rows) if rows else None


def _apply_catalogue_to_server(server_id, conn):
    """
    For all agent-discovered software on a server that have blank
    license/support/risk fields, apply catalogue enrichment.
    """
    rows = conn.execute(
        """SELECT id, name FROM software_inventory
           WHERE server_id=? AND discovered_by='agent'
           AND (license_type IS NULL OR support_status IS NULL OR risk_rating IS NULL)""",
        (server_id,)
    ).fetchall()
    enriched = 0
    for row in rows:
        match = _enrich_from_catalogue(row["name"], conn)
        if match:
            conn.execute(
                """UPDATE software_inventory SET
                   vendor         = COALESCE(vendor, ?),
                   license_type   = COALESCE(license_type, ?),
                   support_status = COALESCE(support_status, ?),
                   risk_rating    = COALESCE(risk_rating, ?)
                   WHERE id=?""",
                (match.get("vendor"), match.get("license_type"),
                 match.get("support_status"), match.get("risk_rating"),
                 row["id"])
            )
            enriched += 1
    return enriched


# ─────────────────────────────────────────────
# API — Software Catalogue
# ─────────────────────────────────────────────

@app.route("/api/software-catalogue", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_catalogue():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM software_catalogue ORDER BY name_pattern"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/software-catalogue", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_add_catalogue():
    d = request.get_json()
    pattern        = (d.get("name_pattern") or "").strip()
    vendor         = (d.get("vendor") or "").strip() or None
    license_type   = (d.get("license_type") or "").strip() or None
    support_status = (d.get("support_status") or "Supported").strip()
    risk_rating    = (d.get("risk_rating") or "Low").strip()
    notes          = (d.get("notes") or "").strip() or None
    if not pattern:
        return jsonify({"error": "name_pattern required"}), 400
    with DB_LOCK, get_db() as conn:
        cur = conn.execute(
            """INSERT INTO software_catalogue
               (name_pattern, vendor, license_type, support_status, risk_rating, notes)
               VALUES (?,?,?,?,?,?)""",
            (pattern, vendor, license_type, support_status, risk_rating, notes)
        )
        row = conn.execute("SELECT * FROM software_catalogue WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify(dict(row)), 201


@app.route("/api/software-catalogue/<int:cid>", methods=["PUT"])
@role_required(['admin', 'viewer'])
def api_update_catalogue(cid):
    d = request.get_json()
    fields, vals = [], []
    for col in ["name_pattern", "vendor", "license_type", "support_status", "risk_rating", "notes"]:
        if col in d:
            fields.append(f"{col}=?")
            vals.append(d[col] or None)
    if not fields:
        return jsonify({"error": "nothing to update"}), 400
    vals.append(cid)
    with DB_LOCK, get_db() as conn:
        conn.execute(f"UPDATE software_catalogue SET {','.join(fields)} WHERE id=?", vals)
        row = conn.execute("SELECT * FROM software_catalogue WHERE id=?", (cid,)).fetchone()
    return jsonify(dict(row))


@app.route("/api/software-catalogue/<int:cid>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_delete_catalogue(cid):
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM software_catalogue WHERE id=?", (cid,))
    return jsonify({"deleted": cid})


@app.route("/api/software-catalogue/apply", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_apply_catalogue():
    """Apply catalogue enrichment to all agent-discovered software with blank fields."""
    total_enriched = 0
    with DB_LOCK, get_db() as conn:
        servers = conn.execute("SELECT id FROM servers").fetchall()
        for srv in servers:
            total_enriched += _apply_catalogue_to_server(srv["id"], conn)
    return jsonify({"ok": True, "enriched": total_enriched})

# ─────────────────────────────────────────────
# API — Agent (token-authenticated, no login)
# ─────────────────────────────────────────────

ENV_THRESHOLDS = {
    "PROD": {"cpu_warn": 70, "cpu_crit": 90, "ram_warn": 80, "ram_crit": 90, "disk_warn": 70, "disk_crit": 85},
    "UAT":  {"cpu_warn": 80, "cpu_crit": 95, "ram_warn": 85, "ram_crit": 95, "disk_warn": 80, "disk_crit": 90},
    "DEV":  {"cpu_warn": 85, "cpu_crit": 95, "ram_warn": 85, "ram_crit": 95, "disk_warn": 85, "disk_crit": 95},
}

_last_alert_sent = {}  # (server_id, metric) -> timestamp — rate limit alerts to once per day

def _check_agent_thresholds(server_id, metrics):
    """Check if agent metrics breach thresholds and send email alerts."""
    with DB_LOCK, get_db() as conn:
        srv = conn.execute("SELECT hostname, environment FROM servers WHERE id=?", (server_id,)).fetchone()
    if not srv:
        return

    hostname = srv["hostname"]
    env      = srv["environment"] or "PROD"
    t        = ENV_THRESHOLDS.get(env, ENV_THRESHOLDS["PROD"])
    now      = time.time()
    alerts   = []

    # Rate limit: once per 24 hours per metric per server
    ALERT_COOLDOWN = 86400

    # Check DB for persisted last-sent times (survives restarts)
    def _get_last_sent(key):
        cached = _last_alert_sent.get(key, 0)
        if cached > 0:
            return cached
        # Check DB
        db_key = f"threshold_alert_{key[0]}_{key[1]}"
        try:
            with DB_LOCK, get_db() as conn:
                row = conn.execute("SELECT value FROM settings WHERE key=?", (db_key,)).fetchone()
            if row:
                last_time = datetime.strptime(row["value"], "%Y-%m-%d %H:%M:%S")
                elapsed = (datetime.utcnow() - last_time).total_seconds()
                ts = now - (ALERT_COOLDOWN - elapsed) if elapsed < ALERT_COOLDOWN else 0
                _last_alert_sent[key] = ts
                return ts
        except Exception:
            pass
        return 0

    def _record_alert_sent(key):
        _last_alert_sent[key] = now
        db_key = f"threshold_alert_{key[0]}_{key[1]}"
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with DB_LOCK, get_db() as conn:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (db_key, now_str)
                )
        except Exception:
            pass

    # CPU
    cpu_pct = metrics.get("cpu_pct")
    if cpu_pct and cpu_pct >= t["cpu_crit"]:
        key = (server_id, "cpu_crit")
        if now - _get_last_sent(key) > ALERT_COOLDOWN:
            alerts.append(f"CPU CRITICAL: {cpu_pct}% (threshold {t['cpu_crit']}%)")
            _record_alert_sent(key)
    elif cpu_pct and cpu_pct >= t["cpu_warn"]:
        key = (server_id, "cpu_warn")
        if now - _get_last_sent(key) > ALERT_COOLDOWN:
            alerts.append(f"CPU WARNING: {cpu_pct}% (threshold {t['cpu_warn']}%)")
            _record_alert_sent(key)

    # RAM
    ram_pct = metrics.get("ram_pct")
    if ram_pct and ram_pct >= t["ram_crit"]:
        key = (server_id, "ram_crit")
        if now - _get_last_sent(key) > ALERT_COOLDOWN:
            alerts.append(f"RAM CRITICAL: {ram_pct}% (threshold {t['ram_crit']}%)")
            _record_alert_sent(key)
    elif ram_pct and ram_pct >= t["ram_warn"]:
        key = (server_id, "ram_warn")
        if now - _get_last_sent(key) > ALERT_COOLDOWN:
            alerts.append(f"RAM WARNING: {ram_pct}% (threshold {t['ram_warn']}%)")
            _record_alert_sent(key)

    # Disk mounts
    disk_mounts = metrics.get("disk_mounts", [])
    if disk_mounts:
        for d in disk_mounts:
            mount = d.get("mount", "?")
            pct   = d.get("pct")
            if pct and pct >= t["disk_crit"]:
                key = (server_id, f"disk_crit_{mount}")
                if now - _get_last_sent(key) > ALERT_COOLDOWN:
                    alerts.append(f"DISK {mount} CRITICAL: {pct}% (threshold {t['disk_crit']}%)")
                    _record_alert_sent(key)
            elif pct and pct >= t["disk_warn"]:
                key = (server_id, f"disk_warn_{mount}")
                if now - _get_last_sent(key) > ALERT_COOLDOWN:
                    alerts.append(f"DISK {mount} WARNING: {pct}% (threshold {t['disk_warn']}%)")
                    _record_alert_sent(key)
    else:
        # Fallback to single disk_pct
        disk_pct = metrics.get("disk_pct")
        if disk_pct and disk_pct >= t["disk_crit"]:
            key = (server_id, "disk_crit")
            if now - _get_last_sent(key) > ALERT_COOLDOWN:
                alerts.append(f"DISK CRITICAL: {disk_pct}% (threshold {t['disk_crit']}%)")
                _record_alert_sent(key)
        elif disk_pct and disk_pct >= t["disk_warn"]:
            key = (server_id, "disk_warn")
            if now - _get_last_sent(key) > ALERT_COOLDOWN:
                alerts.append(f"DISK WARNING: {disk_pct}% (threshold {t['disk_warn']}%)")
                _record_alert_sent(key)

    # Send email if any alerts
    if alerts:
        smtp_host = get_setting("smtp_host", "")
        smtp_to   = get_setting("smtp_to_servers", "") or get_setting("smtp_to", "")
        if smtp_host and smtp_to:
            recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]
            try:
                body = f"Server: {hostname} ({env})\n\n" + "\n".join(f"⚠ {a}" for a in alerts)
                body += f"\n\nTime: {datetime.now()}\nDashboard: https://frm-rbautodev01:9443/"
                m = MIMEText(body)
                m["Subject"] = f"[CROIT Server Alert] {hostname} — {len(alerts)} alert{'s' if len(alerts)>1 else ''}"
                m["From"]    = get_setting("smtp_from", "")
                m["To"]      = ", ".join(recipients)
                smtp_port = int(get_setting("smtp_port", "25"))
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
                    s.sendmail(m["From"], recipients, m.as_string())
                print(f"[Server Alert] Email sent for {hostname}: {', '.join(alerts)}")
            except Exception as e:
                print(f"[Server Alert] Email failed for {hostname}: {e}")


def _check_service_alerts(server_id, process_services):
    """
    Alert on watched critical-process status transitions.

    For each watched service (watched_services table), compare the current status
    (from this heartbeat's process_services; "down" if the watched service is
    absent entirely) against the last recorded status in service_events. On a real
    transition we insert a service_events row (history is always complete) and send
    an email reusing the EXACT SMTP pattern/settings keys from _check_agent_thresholds.
    Email send respects a per-(server,service) 24h cooldown; the event row is not
    cooldown-gated. Never raises so the heartbeat is never broken.
    """
    try:
        if not isinstance(process_services, list):
            return

        with DB_LOCK, get_db() as conn:
            srv = conn.execute(
                "SELECT hostname, environment FROM servers WHERE id=?", (server_id,)
            ).fetchone()
            if not srv:
                return
            watched_rows = conn.execute(
                "SELECT service_name FROM watched_services WHERE server_id=?", (server_id,)
            ).fetchall()
        watched = [r["service_name"] for r in watched_rows]
        if not watched:
            return

        hostname = srv["hostname"]
        env      = srv["environment"] or "PROD"
        now      = time.time()
        ALERT_COOLDOWN = 86400  # once per 24h per (server, service)

        # Map current status/ports from this heartbeat
        current = {}
        for entry in process_services:
            if isinstance(entry, dict) and entry.get("name"):
                current[entry["name"]] = entry

        # Cooldown helpers (same settings-table mechanism as _check_agent_thresholds)
        def _get_last_sent(key):
            cached = _last_alert_sent.get(key, 0)
            if cached > 0:
                return cached
            db_key = f"threshold_alert_{key[0]}_{key[1]}"
            try:
                with DB_LOCK, get_db() as conn:
                    row = conn.execute("SELECT value FROM settings WHERE key=?", (db_key,)).fetchone()
                if row:
                    last_time = datetime.strptime(row["value"], "%Y-%m-%d %H:%M:%S")
                    elapsed = (datetime.utcnow() - last_time).total_seconds()
                    ts = now - (ALERT_COOLDOWN - elapsed) if elapsed < ALERT_COOLDOWN else 0
                    _last_alert_sent[key] = ts
                    return ts
            except Exception:
                pass
            return 0

        def _record_alert_sent(key):
            _last_alert_sent[key] = now
            db_key = f"threshold_alert_{key[0]}_{key[1]}"
            now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            try:
                with DB_LOCK, get_db() as conn:
                    conn.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (db_key, now_str)
                    )
            except Exception:
                pass

        def _send_email(subject, body):
            smtp_host = get_setting("smtp_host", "")
            smtp_to   = get_setting("smtp_to_servers", "") or get_setting("smtp_to", "")
            if not (smtp_host and smtp_to):
                return
            recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]
            try:
                m = MIMEText(body)
                m["Subject"] = subject
                m["From"]    = get_setting("smtp_from", "")
                m["To"]      = ", ".join(recipients)
                smtp_port = int(get_setting("smtp_port", "25"))
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
                    s.sendmail(m["From"], recipients, m.as_string())
                print(f"[Service Alert] Email sent for {hostname}: {subject}")
            except Exception as e:
                print(f"[Service Alert] Email failed for {hostname}: {e}")

        for name in watched:
            entry = current.get(name)
            cur_status = (entry.get("status") if entry else None) or "down"
            if cur_status not in ("running", "down"):
                cur_status = "down"
            ports_info = ""
            if entry:
                ports = entry.get("ports") or []
                ports_info = ",".join(str(p) for p in ports)

            with DB_LOCK, get_db() as conn:
                last_row = conn.execute(
                    "SELECT status FROM service_events WHERE server_id=? AND service_name=? ORDER BY id DESC LIMIT 1",
                    (server_id, name)
                ).fetchone()
            last_status = last_row["status"] if last_row else None

            # Transition running/none -> down
            if cur_status == "down" and last_status != "down":
                with DB_LOCK, get_db() as conn:
                    conn.execute(
                        "INSERT INTO service_events (server_id, service_name, status) VALUES (?,?,?)",
                        (server_id, name, "down")
                    )
                key = ("service", f"{server_id}_{name}")
                if now - _get_last_sent(key) > ALERT_COOLDOWN:
                    body = (
                        f"Server: {hostname} ({env})\n"
                        f"Service: {name}\n"
                        f"Status: DOWN\n"
                        f"Ports: {ports_info or '-'}\n\n"
                        f"Time: {datetime.now()}\nDashboard: https://frm-rbautodev01:9443/"
                    )
                    _send_email(f"[CROIT Service Alert] {hostname} — {name} DOWN", body)
                    _record_alert_sent(key)

            # Transition down -> running (recovery)
            elif cur_status == "running" and last_status == "down":
                with DB_LOCK, get_db() as conn:
                    conn.execute(
                        "INSERT INTO service_events (server_id, service_name, status) VALUES (?,?,?)",
                        (server_id, name, "running")
                    )
                key = ("service", f"{server_id}_{name}")
                if now - _get_last_sent(key) > ALERT_COOLDOWN:
                    body = (
                        f"Server: {hostname} ({env})\n"
                        f"Service: {name}\n"
                        f"Status: RECOVERED (running)\n"
                        f"Ports: {ports_info or '-'}\n\n"
                        f"Time: {datetime.now()}\nDashboard: https://frm-rbautodev01:9443/"
                    )
                    _send_email(f"[CROIT Service Alert] {hostname} — {name} RECOVERED", body)
                    _record_alert_sent(key)
            # else: status unchanged — no event, no email
    except Exception as e:
        print(f"[Service Alert] _check_service_alerts failed: {e}")


# ── Patch Alert ───────────────────────────────────────────────────────────────

_patch_alert_sent: dict = {}   # server_id -> epoch float of last critical alert
_eol_alert_sent:   dict = {}   # server_id -> epoch float of last EOL/high-risk software alert
_ver_alert_sent:   dict = {}   # server_id -> epoch float of last version-outdated alert


# ── Software Version Check Engine ────────────────────────────────────────────

def _parse_version(ver_str):
    """
    Parse a version string into a tuple of ints for comparison.
    Strips leading 'v', 'V', and common suffixes like '-lts', '-stable'.
    Returns None if unparseable.
    """
    if not ver_str:
        return None
    # Strip leading v/V and common suffixes
    clean = re.sub(r'^[vV]', '', str(ver_str).strip())
    clean = re.sub(r'[-_](lts|stable|release|final|ga|ce|ee).*$', '', clean, flags=re.IGNORECASE)
    # Extract numeric parts only
    parts = re.findall(r'\d+', clean)
    if not parts:
        return None
    try:
        return tuple(int(p) for p in parts[:4])
    except Exception:
        return None


def _is_outdated(installed, latest):
    """
    Returns True if installed version is older than latest.
    Returns False if equal or newer, or if either is unparseable.
    """
    iv = _parse_version(installed)
    lv = _parse_version(latest)
    if iv is None or lv is None:
        return False
    # Pad to same length
    max_len = max(len(iv), len(lv))
    iv = iv + (0,) * (max_len - len(iv))
    lv = lv + (0,) * (max_len - len(lv))
    return iv < lv


def _fetch_latest_version(tracker):
    """
    Fetch the latest version for a tracker entry.
    Returns version string or None on failure.
    """
    check_type   = tracker["check_type"]
    check_source = tracker["check_source"]
    regex_pat    = tracker["regex_pattern"]

    try:
        if check_type == "github_release":
            # Use GitHub API — add token via settings to raise rate limit from 60 to 5000/hr
            api_url = f"https://api.github.com/repos/{check_source}/releases/latest"
            gh_token = get_setting("github_token", "")
            headers  = {"Accept": "application/vnd.github+json", "User-Agent": "CROIT-Monitor/1.0"}
            if gh_token:
                headers["Authorization"] = f"Bearer {gh_token}"
            resp = requests.get(api_url, timeout=10, headers=headers)
            if resp.status_code == 200:
                tag = resp.json().get("tag_name", "")
                return re.sub(r'^[vV]', '', tag).strip() or None
            return None

        elif check_type == "jenkins_update_center":
            # Jenkins publishes latest LTS version as plain text
            resp = requests.get(check_source, timeout=10,
                                headers={"User-Agent": "CROIT-Monitor/1.0"})
            if resp.status_code == 200:
                return resp.text.strip() or None
            return None

        elif check_type == "url_regex":
            resp = requests.get(check_source, timeout=15,
                                headers={"User-Agent": "CROIT-Monitor/1.0"})
            if resp.status_code == 200 and regex_pat:
                m = re.search(regex_pat, resp.text)
                if m:
                    return m.group(1).strip()
            return None

    except Exception as e:
        print(f"[VerCheck] Failed to fetch latest for '{tracker['display_name']}': {e}",
              flush=True)
        return None


def _run_version_checks():
    """
    Fetch latest versions for all enabled trackers, then compare against
    every server's installed software and update findings table.
    """
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    with DB_LOCK, get_db() as conn:
        trackers = conn.execute(
            "SELECT * FROM software_version_tracker WHERE enabled=1"
        ).fetchall()

    for tracker in trackers:
        tid          = tracker["id"]
        name_match   = tracker["name_match"].lower()
        display_name = tracker["display_name"]

        latest_ver = _fetch_latest_version(tracker)
        if latest_ver:
            with DB_LOCK, get_db() as conn:
                conn.execute(
                    "UPDATE software_version_tracker SET latest_version=?, last_checked=? WHERE id=?",
                    (latest_ver, now_str, tid)
                )
            print(f"[VerCheck] {display_name}: latest={latest_ver}", flush=True)
        else:
            print(f"[VerCheck] {display_name}: could not fetch latest version", flush=True)
            # Still update last_checked so we don't hammer failed sources
            with DB_LOCK, get_db() as conn:
                conn.execute(
                    "UPDATE software_version_tracker SET last_checked=? WHERE id=?",
                    (now_str, tid)
                )
            continue

        # Small delay between API calls to avoid rate limiting
        time.sleep(1)

        # Find all installed instances matching this tracker
        with DB_LOCK, get_db() as conn:
            installed_rows = conn.execute(
                """SELECT si.server_id, si.name, si.version
                   FROM software_inventory si
                   WHERE LOWER(si.name) LIKE ?""",
                (f"%{name_match}%",)
            ).fetchall()

        for row in installed_rows:
            server_id     = row["server_id"]
            installed_ver = row["version"]
            sw_name       = row["name"]

            if not installed_ver:
                status = "unknown"
            elif _is_outdated(installed_ver, latest_ver):
                status = "outdated"
            else:
                status = "up_to_date"

            with DB_LOCK, get_db() as conn:
                existing = conn.execute(
                    "SELECT id, status, alerted FROM software_version_findings WHERE server_id=? AND tracker_id=?",
                    (server_id, tid)
                ).fetchone()
                if existing:
                    # Reset alerted flag if version changed (new outdated finding)
                    alerted = existing["alerted"]
                    if existing["status"] != status:
                        alerted = 0
                    conn.execute(
                        """UPDATE software_version_findings
                           SET sw_name=?, installed_ver=?, latest_ver=?, status=?, last_seen=?, alerted=?
                           WHERE id=?""",
                        (sw_name, installed_ver, latest_ver, status, now_str, alerted, existing["id"])
                    )
                else:
                    conn.execute(
                        """INSERT INTO software_version_findings
                           (server_id, tracker_id, sw_name, installed_ver, latest_ver, status, alerted, last_seen)
                           VALUES (?,?,?,?,?,?,0,?)""",
                        (server_id, tid, sw_name, installed_ver, latest_ver, status, now_str)
                    )


def _send_version_alert(server_id, hostname, outdated_list):
    """Send email alert for outdated software on a server."""
    smtp_host = get_setting("smtp_host", "")
    smtp_to   = get_setting("smtp_to_software", "") or get_setting("smtp_to", "")

    lines = [
        f"Server:  {hostname}",
        f"Time:    {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        f"📦 OUTDATED SOFTWARE DETECTED ({len(outdated_list)} package{'s' if len(outdated_list) > 1 else ''})",
        "-" * 60,
    ]
    for item in outdated_list:
        installed = item["installed_ver"] or "unknown"
        lines.append(f"  • {item['sw_name']}")
        lines.append(f"      Installed : {installed}")
        lines.append(f"      Latest    : {item['latest_ver']}")
        lines.append("")

    lines += [
        "Action required: update these packages to the latest versions.",
        "This helps address audit findings and reduces security exposure.",
        f"Dashboard: https://frm-rbautodev01:9443/",
    ]

    if not smtp_host or not smtp_to:
        print(f"[VerAlert] {hostname}: {len(outdated_list)} outdated package(s) — email not configured")
        return

    smtp_port  = int(get_setting("smtp_port", "25"))
    smtp_from  = get_setting("smtp_from", "")
    recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]
    subject    = f"[CROIT SW Update] {hostname} — {len(outdated_list)} outdated package{'s' if len(outdated_list) > 1 else ''}"

    try:
        m = MIMEText("\n".join(lines))
        m["Subject"] = subject
        m["From"]    = smtp_from
        m["To"]      = ", ".join(recipients)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(smtp_from, recipients, m.as_string())
        print(f"[VerAlert] Email sent for {hostname}: {len(outdated_list)} outdated package(s)")
    except Exception as e:
        print(f"[VerAlert] Email failed for {hostname}: {e}")


def _send_version_alerts():
    """
    After version checks run, find servers with unalerted outdated findings
    and send one consolidated email per server. Rate-limited to once per 24h.
    Persists last-sent time in the database to survive restarts.
    """
    now = time.time()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    with DB_LOCK, get_db() as conn:
        servers = conn.execute("SELECT id, hostname FROM servers").fetchall()

    for srv in servers:
        server_id = srv["id"]
        hostname  = srv["hostname"]

        # Check in-memory cache first
        last_sent = _ver_alert_sent.get(server_id, 0)
        if now - last_sent < 86400:
            continue

        # Also check database for persistence across restarts
        with DB_LOCK, get_db() as conn:
            last_alert_row = conn.execute(
                "SELECT value FROM settings WHERE key=?",
                (f"ver_alert_last_{server_id}",)
            ).fetchone()
        if last_alert_row:
            try:
                last_db_time = datetime.strptime(last_alert_row["value"], "%Y-%m-%d %H:%M:%S")
                elapsed = (datetime.utcnow() - last_db_time).total_seconds()
                if elapsed < 86400:
                    _ver_alert_sent[server_id] = now - (86400 - elapsed)
                    continue
            except (ValueError, TypeError):
                pass

        with DB_LOCK, get_db() as conn:
            outdated = conn.execute(
                """SELECT sw_name, installed_ver, latest_ver
                   FROM software_version_findings
                   WHERE server_id=? AND status='outdated'
                   ORDER BY sw_name""",
                (server_id,)
            ).fetchall()

        if not outdated:
            continue

        outdated_list = [dict(r) for r in outdated]
        _send_version_alert(server_id, hostname, outdated_list)
        _ver_alert_sent[server_id] = now

        # Persist last-sent time to DB so it survives restarts
        with DB_LOCK, get_db() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"ver_alert_last_{server_id}", now_str)
            )
            conn.execute(
                "UPDATE software_version_findings SET alerted=1 WHERE server_id=? AND status='outdated'",
                (server_id,)
            )


def version_check_loop():
    """
    Background thread: runs version checks every 6 hours.
    Staggers the first run by 2 minutes to let the app fully start.
    """
    time.sleep(120)  # wait 2 min after startup
    while True:
        try:
            print("[VerCheck] Starting software version check run...", flush=True)
            _run_version_checks()
            _send_version_alerts()
            print("[VerCheck] Version check run complete.", flush=True)
        except Exception as e:
            print(f"[VerCheck] ERROR in version_check_loop: {e}", flush=True)
        time.sleep(6 * 3600)  # run every 6 hours


def _send_patch_alert(server_id, payload):
    """Send (or log) a critical patch status alert for the given server."""
    with DB_LOCK, get_db() as conn:
        srv = conn.execute("SELECT hostname FROM servers WHERE id=?", (server_id,)).fetchone()
    hostname        = srv["hostname"] if srv else f"server-{server_id}"
    pending_updates = payload.get("pending_updates")
    timestamp       = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    smtp_host = get_setting("smtp_host", "")
    smtp_to   = get_setting("smtp_to_patches", "") or get_setting("smtp_to", "")

    if not smtp_host or not smtp_to:
        print(f"[Patch Alert] CRITICAL patch status for {hostname}: "
              f"{pending_updates} pending updates at {timestamp}")
        return

    smtp_port = int(get_setting("smtp_port", "25"))
    smtp_from = get_setting("smtp_from", "")
    recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]
    try:
        body = (
            f"Server: {hostname}\n"
            f"Patch Status: CRITICAL\n"
            f"Pending Updates: {pending_updates}\n"
            f"Transition Time: {timestamp}\n"
        )
        m = MIMEText(body)
        m["Subject"] = f"[Uptime Monitor] CRITICAL patch status on {hostname}"
        m["From"]    = smtp_from
        m["To"]      = ", ".join(recipients)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(smtp_from, recipients, m.as_string())
        print(f"[Patch Alert] Critical patch alert sent for {hostname}")
    except Exception as e:
        print(f"[Patch Alert] Email failed for {hostname}: {e}")


def _check_patch_alert(server_id, payload):
    """Check if a critical patch alert should be sent for this server."""
    new_status = payload.get("patch_status")

    if new_status != "critical":
        # Reset suppression timer on non-critical transition
        if server_id in _patch_alert_sent:
            del _patch_alert_sent[server_id]
        return

    # Fetch previous stored patch_status (the row before the one just inserted)
    with DB_LOCK, get_db() as conn:
        prev = conn.execute(
            "SELECT patch_status FROM agent_metrics WHERE server_id=? "
            "ORDER BY collected_at DESC LIMIT 1 OFFSET 1",
            (server_id,)
        ).fetchone()
    prev_status = prev["patch_status"] if prev else None

    if prev_status == "critical":
        # Already critical — check 24-hour suppression window
        last_sent = _patch_alert_sent.get(server_id, 0)
        if time.time() - last_sent < 86400:
            return   # suppress duplicate

    # Send alert and record time
    _send_patch_alert(server_id, payload)
    _patch_alert_sent[server_id] = time.time()


def _check_software_eol_alert(server_id):
    """
    After software inventory is refreshed, check for EOL or High/Critical risk
    packages and send a daily email alert if any are found.
    Suppressed to once per 24 hours per server to avoid inbox spam.
    """
    now = time.time()
    last_sent = _eol_alert_sent.get(server_id, 0)
    if now - last_sent < 86400:
        return  # already alerted within the last 24 hours

    with DB_LOCK, get_db() as conn:
        srv = conn.execute(
            "SELECT hostname, environment FROM servers WHERE id=?", (server_id,)
        ).fetchone()
        if not srv:
            return

        eol_packages = conn.execute(
            """SELECT name, version, vendor, risk_rating
               FROM software_inventory
               WHERE server_id=? AND support_status='End of Life'
               ORDER BY name""",
            (server_id,)
        ).fetchall()

        high_risk_packages = conn.execute(
            """SELECT name, version, vendor, risk_rating, support_status
               FROM software_inventory
               WHERE server_id=? AND risk_rating IN ('High','Critical')
                 AND (support_status IS NULL OR support_status != 'End of Life')
               ORDER BY risk_rating, name""",
            (server_id,)
        ).fetchall()

    if not eol_packages and not high_risk_packages:
        return  # nothing to alert on

    hostname = srv["hostname"]
    env      = srv["environment"] or "PROD"

    smtp_host = get_setting("smtp_host", "")
    smtp_to   = get_setting("smtp_to_software", "") or get_setting("smtp_to", "")
    if not smtp_host or not smtp_to:
        # Log to console if email not configured
        print(f"[SW Alert] {hostname}: {len(eol_packages)} EOL, "
              f"{len(high_risk_packages)} High/Critical risk packages detected")
        _eol_alert_sent[server_id] = now
        return

    smtp_port  = int(get_setting("smtp_port", "25"))
    smtp_from  = get_setting("smtp_from", "")
    recipients = [r.strip() for r in smtp_to.split(",") if r.strip()]

    # Build email body
    lines = [
        f"Server:      {hostname}",
        f"Environment: {env}",
        f"Time:        {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
    ]

    if eol_packages:
        lines.append(f"⛔ END-OF-LIFE SOFTWARE ({len(eol_packages)} package{'s' if len(eol_packages) > 1 else ''})")
        lines.append("-" * 60)
        for p in eol_packages:
            ver    = p["version"] or "unknown version"
            vendor = f" ({p['vendor']})" if p["vendor"] else ""
            lines.append(f"  • {p['name']} {ver}{vendor}")
        lines.append("")

    if high_risk_packages:
        lines.append(f"⚠ HIGH / CRITICAL RISK SOFTWARE ({len(high_risk_packages)} package{'s' if len(high_risk_packages) > 1 else ''})")
        lines.append("-" * 60)
        for p in high_risk_packages:
            ver    = p["version"] or "unknown version"
            vendor = f" ({p['vendor']})" if p["vendor"] else ""
            status = f" [{p['support_status']}]" if p["support_status"] else ""
            lines.append(f"  • [{p['risk_rating']}] {p['name']} {ver}{vendor}{status}")
        lines.append("")

    lines += [
        "Action required: review and update or replace these packages.",
        f"Dashboard: https://frm-rbautodev01:9443/",
    ]

    total   = len(eol_packages) + len(high_risk_packages)
    subject = (
        f"[CROIT SW Alert] {hostname} — "
        f"{len(eol_packages)} EOL, {len(high_risk_packages)} High/Critical risk"
    )

    try:
        m = MIMEText("\n".join(lines))
        m["Subject"] = subject
        m["From"]    = smtp_from
        m["To"]      = ", ".join(recipients)
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.sendmail(smtp_from, recipients, m.as_string())
        print(f"[SW Alert] Email sent for {hostname}: {total} software issue(s)")
        _eol_alert_sent[server_id] = now
    except Exception as e:
        print(f"[SW Alert] Email failed for {hostname}: {e}")


def _get_agent_server(token):
    """Validate agent token and return server_id, or None."""
    with DB_LOCK, get_db() as conn:
        row = conn.execute(
            "SELECT server_id FROM agent_tokens WHERE token=?", (token,)
        ).fetchone()
    return row["server_id"] if row else None


@app.route("/api/agent/heartbeat", methods=["POST"])
def api_agent_heartbeat():
    """Agent posts metrics here. Authenticated by Bearer token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Missing token"}), 401
    token     = auth[7:].strip()
    server_id = _get_agent_server(token)
    if not server_id:
        return jsonify({"error": "Invalid token"}), 401

    d = request.get_json()
    if not d:
        return jsonify({"error": "No data"}), 400

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Update last_seen
    with DB_LOCK, get_db() as conn:
        conn.execute(
            "UPDATE agent_tokens SET last_seen=? WHERE token=?", (now_str, token)
        )
        # Insert metrics
        conn.execute("""
            INSERT INTO agent_metrics
            (server_id, os_name, os_version, kernel, cpu_pct, cpu_cores, cpu_threads,
             ram_total_gb, ram_used_gb, ram_pct,
             disk_total_gb, disk_used_gb, disk_pct, disk_mounts,
             uptime_sec, load_1m, load_5m, load_15m, process_count,
             pending_updates, reboot_required, patch_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            server_id,
            d.get("os_name"),    d.get("os_version"), d.get("kernel"),
            d.get("cpu_pct"),    d.get("cpu_cores"),  d.get("cpu_threads"),
            d.get("ram_total_gb"), d.get("ram_used_gb"), d.get("ram_pct"),
            d.get("disk_total_gb"), d.get("disk_used_gb"), d.get("disk_pct"),
            json.dumps(d.get("disk_mounts", [])),
            d.get("uptime_sec"),
            d.get("load_1m"), d.get("load_5m"), d.get("load_15m"),
            d.get("process_count"),
            d.get("pending_updates"), d.get("reboot_required"), d.get("patch_status")
        ))
        # Auto-update server OS fields if provided
        if d.get("os_name") or d.get("os_version"):
            os_str = " ".join(filter(None, [d.get("os_name"), d.get("os_version")])).strip()
            if os_str:
                conn.execute("UPDATE servers SET os=? WHERE id=?", (os_str, server_id))

        # Keep only last 1440 rows per server (24h at 1min intervals)
        conn.execute("""
            DELETE FROM agent_metrics WHERE server_id=? AND id NOT IN (
                SELECT id FROM agent_metrics WHERE server_id=?
                ORDER BY collected_at DESC LIMIT 1440
            )
        """, (server_id, server_id))

    # Process installed_software from agent heartbeat
    installed_software = d.get("installed_software", [])

    # Store folder_sizes in latest metrics (as JSON in settings for simplicity)
    folder_sizes = d.get("folder_sizes", [])
    if folder_sizes and isinstance(folder_sizes, list):
        with DB_LOCK, get_db() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (f"folder_sizes_{server_id}", json.dumps(folder_sizes))
            )

    if installed_software:
        with DB_LOCK, get_db() as conn:
            # Remove previously agent-discovered software for this server
            conn.execute(
                "DELETE FROM software_inventory WHERE server_id=? AND discovered_by='agent'",
                (server_id,)
            )
            for sw in installed_software:
                sw_name = (sw.get("name") or "").strip()
                if not sw_name:
                    continue
                # Check catalogue for auto-enrichment
                match = _enrich_from_catalogue(sw_name, conn)
                conn.execute(
                    """INSERT INTO software_inventory
                       (server_id, name, version, vendor, license_type, support_status, risk_rating, install_path, discovered_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        server_id,
                        sw_name,
                        (sw.get("version") or "").strip() or None,
                        (sw.get("vendor") or match.get("vendor") if match else sw.get("vendor") or "").strip() or None,
                        sw.get("license_type") or (match.get("license_type") if match else None),
                        sw.get("support_status") or (match.get("support_status") if match else None),
                        sw.get("risk_rating") or (match.get("risk_rating") if match else None),
                        (sw.get("install_path") or "").strip() or None,
                        "agent",
                    )
                )

    # Process discovered_services from agent heartbeat
    discovered_services = d.get("discovered_services", {})
    if discovered_services and isinstance(discovered_services, dict):
        now_str_svc = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with DB_LOCK, get_db() as conn:
            # Clear previous discovered services for this server
            conn.execute("DELETE FROM server_services WHERE server_id=?", (server_id,))

            # Insert listening ports — ensure it's a list
            ports_data = discovered_services.get("listening_ports", [])
            if isinstance(ports_data, dict):
                ports_data = [ports_data] if ports_data.get("port") else []
            if not isinstance(ports_data, list):
                ports_data = []
            for svc in ports_data:
                if not isinstance(svc, dict) or not svc.get("port"):
                    continue
                conn.execute(
                    """INSERT INTO server_services
                       (server_id, category, name, port, protocol, address, pid, process, status, last_seen)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        server_id, "port",
                        svc.get("process") or f"port-{svc.get('port')}",
                        svc.get("port"),
                        svc.get("protocol", "tcp"),
                        svc.get("address"),
                        svc.get("pid"),
                        svc.get("process"),
                        svc.get("state", "LISTEN"),
                        now_str_svc,
                    )
                )

            # Insert systemd / windows services — ensure it's a list
            svc_data = discovered_services.get("systemd_services", [])
            if isinstance(svc_data, dict):
                svc_data = [svc_data] if svc_data.get("name") else []
            if not isinstance(svc_data, list):
                svc_data = []
            for svc in svc_data:
                if not isinstance(svc, dict) or not svc.get("name"):
                    continue
                conn.execute(
                    """INSERT INTO server_services
                       (server_id, category, name, status, description, service_type, last_seen)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        server_id, "service",
                        svc.get("name", ""),
                        svc.get("status"),
                        svc.get("description"),
                        svc.get("type", "systemd"),
                        now_str_svc,
                    )
                )

            # Insert containers — ensure it's a list
            ctr_data = discovered_services.get("containers", [])
            if isinstance(ctr_data, dict):
                ctr_data = [ctr_data] if ctr_data.get("name") else []
            if not isinstance(ctr_data, list):
                ctr_data = []
            for ctr in ctr_data:
                if not isinstance(ctr, dict) or not ctr.get("name"):
                    continue
                conn.execute(
                    """INSERT INTO server_services
                       (server_id, category, name, status, image, ports_info, container_id, service_type, last_seen)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        server_id, "container",
                        ctr.get("name", ""),
                        ctr.get("status"),
                        ctr.get("image"),
                        ctr.get("ports"),
                        ctr.get("container_id"),
                        ctr.get("type", "docker"),
                        now_str_svc,
                    )
                )

            # Insert critical process-pattern services — ensure it's a list
            proc_data = discovered_services.get("process_services", [])
            if isinstance(proc_data, dict):
                proc_data = [proc_data] if proc_data.get("name") else []
            if not isinstance(proc_data, list):
                proc_data = []
            for proc in proc_data:
                if not isinstance(proc, dict) or not proc.get("name"):
                    continue
                ports = proc.get("ports") or []
                if isinstance(ports, list):
                    ports_info = ",".join(str(p) for p in ports)
                else:
                    ports_info = str(ports)
                conn.execute(
                    """INSERT INTO server_services
                       (server_id, category, name, status, process, ports_info, service_type, last_seen)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        server_id, "process",
                        proc.get("name", ""),
                        proc.get("status"),
                        proc.get("pattern"),
                        ports_info,
                        "process",
                        now_str_svc,
                    )
                )

    # Check thresholds and send alerts if needed
    _check_agent_thresholds(server_id, d)
    # Check watched critical-process status transitions and alert on down/recovery
    _check_service_alerts(server_id, (discovered_services or {}).get("process_services", []))
    # Check patch status and send critical patch alert if needed
    _check_patch_alert(server_id, d)
    # Check for EOL / high-risk software and alert once per day
    if installed_software:
        _check_software_eol_alert(server_id)

    return jsonify({"ok": True, "server_id": server_id})


@app.route("/api/agent/metrics/<int:sid>", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_agent_metrics(sid):
    """Get latest metrics + history for a server."""
    limit  = int(request.args.get("limit", 60))
    with DB_LOCK, get_db() as conn:
        latest = conn.execute(
            "SELECT * FROM agent_metrics WHERE server_id=? ORDER BY collected_at DESC LIMIT 1",
            (sid,)
        ).fetchone()
        history = conn.execute(
            """SELECT cpu_pct, ram_pct, disk_pct, load_1m, collected_at
               FROM agent_metrics WHERE server_id=?
               ORDER BY collected_at DESC LIMIT ?""",
            (sid, limit)
        ).fetchall()
        token_row = conn.execute(
            "SELECT token, last_seen FROM agent_tokens WHERE server_id=?", (sid,)
        ).fetchone()

    latest_dict = None
    if latest:
        latest_dict = dict(latest)
        # Parse disk_mounts JSON string back to list
        if latest_dict.get("disk_mounts"):
            try:
                latest_dict["disk_mounts"] = json.loads(latest_dict["disk_mounts"])
            except Exception:
                latest_dict["disk_mounts"] = []

    return jsonify({
        "latest":    latest_dict,
        "history":   [dict(r) for r in reversed(history)],
        "token":     token_row["token"] if token_row else None,
        "last_seen": token_row["last_seen"] if token_row else None,
    })


@app.route("/api/servers/<int:sid>/services", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_server_services(sid):
    """Get discovered services for a server."""
    category = request.args.get("category")  # port, service, container, or None for all
    with DB_LOCK, get_db() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM server_services WHERE server_id=? AND category=? ORDER BY category, name",
                (sid, category)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM server_services WHERE server_id=? ORDER BY category, name",
                (sid,)
            ).fetchall()
    services = [dict(r) for r in rows]
    # Load the stable watched set and compute 'watched' for process-category rows.
    # (The 'watched' column on server_services is volatile — recomputed here from
    #  the watched_services table, which survives the heartbeat DELETE/reinsert.)
    with DB_LOCK, get_db() as conn:
        watched_rows = conn.execute(
            "SELECT service_name FROM watched_services WHERE server_id=?", (sid,)
        ).fetchall()
    watched_set = {r["service_name"] for r in watched_rows}
    for s in services:
        if s.get("category") == "process":
            s["watched"] = s["name"] in watched_set
        else:
            s["watched"] = False
    # Build summary counts
    summary = {
        "total":      len(services),
        "ports":      len([s for s in services if s["category"] == "port"]),
        "services":   len([s for s in services if s["category"] == "service"]),
        "containers": len([s for s in services if s["category"] == "container"]),
        "processes":  len([s for s in services if s["category"] == "process"]),
    }
    return jsonify({"services": services, "summary": summary})


@app.route("/api/servers/<int:sid>/services/watch", methods=["POST"])
@role_required(['admin'])
def api_server_service_watch(sid):
    """Arm/disarm alerting for a critical process service on this server."""
    body = request.get_json(silent=True) or {}
    name = (body.get("service_name") or "").strip()
    watched = bool(body.get("watched"))
    if not name:
        return jsonify({"error": "service_name is required"}), 400
    with DB_LOCK, get_db() as conn:
        if watched:
            conn.execute(
                "INSERT OR IGNORE INTO watched_services (server_id, service_name) VALUES (?,?)",
                (sid, name)
            )
        else:
            conn.execute(
                "DELETE FROM watched_services WHERE server_id=? AND service_name=?",
                (sid, name)
            )
    return jsonify({"ok": True, "service_name": name, "watched": watched})


@app.route("/api/servers/<int:sid>/service-events", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_server_service_events(sid):
    """Recent status transitions for critical process services on this server."""
    service_name = request.args.get("service_name")
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 500))
    with DB_LOCK, get_db() as conn:
        if service_name:
            rows = conn.execute(
                """SELECT id, service_name, status, changed_at FROM service_events
                   WHERE server_id=? AND service_name=? ORDER BY id DESC LIMIT ?""",
                (sid, service_name, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, service_name, status, changed_at FROM service_events
                   WHERE server_id=? ORDER BY id DESC LIMIT ?""",
                (sid, limit)
            ).fetchall()
    return jsonify({"events": [dict(r) for r in rows]})


@app.route("/api/servers/<int:sid>/folder-sizes", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_server_folder_sizes(sid):
    """Get folder size breakdown for a server."""
    with DB_LOCK, get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?",
            (f"folder_sizes_{sid}",)
        ).fetchone()
    if not row:
        return jsonify({"folders": []})
    try:
        folders = json.loads(row["value"])
        # Sort by size descending
        folders.sort(key=lambda f: f.get("size_gb", 0), reverse=True)
        return jsonify({"folders": folders})
    except (json.JSONDecodeError, TypeError):
        return jsonify({"folders": []})


@app.route("/api/agent/token/<int:sid>", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_generate_agent_token(sid):
    """Generate or regenerate agent token for a server."""
    with DB_LOCK, get_db() as conn:
        srv = conn.execute("SELECT id FROM servers WHERE id=?", (sid,)).fetchone()
        if not srv:
            return jsonify({"error": "Server not found"}), 404
        token = secrets.token_hex(32)
        conn.execute("""
            INSERT INTO agent_tokens (server_id, token)
            VALUES (?, ?)
            ON CONFLICT(server_id) DO UPDATE SET token=excluded.token, last_seen=NULL
        """, (sid, token))
    return jsonify({"token": token, "server_id": sid})


@app.route("/api/agent/token/<int:sid>", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_agent_token(sid):
    """Get existing agent token for a server."""
    with DB_LOCK, get_db() as conn:
        row = conn.execute(
            "SELECT token, last_seen FROM agent_tokens WHERE server_id=?", (sid,)
        ).fetchone()
    if not row:
        return jsonify({"token": None, "last_seen": None})
    return jsonify({"token": row["token"], "last_seen": row["last_seen"]})


# ─────────────────────────────────────────────
# Public DB Status Page API (no login required)
# ─────────────────────────────────────────────

@app.route("/api/db-status/public", methods=["GET"])
def api_db_status_public():
    """Public endpoint — returns DB health summary without credentials."""
    with DB_LOCK, get_db() as conn:
        dbs = conn.execute(
            "SELECT id, name, db_type, host, port, database, group_name, enabled FROM db_monitors ORDER BY group_name, name"
        ).fetchall()
    result = []
    for db in dbs:
        d = dict(db)
        with DB_LOCK, get_db() as conn:
            last = conn.execute(
                "SELECT status, latency_ms, connections, msg, checked_at FROM db_heartbeats WHERE db_id=? ORDER BY checked_at DESC LIMIT 1",
                (d["id"],)
            ).fetchone()
            # 24h uptime
            from_str = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
            rows = conn.execute(
                "SELECT status FROM db_heartbeats WHERE db_id=? AND checked_at >= ?",
                (d["id"], from_str)
            ).fetchall()
        total = len(rows)
        up    = sum(1 for r in rows if r["status"] == 1)
        d["uptime_24h"] = round(up / total * 100, 2) if total else None
        d["last_check"] = dict(last) if last else None
        result.append(d)
    return jsonify(result)


# ─────────────────────────────────────────────
# Software Version Tracker API
# ─────────────────────────────────────────────

@app.route("/api/version-tracker", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_version_trackers():
    with DB_LOCK, get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM software_version_tracker ORDER BY display_name"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/version-tracker", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_add_version_tracker():
    d = request.get_json() or {}
    required = ("name_match", "display_name", "check_type", "check_source")
    if not all(d.get(k, "").strip() for k in required):
        return jsonify({"error": "name_match, display_name, check_type and check_source are required"}), 400
    with DB_LOCK, get_db() as conn:
        conn.execute(
            """INSERT INTO software_version_tracker
               (name_match, display_name, check_type, check_source, regex_pattern, enabled, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (d["name_match"].strip(), d["display_name"].strip(),
             d["check_type"].strip(), d["check_source"].strip(),
             d.get("regex_pattern", "").strip() or None,
             1 if d.get("enabled", True) else 0,
             d.get("notes", "").strip() or None)
        )
    return jsonify({"ok": True}), 201


@app.route("/api/version-tracker/<int:tid>", methods=["PUT"])
@role_required(['admin', 'viewer'])
def api_update_version_tracker(tid):
    d = request.get_json() or {}
    with DB_LOCK, get_db() as conn:
        row = conn.execute("SELECT id FROM software_version_tracker WHERE id=?", (tid,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        conn.execute(
            """UPDATE software_version_tracker
               SET name_match=?, display_name=?, check_type=?, check_source=?,
                   regex_pattern=?, enabled=?, notes=?
               WHERE id=?""",
            (d.get("name_match", "").strip(),
             d.get("display_name", "").strip(),
             d.get("check_type", "").strip(),
             d.get("check_source", "").strip(),
             d.get("regex_pattern", "").strip() or None,
             1 if d.get("enabled", True) else 0,
             d.get("notes", "").strip() or None,
             tid)
        )
    return jsonify({"ok": True})


@app.route("/api/version-tracker/<int:tid>", methods=["DELETE"])
@role_required(['admin', 'viewer'])
def api_delete_version_tracker(tid):
    with DB_LOCK, get_db() as conn:
        conn.execute("DELETE FROM software_version_findings WHERE tracker_id=?", (tid,))
        conn.execute("DELETE FROM software_version_tracker WHERE id=?", (tid,))
    return jsonify({"ok": True})


@app.route("/api/version-tracker/run", methods=["POST"])
@role_required(['admin', 'viewer'])
def api_run_version_checks():
    """Trigger an immediate version check run (runs in background thread)."""
    def _run():
        try:
            _run_version_checks()
            _send_version_alerts()
        except Exception as e:
            print(f"[VerCheck] Manual run error: {e}", flush=True)
    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Version check started in background"})


@app.route("/api/version-findings", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_get_version_findings():
    server_id = request.args.get("server_id")
    status    = request.args.get("status")
    with DB_LOCK, get_db() as conn:
        query  = """
            SELECT f.*, s.hostname, s.environment, t.display_name, t.check_type
            FROM software_version_findings f
            JOIN servers s ON s.id = f.server_id
            JOIN software_version_tracker t ON t.id = f.tracker_id
            WHERE 1=1
        """
        params = []
        if server_id:
            query += " AND f.server_id=?"
            params.append(server_id)
        if status:
            query += " AND f.status=?"
            params.append(status)
        query += " ORDER BY f.status DESC, s.hostname, f.sw_name"
        rows = conn.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/version-findings/summary", methods=["GET"])
@role_required(['admin', 'viewer'])
def api_version_findings_summary():
    with DB_LOCK, get_db() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM software_version_findings").fetchone()[0]
        outdated = conn.execute("SELECT COUNT(*) FROM software_version_findings WHERE status='outdated'").fetchone()[0]
        unknown  = conn.execute("SELECT COUNT(*) FROM software_version_findings WHERE status='unknown'").fetchone()[0]
        up2date  = conn.execute("SELECT COUNT(*) FROM software_version_findings WHERE status='up_to_date'").fetchone()[0]
        servers_affected = conn.execute(
            "SELECT COUNT(DISTINCT server_id) FROM software_version_findings WHERE status='outdated'"
        ).fetchone()[0]
    return jsonify({
        "total": total, "outdated": outdated,
        "up_to_date": up2date, "unknown": unknown,
        "servers_affected": servers_affected,
    })


# ─────────────────────────────────────────────
# Serve logo
# ─────────────────────────────────────────────

@app.route("/logo/<filename>")
def serve_logo(filename):
    logo_dir = os.path.join(app.root_path, "logo")
    # Support both png and avif
    return send_from_directory(logo_dir, filename)


# ─────────────────────────────────────────────
# API — Export / Import (Disaster Recovery)
# ─────────────────────────────────────────────

EXPORT_FORMAT_VERSION = "1.0"
SUPPORTED_FORMAT_VERSIONS = ["1.0"]
MAX_IMPORT_SIZE = 50 * 1024 * 1024  # 50 MB

@app.route("/api/export", methods=["GET"])
@role_required(['admin'])
def api_export():
    """Export all configuration data as a JSON backup file."""
    try:
        with DB_LOCK, get_db() as conn:
            # Monitors
            monitors = [dict(r) for r in conn.execute(
                "SELECT name, url, type, interval, retries, timeout, keyword, accepted_codes, enabled, notify_email, description, tags, group_name, request_body, request_headers FROM monitors"
            ).fetchall()]

            # DB Monitors (include password for full recovery)
            db_monitors = [dict(r) for r in conn.execute(
                "SELECT name, db_type, host, port, database, username, password, interval, enabled, notify_email, description, group_name, long_running_threshold FROM db_monitors"
            ).fetchall()]

            # Status pages with monitor assignments
            pages = [dict(r) for r in conn.execute(
                "SELECT id, slug, title, description, theme, show_tags, custom_css FROM status_pages"
            ).fetchall()]
            status_pages = []
            for p in pages:
                page_monitors = [dict(r) for r in conn.execute(
                    """SELECT m.name AS monitor_name, m.url AS monitor_url, spm.sort_order
                       FROM status_page_monitors spm
                       JOIN monitors m ON m.id = spm.monitor_id
                       WHERE spm.page_id = ?
                       ORDER BY spm.sort_order""", (p["id"],)
                ).fetchall()]
                status_pages.append({
                    "slug": p["slug"], "title": p["title"], "description": p["description"],
                    "theme": p["theme"], "show_tags": p["show_tags"], "custom_css": p["custom_css"],
                    "monitors": page_monitors
                })

            # Settings
            settings = [dict(r) for r in conn.execute("SELECT key, value FROM settings").fetchall()]

            # Maintenance windows
            maint_rows = conn.execute(
                """SELECT mw.title, mw.start_dt, mw.end_dt, mw.repeat_weekly,
                          m.name AS monitor_name, m.url AS monitor_url
                   FROM maintenance_windows mw
                   LEFT JOIN monitors m ON m.id = mw.monitor_id"""
            ).fetchall()
            maintenance_windows = [dict(r) for r in maint_rows]

            # Servers
            servers = [dict(r) for r in conn.execute(
                "SELECT hostname, ip_address, os, environment, role, cpu_cores, ram_gb, disk_gb, location, last_patched, notes FROM servers"
            ).fetchall()]

            # Software inventory
            sw_rows = conn.execute(
                """SELECT s.hostname AS server_hostname, si.name, si.version, si.vendor,
                          si.license_type, si.support_status, si.risk_rating, si.install_path, si.discovered_by
                   FROM software_inventory si
                   JOIN servers s ON s.id = si.server_id"""
            ).fetchall()
            software_inventory = [dict(r) for r in sw_rows]

            # Software catalogue
            software_catalogue = [dict(r) for r in conn.execute(
                "SELECT name_pattern, vendor, license_type, support_status, risk_rating, notes FROM software_catalogue"
            ).fetchall()]

            # Service dependencies
            dep_rows = conn.execute(
                """SELECT m1.name AS monitor_name, m1.url AS monitor_url,
                          m2.name AS depends_on_name, m2.url AS depends_on_url, d.label
                   FROM dependencies d
                   JOIN monitors m1 ON m1.id = d.monitor_id
                   JOIN monitors m2 ON m2.id = d.depends_on"""
            ).fetchall()
            service_dependencies = [dict(r) for r in dep_rows]

            # Topology positions
            topo_rows = conn.execute(
                """SELECT m.name AS monitor_name, m.url AS monitor_url, tl.pos_x, tl.pos_y
                   FROM topology_layout tl
                   JOIN monitors m ON m.id = tl.monitor_id"""
            ).fetchall()
            topology_positions = [dict(r) for r in topo_rows]

            # Version trackers
            version_trackers = [dict(r) for r in conn.execute(
                "SELECT name_match, display_name, check_type, check_source, regex_pattern, enabled, notes FROM software_version_tracker"
            ).fetchall()]

        # Build export structure
        export_data = {
            "metadata": {
                "exported_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "app_version": "1.0.0",
                "format_version": EXPORT_FORMAT_VERSION,
                "warning": "This file contains sensitive credentials (database passwords, SMTP passwords). Store securely."
            },
            "monitors": monitors,
            "db_monitors": db_monitors,
            "status_pages": status_pages,
            "settings": settings,
            "maintenance_windows": maintenance_windows,
            "servers": servers,
            "software_inventory": software_inventory,
            "software_catalogue": software_catalogue,
            "service_dependencies": service_dependencies,
            "topology_positions": topology_positions,
            "version_trackers": version_trackers
        }

        today = datetime.utcnow().strftime("%Y-%m-%d")
        response = app.response_class(
            json.dumps(export_data, indent=2, default=str),
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="croit-monitor-backup-{today}.json"'}
        )
        return response

    except Exception as e:
        return jsonify({"error": f"Export failed: {str(e)}"}), 500


@app.route("/api/import", methods=["POST"])
@role_required(['admin'])
def api_import():
    """Import configuration data from a JSON backup file."""
    # --- Validate file presence and size ---
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "No file provided"}), 400

    file_data = file.read()
    if len(file_data) > MAX_IMPORT_SIZE:
        return jsonify({"error": "File too large. Maximum size is 50 MB."}), 400

    # --- Parse JSON ---
    try:
        data = json.loads(file_data)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Invalid JSON: {str(e)}"}), 400

    # --- Validate mode ---
    mode = request.form.get('mode', 'clean')
    if mode not in ('clean', 'merge'):
        return jsonify({"error": f"Invalid mode '{mode}'. Valid options: clean, merge"}), 400

    # --- Validate metadata ---
    if "metadata" not in data:
        return jsonify({"error": "Missing required section: metadata"}), 400
    if "format_version" not in data["metadata"]:
        return jsonify({"error": "Missing required field: metadata.format_version"}), 400
    if data["metadata"]["format_version"] not in SUPPORTED_FORMAT_VERSIONS:
        return jsonify({"error": f"Unsupported format version '{data['metadata']['format_version']}'. Supported: {SUPPORTED_FORMAT_VERSIONS}"}), 400

    # --- Validate required sections ---
    required_sections = ["monitors", "db_monitors", "settings", "status_pages",
                         "maintenance_windows", "servers", "software_inventory",
                         "software_catalogue", "service_dependencies", "version_trackers"]
    missing = [s for s in required_sections if s not in data]
    if missing:
        return jsonify({"error": f"Missing required sections: {', '.join(missing)}"}), 400

    # --- Validate monitor entries ---
    for i, m in enumerate(data["monitors"]):
        for field in ("name", "url", "type"):
            if field not in m or not m[field]:
                return jsonify({"error": f"Invalid monitor at index {i}: missing required field '{field}'"}), 400

    # --- Validate db_monitor entries ---
    for i, d in enumerate(data["db_monitors"]):
        for field in ("name", "db_type", "host"):
            if field not in d or not d[field]:
                return jsonify({"error": f"Invalid db_monitor at index {i}: missing required field '{field}'"}), 400

    # --- All validation passed, proceed with import ---
    try:
        with DB_LOCK, get_db() as conn:
            summary = _perform_import(conn, data, mode)
        return jsonify({"ok": True, "mode": mode, "summary": summary}), 200
    except Exception as e:
        return jsonify({"error": f"Import failed: {str(e)}. All changes have been rolled back."}), 500


def _perform_import(conn, data, mode):
    """Execute the actual import inside a transaction. Returns summary counts."""
    summary = {}

    if mode == "clean":
        # Delete all config tables (preserve users, heartbeats, metrics)
        for table in ["status_page_monitors", "dependencies", "topology_layout",
                      "maintenance_windows", "software_inventory", "software_catalogue",
                      "software_version_tracker", "servers", "status_pages",
                      "db_monitors", "monitors", "settings",
                      "server_monitors", "server_db_monitors"]:
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception:
                pass  # Table might not exist in older schemas

    # --- Insert monitors ---
    inserted = 0
    skipped = 0
    for m in data["monitors"]:
        if mode == "merge":
            existing = conn.execute("SELECT id FROM monitors WHERE name=? AND url=?", (m["name"], m["url"])).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            """INSERT INTO monitors (name, url, type, interval, retries, timeout, keyword,
               accepted_codes, enabled, notify_email, description, tags, group_name, request_body, request_headers)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m["name"], m["url"], m["type"], m.get("interval", 60), m.get("retries", 3),
             m.get("timeout", 10), m.get("keyword"), m.get("accepted_codes", "200-299"),
             m.get("enabled", 1), m.get("notify_email", 0), m.get("description"),
             m.get("tags"), m.get("group_name", ""), m.get("request_body"), m.get("request_headers"))
        )
        inserted += 1
    summary["monitors"] = {"inserted": inserted, "skipped": skipped}

    # --- Insert db_monitors ---
    inserted = 0
    skipped = 0
    for d in data["db_monitors"]:
        if mode == "merge":
            existing = conn.execute(
                "SELECT id FROM db_monitors WHERE name=? AND host=? AND port=? AND database=?",
                (d["name"], d["host"], d.get("port", 1433), d.get("database"))
            ).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            """INSERT INTO db_monitors (name, db_type, host, port, database, username, password,
               interval, enabled, notify_email, description, group_name, long_running_threshold)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["name"], d["db_type"], d["host"], d.get("port", 1433), d.get("database"),
             d.get("username"), d.get("password"), d.get("interval", 60),
             d.get("enabled", 1), d.get("notify_email", 0), d.get("description"),
             d.get("group_name", ""), d.get("long_running_threshold"))
        )
        inserted += 1
    summary["db_monitors"] = {"inserted": inserted, "skipped": skipped}

    # --- Insert servers ---
    inserted = 0
    skipped = 0
    for s in data["servers"]:
        if mode == "merge":
            existing = conn.execute("SELECT id FROM servers WHERE hostname=?", (s["hostname"],)).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            """INSERT INTO servers (hostname, ip_address, os, environment, role, cpu_cores, ram_gb, disk_gb, location, last_patched, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (s["hostname"], s.get("ip_address"), s.get("os"), s.get("environment", "PROD"),
             s.get("role"), s.get("cpu_cores"), s.get("ram_gb"), s.get("disk_gb"),
             s.get("location"), s.get("last_patched"), s.get("notes"))
        )
        inserted += 1
    summary["servers"] = {"inserted": inserted, "skipped": skipped}

    # --- Insert settings ---
    inserted = 0
    for item in data["settings"]:
        if mode == "merge":
            # Upsert — always overwrite for settings
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (item["key"], item.get("value")))
        else:
            conn.execute("INSERT INTO settings (key, value) VALUES (?,?)", (item["key"], item.get("value")))
        inserted += 1
    summary["settings"] = {"inserted": inserted, "skipped": 0}

    # --- Insert status_pages ---
    inserted = 0
    skipped = 0
    for sp in data["status_pages"]:
        if mode == "merge":
            existing = conn.execute("SELECT id FROM status_pages WHERE slug=?", (sp["slug"],)).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            """INSERT INTO status_pages (slug, title, description, theme, show_tags, custom_css)
               VALUES (?,?,?,?,?,?)""",
            (sp["slug"], sp["title"], sp.get("description"), sp.get("theme", "dark"),
             sp.get("show_tags", 0), sp.get("custom_css"))
        )
        page_id = conn.execute("SELECT id FROM status_pages WHERE slug=?", (sp["slug"],)).fetchone()["id"]
        # Link monitors to this status page
        for pm in sp.get("monitors", []):
            mon = conn.execute("SELECT id FROM monitors WHERE name=? AND url=?",
                               (pm["monitor_name"], pm["monitor_url"])).fetchone()
            if mon:
                conn.execute("INSERT OR IGNORE INTO status_page_monitors (page_id, monitor_id, sort_order) VALUES (?,?,?)",
                             (page_id, mon["id"], pm.get("sort_order", 0)))
        inserted += 1
    summary["status_pages"] = {"inserted": inserted, "skipped": skipped}

    # --- Insert maintenance_windows ---
    inserted = 0
    for mw in data["maintenance_windows"]:
        monitor_id = None
        if mw.get("monitor_name") and mw.get("monitor_url"):
            mon = conn.execute("SELECT id FROM monitors WHERE name=? AND url=?",
                               (mw["monitor_name"], mw["monitor_url"])).fetchone()
            if mon:
                monitor_id = mon["id"]
        conn.execute(
            """INSERT INTO maintenance_windows (monitor_id, title, start_dt, end_dt, repeat_weekly)
               VALUES (?,?,?,?,?)""",
            (monitor_id, mw["title"], mw["start_dt"], mw["end_dt"], mw.get("repeat_weekly", 0))
        )
        inserted += 1
    summary["maintenance_windows"] = {"inserted": inserted, "skipped": 0}

    # --- Insert software_inventory ---
    inserted = 0
    skipped = 0
    for si in data["software_inventory"]:
        server = conn.execute("SELECT id FROM servers WHERE hostname=?", (si["server_hostname"],)).fetchone()
        if not server:
            skipped += 1
            continue
        if mode == "merge":
            existing = conn.execute(
                "SELECT id FROM software_inventory WHERE server_id=? AND name=?",
                (server["id"], si["name"])
            ).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            """INSERT INTO software_inventory (server_id, name, version, vendor, license_type, support_status, risk_rating, install_path, discovered_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (server["id"], si["name"], si.get("version"), si.get("vendor"),
             si.get("license_type"), si.get("support_status"), si.get("risk_rating"),
             si.get("install_path"), si.get("discovered_by", "manual"))
        )
        inserted += 1
    summary["software_inventory"] = {"inserted": inserted, "skipped": skipped}

    # --- Insert software_catalogue ---
    inserted = 0
    skipped = 0
    for sc in data["software_catalogue"]:
        if mode == "merge":
            existing = conn.execute(
                "SELECT id FROM software_catalogue WHERE name_pattern=? AND vendor=?",
                (sc["name_pattern"], sc.get("vendor"))
            ).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            """INSERT INTO software_catalogue (name_pattern, vendor, license_type, support_status, risk_rating, notes)
               VALUES (?,?,?,?,?,?)""",
            (sc["name_pattern"], sc.get("vendor"), sc.get("license_type"),
             sc.get("support_status", "Supported"), sc.get("risk_rating", "Low"), sc.get("notes"))
        )
        inserted += 1
    summary["software_catalogue"] = {"inserted": inserted, "skipped": skipped}

    # --- Insert service_dependencies ---
    inserted = 0
    skipped = 0
    for dep in data["service_dependencies"]:
        mon1 = conn.execute("SELECT id FROM monitors WHERE name=? AND url=?",
                            (dep["monitor_name"], dep["monitor_url"])).fetchone()
        mon2 = conn.execute("SELECT id FROM monitors WHERE name=? AND url=?",
                            (dep["depends_on_name"], dep["depends_on_url"])).fetchone()
        if not mon1 or not mon2:
            skipped += 1
            continue
        if mode == "merge":
            existing = conn.execute(
                "SELECT id FROM dependencies WHERE monitor_id=? AND depends_on=?",
                (mon1["id"], mon2["id"])
            ).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            "INSERT INTO dependencies (monitor_id, depends_on, label) VALUES (?,?,?)",
            (mon1["id"], mon2["id"], dep.get("label"))
        )
        inserted += 1
    summary["service_dependencies"] = {"inserted": inserted, "skipped": skipped}

    # --- Insert topology_positions ---
    inserted = 0
    skipped = 0
    for tp in data.get("topology_positions", []):
        mon = conn.execute("SELECT id FROM monitors WHERE name=? AND url=?",
                           (tp["monitor_name"], tp["monitor_url"])).fetchone()
        if not mon:
            skipped += 1
            continue
        if mode == "merge":
            existing = conn.execute("SELECT monitor_id FROM topology_layout WHERE monitor_id=?", (mon["id"],)).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            "INSERT OR REPLACE INTO topology_layout (monitor_id, pos_x, pos_y) VALUES (?,?,?)",
            (mon["id"], tp.get("pos_x", 0), tp.get("pos_y", 0))
        )
        inserted += 1
    summary["topology_positions"] = {"inserted": inserted, "skipped": skipped}

    # --- Insert version_trackers ---
    inserted = 0
    skipped = 0
    for vt in data["version_trackers"]:
        if mode == "merge":
            existing = conn.execute(
                "SELECT id FROM software_version_tracker WHERE name_match=? AND check_source=?",
                (vt["name_match"], vt["check_source"])
            ).fetchone()
            if existing:
                skipped += 1
                continue
        conn.execute(
            """INSERT INTO software_version_tracker (name_match, display_name, check_type, check_source, regex_pattern, enabled, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (vt["name_match"], vt["display_name"], vt["check_type"], vt["check_source"],
             vt.get("regex_pattern"), vt.get("enabled", 1), vt.get("notes"))
        )
        inserted += 1
    summary["version_trackers"] = {"inserted": inserted, "skipped": skipped}

    return summary


# ─────────────────────────────────────────────
# Serve frontend
# ─────────────────────────────────────────────

@app.route("/login")
def serve_login():
    dist = os.path.join(app.root_path, "frontend", "dist")
    return send_from_directory(dist, "login.html")

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    dist   = os.path.join(app.root_path, "frontend", "dist")
    # Never intercept API routes — let Flask handle them
    if path.startswith("api/"):
        from flask import abort
        abort(404)
    # Always serve static assets without auth check
    if path and path.startswith(("logo/", "app.js", "db.js", "servers.js", "software.js", "login.html")):
        target = os.path.join(dist, path)
        if os.path.exists(target):
            return send_from_directory(dist, path)
    # Status pages are public (no login required)
    params = request.args
    if params.get("page"):
        target = os.path.join(dist, "index.html")
        return send_from_directory(dist, "index.html")
    # All other pages require login
    if not current_user.is_authenticated:
        return redirect(f"/login?next={request.path}")
    target = os.path.join(dist, path)
    if path and os.path.exists(target):
        return send_from_directory(dist, path)
    return send_from_directory(dist, "index.html")


# ─────────────────────────────────────────────
# Startup — runs for both Gunicorn and dev server
# ─────────────────────────────────────────────

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

init_db()
load_default_monitors()

threading.Thread(target=monitor_loop,        daemon=True).start()
threading.Thread(target=ssl_check_loop,      daemon=True).start()
threading.Thread(target=weekly_report_loop,  daemon=True).start()
threading.Thread(target=db_monitor_loop,     daemon=True).start()
threading.Thread(target=version_check_loop,  daemon=True).start()

print("\n[OK] Uptime Monitor initialised.\n")

# ─────────────────────────────────────────────
# Entry point (Flask dev server only)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("[OK] Running with Flask dev server on http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
