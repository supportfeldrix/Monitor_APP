# Server Build Request — CROIT Uptime Monitoring Dashboard

**Requested By:** CRO IT Team  
**Date:** 12 June 2026  
**Application:** CROIT Uptime & Database Monitoring Dashboard  
**Priority:** Standard  

---

## 1. Executive Summary

We require **two Linux servers** to host the CROIT Uptime Monitoring Dashboard — one for UAT (testing) and one for Production. This is a lightweight Python/Flask web application that monitors HTTP/HTTPS endpoints, TCP ports, and MSSQL databases across our infrastructure. It runs with minimal resource requirements.

---

## 2. Servers Required

| Item | UAT Server | Production Server |
|------|-----------|-------------------|
| **Hostname (suggested)** | `frm-rbcroitmon-uat` | `frm-rbcroitmon-prod` |
| **Purpose** | Testing & development | Live monitoring dashboard |
| **Environment** | Non-Production | Production |

---

## 3. Hardware Specifications

### UAT Server (Minimum)

| Resource | Specification | Justification |
|----------|--------------|---------------|
| **CPU** | 2 vCPU | Runs background monitoring threads + web server |
| **RAM** | 4 GB | Python app + Gunicorn workers + pyodbc connections |
| **Disk** | 30 GB SSD/fast storage | OS + application + SQLite DB + logs + backups |
| **NIC** | 1x standard | Internal network connectivity |

### Production Server (Recommended)

| Resource | Specification | Justification |
|----------|--------------|---------------|
| **CPU** | 4 vCPU | Handles more concurrent monitors, agent metrics, and user sessions |
| **RAM** | 8 GB | Headroom for 50+ monitors, DB polling, extended metrics collection |
| **Disk** | 50 GB SSD/fast storage | OS + application + SQLite DB + logs + backups + growth |
| **NIC** | 1x standard | Internal network connectivity |

---

## 4. Operating System

| Item | Requirement |
|------|-------------|
| **OS** | RHEL 8.x or RHEL 9.x (64-bit) |
| **Alternative** | Rocky Linux 8.x / 9.x also acceptable |
| **Kernel** | Standard enterprise kernel (no custom modules needed) |

---

## 5. Software Packages Required

The following packages must be installed or available:

| Package | Version | Purpose |
|---------|---------|---------|
| **Python** | 3.9+ (3.11 preferred) | Application runtime |
| **python3-pip** | Latest | Python package installer |
| **python3-venv** | Matching Python version | Virtual environment support |
| **nginx** | 1.20+ | Reverse proxy, SSL termination, static caching |
| **unixODBC** | 2.3+ | ODBC driver manager for MSSQL connectivity |
| **msodbcsql17** or **msodbcsql18** | Latest | Microsoft ODBC Driver for SQL Server |
| **gcc / python3-devel** | Latest | Compile native Python extensions (pyodbc) |
| **openssl** | 1.1+ | SSL/TLS support |
| **curl** | Any | Health check testing |

> **Note on MSSQL ODBC Driver:** If the Microsoft ODBC driver cannot be installed from Microsoft's repository (no internet), we can provide the RPM offline. The driver is required for database monitoring features.

---

## 6. Network Requirements

### Inbound (to this server)

| Source | Port | Protocol | Purpose |
|--------|------|----------|---------|
| CRO IT Team workstations (office network) | 9443/TCP | HTTPS | Web dashboard access |
| Monitored Linux/Windows servers (agents) | 9443/TCP | HTTPS | Agent metric reporting |

### Outbound (from this server)

| Destination | Port | Protocol | Purpose |
|-------------|------|----------|---------|
| All monitored web endpoints | 80/TCP, 443/TCP | HTTP/HTTPS | HTTP/HTTPS uptime checks |
| MSSQL database servers | 1433/TCP | TDS | Database monitoring & extended metrics |
| Monitored servers (TCP checks) | Various | TCP | TCP port availability checks |
| LDAP server (if AD auth enabled) | 636/TCP | LDAPS | User authentication |
| SMTP relay (if email alerts enabled) | 25 or 587/TCP | SMTP/TLS | Alert notifications |

### DNS

| Requirement | Detail |
|-------------|--------|
| Forward DNS entry | Hostname must resolve from CRO IT workstations |
| Reverse DNS | Not required |

---

## 7. Firewall Rules Summary

