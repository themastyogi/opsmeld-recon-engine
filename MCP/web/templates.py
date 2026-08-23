"""
Opsmeld Reconciliation Engine - Web Console Templates
HTML templates for Dashboard Hub and Settings UI styled with LEDGER_CSS.
"""

from core.ledger_theme import LEDGER_CSS, escape_html


def render_dashboard_html(client_name: str, reports_summary: dict) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Opsmeld Engine - Control Center</title>
    <style>
    {LEDGER_CSS}
    .action-btn {{
        display: inline-block;
        padding: 10px 18px;
        background: #0E6251;
        color: white;
        text-decoration: none;
        border-radius: 6px;
        font-weight: 500;
        font-size: 0.9rem;
    }}
    .action-btn-sec {{
        background: #596562;
    }}
    .nav-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 24px;
        border-bottom: 1px solid var(--border-color);
        padding-bottom: 16px;
    }}
    </style>
</head>
<body>
    <div class="nav-bar">
        <div>
            <h1>Opsmeld Operations & Recon Engine</h1>
            <p style="color: var(--text-muted); margin: 0;">Active Client Profile: <strong>{escape_html(client_name)}</strong></p>
        </div>
        <div>
            <a href="/settings" class="action-btn action-btn-sec">⚙️ Settings & Configuration</a>
        </div>
    </div>

    <div class="stat-grid">
        <div class="stat-tile">
            <div class="label">Engine Status</div>
            <div class="value" style="color: var(--teal-text);">Ready</div>
        </div>
        <div class="stat-tile">
            <div class="label">Active Modules</div>
            <div class="value mono">4</div>
        </div>
        <div class="stat-tile">
            <div class="label">Safety Mode</div>
            <div class="value mono" style="color: var(--teal-text);">STAGED (Do Not Post)</div>
        </div>
    </div>

    <div class="ledger-card">
        <h2>Persona Modules & Reports</h2>
        <table class="ledger-table">
            <thead>
                <tr>
                    <th>Module Name</th>
                    <th>Description</th>
                    <th>Type</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong>AR Manager Ledger</strong></td>
                    <td>Accounts Receivable collections view & credit limit risk tiering</td>
                    <td><span class="stamp stamp-clear">Report</span></td>
                    <td><a href="/reports/ar-manager" class="action-btn" target="_blank">View Live Report</a></td>
                </tr>
                <tr>
                    <td><strong>AP Manager Ledger</strong></td>
                    <td>Accounts Payable payment optimization & early discount capture</td>
                    <td><span class="stamp stamp-watch">Report</span></td>
                    <td><span class="mono" style="color: var(--text-muted);">Ready (Phase 2)</span></td>
                </tr>
                <tr>
                    <td><strong>SO & PI Document Builder</strong></td>
                    <td>Creates draft Sales Orders and Purchase Invoices in Business Central</td>
                    <td><span class="stamp stamp-critical">Draft Action</span></td>
                    <td><span class="mono" style="color: var(--text-muted);">Staged Mode</span></td>
                </tr>
                <tr>
                    <td><strong>Demand & Forecast Engine</strong></td>
                    <td>Inventory reorder analytics and historical demand trends</td>
                    <td><span class="stamp stamp-clear">Analytics</span></td>
                    <td><span class="mono" style="color: var(--text-muted);">Ready (Phase 2)</span></td>
                </tr>
            </tbody>
        </table>
    </div>
</body>
</html>
"""


def render_settings_html(client_data: dict, rules_data: dict, message: str = "") -> str:
    notice_html = f'<div style="padding:12px; background:#E6F4F1; color:#0E6251; border-radius:6px; margin-bottom:20px;">{escape_html(message)}</div>' if message else ''
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Opsmeld Engine - Settings</title>
    <style>
    {LEDGER_CSS}
    .form-group {{
        margin-bottom: 18px;
    }}
    .form-group label {{
        display: block;
        font-weight: 600;
        margin-bottom: 6px;
        font-size: 0.9rem;
    }}
    .form-group input, .form-group select {{
        width: 100%;
        padding: 10px 12px;
        border: 1px solid var(--border-color);
        border-radius: 6px;
        font-family: inherit;
        font-size: 0.95rem;
        box-sizing: border-box;
    }}
    .submit-btn {{
        padding: 12px 24px;
        background: #0E6251;
        color: white;
        border: none;
        border-radius: 6px;
        font-weight: 600;
        font-size: 1rem;
        cursor: pointer;
    }}
    </style>
</head>
<body>
    <div style="margin-bottom: 20px;">
        <a href="/" style="color: var(--text-muted); text-decoration: none;">← Back to Dashboard Hub</a>
    </div>

    <h1>Configuration Center</h1>
    <p style="color: var(--text-muted);">Manage Business Central Azure Entra ID credentials and operational rules without editing code.</p>

    {notice_html}

    <form method="POST" action="/api/settings">
        <div class="ledger-card">
            <h2>Business Central Connection Setup</h2>
            <div class="form-group">
                <label for="name">Company Profile Name</label>
                <input type="text" id="name" name="name" value="{escape_html(client_data.get('name', ''))}" required>
            </div>
            <div class="form-group">
                <label for="tenant_id">Azure Entra Tenant ID</label>
                <input type="text" id="tenant_id" name="tenant_id" class="mono" value="{escape_html(client_data.get('tenant_id', ''))}" placeholder="e.g. db961cfa-xxxx-xxxx-xxxx-xxxxxxxxxxxx" required>
            </div>
            <div class="form-group">
                <label for="app_client_id">Azure App Client ID</label>
                <input type="text" id="app_client_id" name="app_client_id" class="mono" value="{escape_html(client_data.get('app_client_id', ''))}" placeholder="e.g. 00000000-xxxx-xxxx-xxxx-xxxxxxxxxxxx" required>
            </div>
            <div class="form-group">
                <label for="environment">Business Central Environment</label>
                <input type="text" id="environment" name="environment" value="{escape_html(client_data.get('environment', 'Production'))}" required>
            </div>
            <div class="form-group">
                <label for="company_name">Business Central Company Name</label>
                <input type="text" id="company_name" name="company_name" value="{escape_html(client_data.get('company_name', 'CRONUS USA, Inc.'))}" required>
            </div>
        </div>

        <div class="ledger-card">
            <h2>Operational Rules & Safety Policy</h2>
            <div class="form-group">
                <label for="safety_mode">Safety Execution Mode</label>
                <select id="safety_mode" name="safety_mode">
                    <option value="staged" selected>Staged Mode (Draft Actions Only, Do Not Post)</option>
                    <option value="read_only">Read-Only Mode (Display Reports Only)</option>
                </select>
            </div>
            <div class="form-group">
                <label for="tier_critical_overdue_days">AR Risk Critical Threshold (Days Overdue)</label>
                <input type="number" id="tier_critical_overdue_days" name="tier_critical_overdue_days" value="{rules_data.get('ar_manager', {}).get('tier_critical_overdue_days', 60)}">
            </div>
            <div class="form-group">
                <label for="credit_limit_warning_pct">Credit Limit Warning Ratio (e.g. 0.85 = 85%)</label>
                <input type="text" id="credit_limit_warning_pct" name="credit_limit_warning_pct" value="{rules_data.get('ar_manager', {}).get('credit_limit_warning_pct', 0.85)}">
            </div>
        </div>

        <button type="submit" class="submit-btn">Save Configuration</button>
    </form>
</body>
</html>
"""
