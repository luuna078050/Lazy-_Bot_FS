import os
import psycopg


def _dsn():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not configured")
    return dsn


def init_db():
    with psycopg.connect(_dsn()) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id BIGSERIAL PRIMARY KEY,
            event_id TEXT UNIQUE NOT NULL,
            outcome TEXT NOT NULL,
            reward DOUBLE PRECISION NOT NULL DEFAULT 0,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS bots (
            bot_id TEXT PRIMARY KEY,
            bot_type TEXT NOT NULL,
            capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """)
        conn.commit()


def record_feedback(data):
    import json
    with psycopg.connect(_dsn()) as conn:
        conn.execute(
            "INSERT INTO feedback(event_id,outcome,reward,details) VALUES(%s,%s,%s,%s) ON CONFLICT(event_id) DO UPDATE SET outcome=EXCLUDED.outcome,reward=EXCLUDED.reward,details=EXCLUDED.details",
            (data["event_id"], data["outcome"], data.get("reward", 0), json.dumps(data.get("details", {}))),
        )
        conn.commit()
    return {"status": "stored", "event_id": data["event_id"]}


def register_bot(data):
    import json
    with psycopg.connect(_dsn()) as conn:
        conn.execute(
            "INSERT INTO bots(bot_id,bot_type,capabilities) VALUES(%s,%s,%s) ON CONFLICT(bot_id) DO UPDATE SET bot_type=EXCLUDED.bot_type,capabilities=EXCLUDED.capabilities,last_seen=now()",
            (data["bot_id"], data["bot_type"], json.dumps(data.get("capabilities", []))),
        )
        conn.commit()
    return {"status": "registered", "bot_id": data["bot_id"]}


def get_stats():
    with psycopg.connect(_dsn()) as conn:
        row = conn.execute("SELECT count(*), COALESCE(avg(reward),0), COALESCE(sum(reward),0) FROM feedback").fetchone()
        bots = conn.execute("SELECT count(*) FROM bots").fetchone()[0]
    return {"feedback_events": row[0], "average_reward": row[1], "total_reward": row[2], "registered_bots": bots}
