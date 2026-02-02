<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>
```
# <q>(1) sanctioned_entity에 name alias(별칭) 테이블을 추가해 매칭 정확도를 올리고, (2) ripple_effect에 (assessed_at_utc, adversary_node, affected_node) 유니크 키를 둬서 중복 적재를 완전히 차단하는 버전까지 “프로덕션 드랍인” 형태로 마무리</q> 마무리
```

아래는 요청하신 2가지를 반영해 **“프로덕션 드랍인(drop-in)”**으로 마무리한 버전입니다:
(1) `sanctioned_entity_alias`(별칭) 테이블 + 대소문자/표기 변형 대응(권장: `citext`), (2) `ripple_effect`에 `(assessed_at_utc, adversary_node, affected_node)` 유니크 제약으로 **중복 적재 완전 차단**(UPSERT까지 포함).
Postgres는 `CREATE UNIQUE INDEX`로 단일/복수 컬럼의 유일성을 강제할 수 있습니다.[^1]

***

## 1) DDL 패치: 제재 엔티티 별칭 + 중복 차단 유니크키

### 1-A) `citext`(선택이지만 강력 권장)

`citext`는 대소문자 무시 비교를 제공하므로 alias 매칭의 일관성이 좋아집니다.[^2]

```sql
CREATE EXTENSION IF NOT EXISTS citext;  -- case-insensitive text [web:1021]
```


### 1-B) sanctioned_entity 별칭 테이블

- `alias_text`는 `citext`로 두면 “Huawei” vs “HUAWEI” 같은 케이스 문제를 DB 레벨에서 흡수합니다.[^2]

```sql
CREATE TABLE IF NOT EXISTS sanctioned_entity_alias (
  alias_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id TEXT NOT NULL REFERENCES sanctioned_entity(entity_id) ON DELETE CASCADE,

  alias_text CITEXT NOT NULL,          -- case-insensitive match [web:1021]
  alias_type TEXT NOT NULL DEFAULT 'aka',   -- aka|native|abbrev|former|misspelling|translation
  language TEXT,                        -- e.g., en, ko, zh
  quality_score REAL NOT NULL DEFAULT 0.8,  -- 0..1 (curation confidence)

  source_url TEXT,
  notes TEXT,
  created_at_utc TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE(entity_id, alias_text)
);

CREATE INDEX IF NOT EXISTS idx_alias_text ON sanctioned_entity_alias(alias_text);
CREATE INDEX IF NOT EXISTS idx_alias_entity ON sanctioned_entity_alias(entity_id);
```


### 1-C) ripple_effect 중복 적재 완전 차단(유니크 키)

요청대로 `(assessed_at_utc, adversary_node, affected_node)` 조합에 유니크 인덱스를 둬서 동일 시각 스냅샷 중복을 막습니다.[^1]

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_ripple_snapshot
ON ripple_effect (assessed_at_utc, adversary_node, affected_node);  -- uniqueness enforced [web:1013]
```

> 운영 팁: `assessed_at_utc`가 “now()”로 매번 달라지면 중복이 자연히 안 생기지만, 배치/재실행 시 같은 스냅샷 타임스탬프를 재사용하는 설계(권장)에서 이 유니크키가 진짜 효력을 발휘합니다.

***

## 2) Ripple SQL: UPSERT로 idempotent(재실행 안전) 처리

이제 `ripple_effect` 삽입은 **ON CONFLICT(유니크키) DO UPDATE**로 고정합니다.[^1]

```sql
-- ripple_upsert.sql
-- Parameters:
-- :assessed_at_utc    timestamptz  (스냅샷 시간: 배치에서 고정값 권장)
-- :adversary_node     text
-- :max_hops           int
-- :decay              real
-- :min_path_weight    real
-- :run_notes          text

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
    LEAST(1.0, 0.35*kinetic_impact + 0.40*economic_impact + 0.25*policy_impact) AS composite_risk
  FROM final_calc
)
INSERT INTO ripple_effect (
  assessed_at_utc, adversary_node, affected_node, hop_depth, path_weight,
  chokepoint_status, kinetic_impact, economic_impact, policy_impact, composite_risk,
  evidence_json
)
SELECT
  :assessed_at_utc,
  adversary_node, affected_node, hop_depth, path_weight,
  CASE
    WHEN composite_risk >= 0.75 THEN 'red'
    WHEN composite_risk >= 0.45 THEN 'amber'
    ELSE 'green'
  END AS chokepoint_status,
  kinetic_impact, economic_impact, policy_impact, composite_risk,
  jsonb_build_object(
    'method','recursive_edge_ripple',
    'max_hops', :max_hops,
    'decay', :decay,
    'min_path_weight', :min_path_weight,
    'run_notes', :run_notes
  )
