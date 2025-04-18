import os, logging, pymysql
from collections import Counter
from decimal import Decimal

# ── ENV ────────────────────────────────────────────────────────────
RDS_HOST     = os.getenv("RDS_HOST")
RDS_USER     = os.getenv("RDS_USER")
RDS_PASSWORD = os.getenv("RDS_PASSWORD")
RDS_DB       = os.getenv("RDS_DB")

log = logging.getLogger()
log.setLevel(logging.INFO)

# ── Connect helper ────────────────────────────────────────────────
def get_conn():
    return pymysql.connect(host=RDS_HOST,
                           user=RDS_USER,
                           password=RDS_PASSWORD,
                           database=RDS_DB,
                           cursorclass=pymysql.cursors.DictCursor,
                           autocommit=True)

# ── Main handler ─────────────────────────────────────────────────
def handler(event, context):
    """
    Recompute wrapped summary for every user from scratch.
    Runs quickly for small class projects (< 10 k rows).
    """
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            # 1. fetch all raw rows
            cur.execute("SELECT user_id, upload_time FROM image_metadata")
            rows = cur.fetchall()

        if not rows:
            log.info("no metadata rows yet")
            return {"statusCode": 200}

        # 2. group by user
        users = {}
        for r in rows:
            u   = r["user_id"] or "unknown"
            dt  = r["upload_time"]
            day = dt.date()

            info = users.setdefault(u, {
                "total": 0,
                "first": day,
                "last":  day,
                "per_day": Counter()
            })
            info["total"] += 1
            info["per_day"][day] += 1
            if day < info["first"]:
                info["first"] = day
            if day > info["last"]:
                info["last"] = day

        # 3. derive metrics and upsert
        with conn.cursor() as cur:
            for u, d in users.items():
                busiest_day, busiest_cnt = d["per_day"].most_common(1)[0]
                span_days = (d["last"] - d["first"]).days + 1
                avg_per_day = round(Decimal(d["total"]) / Decimal(span_days), 2)

                sql = """
                INSERT INTO photo_wrapped_summary
                    (user_id, total_photos, first_date, last_date,
                     busiest_day, busiest_day_count, avg_photos_per_day)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    total_photos       = VALUES(total_photos),
                    first_date         = VALUES(first_date),
                    last_date          = VALUES(last_date),
                    busiest_day        = VALUES(busiest_day),
                    busiest_day_count  = VALUES(busiest_day_count),
                    avg_photos_per_day = VALUES(avg_photos_per_day)
                """
                cur.execute(sql, (
                    u, d["total"], d["first"], d["last"],
                    busiest_day, busiest_cnt, avg_per_day
                ))

        log.info("✅ summaries refreshed for %d users", len(users))
        return {"statusCode": 200}

    except Exception as e:
        log.exception("analysis lambda error")
        raise
