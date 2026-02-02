# Project Sentinel
![Status](https://img.shields.io/badge/Status-Prototype-orange?style=for-the-badge)
![Security](https://img.shields.io/badge/Security-Economic%20Security-blue?style=for-the-badge)
![Stack](https://img.shields.io/badge/Tech-Python%20%7C%20PostgreSQL-green?style=for-the-badge&logo=python)
![Focus](https://img.shields.io/badge/Focus-HBM%20Supply%20Chain-red?style=for-the-badge)
OSINT-driven supply chain risk assessment system for semiconductor chokepoints.

## Features

- **HBM Supply Chain Monitoring**: Track High Bandwidth Memory flows from Korean chokepoints
- **Export Control Violation Detection**: Identify potential sanctions evasion patterns
- **Multi-hop Smuggling Route Analysis**: Recursive CTE queries for circular trade detection
- **Risk Scoring**: Composite assessment across kinetic, economic, and policy dimensions

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  OSINT Signals  │────▶│  Risk Pipeline   │────▶│   Dashboard     │
│  (signals.jsonl)│     │  (sentinel.py)   │     │  (SQL views)    │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────────┐
                        │   PostgreSQL     │
                        │   (schema2.sql)  │
                        └──────────────────┘
```

## Quick Start

1. Clone repository
   ```bash
   git clone https://github.com/YOUR_USERNAME/Project-Sentinel.git
   cd Project-Sentinel
   ```

2. Install dependencies
   ```bash
   pip install -r requirements.txt
   ```

3. Configure environment
   ```bash
   cp .env.example .env
   # Edit .env with your database credentials
   ```

4. Initialize database
   ```bash
   psql -f schema2.sql
   ```

5. Run pipeline
   ```bash
   python sentinel.py
   ```

## Database Schema

- **supply_nodes**: Entities in supply chain (IP holders, chokepoints, proxies, end-users)
- **shipments**: HBM module transactions with manifest data
- **osint_signal**: Structured intelligence from think tanks and news sources
- **risk_assessments**: Computed risk scores with evidence chains

## Key Queries

- `analytics.sql`: Multi-hop smuggling route detection via recursive CTE
- `dashboardd.sql`: Risk assessment visualization queries

## License

MIT
---
### ⚠️ Disclaimer
This repository is a **research prototype** developed to demonstrate the technical feasibility of AI-augmented export controls. It uses open-source data (OSINT) only. No classified military intelligence or proprietary trade secrets were accessed during its development.
