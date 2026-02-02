<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>
```
# <q>원하시면, alias 품질을 더 끌어올리기 위해 alias_text에 대해 pg_trgm(유사도 검색)까지 추가하는 “오타/로마자 변환” 대응 패치</q> 패치 추가
```

`pg_trgm` 패치를 추가해 `sanctioned_entity_alias.alias_text`에서 **오타/로마자 변환/부분일치**까지 커버하는 “유사도 검색”을 DB 레벨로 넣겠습니다.
Postgres `pg_trgm` 확장은 trigram 기반 유사도 함수/연산자와 이를 가속하는 GiST/GIN 인덱스(`gin_trgm_ops`, `gist_trgm_ops`)를 제공하며, `%` 연산자는 세션의 `pg_trgm.similarity_threshold`를 기준으로 필터링할 수 있습니다.[^1]

***

## 1) DDL 패치: pg_trgm + 인덱스(프로덕션 기본)

### 1-A) 확장 활성화

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- trigram similarity [web:1034]
```


### 1-B) alias_text에 trigram 인덱스

대부분의 “검색/필터”는 GIN이 빠른 편이라 기본은 GIN으로 두고, **정렬(distance order)** 를 자주 쓰면 GiST를 추가합니다.[^1]

```sql
-- (기본) 유사도/LIKE/ILIKE 가속: GIN + gin_trgm_ops [web:1034]
CREATE INDEX IF NOT EXISTS idx_alias_text_trgm_gin
ON sanctioned_entity_alias
USING GIN (alias_text gin_trgm_ops);

-- (선택) 거리 기반 정렬을 자주 하면 GiST도 추가 가능 [web:1034]
-- CREATE INDEX IF NOT EXISTS idx_alias_text_trgm_gist
-- ON sanctioned_entity_alias
-- USING GIST (alias_text gist_trgm_ops);
```


***

## 2) API/쿼리 패치: “정확→유사도 폴백” 2단계 매칭

`ILIKE`로 1차(명확/빠름) 검색 후, 결과가 부족하면 `%`(유사도 임계치) + `similarity()`로 재랭크하는 방식이 운영에서 안정적입니다.[^1]

```sql
-- Parameters:
-- :q text
-- :limit int
-- (optional) set per-session threshold:
--   SET pg_trgm.similarity_threshold = 0.25;  -- default is 0.3 [web:1034]

WITH exact AS (
  SELECT
    e.entity_id, e.entity_name, e.regime, e.program, e.source_url, e.updated_at_utc,
    a.alias_text, a.alias_type, a.quality_score,
    1.0::real AS sim
  FROM sanctioned_entity_alias a
  JOIN sanctioned_entity e ON e.entity_id = a.entity_id
  WHERE a.alias_text ILIKE ('%' || :q || '%')
  ORDER BY a.quality_score DESC, e.updated_at_utc DESC
  LIMIT :limit
),
fuzzy AS (
  SELECT
    e.entity_id, e.entity_name, e.regime, e.program, e.source_url, e.updated_at_utc,
    a.alias_text, a.alias_type, a.quality_score,
    similarity(a.alias_text::text, :q) AS sim
  FROM sanctioned_entity_alias a
  JOIN sanctioned_entity e ON e.entity_id = a.entity_id
  WHERE a.alias_text % :q          -- uses similarity_threshold and can use trigram index [web:1034]
  ORDER BY sim DESC, a.quality_score DESC
  LIMIT :limit
)
SELECT * FROM exact
UNION ALL
SELECT * FROM fuzzy
LIMIT :limit;
```


***

## 3) FastAPI 패치(실행형): 유사도 임계치 제어

`%` 연산자는 `pg_trgm.similarity_threshold`에 의해 결정되므로, API에서 상황별로 임계치를 조정할 수 있게 합니다(예: 한글/로마자 혼용이면 완화).[^1]

```python
# api_patch_trgm.py (핵심만)
from fastapi import Query

