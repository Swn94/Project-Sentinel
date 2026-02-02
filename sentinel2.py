import psycopg2
from psycopg2.extras import RealDictCursor
import os
import json
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class SentinelGuard:
    def __init__(self):
        # Connect to PostgreSQL (Use Environment Variables for Security)
        self.conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "sentinel_db"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASS", "password"),
            host="localhost"
        )
        print("[SYSTEM] Connected to PostgreSQL Securely.")

    def scan_for_smuggling(self):
        """
        Detects 'Circular Trade' patterns where HBM leaves Korea 
        and enters China via a 3rd party proxy.
        """
        query = """
        WITH suspicious_flow AS (
            SELECT 
                s.shipment_id,
                origin.entity_name as origin,
                dest.entity_name as likely_proxy,
                s.volume_units,
                s.manifest_data->>'declared_value' as value
            FROM shipments s
            JOIN supply_nodes origin ON s.origin_id = origin.node_id
            JOIN supply_nodes dest ON s.destination_id = dest.node_id
            WHERE origin.country_code = 'KR'  -- From Chokepoint
              AND dest.risk_level > 0.5       -- To Risky Node
        )
        SELECT * FROM suspicious_flow
        WHERE volume_units > 1000; -- Threshold for Strategic Significance
        """
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            alerts = cur.fetchall()
            
            if alerts:
                self.trigger_export_control_protocol(alerts)
            else:
                print("[STATUS] No immediate threats detected in HBM flow.")

    def trigger_export_control_protocol(self, alerts):
        print(f"🚨 ALERT: {len(alerts)} Suspicious Transactions Detected!")
        print(json.dumps(alerts, indent=4, default=str))
        # Log logic would go here

if __name__ == "__main__":
    sentinel = SentinelGuard()
    sentinel.scan_for_smuggling()