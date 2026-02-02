# Project Sentinel

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
