<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>
```
# <q>원하시는 DB는 (A)만 Postgres라고 했는데, (B)(C)도 Postgres로 통일</q> 통일로 합쳐서 출력
```

PostgreSQL로 **A(리플 이펙트) + B(제재리스트 동기화) + C(FastAPI 백엔드)** 전부 통일한 “Project Sentinel” 프로토타입을 아래에 한 번에 제공합니다.
제재 리스트는 프로토타입 단계에서 OpenSanctions의 “Consolidated/UNSC” 같은 공개 데이터셋을 동기화 소스로 사용할 수 있습니다.[^1][^2]

***

## 1) PostgreSQL DDL (노드/에지/OSINT/제재/리플/평가)

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1) Supply chain graph
CREATE TABLE IF NOT EXISTS supply_chain_node (
  node_id TEXT PRIMARY KEY,
  node_name TEXT NOT NULL,
  node_type TEXT NOT NULL,         -- memory_maker, packaging, material, equipment, fab, logistics
  country_code TEXT,
  parent_org TEXT,
  criticality_score REAL NOT NULL DEFAULT 0.5,   -- 0..1
  chokepoint_flag BOOLEAN NOT NULL DEFAULT FALSE,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS supply_chain_edge (
  edge_id TEXT PRIMARY KEY,
  from_node_id TEXT NOT NULL REFERENCES supply_chain_node(node_id) ON DELETE CASCADE,
  to_node_id   TEXT NOT NULL REFERENCES supply_chain_node(node_id) ON DELETE CASCADE,
  dependency_type TEXT NOT NULL,    -- supplies, packages, fabricates_for, ships_for
  dependency_weight REAL NOT NULL DEFAULT 0.5,  -- 0..1
  UNIQUE(from_node_id, to_node_id, dependency_type)
);

CREATE INDEX IF NOT EXISTS idx_edge_from ON supply_chain_edge(from_node_id);
CREATE INDEX IF NOT EXISTS idx_edge_to ON supply_chain_edge(to_node_id);

-- 2) Sanctions (normalized)
CREATE TABLE IF NOT EXISTS sanctioned_entity (
  entity_id TEXT PRIMARY KEY,
  entity_name TEXT NOT NULL,
  regime TEXT NOT NULL,            -- UN / EU / US_OFAC / US_BIS / etc
  program TEXT,
  listed_on_utc TIMESTAMPTZ,
  source_url TEXT,
  notes TEXT,
  updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sanction_regime ON sanctioned_entity(regime);
CREATE INDEX IF NOT EXISTS idx_sanction_name ON sanctioned_entity(entity_name);

-- 3) OSINT signals (JSON interchange)
CREATE TABLE IF NOT EXISTS osint_signal (
  signal_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  collected_at_utc TIMESTAMPTZ NOT NULL,
  source_type TEXT NOT NULL,       -- web|academic_db|sns
  source_name TEXT,
  url TEXT,
  lang TEXT NOT NULL DEFAULT 'english',
  title TEXT,
  summary TEXT,
  raw_json JSONB NOT NULL,
  sha256 TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_signal_time ON osint_signal(collected_at_utc DESC);

-- Link signals to nodes/entities
CREATE TABLE IF NOT EXISTS signal_link (
  link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  signal_id UUID NOT NULL REFERENCES osint_signal(signal_id) ON DELETE CASCADE,
  node_id TEXT REFERENCES supply_chain_node(node_id) ON DELETE SET NULL,
  entity_id TEXT REFERENCES sanctioned_entity(entity_id) ON DELETE SET NULL,
  mention_confidence REAL NOT NULL DEFAULT 0.5,
  UNIQUE(signal_id, node_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_link_signal ON signal_link(signal_id);
CREATE INDEX IF NOT EXISTS idx_link_node ON signal_link(node_id);
CREATE INDEX IF NOT EXISTS idx_link_entity ON signal_link(entity_id);

-- 4) Ripple effect results (graph expansion output)
CREATE TABLE IF NOT EXISTS ripple_effect (
  ripple_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assessed_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),
  adversary_node TEXT NOT NULL REFERENCES supply_chain_node(node_id) ON DELETE CASCADE,
  affected_node  TEXT NOT NULL REFERENCES supply_chain_node(node_id) ON DELETE CASCADE,
  hop_depth INT NOT NULL,
  path_weight REAL NOT NULL,
  chokepoint_status TEXT NOT NULL, -- green|amber|red
  kinetic_impact REAL NOT NULL,    -- 0..1
  economic_impact REAL NOT NULL,   -- 0..1
  policy_impact REAL NOT NULL,     -- 0..1
  composite_risk REAL NOT NULL,    -- 0..1
  evidence_json JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ripple_time ON ripple_effect(assessed_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_ripple_adv ON ripple_effect(adversary_node, assessed_at_utc DESC);
```


***

## 2) A) Postgres Ripple Effect SQL (edge 기반 자동 확장)

`WITH RECURSIVE`로 그래프를 확장하고, 감쇠(decay)와 경로가중치(path_weight)로 ripple을 계량합니다.

```sql
-- Parameters:
-- :adversary_node   text
-- :max_hops         int
-- :decay            real (0.0..1.0), e.g., 0.85
-- :min_path_weight  real, e.g., 0.08
-- :run_notes        text (optional)

WITH RECURSIVE traverse AS (
  SELECT
    e.from_node_id AS adversary_node,
    e.to_node_id   AS affected_node,
    1              AS hop_depth,
    (e.dependency_weight * :decay) AS path_weight,
    ARRAY[e.from_node_id, e.to_node_id]::text[] AS path_nodes
  FROM supply_chain_edge e
  WHERE e.from_node_id = :adversary_node

  UNION ALL

  SELECT
    t.adversary_node,
    e.to_node_id AS affected_node,
    t.hop_depth + 1 AS hop_depth,
    (t.path_weight * e.dependency_weight * :decay) AS path_weight,
    (t.path_nodes || e.to_node_id)::text[] AS path_nodes
  FROM traverse t
  JOIN supply_chain_edge e ON e.from_node_id = t.affected_node
  WHERE t.hop_depth < :max_hops
    AND NOT (e.to_node_id = ANY(t.path_nodes))
),
scored AS (
  SELECT
    adversary_node,
    affected_node,
    MIN(hop_depth) AS hop_depth,
    MAX(path_weight) AS path_weight
  FROM traverse
  GROUP BY adversary_node, affected_node
  HAVING MAX(path_weight) >= :min_path_weight
),
impact AS (
  SELECT
    s.*,
    n.criticality_score,
    n.chokepoint_flag
  FROM scored s
  JOIN supply_chain_node n ON n.node_id = s.affected_node
),
final_calc AS (
  SELECT
    adversary_node,
    affected_node,
    hop_depth,
    path_weight,
    LEAST(1.0, 0.20 + 0.55*(CASE WHEN chokepoint_flag THEN 1 ELSE 0 END) + 0.25*criticality_score) AS kinetic_impact,
    LEAST(1.0, 0.15 + 0.65*criticality_score) AS economic_impact,
    LEAST(1.0, 0.10 + 0.60*(1.0 - path_weight) + 0.30*criticality_score) AS policy_impact
  FROM impact
),
final_scored AS (
  SELECT
    *,
    LEAST(1.0, 0.35*kinetic_impact + 0.40*economic_impact + 0.25*policy_impact) AS composite_risk,
    CASE
      WHEN LEAST(1.0, 0.35*kinetic_impact + 0.40*economic_impact + 0.25*policy_impact) >= 0.75 THEN 'red'
      WHEN LEAST(1.0, 0.35*kinetic_impact + 0.40*economic_impact + 0.25*policy_impact) >= 0.45 THEN 'amber'
      ELSE 'green'
    END AS chokepoint_status
  FROM final_calc
)
INSERT INTO ripple_effect (
  adversary_node, affected_node, hop_depth, path_weight,
  chokepoint_status, kinetic_impact, economic_impact, policy_impact, composite_risk,
  evidence_json
)
SELECT
  adversary_node, affected_node, hop_depth, path_weight,
  chokepoint_status, kinetic_impact, economic_impact, policy_impact, composite_risk,
  jsonb_build_object(
    'method','recursive_edge_ripple',
    'max_hops', :max_hops,
    'decay', :decay,
    'min_path_weight', :min_path_weight,
    'run_notes', :run_notes
  )
FROM final_scored
ON CONFLICT DO NOTHING;  -- prototype: avoid accidental duplicates by policy, or add a uniqueness key later
```


***

## 3) B) 제재 리스트 동기화(UNSC 등) → Postgres Upsert

프로토타입: OpenSanctions의 UNSC 통합 데이터셋(예: `un_sc_sanctions`)을 사용해 `targets.simple.csv`를 주기적으로 동기화합니다.[^2]
추가로, OpenSanctions “Consolidated Sanctions”도 데이터셋으로 제공됩니다.[^1]

### 3-A) 동기화 DDL 보강(업서트 키)

```sql
ALTER TABLE sanctioned_entity
  ADD COLUMN IF NOT EXISTS source_dataset TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_sanction_key
ON sanctioned_entity(regime, entity_name, COALESCE(source_dataset,''));  -- 실무에서는 entity_id를 소스의 stable id로 맞추는 것을 권장
```


### 3-B) `sync_sanctions_pg.py` (UNSC + Consolidated 예시)

```python
# sync_sanctions_pg.py
# pip install "psycopg[binary]" requests

import csv, io, os, hashlib, datetime, requests
import psycopg

UNSC_SIMPLE_CSV = "https://data.opensanctions.org/datasets/latest/un_sc_sanctions/targets.simple.csv"  # [web:963]
CONS_SIMPLE_CSV = "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv"       # [web:981]

UPSERT_SQL = """
INSERT INTO sanctioned_entity
(entity_id, entity_name, regime, program, listed_on_utc, source_url, source_dataset, notes, updated_at_utc)
VALUES
(%(entity_id)s,%(entity_name)s,%(regime)s,%(program)s,%(listed_on_utc)s,%(source_url)s,%(source_dataset)s,%(notes)s,now())
ON CONFLICT (entity_id) DO UPDATE SET
  entity_name = EXCLUDED.entity_name,
  regime = EXCLUDED.regime,
  program = EXCLUDED.program,
  listed_on_utc = EXCLUDED.listed_on_utc,
  source_url = EXCLUDED.source_url,
  source_dataset = EXCLUDED.source_dataset,
  notes = EXCLUDED.notes,
  updated_at_utc = now();
"""

def utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def stable_entity_id(regime: str, source_dataset: str, name: str) -> str:
    key = f"{regime}|{source_dataset}|{name}".encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:32]

def ingest_csv(dsn: str, url: str, regime: str, source_dataset: str, notes: str) -> int:
    r = requests.get(url, timeout=120)
    r.raise_for_status()

    reader = csv.DictReader(io.StringIO(r.text))
    rows = 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            for rec in reader:
                name = (rec.get("name") or rec.get("caption") or "").strip()
                if not name:
                    continue
                entity_id = stable_entity_id(regime, source_dataset, name)
                cur.execute(UPSERT_SQL, {
                    "entity_id": entity_id,
                    "entity_name": name,
                    "regime": regime,
                    "program": rec.get("topics") or None,
                    "listed_on_utc": utc_now(),
                    "source_url": rec.get("source_url") or None,
                    "source_dataset": source_dataset,
                    "notes": notes
                })
                rows += 1
        conn.commit()
    return rows

if __name__ == "__main__":
    dsn = os.environ["PG_DSN"]
    n1 = ingest_csv(dsn, UNSC_SIMPLE_CSV, regime="UN", source_dataset="un_sc_sanctions",
                    notes="ingested_from=opensanctions un_sc_sanctions")  # [web:963]
    n2 = ingest_csv(dsn, CONS_SIMPLE_CSV, regime="CONSOLIDATED", source_dataset="sanctions",
                    notes="ingested_from=opensanctions consolidated sanctions")            # [web:981]
    print({"un": n1, "consolidated": n2})
```


***

## 4) C) FastAPI + psycopg3: 실행형 백엔드(대시보드용)

FastAPI에서 psycopg 연결은 “요청당 연결(or 풀)” 패턴으로 안정적으로 운영할 수 있습니다.[^3]

### 4-A) `api.py` (최소 실행 가능)

```python
# api.py
# pip install fastapi uvicorn "psycopg[binary]" requests

import os, json
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import psycopg

PG_DSN = os.environ["PG_DSN"]
app = FastAPI(title="Project Sentinel (HBM Supply Chain Risk)")

class RippleRequest(BaseModel):
    adversary_node: str
    max_hops: int = 3
    decay: float = 0.85
    min_path_weight: float = 0.08
    run_notes: str | None = "project_sentinel"

RIPPLE_SQL = open("ripple.sql", "r", encoding="utf-8").read()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/assess/ripple")
def assess_ripple(req: RippleRequest):
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(RIPPLE_SQL, {
                "adversary_node": req.adversary_node,
                "max_hops": req.max_hops,
                "decay": req.decay,
                "min_path_weight": req.min_path_weight,
                "run_notes": req.run_notes
            })
        conn.commit()
    return {"status": "completed", "adversary_node": req.adversary_node}

@app.get("/risks/latest")
def risks_latest(limit: int = 50):
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT assessed_at_utc, adversary_node, affected_node, hop_depth,
                     chokepoint_status, composite_risk, kinetic_impact, economic_impact, policy_impact,
                     evidence_json
              FROM ripple_effect
              ORDER BY assessed_at_utc DESC, composite_risk DESC
              LIMIT %s
            """, (limit,))
            cols = [d[^0] for d in cur.description]
            return {"rows": [dict(zip(cols, r)) for r in cur.fetchall()]}

@app.get("/sanctions/search")
def sanctions_search(q: str, limit: int = 25):
    # prototype string match; production: trigram index / full-text
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT entity_id, entity_name, regime, program, source_url, updated_at_utc
              FROM sanctioned_entity
              WHERE lower(entity_name) LIKE lower(%s)
              ORDER BY updated_at_utc DESC
              LIMIT %s
            """, (f"%{q}%", limit))
            cols = [d[^0] for d in cur.description]
            return {"rows": [dict(zip(cols, r)) for r in cur.fetchall()]}
```


### 4-B) 실행 방법

- `ripple.sql` 파일에 2)A의 INSERT…SELECT SQL을 그대로 저장
- 실행: `uvicorn api:app --host 0.0.0.0 --port 8000`

***

## 5) 운영용 최소 디렉터리 구조

```text
project_sentinel/
  schema.sql
  ripple.sql
  sync_sanctions_pg.py
  api.py
  requirements.txt
```

`requirements.txt`

```text
fastapi
uvicorn
psycopg[binary]
requests
pydantic
```

원하시면, (1) `sanctioned_entity`에 **name alias(별칭) 테이블**을 추가해 매칭 정확도를 올리고, (2) `ripple_effect`에 `(assessed_at_utc, adversary_node, affected_node)` 유니크 키를 둬서 중복 적재를 완전히 차단하는 버전까지 “프로덕션 드랍인” 형태로 마무리해 드릴 수 있습니다.
<span style="display:none">[^10][^11][^12][^13][^14][^15][^16][^17][^18][^19][^20][^21][^22][^23][^24][^25][^26][^27][^28][^29][^30][^31][^4][^5][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://www.opensanctions.org/datasets/sanctions/

[^2]: https://www.opensanctions.org/datasets/un_sc_sanctions/

[^3]: https://blog.danielclayton.co.uk/posts/database-connections-with-fastapi/

[^4]: gaza_militia_analysis_report.md

[^5]: Objective-KeyResults-ODCafeteria.csv

[^6]: --URL.csv

[^7]: --.csv

[^8]: equality_of_arms_essay_final.txt

[^9]: readme8.MD

[^10]: guggajeongbohagyi_DCPAD_ceorijeolcaro_yeongeogweon-junggugeogweon-webgwa-hagsul-DBro-repeoreonseureul-jehanhayeo.md

[^11]: http://arxiv.org/pdf/2110.09635v1.pdf

[^12]: http://arxiv.org/pdf/2411.14829.pdf

[^13]: https://arxiv.org/html/2411.10609v1

[^14]: https://www.mdpi.com/2306-5729/7/11/153/pdf?version=1667831241

[^15]: http://ijece.iaescore.com/index.php/IJECE/article/download/17507/12977

[^16]: https://dl.acm.org/doi/pdf/10.1145/3607199.3607242

[^17]: https://arxiv.org/pdf/1810.03115.pdf

[^18]: https://arxiv.org/pdf/2207.00220.pdf

[^19]: https://www.opensanctions.org/datasets/default/

[^20]: https://dataresearchcenter.org/library/all/

[^21]: https://github.com/opensanctions/opensanctions

[^22]: https://dataresearchcenter.org/library/sanctions/

[^23]: https://github.com/chuck-alt-delete/fastapi_psycopg3_example

[^24]: https://stackoverflow.com/questions/79384228/batch-insert-data-using-psycopg2-vs-psycopg3

[^25]: https://docs.ofac-api.com/datasources

[^26]: https://naysan.ca/2020/05/16/pandas-to-postgresql-using-psycopg2-bulk-insert-using-execute_values/

[^27]: https://sanctions.network

[^28]: https://taejoone.jeju.onl/posts/psycopg3-postgres-example/

[^29]: https://jacopofarina.eu/posts/ingest-data-into-postgres-fast/

[^30]: https://bellingcat.gitbook.io/toolkit/more/all-tools/opensanctions

[^31]: https://spwoodcock.dev/blog/2024-10-fastapi-pydantic-psycopg/

