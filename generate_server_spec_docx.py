"""
Generate a professional Word document (.docx) from the server spec.
Run: python generate_server_spec_docx.py
Output: SERVER-SPEC-REQUEST.docx
"""

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import os

def set_cell_shading(cell, color):
    """Set background color of a table cell."""
    shading = OxmlElement('w:shd')
    shading.set(qn('w:fill'), color)
    shading.set(qn('w:val'), 'clear')
    cell._tc.get_or_add_tcPr().append(shading)

def add_table_row(table, cells, bold=False, header=False):
    """Add a row to a table with optional formatting."""
    row = table.add_row()
    for i, text in enumerate(cells):
        cell = row.cells[i]
        cell.text = ''
        p = cell.paragraphs[0]
        run = p.add_run(str(text))
        run.font.size = Pt(9)
        if bold or header:
            run.bold = True
        if header:
            set_cell_shading(cell, '1F4E79')
            run.font.color.rgb = RGBColor(255, 255, 255)
    return row

def create_table(doc, headers, rows, col_widths=None):
    """Create a formatted table."""
    table = doc.add_table(rows=0, cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    
    # Header row
    add_table_row(table, headers, header=True)
    
    # Data rows
    for row_data in rows:
        add_table_row(table, row_data)
    
    # Set column widths if provided
    if col_widths:
        for i, width in enumerate(col_widths):
            for row in table.rows:
                row.cells[i].width = Cm(width)
    
    return table

def main():
    doc = Document()
    
    # Page margins
    sections = doc.sections
    for section in sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)
    
    # ─── Title Page ───────────────────────────────────────────────
    doc.add_paragraph()
    doc.add_paragraph()
    doc.add_paragraph()
    
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run('Server Build Request')
    run.font.size = Pt(28)
    run.font.color.rgb = RGBColor(31, 78, 121)
    run.bold = True
    
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run('CROIT Uptime & Database Monitoring Dashboard')
    run.font.size = Pt(16)
    run.font.color.rgb = RGBColor(89, 89, 89)
    
    doc.add_paragraph()
    
    # Meta info
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = meta.add_run('UAT & Production Environments')
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(89, 89, 89)
    
    doc.add_paragraph()
    doc.add_paragraph()
    
    # Info box
    info_table = doc.add_table(rows=0, cols=2)
    info_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    info_data = [
        ('Requested By:', 'CRO IT Team'),
        ('Date:', '12 June 2026'),
        ('Priority:', 'Standard'),
        ('Document Version:', '1.0'),
    ]
    for label, value in info_data:
        row = info_table.add_row()
        row.cells[0].text = label
        row.cells[0].paragraphs[0].runs[0].bold = True if row.cells[0].paragraphs[0].runs else None
        row.cells[1].text = value
        # Bold the label
        row.cells[0].paragraphs[0].clear()
        r = row.cells[0].paragraphs[0].add_run(label)
        r.bold = True
        r.font.size = Pt(10)
        row.cells[1].paragraphs[0].clear()
        r2 = row.cells[1].paragraphs[0].add_run(value)
        r2.font.size = Pt(10)
    
    # Page break
    doc.add_page_break()
    
    # ─── Section 1: Summary ──────────────────────────────────────
    h = doc.add_heading('1. Executive Summary', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    doc.add_paragraph(
        'We require two Linux servers to host the CROIT Uptime Monitoring Dashboard — '
        'one for UAT (testing) and one for Production. This is a lightweight Python/Flask '
        'web application that monitors HTTP/HTTPS endpoints, TCP ports, and MSSQL databases '
        'across our infrastructure. It runs with minimal resource requirements and does not '
        'require containers, external databases, or complex middleware.'
    )
    
    # ─── Section 2: Servers Required ─────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('2. Servers Required', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc, 
        ['Item', 'UAT Server', 'Production Server'],
        [
            ['Hostname (suggested)', 'frm-rbcroitmon-uat', 'frm-rbcroitmon-prod'],
            ['Purpose', 'Testing & development', 'Live monitoring dashboard'],
            ['Environment', 'Non-Production', 'Production'],
        ]
    )
    
    # ─── Section 3: Hardware ─────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('3. Hardware Specifications', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    doc.add_heading('UAT Server (Minimum)', level=2)
    create_table(doc,
        ['Resource', 'Specification', 'Justification'],
        [
            ['CPU', '2 vCPU', 'Background monitoring threads + web server'],
            ['RAM', '4 GB', 'Python app + Gunicorn workers + pyodbc connections'],
            ['Disk', '30 GB SSD', 'OS + application + SQLite DB + logs + backups'],
            ['NIC', '1x standard', 'Internal network connectivity'],
        ]
    )
    
    doc.add_paragraph()
    doc.add_heading('Production Server (Recommended)', level=2)
    create_table(doc,
        ['Resource', 'Specification', 'Justification'],
        [
            ['CPU', '4 vCPU', 'Handles 50+ monitors, agent metrics, concurrent users'],
            ['RAM', '8 GB', 'Headroom for DB polling, extended metrics collection'],
            ['Disk', '50 GB SSD', 'OS + application + SQLite DB + logs + backups + growth'],
            ['NIC', '1x standard', 'Internal network connectivity'],
        ]
    )
    
    # ─── Section 4: OS ───────────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('4. Operating System', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Item', 'Requirement'],
        [
            ['OS', 'RHEL 8.x or RHEL 9.x (64-bit)'],
            ['Alternative', 'Rocky Linux 8.x / 9.x also acceptable'],
            ['Kernel', 'Standard enterprise kernel (no custom modules needed)'],
        ]
    )
    
    # ─── Section 5: Software ─────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('5. Software Packages Required', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Package', 'Version', 'Purpose'],
        [
            ['Python 3', '3.9+ (3.11 preferred)', 'Application runtime'],
            ['python3-pip', 'Latest', 'Python package installer'],
            ['python3-venv', 'Matching Python version', 'Virtual environment support'],
            ['nginx', '1.20+', 'Reverse proxy, SSL termination'],
            ['unixODBC', '2.3+', 'ODBC driver manager for MSSQL'],
            ['msodbcsql17 or msodbcsql18', 'Latest', 'Microsoft ODBC Driver for SQL Server'],
            ['gcc / python3-devel', 'Latest', 'Compile native Python extensions (pyodbc)'],
            ['openssl', '1.1+', 'SSL/TLS support'],
            ['curl', 'Any', 'Health check testing'],
        ]
    )
    
    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(6)
    run = note.add_run('Note: ')
    run.bold = True
    run.font.size = Pt(9)
    run = note.add_run(
        'If the Microsoft ODBC driver cannot be installed from Microsoft\'s repository '
        '(no internet), we can provide the RPM offline.'
    )
    run.font.size = Pt(9)
    
    # ─── Section 6: Network ──────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('6. Network Requirements', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    doc.add_heading('Inbound (to this server)', level=2)
    create_table(doc,
        ['Source', 'Port', 'Protocol', 'Purpose'],
        [
            ['CRO IT workstations', '9443/TCP', 'HTTPS', 'Web dashboard access'],
            ['Monitored servers (agents)', '9443/TCP', 'HTTPS', 'Agent metric reporting'],
        ]
    )
    
    doc.add_paragraph()
    doc.add_heading('Outbound (from this server)', level=2)
    create_table(doc,
        ['Destination', 'Port', 'Protocol', 'Purpose'],
        [
            ['Monitored web endpoints', '80, 443/TCP', 'HTTP/HTTPS', 'Uptime checks'],
            ['MSSQL database servers', '1433/TCP', 'TDS', 'Database monitoring'],
            ['Monitored servers (TCP checks)', 'Various', 'TCP', 'Port availability checks'],
            ['LDAP server (optional)', '636/TCP', 'LDAPS', 'AD user authentication'],
            ['SMTP relay (optional)', '25 or 587/TCP', 'SMTP', 'Alert email notifications'],
        ]
    )
    
    doc.add_paragraph()
    doc.add_heading('DNS', level=2)
    create_table(doc,
        ['Requirement', 'Detail'],
        [
            ['Forward DNS entry', 'Hostname must resolve from CRO IT workstations'],
            ['Reverse DNS', 'Not required'],
        ]
    )
    
    # ─── Section 7: Storage ──────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('7. Storage Layout', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Mount Point', 'Size (UAT / PROD)', 'Purpose'],
        [
            ['/', '20 GB / 20 GB', 'OS and standard packages'],
            ['/opt/croit-monitor', '10 GB / 30 GB', 'Application, database, logs, backups'],
        ]
    )
    
    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(6)
    run = note.add_run(
        'A single root partition of 30 GB (UAT) / 50 GB (PROD) is also acceptable. '
        'No separate data volume required — the SQLite database is lightweight (< 100 MB typical).'
    )
    run.font.size = Pt(9)
    run.italic = True
    
    # ─── Section 8: User Accounts ────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('8. User Account Requirements', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Account', 'Type', 'Purpose'],
        [
            ['f5151422 (or svc_croit)', 'Standard user', 'Application owner, runs Gunicorn'],
            ['sudo access', 'Required for initial setup', 'Package install, nginx config, systemd'],
        ]
    )
    
    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(6)
    run = note.add_run(
        'After initial setup, the application runs entirely as a non-root user. '
        'Sudo is only needed for package installation, nginx configuration, and systemd service registration.'
    )
    run.font.size = Pt(9)
    run.italic = True
    
    # ─── Section 9: SSL ──────────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('9. SSL Certificate Requirements', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Item', 'Requirement'],
        [
            ['Certificate', 'Standard FNB internal certificate for the hostname'],
            ['Format', 'PEM format (.crt + .key files)'],
            ['Private Key', 'Unencrypted (no passphrase)'],
            ['Location', '/opt/croit-monitor/ssl/'],
            ['Used by', 'Nginx for HTTPS termination on port 9443'],
        ]
    )
    
    # ─── Section 10: Architecture ────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('10. Application Architecture', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    arch_text = (
        'The application follows a simple architecture:\n\n'
        '1. Nginx receives HTTPS requests on port 9443\n'
        '2. Nginx terminates SSL and proxies to Gunicorn on localhost:5000\n'
        '3. Gunicorn (4 sync workers) runs the Flask application\n'
        '4. Flask serves the web UI and REST API\n'
        '5. Background threads perform HTTP/TCP/DB monitoring checks\n'
        '6. All data stored in a single SQLite file (uptime.db)\n'
        '7. Server agents push metrics to the app via HTTPS API'
    )
    doc.add_paragraph(arch_text)
    
    # Architecture diagram as a simple table
    doc.add_paragraph()
    arch_diagram = doc.add_paragraph()
    arch_diagram.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = arch_diagram.add_run(
        'Browser → HTTPS:9443 → Nginx → HTTP:5000 → Gunicorn → Flask App → SQLite DB\n'
        '                                                           ↕\n'
        '                                              Monitored Endpoints / MSSQL / Agents'
    )
    run.font.name = 'Consolas'
    run.font.size = Pt(9)
    
    # ─── Section 11: Backup ──────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('11. Backup Requirements', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Item', 'Detail'],
        [
            ['What to back up', 'SQLite database file (uptime.db, typically < 50 MB)'],
            ['Frequency', 'Daily at 02:00'],
            ['Retention', '7 days'],
            ['Method', 'File copy + gzip (automated via cron)'],
            ['Offsite backup', 'Not required — data is recreatable'],
        ]
    )
    
    # ─── Section 12: Availability ────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('12. Availability & Monitoring', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Item', 'Requirement'],
        [
            ['Uptime SLA', 'Standard (not business-critical path)'],
            ['Auto-start on reboot', 'Yes — systemd service'],
            ['Health check endpoint', 'GET /api/auth/me (returns HTTP response)'],
            ['Log rotation', 'Standard logrotate for /opt/croit-monitor/logs/*.log'],
        ]
    )
    
    # ─── Section 13: NOT Needed ──────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('13. What Is NOT Required', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    not_needed = [
        'Docker / Podman / container runtime',
        'Kubernetes / OpenShift',
        'PostgreSQL / MySQL / external database server',
        'Redis / message queue',
        'Java / Node.js runtime',
        'Load balancer (single instance is sufficient)',
        'NFS or shared storage',
        'GPU',
    ]
    for item in not_needed:
        p = doc.add_paragraph(f'✗  {item}')
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.left_indent = Cm(1)
    
    # ─── Section 14: Timeline ────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('14. Deployment Timeline', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Phase', 'Activity'],
        [
            ['Week 1', 'Server provisioned, OS installed, network/firewall rules applied'],
            ['Week 2', 'Packages installed, SSL certs issued, application deployed'],
            ['Week 3', 'UAT testing, agent enrollment, monitor configuration'],
            ['Week 4', 'PROD deployment and go-live'],
        ]
    )
    
    # ─── Section 15: Post-Provisioning ───────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('15. Post-Provisioning (Handled by CRO IT)', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    doc.add_paragraph(
        'Once the server is provisioned with the OS, packages, and network access, '
        'our team will handle:'
    )
    
    steps = [
        'Deploy application code (app.py, frontend, configs)',
        'Create Python virtual environment and install pip packages',
        'Configure Gunicorn and Nginx',
        'Register the systemd service',
        'Configure monitors and users',
        'Enroll server agents for metric collection',
    ]
    for i, step in enumerate(steps, 1):
        doc.add_paragraph(f'{i}. {step}')
    
    # ─── Section 16: Contact ─────────────────────────────────────
    doc.add_paragraph()
    h = doc.add_heading('16. Contact', level=1)
    h.runs[0].font.color.rgb = RGBColor(31, 78, 121)
    
    create_table(doc,
        ['Role', 'Name', 'Contact'],
        [
            ['Requestor', '[Your Name]', '[Your Email]'],
            ['Technical Lead', '[Your Name]', '[Your Email]'],
            ['Team', 'CRO IT', '[Team DL]'],
        ]
    )
    
    # ─── Footer ──────────────────────────────────────────────────
    doc.add_paragraph()
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = footer.add_run('— End of Document —')
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(150, 150, 150)
    run.italic = True
    
    # Save
    output_path = os.path.join(os.path.dirname(__file__), 'SERVER-SPEC-REQUEST.docx')
    doc.save(output_path)
    print(f'Document saved: {output_path}')

if __name__ == '__main__':
    main()
