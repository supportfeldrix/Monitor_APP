# CROIT Uptime Monitoring — Reference Guide
**How to monitor web frontends, backend APIs, and infrastructure services**

---

## 1. Monitor Types Available

### HTTP / HTTPS Monitor
Sends an HTTP GET request to a URL and checks the response status code.
Use this for any web page, login page, or API endpoint that returns a standard HTTP response.

**When to use:**
- Web application frontends (login pages, dashboards)
- REST APIs that return HTTP 200 when healthy
- Any HTTPS endpoint you want to confirm is reachable

**Setup:**
| Field | Value |
|---|---|
| Monitor Type | HTTP / HTTPS |
| URL | Full URL e.g. `https://app.example.com/login` |
| Accepted Status Codes | `200-299` (default) or add `403` if the page redirects to login |
| Interval | 60 seconds recommended |
| Retries | 3 (waits for 3 failures before marking as DOWN) |

**Example — Actimize Webfront:**
```
Type:    HTTP / HTTPS
URL:     https://app-uat.frs.actimizecloud.com/RCM/acegi/acegilogin.jsp
Codes:   200-299
```

---

### HTTP Keyword Monitor
Fetches a URL and checks that a specific word or phrase appears in the response body.
If the keyword is **not found**, the monitor is marked **DOWN** even if the HTTP status is 200.

**When to use:**
- REST API `/health` or `/status` endpoints that return JSON
- Services where a 200 response does not guarantee the service is healthy
- APIs that return `{"status":"ok"}` or `{"healthy":true}` when running correctly

**Setup:**
| Field | Value |
|---|---|
| Monitor Type | HTTP Keyword |
| URL | The health/status endpoint URL |
| Keyword | The word or phrase that must appear in the response |
| Accepted Status Codes | `200-299` |

**Example — Internal API health check:**
```
Type:    HTTP Keyword
URL:     https://your-api.fnb.co.za/health
Keyword: "status":"ok"
```

**Example — APISIX Prometheus metrics:**
```
Type:    HTTP Keyword
URL:     https://apisix-metrics-route-cro-apisix-uat.apps.dev-02-rb.ocp.fnb.co.za/apisix/prometheus/metrics
Keyword: nginx_connections_active
```

**Tip:** Keep the keyword short and unique. Use part of the JSON key-value pair
e.g. `"status":"ok"` rather than just `ok` to avoid false positives.

---

### TCP Port Monitor
Checks if a specific port is open and accepting connections on a host.
Does not send any HTTP request — just verifies the port is reachable.

**When to use:**
- Databases (PostgreSQL, Oracle, SQL Server, MySQL)
- Message queues (IBM MQ, RabbitMQ, Kafka)
- Any backend service that listens on a TCP port
- Services that do not have an HTTP interface

**Setup:**
| Field | Value |
|---|---|
| Monitor Type | TCP Port |
| Host:Port | `hostname:port` e.g. `db-server.fnb.co.za:5432` |
| Interval | 60 seconds |
| Timeout | 10 seconds |

**Example — PostgreSQL database:**
```
Type:    TCP Port
Host:    frm-rbautodev01:5432
```

**Example — IBM MQ:**
```
Type:    TCP Port
Host:    mq-server.fnb.co.za:1414
```

**Example — WSO2 management port:**
```
Type:    TCP Port
Host:    wso2.fnb.co.za:9443
```

---

## 2. Monitoring Backend APIs — Step by Step

### Step 1 — Identify what the API exposes

Ask the API owner or check the documentation:

- Does it have a `/health`, `/status`, `/ping`, or `/actuator/health` endpoint?
- Does it return JSON with a status field?
- What port does it run on?

### Step 2 — Choose the right monitor type

```
API has a /health endpoint that returns JSON  →  Use HTTP Keyword
API returns HTTP 200 when running             →  Use HTTP / HTTPS
API is a database or non-HTTP service         →  Use TCP Port
API is behind a gateway (WSO2, APISIX)        →  Monitor the gateway endpoint
```

### Step 3 — Add the monitor in the dashboard

1. Open the dashboard at `http://localhost:5000`
2. Click **+ Add Monitor** (top right)
3. Fill in the fields:
   - **Monitor Type** — select from the dropdown
   - **Friendly Name** — clear name e.g. `TOM Batch API - PROD`
   - **URL or Host:Port** — the endpoint to check
   - **Application Group** — group it with related services e.g. `TOM`
   - **Keyword** — only for HTTP Keyword type
   - **Interval** — how often to check (60s recommended)
   - **Retries** — how many failures before alerting (3 recommended)
