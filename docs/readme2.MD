# 🤖 Vibe Coding Prompt: Project Sentinel (PostgreSQL Ver.)

**Role:** Senior Data Engineer at a Defense Think Tank.
**Goal:** Build a backend for "Project Sentinel," a supply chain monitoring system backed by PostgreSQL.

**Tech Stack:**
1.  **Database:** PostgreSQL 16 (Production-grade).
2.  **Language:** Python (using `psycopg2` and `pandas`).
3.  **Data Modeling:** Use Relational tables for Nodes, but `JSONB` for storing unstructured OSINT signals (flexibility).

**Requirements:**
1.  **Schema Design (`schema.sql`):**
    * Table `nodes`: Stores supply chain entities (US IP, KR Foundry, CN End-user).
    * Table `shipments`: Records transactions. Use `JSONB` column for 'cargo_manifest' details.
    * **Indexing:** Create a GIN index on the JSONB column for high-speed signal searching.
2.  **Logic (`sentinel_db.py`):**
    * Write a Python class that connects to Postgres.
    * Implement a function `detect_leakage()` that runs a SQL query to find HBM shipments routed to non-ally regions.
3.  **SQL Strategy:**
    * Use **Common Table Expressions (CTEs)** for readability.
    * Demonstrate "Recursive Queries" to trace multi-hop smuggling routes.

**Tone:** Highly technical, focused on data integrity and query performance.