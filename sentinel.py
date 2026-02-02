# sentinel.py
import json, sqlite3, hashlib, uuid, datetime
from typing import Dict, Any, List

def utc_now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4()}"

def compute_chokepoint_status(composite_risk: float) -> str:
    if composite_risk >= 0.75:
        return "red"
    if composite_risk >= 0.45:
        return "amber"
    return "green"

def compute_risk_from_signal(signal: Dict[str, Any], node_criticality: float) -> Dict[str, float]:
    rm = signal["risk_markers"]
    # Professional, military-grade scalarization (tunable)
    kinetic_impact = min(1.0, 0.15 + 0.55 * rm["disruption"] + 0.30 * rm["export_controls"])
    economic_impact = min(1.0, 0.10 + 0.60 * rm["hbm"] + 0.30 * rm["packaging"])
    policy_impact   = min(1.0, 0.10 + 0.70 * rm["export_controls"] + 0.20 * rm["sanctions"])

    # Criticality amplifies everything
    kinetic_impact *= (0.6 + 0.4 * node_criticality)
    economic_impact *= (0.6 + 0.4 * node_criticality)
    policy_impact *= (0.6 + 0.4 * node_criticality)

    # Composite (weights reflect defense/econ-security posture)
    composite_risk = min(1.0, 0.35 * kinetic_impact + 0.40 * economic_impact + 0.25 * policy_impact)

    return {
        "kinetic_impact": float(compute_cap(kinetic_impact)),
        "economic_impact": float(compute_cap(economic_impact)),
        "policy_impact": float(compute_cap(policy_impact)),
        "composite_risk": float(compute_cap(composite_risk)),
    }

def compute_cap(x: float) -> float:
    return max(0.0, min(1.0, x))

def ensure_schema(conn: sqlite3.Connection, schema_sql_path: str) -> None:
    with open(schema_sql_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()

def upsert_signal(conn: sqlite3.Connection, signal: Dict[str, Any]) -> str:
    raw_json = json.dumps(signal, ensure_ascii=False, separators=(",", ":"))
    sha = sha256_text(raw_json)
    cur = conn.cursor()
    cur.execute("SELECT signal_id FROM osint_signal WHERE sha256 = ?", (sha,))
    row = cur.fetchone()
    if row:
        return row[0]

    signal_id = new_id("sig")
    conn.execute(
        """INSERT INTO osint_signal
           (signal_id, collected_at_utc, source_type, source_name, url, lang, title, summary, raw_json, sha256)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            signal_id,
            signal["collected_at_utc"],
            signal["source_type"],
            signal.get("source_name"),
            signal["url"],
            signal.get("lang", "english"),
            signal["title"],
            signal["summary"],
            raw_json,
            sha,
        ),
    )
    conn.commit()
    return signal_id

def link_signal(conn: sqlite3.Connection, signal_id: str, node_id: str = None, entity_id: str = None, mention_confidence: float = 0.6) -> None:
    link_id = new_id("lnk")
    conn.execute(
        """INSERT OR IGNORE INTO signal_link (link_id, signal_id, node_id, entity_id, mention_confidence)
           VALUES (?,?,?,?,?)""",
        (link_id, signal_id, node_id, entity_id, float(mention_confidence)),
    )
    conn.commit()

def get_node_criticality(conn: sqlite3.Connection, node_id: str) -> float:
    cur = conn.cursor()
    cur.execute("SELECT criticality_score FROM supply_chain_node WHERE node_id = ?", (node_id,))
    row = cur.fetchone()
    return float(row[0]) if row else 0.5

def write_assessment(conn: sqlite3.Connection, adversary_node: str, evidence_signal_ids: List[str], risk: Dict[str, float]) -> None:
    assessment_id = new_id("asmt")
    chokepoint_status = compute_chokepoint_status(risk["composite_risk"])
    evidence_json = json.dumps({"signal_ids": evidence_signal_ids}, ensure_ascii=False)

    conn.execute(
        """INSERT INTO risk_assessment
           (assessment_id, assessed_at_utc, adversary_node, chokepoint_status,
            kinetic_impact, economic_impact, policy_impact, composite_risk, evidence_json)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            assessment_id,
            utc_now_iso(),
            adversary_node,
            chokepoint_status,
            risk["kinetic_impact"],
            risk["economic_impact"],
            risk["policy_impact"],
            risk["composite_risk"],
            evidence_json,
        ),
    )
    conn.commit()

def run_pipeline(db_path: str, schema_sql_path: str, signals_jsonl_path: str, adversary_node: str) -> None:
    conn = sqlite3.connect(db_path)
    ensure_schema(conn, schema_sql_path)

    evidence_signal_ids = []
    aggregated = {"kinetic_impact":0.0,"economic_impact":0.0,"policy_impact":0.0,"composite_risk":0.0}

    # For prototype: treat adversary_node as a supply_chain_node id
    node_criticality = get_node_criticality(conn, adversary_node)

    with open(signals_jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            signal = json.loads(line)
            if signal.get("lang", "english") != "english":
                continue

            signal_id = upsert_signal(conn, signal)
            evidence_signal_ids.append(signal_id)

            # Optional linking (very simple heuristic for prototype)
            link_signal(conn, signal_id, node_id=adversary_node, mention_confidence=0.65)

            risk = compute_risk_from_signal(signal, node_criticality)
            # Conservative aggregator: take max across signals for early warning
            for k in aggregated:
                aggregated[k] = max(aggregated[k], risk[k])

    write_assessment(conn, adversary_node=adversary_node, evidence_signal_ids=evidence_signal_ids, risk=aggregated)
    conn.close()

if __name__ == "__main__":
    # Example:
    # python sentinel.py
    db_path = "sentinel.sqlite"
    schema_sql_path = "schema.sql"
    signals_jsonl_path = "signals.jsonl"
    adversary_node = "node_packaging_chokepoint_001"
    run_pipeline(db_path, schema_sql_path, signals_jsonl_path, adversary_node)
    print("Project Sentinel prototype run complete.")
