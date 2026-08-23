# Opsmeld Reconciliation Engine — Business Central MCP

An intelligent, modular reconciliation engine and active financial operations assistant for Microsoft Dynamics 365 Business Central powered by Model Context Protocol (MCP).

## Overview

Opsmeld connects to Business Central via MCP to fetch subledger data, analyze risks, generate executive persona reports (AR Manager, AP Manager), and build staged draft actions (Sales Orders, Purchase Invoices, General Journal Vouchers).

## Architecture & Features

- **Multi-Tenant Configuration Engine**: Configure tenant IDs and rules safely via web UI or `config/clients.json`.
- **Web Control Center (`server.py`)**: Centralized dashboard on `http://localhost:8000`.
- **AR Manager Persona Module**: Credit utilization risk tiering (`COLLECT`, `WATCH`, `CLEAR`).
- **Ledger Design System**: Standardized styling with Spectral, Inter, IBM Plex Mono, and XSS protection.
- **Safety Mode (`STAGED`)**: Unposted draft document creation (`Do Not Post`).

## Getting Started

1. Start the web management console:
   ```bash
   python server.py
   ```
2. Open `http://localhost:8000` in your browser.
3. Configure your Business Central connection at `http://localhost:8000/settings`.