4. Click **Save Monitor**

### Step 4 — Add to a Status Page (optional)

1. Go to **Status Pages** in the left menu
2. Click **Edit** on the relevant status page
3. Tick the new monitor in the monitor list
4. Click **Save Page**

---

## 3. Common Backend Services — Quick Reference

| Service | Recommended Monitor Type | Typical Port | Notes |
|---|---|---|---|
| REST API with `/health` | HTTP Keyword | 443 / 8080 | Keyword: `"status":"ok"` or `"healthy":true` |
| REST API no health endpoint | HTTP / HTTPS | 443 / 8080 | Monitor any endpoint returning 200 |
| SOAP / WS endpoint | HTTP / HTTPS | 443 / 8080 | Monitor the WSDL URL |
| PostgreSQL | TCP Port | 5432 | |
| Oracle DB | TCP Port | 1521 | |
| SQL Server | TCP Port | 1433 | |
| IBM MQ | TCP Port | 1414 | |
| RabbitMQ | TCP Port | 5672 | Or 15672 for management UI |
| Kafka | TCP Port | 9092 | |
| Redis | TCP Port | 6379 | |
| WSO2 API Manager | HTTP / HTTPS | 9443 | Monitor publisher or gateway URL |
| APISIX Gateway | HTTP Keyword | 443 | Use Prometheus metrics endpoint |
| Spring Boot app | HTTP Keyword | 8080 | `/actuator/health` · Keyword: `"status":"UP"` |
| Node.js app | HTTP Keyword | 3000 | `/health` · Keyword: `ok` |
| .NET Core app | HTTP Keyword | 5000 | `/health` · Keyword: `Healthy` |

---

## 4. Recommended Health Endpoint Standard

If your team owns the backend service, add a `/health` endpoint that returns:

```json
{
  "status": "ok",
  "service": "your-service-name",
  "version": "1.0.0",
  "timestamp": "2026-04-23T08:00:00Z"
}
```

Then configure the monitor as:
```
Type:    HTTP Keyword
URL:     https://your-service/health
Keyword: "status":"ok"
```

This is the industry standard pattern. It costs almost nothing to implement and gives
you reliable monitoring that distinguishes between "port is open" and "service is actually healthy".

---

## 5. Monitor Settings Reference

| Setting | Description | Recommended Value |
|---|---|---|
| Interval | How often the check runs | 60 seconds |
| Retries | Consecutive failures before DOWN alert | 3 |
| Timeout | How long to wait for a response | 10 seconds |
| Accepted Status Codes | HTTP codes considered healthy | `200-299` or `200-299,403` |
| Application Group | Groups monitors on the dashboard | Use app name e.g. `TOM`, `Actimize Cloud` |
| Tags | Optional labels for filtering | e.g. `production, api, database` |
| Email Alert | Send email when status changes | Enable for critical services |

---

## 6. What Cannot Be Monitored Without Additional Setup

| Requirement | Why it cannot be done | Solution |
|---|---|---|
| Active user / session count | The monitor makes 1 request — it cannot see other users | Expose a `/metrics` endpoint from the app |
| Database query performance | TCP check only verifies port is open | Use a dedicated DB monitoring tool |
| Message queue depth | Requires MQ API access | Expose via a health endpoint |
| External SaaS services (Actimize cloud) | No access to internal metrics | HTTP monitoring of the login page is the best available |
| SSL certificate expiry | Not currently implemented | Can be added as a future enhancement |

---

## 7. Accessing the Application

| URL | Purpose |
|---|---|
| `http://localhost:5000` | Main dashboard (internal use) |
| `http://localhost:5000/?page=default` | Default status page (share with team) |
| `http://localhost:5000/?page=fnbcroit-status` | CROIT Infrastructure status page |
| `http://10.200.116.150:5000` | Access from other machines on the network |

**To start the application:** Double-click `start.bat` in the `Podman_Dashboard_UAT` folder.

**To stop the application:** Press `Ctrl+C` in the CMD window, then type `Y`.

---

*Document created: April 2026*
*Maintained by: CROIT Team — frm-rbautodev01*