```
INBOUND:
  Office Network → Server:9443 (HTTPS — dashboard access)
  Agent Servers  → Server:9443 (HTTPS — metric push)

OUTBOUND:
  Server → Monitored Hosts:80,443 (HTTP/HTTPS checks)
  Server → MSSQL Servers:1433 (Database monitoring)
  Server → Various Hosts:Various Ports (TCP port checks)
  Server → LDAP:636 (Optional — AD authentication)
  Server → SMTP:25/587 (Optional — email alerts)
```

---

## 8. Storage Layout

| Mount Point | Size | Purpose |
|-------------|------|---------|
| `/` | 20 GB | OS and standard packages |
| `/opt/croit-monitor` | 10 GB (UAT) / 20 GB (PROD) | Application, database, logs, backups |

> **Or** a single 30 GB (UAT) / 50 GB (PROD) root partition is acceptable. No separate data volume required — the SQLite database is lightweight.

---

## 9. User Account Requirements

| Account | Type | Purpose |
|---------|------|---------|
| `f5151422` (or service account `svc_croit`) | Standard user | Application owner, runs Gunicorn |
| `sudo` access | Required for initial setup only | Install packages, configure nginx, create systemd service |

> After initial setup, the application runs entirely as a non-root user. Sudo is only needed for package installation, nginx config, and systemd service registration.

---

## 10. SSL Certificates

| Item | Requirement |
|------|-------------|
| **Certificate** | Standard FNB internal certificate for the hostname |
| **Format** | PEM format (.crt + .key) |
| **Key** | Unencrypted private key (no passphrase) — or we extract it ourselves |
| **Location** | Placed in `/opt/croit-monitor/ssl/` |
| **Used by** | Nginx for HTTPS termination on port 9443 |

---

## 11. Application Architecture

```
                    Browser (CRO IT Team)
                          │
                          ▼ HTTPS :9443
                    ┌─────────────┐
                    │   Nginx     │  (SSL termination, reverse proxy)
                    └──────┬──────┘
                           │ HTTP :5000 (localhost only)
                           ▼
                    ┌─────────────┐
                    │  Gunicorn   │  (4 workers, sync, production WSGI)
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Flask App  │  (app.py — single file backend)
                    │             │
                    │ • Web API   │ ──► SQLite DB (uptime.db)
                    │ • Monitor   │ ──► HTTP/TCP endpoints
                    │   Threads   │ ──► MSSQL servers (pyodbc)
                    │ • Agent API │ ◄── Server agents (metrics push)
                    └─────────────┘
```

---

## 12. Backup Requirements

| Item | Detail |
|------|--------|
| **What to back up** | SQLite database file (`uptime.db`, typically < 50 MB) |
| **Frequency** | Daily at 02:00 |
| **Retention** | 7 days |
| **Method** | Simple file copy + gzip (automated via cron) |
| **Offsite** | Not required — data is recreatable (monitoring config only) |

---

## 13. Monitoring & Availability

| Item | Requirement |
|------|-------------|
| **Uptime SLA** | Standard (non-critical — monitoring tool, not business transaction path) |
| **Auto-start on reboot** | Yes — systemd service (`croit-monitor.service`) |
| **Health check endpoint** | `GET /api/auth/me` returns 401 (confirming app is responsive) |
| **Log rotation** | Standard logrotate for `/opt/croit-monitor/logs/*.log` |

---

## 14. What We Do NOT Need

- ❌ Docker / Podman / container runtime
- ❌ Kubernetes / OpenShift
- ❌ PostgreSQL / MySQL / external database server
- ❌ Redis / message queue
- ❌ Java / Node.js runtime
- ❌ Load balancer (single instance is sufficient)
- ❌ NFS or shared storage
- ❌ GPU

---

## 15. Deployment Timeline

| Phase | Activity |
|-------|----------|
| **Week 1** | Server provisioned, OS installed, network/firewall rules applied |
| **Week 2** | Packages installed, SSL certs issued, application deployed |
| **Week 3** | UAT testing, agent enrollment, monitor configuration |
| **Week 4** | PROD deployment and go-live |

---

## 16. Post-Provisioning — What We Handle

Once the server is provisioned with the OS, packages, and network access, our team will:

1. Deploy the application code (`app.py`, frontend, configs)
2. Create the Python virtual environment and install pip packages
3. Configure Gunicorn and Nginx
4. Register the systemd service
5. Configure monitors and users
6. Enroll server agents for metric collection

---

## 17. Contact

| Role | Name | Contact |
|------|------|---------|
| Requestor | *[Your Name]* | *[Your Email]* |
| Technical Lead | *[Your Name]* | *[Your Email]* |
| Team | CRO IT | *[Team DL]* |

---

*Document generated: 12 June 2026*