FROM final_scored
ON CONFLICT (assessed_at_utc, adversary_node, affected_node) DO UPDATE SET  -- uniqueness key [web:1013]
  hop_depth = EXCLUDED.hop_depth,
  path_weight = EXCLUDED.path_weight,
  chokepoint_status = EXCLUDED.chokepoint_status,
  kinetic_impact = EXCLUDED.kinetic_impact,
  economic_impact = EXCLUDED.economic_impact,
  policy_impact = EXCLUDED.policy_impact,
  composite_risk = EXCLUDED.composite_risk,
  evidence_json = EXCLUDED.evidence_json;
```


***

## 3) Sanctions 동기화: alias까지 함께 적재(프로덕션형)

OpenSanctions의 공개 제재 데이터셋을 동기화 소스로 사용할 수 있습니다.[^3]
(아래는 “entity + alias”를 동시에 넣는 구조이며, alias는 name/별칭 필드가 있는 소스를 붙일 때 더 강력해집니다.)

```python
# sync_sanctions_pg_prod.py
# pip install "psycopg[binary]" requests

import csv, io, os, hashlib, datetime, requests
import psycopg

CONS_SIMPLE_CSV = "https://data.opensanctions.org/datasets/latest/sanctions/targets.simple.csv"  # [web:981]

def stable_entity_id(regime: str, dataset: str, name: str) -> str:
    return hashlib.sha256(f"{regime}|{dataset}|{name}".encode("utf-8")).hexdigest()[:32]

UPSERT_ENTITY = """
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

UPSERT_ALIAS = """
INSERT INTO sanctioned_entity_alias
(entity_id, alias_text, alias_type, language, quality_score, source_url, notes)
VALUES
(%(entity_id)s,%(alias_text)s,%(alias_type)s,%(language)s,%(quality_score)s,%(source_url)s,%(notes)s)
ON CONFLICT (entity_id, alias_text) DO UPDATE SET
  alias_type = EXCLUDED.alias_type,
  language = EXCLUDED.language,
  quality_score = EXCLUDED.quality_score,
  source_url = EXCLUDED.source_url,
  notes = EXCLUDED.notes;
"""

def utc_now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def sync_consolidated(dsn: str, regime="CONSOLIDATED", dataset="sanctions") -> dict:
    r = requests.get(CONS_SIMPLE_CSV, timeout=120)
    r.raise_for_status()

    entities, aliases = 0, 0
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            reader = csv.DictReader(io.StringIO(r.text))
            for rec in reader:
                name = (rec.get("name") or rec.get("caption") or "").strip()
                if not name:
                    continue

                entity_id = stable_entity_id(regime, dataset, name)
                cur.execute(UPSERT_ENTITY, {
                    "entity_id": entity_id,
                    "entity_name": name,
                    "regime": regime,
                    "program": rec.get("topics") or None,
                    "listed_on_utc": utc_now(),
                    "source_url": rec.get("source_url") or None,
                    "source_dataset": dataset,
                    "notes": "ingested_from=opensanctions consolidated sanctions"  # [web:981]
                })
                entities += 1

                # 최소 alias 정책: 기본 이름을 alias로도 등록(검색/조인 단순화)
                cur.execute(UPSERT_ALIAS, {
                    "entity_id": entity_id,
                    "alias_text": name,
                    "alias_type": "primary",
                    "language": "en",
                    "quality_score": 0.9,
                    "source_url": rec.get("source_url") or None,
                    "notes": "auto_primary_alias"
                })
                aliases += 1

        conn.commit()

    return {"entities_upserted": entities, "aliases_upserted": aliases}

if __name__ == "__main__":
    dsn = os.environ["PG_DSN"]
    print(sync_consolidated(dsn))
```


***

## 4) API 패치: alias 기반 매칭(정확도 향상)

이제 `/sanctions/search`는 본문 이름뿐 아니라 alias도 검색하고, alias hit이면 원 엔티티를 반환합니다.

```python
# api_patch_sanctions.py (핵심 쿼리만)
@app.get("/sanctions/search")
def sanctions_search(q: str, limit: int = 25):
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
              SELECT
                e.entity_id, e.entity_name, e.regime, e.program, e.source_url, e.updated_at_utc,
                a.alias_text, a.alias_type, a.quality_score
              FROM sanctioned_entity_alias a
              JOIN sanctioned_entity e ON e.entity_id = a.entity_id
              WHERE a.alias_text LIKE %s
              ORDER BY a.quality_score DESC, e.updated_at_utc DESC
              LIMIT %s
            """, (f"%{q}%", limit))
            cols = [d[^0] for d in cur.description]
            return {"rows": [dict(zip(cols, r)) for r in cur.fetchall()]}
