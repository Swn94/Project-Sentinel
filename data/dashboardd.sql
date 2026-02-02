-- Top risks
SELECT assessed_at_utc, adversary_node, chokepoint_status, composite_risk, kinetic_impact, economic_impact, policy_impact
FROM risk_assessment
ORDER BY assessed_at_utc DESC
LIMIT 20;

-- Signals backing the latest assessment
SELECT s.collected_at_utc, s.source_name, s.title, s.url
FROM risk_assessment r
JOIN json_each(r.evidence_json, '$.signal_ids') je
JOIN osint_signal s ON s.signal_id = je.value
ORDER BY s.collected_at_utc DESC;
