"""
Opsmeld Reconciliation Engine - Ledger Theme Design System
Shared CSS styling and HTML escaping utilities for persona reports and dashboards.
"""

import html

LEDGER_CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&family=Spectral:wght@500;600;700&display=swap');

:root {
  --bg-primary: #F8FAF9;
  --bg-card: #FFFFFF;
  --text-main: #1A2321;
  --text-muted: #596562;
  --border-color: #E2E8E5;
  
  /* Semantic Tiers */
  --teal-bg: #E6F4F1;
  --teal-text: #0E6251;
  --teal-border: #A3E4D7;
  
  --amber-bg: #FEF9E7;
  --amber-text: #7D6608;
  --amber-border: #F9E79F;
  
  --rust-bg: #FDEDEC;
  --rust-text: #78281F;
  --rust-border: #F5B7B1;
}

body {
  font-family: 'Inter', sans-serif;
  background-color: var(--bg-primary);
  color: var(--text-main);
  margin: 0;
  padding: 32px;
}

h1, h2, h3 {
  font-family: 'Spectral', serif;
  color: var(--text-main);
  margin-top: 0;
}

.mono, .amount, .count, .doc-id {
  font-family: 'IBM Plex Mono', monospace;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}

.stat-tile {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

.stat-tile .label {
  font-size: 0.85rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 8px;
}

.stat-tile .value {
  font-size: 1.6rem;
  font-weight: 600;
}

.ledger-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.03);
}

.ledger-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 16px;
}

.ledger-table th, .ledger-table td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid var(--border-color);
}

.ledger-table th {
  font-size: 0.85rem;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: #F1F5F3;
}

.stamp {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.stamp-clear, .stamp-pay-now, .stamp-healthy {
  background: var(--teal-bg);
  color: var(--teal-text);
  border: 1px solid var(--teal-border);
}

.stamp-watch, .stamp-pay-soon, .stamp-warning {
  background: var(--amber-bg);
  color: var(--amber-text);
  border: 1px solid var(--amber-border);
}

.stamp-collect, .stamp-critical, .stamp-risk {
  background: var(--rust-bg);
  color: var(--rust-text);
  border: 1px solid var(--rust-border);
}

.split-bar {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  margin: 12px 0;
}

.split-bar-clear { background: var(--teal-text); }
.split-bar-watch { background: var(--amber-text); }
.split-bar-collect { background: var(--rust-text); }
"""


def escape_html(value: str) -> str:
    """Escapes user input string to prevent XSS in generated HTML reports."""
    if value is None:
        return ""
    return html.escape(str(value))