@app.get("/sanctions/search_fuzzy")
def sanctions_search_fuzzy(
    q: str,
    limit: int = 25,
    similarity_threshold: float = Query(0.25, ge=0.05, le=0.95)
):
    sql = """
    SET pg_trgm.similarity_threshold = %(thr)s;
    WITH exact AS (
      SELECT e.entity_id, e.entity_name, e.regime, e.program, e.source_url, e.updated_at_utc,
             a.alias_text, a.alias_type, a.quality_score,
             1.0::real AS sim
      FROM sanctioned_entity_alias a
      JOIN sanctioned_entity e ON e.entity_id = a.entity_id
      WHERE a.alias_text ILIKE ('%%' || %(q)s || '%%')
      ORDER BY a.quality_score DESC, e.updated_at_utc DESC
      LIMIT %(limit)s
    ),
    fuzzy AS (
      SELECT e.entity_id, e.entity_name, e.regime, e.program, e.source_url, e.updated_at_utc,
             a.alias_text, a.alias_type, a.quality_score,
             similarity(a.alias_text::text, %(q)s) AS sim
      FROM sanctioned_entity_alias a
      JOIN sanctioned_entity e ON e.entity_id = a.entity_id
      WHERE a.alias_text %% %(q)s
      ORDER BY sim DESC, a.quality_score DESC
      LIMIT %(limit)s
    )
    SELECT * FROM exact
    UNION ALL
    SELECT * FROM fuzzy
    LIMIT %(limit)s;
    """
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"q": q, "limit": limit, "thr": similarity_threshold})
            cols = [d[^0] for d in cur.description]
            return {"rows": [dict(zip(cols, r)) for r in cur.fetchall()]}
```


***

## 4) 운영 기본값(권장)

- 기본 `similarity_threshold=0.25`로 시작하고, 오탐이 많으면 0.30~0.35로 올립니다(문서 기본값은 0.3 언급).[^1]
- alias는 “원문/번역/약칭/오타”로 분류하고(`alias_type`), API는 `quality_score`와 `sim`을 함께 보여주면 분석가가 빠르게 판정할 수 있습니다.

이 패치를 적용하면 제재 엔티티 매칭은 (1) 정확 부분일치 → (2) trigram 유사도 폴백 → (3) 품질점수 재랭크로 안정적으로 동작합니다.[^1]
<span style="display:none">[^10][^11][^12][^13][^14][^15][^16][^17][^18][^19][^2][^20][^21][^22][^23][^24][^25][^26][^27][^28][^29][^3][^30][^31][^4][^5][^6][^7][^8][^9]</span>

<div align="center">⁂</div>

[^1]: https://www.postgresql.org/docs/current/pgtrgm.html

[^2]: gaza_militia_analysis_report.md

[^3]: Objective-KeyResults-ODCafeteria.csv

[^4]: --URL.csv

[^5]: --.csv

[^6]: equality_of_arms_essay_final.txt

[^7]: readme8.MD

[^8]: guggajeongbohagyi_DCPAD_ceorijeolcaro_yeongeogweon-junggugeogweon-webgwa-hagsul-DBro-repeoreonseureul-jehanhayeo.md

[^9]: https://bulletennauki.ru/gallery/122_10.pdf

[^10]: http://arxiv.org/pdf/2403.03751.pdf

[^11]: https://arxiv.org/pdf/2410.00846.pdf

[^12]: https://arxiv.org/pdf/1910.06169.pdf

[^13]: http://arxiv.org/pdf/2406.05327.pdf

[^14]: https://arxiv.org/pdf/2205.04834.pdf

[^15]: https://arxiv.org/pdf/2212.13297.pdf

[^16]: https://arxiv.org/ftp/arxiv/papers/2303/2303.12376.pdf

[^17]: https://academic.oup.com/nargab/article/doi/10.1093/nargab/lqae159/7921051

[^18]: https://www.postgresql.org/docs/9.0/pgtrgm.html

[^19]: https://devtechtools.org/en/blog/postgresql-pg-trgm-gin-vs-gist-fuzzy-search-performance

[^20]: https://stackoverflow.com/questions/43867449/optimizing-a-postgres-similarity-query-pg-trgm-gin-index

[^21]: https://runebook.dev/en/docs/postgresql/pgtrgm

[^22]: https://postgresql.kr/docs/8.3/pgtrgm.html

[^23]: https://devtechtools.org/en/blog/postgresql-pg-trgm-gin-index-fuzzy-search-performance

[^24]: https://postgrespro.com/docs/postgresql/9.4/pgtrgm

[^25]: https://www.reddit.com/r/PostgreSQL/comments/1as668i/how_to_speed_up_selectlike_queries_using_pg_trgm/

[^26]: https://pganalyze.com/blog/gin-index

[^27]: https://www.pythian.com/blog/technical-track/indexing-text-columns-with-gist-or-gin-to-optimize-like-ilike-using-pg_trgm-in-postgres-9-1-part-1-2

[^28]: https://stackoverflow.com/questions/76556461/postgres-like-operator-vs-similarity-pg-trgm-similarity-threshold-differen

[^29]: https://corekms.tistory.com/entry/pgtrgm-을-이용한-전후위-like-검색

[^30]: https://stackoverflow.com/questions/60177437/why-is-postgres-trigram-word-similarity-function-not-using-a-gin-index

[^31]: https://stackoverflow.com/questions/66178283/postgres-pg-trgm-how-to-compare-similarity-for-array-of-strings

