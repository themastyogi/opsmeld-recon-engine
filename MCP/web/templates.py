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
    <title>Opsmeld Engine - Configuration & Settings</title>
    <style>
    {LEDGER_CSS}
    :root {{
      --nav-dark: #0B2920;
      --nav-active: #143F33;
    }}
    body {{
        margin: 0;
        padding: 0;
        background-color: #F4F6F5;
        font-family: 'Inter', sans-serif;
    }}
    .top-header {{
      background: var(--nav-dark);
      color: white;
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0 24px;
      height: 54px;
    }}
    .top-nav {{
      display: flex;
      gap: 4px;
      height: 100%;
    }}
    .top-nav-item {{
      padding: 0 16px;
      display: flex;
      align-items: center;
      color: #9CA3AF;
      font-size: 0.9rem;
      font-weight: 500;
      cursor: pointer;
      text-decoration: none;
    }}
    .top-nav-item:hover, .top-nav-item.active {{
      color: white;
      background: var(--nav-active);
    }}
    .settings-container {{
      max-width: 1000px;
      margin: 28px auto;
      padding: 0 24px;
    }}
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
    <div class="top-header">
        <div style="display: flex; align-items: center; gap: 24px;">
            <div style="font-weight: 800; font-size: 1.1rem; letter-spacing: -0.02em;">🟢 opsmeld</div>
            <div class="top-nav">
                <a href="/" class="top-nav-item">Collections</a>
                <a href="/" class="top-nav-item">🛡️ Data Trust</a>
                <a href="/settings" class="top-nav-item active">⚙️ Configuration</a>
            </div>
        </div>
        <div style="font-size: 0.85rem;">
            <a href="/" style="color: #9CA3AF; text-decoration: none;">← Return to App Shell</a>
        </div>
    </div>

    <div class="settings-container">
        <h1>Configuration Center</h1>
        <p style="color: var(--text-muted);">Manage shared Business Central Azure Entra connection credentials and Data Trust operational rules.</p>

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
            <h2>🛡️ Data Trust Rule Packs Configuration</h2>
            <p style="color: var(--text-muted); font-size: 0.88rem;">Configure Data Trust evaluation policies. Rule Packs 1 and 2 operate deterministically; Rule Pack 3 evaluates candidate naration divergence.</p>
            
            <div style="border-bottom: 1px solid var(--border-color); margin-bottom: 16px; display: flex; gap: 12px;">
                <button type="button" onclick="showSettingsTab('pd')" id="tab-btn-pd" style="padding: 8px 16px; background: #0E6251; color: white; border: none; border-radius: 4px 4px 0 0; font-weight: 600; cursor: pointer;">Rule Pack 1: Posting-Date Policy</button>
                <button type="button" onclick="showSettingsTab('sb')" id="tab-btn-sb" style="padding: 8px 16px; background: #E5E7EB; color: #374151; border: none; border-radius: 4px 4px 0 0; font-weight: 600; cursor: pointer;">Rule Pack 2: Subledger Bypass</button>
                <button type="button" onclick="showSettingsTab('tax')" id="tab-btn-tax" style="padding: 8px 16px; background: #E5E7EB; color: #374151; border: none; border-radius: 4px 4px 0 0; font-weight: 600; cursor: pointer;">Rule Pack 3: Narration Taxonomy</button>
            </div>

            <!-- Tab 1: Posting Date Policy -->
            <div id="tab-pd" style="display: block;">
                <div class="form-group">
                    <label>Scope Selector</label>
                    <select id="dt_scope_type" name="dt_scope_type">
                        <option value="Company" selected>Company Default</option>
                        <option value="User">User Specific</option>
                        <option value="User Group">User Group</option>
                        <option value="Document Type">Document Type Specific</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>Allowed Posting Mode</label>
                    <select id="dt_posting_mode" name="dt_posting_mode">
                        <option value="CURRENT_MONTH" selected>CURRENT_MONTH (Current Calendar Month)</option>
                        <option value="TODAY_ONLY">TODAY_ONLY (Posting Date must match Today)</option>
                        <option value="OPEN_PERIOD">OPEN_PERIOD (Any Open Accounting Period)</option>
                        <option value="CUSTOM_RANGE">CUSTOM_RANGE (Custom Days Allowance)</option>
                    </select>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px;">
                    <div class="form-group">
                        <label>Max Backdating Days</label>
                        <input type="number" name="dt_max_backdate" value="7">
                    </div>
                    <div class="form-group">
                        <label>Approval Threshold (Days)</label>
                        <input type="number" name="dt_appr_backdate" value="3">
                    </div>
                    <div class="form-group">
                        <label>Max Future-Dating Days</label>
                        <input type="number" name="dt_max_future" value="2">
                    </div>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
                    <div class="form-group">
                        <label>Month Close Date</label>
                        <input type="text" name="dt_month_close" value="2026-08-31" placeholder="YYYY-MM-DD">
                    </div>
                    <div class="form-group">
                        <label>Month Close Adjustment Window (Days)</label>
                        <input type="number" name="dt_month_adj" value="5">
                    </div>
                </div>
            </div>

            <!-- Tab 2: Subledger Bypass Control Accounts -->
            <div id="tab-sb" style="display: none;">
                <p style="font-size: 0.85rem; color: var(--text-muted);">Mapped Subledger Control Accounts monitored for direct manual G/L entry bypasses.</p>
                <table class="ledger-table" style="margin-bottom: 12px;">
                    <thead>
                        <tr>
                            <th>Account No</th>
                            <th>Account Name</th>
                            <th>Subledger Type</th>
                            <th>Expected Sources</th>
                            <th>Direct Posting</th>
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td><strong class="mono">10200</strong></td>
                            <td>Accounts Payable Control</td>
                            <td><span class="stamp stamp-watch">VENDOR</span></td>
                            <td><span class="mono">Purchase, Payables</span></td>
                            <td><span style="color:#DC2626; font-weight:700;">Disabled</span></td>
                        </tr>
                        <tr>
                            <td><strong class="mono">10100</strong></td>
                            <td>Accounts Receivable Control</td>
                            <td><span class="stamp stamp-watch">CUSTOMER</span></td>
                            <td><span class="mono">Sales, Receivables</span></td>
                            <td><span style="color:#DC2626; font-weight:700;">Disabled</span></td>
                        </tr>
                        <tr>
                            <td><strong class="mono">10500</strong></td>
                            <td>Inventory Control Account</td>
                            <td><span class="stamp stamp-watch">ITEM</span></td>
                            <td><span class="mono">Inventory, Purchase</span></td>
                            <td><span style="color:#DC2626; font-weight:700;">Disabled</span></td>
                        </tr>
                        <tr>
                            <td><strong class="mono">20100</strong></td>
                            <td>Bank Account Control</td>
                            <td><span class="stamp stamp-watch">BANK</span></td>
                            <td><span class="mono">Bank, Payment</span></td>
                            <td><span style="color:#DC2626; font-weight:700;">Disabled</span></td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Tab 3: Narration Category Taxonomy -->
            <div id="tab-tax" style="display: none;">
                <div class="form-group">
                    <label>Minimum Peer History Transactions (N1 Rare Narration Threshold)</label>
                    <input type="number" name="dt_min_peer" value="20" placeholder="Minimum transactions required for baseline evaluation (Default: 20)">
                    <small style="color: var(--text-muted); display: block; margin-top: 4px;">Baseline-dependent checks hard-gate on this threshold. Below 20 historical transactions, N1 evaluates to Not Evaluated.</small>
                </div>
                <div class="form-group">
                    <label>Level 2 Client Category Mappings (JSON Format)</label>
                    <textarea name="dt_taxonomy_json" style="width: 100%; height: 110px; font-family: monospace; font-size: 0.85rem; padding: 8px; border: 1px solid var(--border-color); border-radius: 6px;">{{
  "Office Supplies": ["stationery", "printer", "paper", "toner", "furniture", "desk", "chair"],
  "Raw Materials": ["steel", "aluminium", "plastic", "metal", "sheet", "resin"],
  "Professional Fees": ["legal", "audit", "consulting", "advisory", "tax", "accounting"],
  "IT Hardware & Software": ["laptop", "monitor", "keyboard", "server", "software", "license"],
  "Travel & Entertainment": ["flight", "hotel", "taxi", "meal", "travel", "lodging"]
}}</textarea>
                </div>
            </div>

        </div>

        <button type="submit" class="submit-btn">Save Configuration</button>
    </form>

    <script>
    function showSettingsTab(tabKey) {{
        document.getElementById('tab-pd').style.display = tabKey === 'pd' ? 'block' : 'none';
        document.getElementById('tab-sb').style.display = tabKey === 'sb' ? 'block' : 'none';
        document.getElementById('tab-tax').style.display = tabKey === 'tax' ? 'block' : 'none';

        document.getElementById('tab-btn-pd').style.background = tabKey === 'pd' ? '#0E6251' : '#E5E7EB';
        document.getElementById('tab-btn-pd').style.color = tabKey === 'pd' ? 'white' : '#374151';

        document.getElementById('tab-btn-sb').style.background = tabKey === 'sb' ? '#0E6251' : '#E5E7EB';
        document.getElementById('tab-btn-sb').style.color = tabKey === 'sb' ? 'white' : '#374151';

        document.getElementById('tab-btn-tax').style.background = tabKey === 'tax' ? '#0E6251' : '#E5E7EB';
        document.getElementById('tab-btn-tax').style.color = tabKey === 'tax' ? 'white' : '#374151';
    }}
    </script>
    </div>
</body>
</html>
"""