```


***

## 5) “드랍인” 적용 순서(그대로 실행)

1) DDL 패치 실행: `citext` → `sanctioned_entity_alias` → `ux_ripple_snapshot`[^2][^1]
2) `ripple.sql`을 `ripple_upsert.sql`로 교체(ON CONFLICT DO UPDATE)[^1]
3) `sync_sanctions_pg_prod.py`로 제재+별칭 적재(OpenSanctions 기반)[^3]
4) FastAPI의 sanctions 검색을 alias 조인 쿼리로 교체

원하시면, alias 품질을 더 끌어올리기 위해 `alias_text`에 대해 `pg_trgm`(유사도 검색)까지 추가하는 “오타/로마자 변환” 대응 패치도 후속으로 붙일 수 있습니다.
<span style="display:none">[^10][^11][^12][^13][^14][^15][^16][^17][^18][^19][^20][^21][^22][^23][^24][^25][^26][^27][^28][^29][^30][^31][^32][^33][^34][^35][^36][^37][^38][^39][^4][^40][^41][^5][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://www.postgresql.org/docs/current/indexes-unique.html

[^2]: https://neon.com/docs/extensions/citext

[^3]: https://www.opensanctions.org/datasets/sanctions/

[^4]: gaza_militia_analysis_report.md

[^5]: Objective-KeyResults-ODCafeteria.csv

[^6]: --URL.csv

[^7]: --.csv

[^8]: equality_of_arms_essay_final.txt

[^9]: readme8.MD

[^10]: guggajeongbohagyi_DCPAD_ceorijeolcaro_yeongeogweon-junggugeogweon-webgwa-hagsul-DBro-repeoreonseureul-jehanhayeo.md

[^11]: https://www.semanticscholar.org/paper/298a644f935d69c8d31f21ed0082fcf55f51a3e3

[^12]: http://dl.acm.org/citation.cfm?doid=2628194.2628252

[^13]: https://www.semanticscholar.org/paper/d0ae3a8299868060bd8ef52f798a866e4bf2ad25

[^14]: https://www.semanticscholar.org/paper/ffa8d79ececec9c4bb2cc49a5124c81617d65ba4

[^15]: https://www.semanticscholar.org/paper/00741fbaff91789b578737deabe5252e590c3292

[^16]: https://www.semanticscholar.org/paper/c998fec8e052faa66b8540cbcff90e86a403bf8d

[^17]: https://www.semanticscholar.org/paper/974d01c9951121cdbb801bfde85fe72ce659a915

[^18]: https://www.authorea.com/users/304888/articles/435404-ncbi-gene-expression-and-hybridization-array-data-repository?commit=3597e9ac8f1a1469b332fa0e96373910e94b6d1a

[^19]: https://www.semanticscholar.org/paper/c28952f14d349e2e64007cd77e2f8bcf169da7b1

[^20]: http://link.springer.com/10.1007/978-3-642-01546-5_34

[^21]: http://arxiv.org/pdf/2411.06256.pdf

[^22]: https://arxiv.org/pdf/1903.08334.pdf

[^23]: http://arxiv.org/pdf/2502.14488.pdf

[^24]: https://www.mdpi.com/2079-9292/9/9/1348/pdf

[^25]: https://arxiv.org/ftp/arxiv/papers/2104/2104.05520.pdf

[^26]: https://arxiv.org/pdf/1912.01668.pdf

[^27]: https://arxiv.org/pdf/1910.06169.pdf

[^28]: https://arxiv.org/pdf/2211.06030.pdf

[^29]: https://neon.com/postgresql/postgresql-indexes/postgresql-unique-index

[^30]: https://stackoverflow.com/questions/14221775/in-postgresql-force-unique-on-combination-of-two-columns

[^31]: https://www.pgtutorial.com/postgresql-tutorial/postgresql-unique-index/

[^32]: https://stackoverflow.com/questions/10468657/postgres-unique-multi-column-index-for-join-table

[^33]: https://bambielli.com/til/2016-12-28-postgres-extensions-citext/

[^34]: https://www.opensanctions.org/datasets/sources.csv

[^35]: https://www.geeksforgeeks.org/postgresql/postgresql-unique-index/

[^36]: https://dataresearchcenter.org/library/all/

[^37]: https://www.postgresql.org/docs/current/sql-createindex.html

[^38]: https://www.magistratehq.com/blog/citext-extension/

[^39]: https://www.opensanctions.org/docs/bulk/csv/

[^40]: https://postgresql.kr/docs/13/sql-createindex.html

[^41]: https://aws.amazon.com/blogs/database/manage-case-insensitive-data-in-postgresql/

