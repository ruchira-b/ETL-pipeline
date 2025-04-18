import os, json, logging, datetime
from collections import Counter
import boto3

# ── Config from environment ─────────────────────────────────────────
PROC_BUCKET = os.environ["OUTPUT_BUCKET"]
META_PREFIX= os.getenv("META_PREFIX", "meta/")
ANAL_PREFIX = os.getenv("ANALYTICS_PREFIX", "analytics/")
THUMB_PREFIX = os.getenv("THUMB_PREFIX", "thumbs/")
MAX_TIMELINE = int(os.getenv("MAX_TIMELINE", "24"))

s3 = boto3.client("s3")
log = logging.getLogger()
log.setLevel(logging.INFO)

# ── Mood mapping table ──────────────────────────────────────────────
MOOD_MAP = {
        'happy': ['smile', 'happy', 'joy', 'celebration', 'party', 'fun', 'laugh'],
        'calm': ['nature', 'water', 'sea', 'ocean', 'sky', 'cloud', 'mountain', 'landscape', 'sunset'],
        'energetic': ['sport', 'running', 'exercise', 'adventure', 'action', 'jump', 'dance'],
        'romantic': ['couple', 'love', 'candle', 'flower', 'date', 'wedding'],
        'melancholy': ['rain', 'fog', 'mist', 'night', 'shadow', 'dark', 'alone'],
        'neutral': ['person', 'people', 'portrait', 'face', 'building', 'urban', 'city']
    }

# ── Utility functions ───────────────────────────────────────────────
def label_to_mood(label_list):
    s = set(label_list)
    for mood, keys in MOOD_MAP.items():
        if s & keys:
            return mood
    return "Undefined"

def color_key(rgb): 
    return ",".join(map(str, rgb))

def hour_bucket(hour):
    return ("Night"     if hour >= 21 or hour < 5 else
            "Morning"   if hour < 12          else
            "Afternoon" if hour < 17          else
            "Evening")

def parse_timestamp(ts_raw):
    """
    Accept either EXIF style 'YYYY:MM:DD HH:MM:SS'
    or ISO 'YYYY‑MM‑DDTHH:MM:SS(.sss)Z'
    Return python datetime (UTC naive)
    """
    try:  # EXIF
        if ":" in ts_raw[:4] and ":" in ts_raw[4:7]:
            return datetime.datetime.strptime(ts_raw, "%Y:%m:%d %H:%M:%S")
        # strip Z for ISO if present
        if ts_raw.endswith("Z"):
            ts_raw = ts_raw[:-1]
        return datetime.datetime.fromisoformat(ts_raw)
    except Exception:
        # fallback: now
        return datetime.datetime.utcnow()

def s3_get_json(bucket, key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None

def s3_put_json(bucket, key, data):
    s3.put_object(Bucket=bucket,
                  Key=key,
                  Body=json.dumps(data, default=int).encode("utf-8"),
                  ContentType="application/json")

# ── Lambda entry ────────────────────────────────────────────────────
def handler(event, context):
    rec       = event["Records"][0]
    bucket    = rec["s3"]["bucket"]["name"]
    meta_key  = rec["s3"]["object"]["key"]

    if not meta_key.startswith(META_PREFIX):
        log.info("Key not under meta/, skipping")
        return {"statusCode": 200}

    # 1. load the meta document
    meta = s3_get_json(bucket, meta_key)
    if not meta:
        log.error("could not read meta JSON")
        return {"statusCode": 500}

    user      = meta.get("user", "unknown")
    wrap_key  = f"{ANAL_PREFIX}{user}/wrapped.json"
    thumb_key = f"{THUMB_PREFIX}{meta['photo_id']}.jpg"

    # 2. fetch or create summary skeleton
    summary = s3_get_json(bucket, wrap_key) or {
        "total_photos": 0,
        "label_counts": {},
        "mood_counts": {},
        "color_counts": {},
        "time_bucket_counts": {},
        "per_day_counts": {},
        "first_date": None,
        "last_date": None,
        "busiest_day": None,
        "busiest_day_photos": []
    }

    # convert dicts -> Counter for math
    for k in ("label_counts","mood_counts","color_counts",
              "time_bucket_counts","per_day_counts"):
        summary[k] = Counter(summary[k])

    # 3. update totals
    summary["total_photos"] += 1
    summary["label_counts"].update(meta["labels"])
    summary["color_counts"].update(color_key(c) for c in meta["dominant_colors"])

    # mood
    mood = label_to_mood(meta["labels"])
    summary["mood_counts"][mood] += 1

    # timestamps
    dt = parse_timestamp(meta.get("capture_time") or meta["upload_time"])
    time_bucket = hour_bucket(dt.hour)
    summary["time_bucket_counts"][time_bucket] += 1

    day_str = dt.strftime("%Y-%m-%d")
    summary["per_day_counts"][day_str] += 1

    # date range
    if not summary["first_date"] or day_str < summary["first_date"]:
        summary["first_date"] = day_str
    if not summary["last_date"] or day_str > summary["last_date"]:
        summary["last_date"] = day_str

    # busiest‑day logic + timeline
    bestselling_cnt = summary["per_day_counts"][summary.get("busiest_day", day_str)]
    today_cnt       = summary["per_day_counts"][day_str]

    # new champ?
    if today_cnt > bestselling_cnt:
        summary["busiest_day"] = day_str
        summary["busiest_day_photos"] = []

    # add photo to timeline if appropriate
    if day_str == summary.get("busiest_day") and len(summary["busiest_day_photos"]) < MAX_TIMELINE:
        summary["busiest_day_photos"].append({
            "time": dt.strftime("%H:%M"),
            "thumb_key": thumb_key
        })
        summary["busiest_day_photos"].sort(key=lambda x: x["time"])

    # 4. friendly derived fields
    most_label, _ = summary["label_counts"].most_common(1)[0]
    fav_color_key, _ = summary["color_counts"].most_common(1)[0]
    fav_color_rgb = list(map(int, fav_color_key.split(",")))
    busiest_day = summary["busiest_day"]
    tot_days = (datetime.datetime.strptime(summary["last_date"], "%Y-%m-%d") -
                datetime.datetime.strptime(summary["first_date"], "%Y-%m-%d")).days + 1
    avg_per_day = round(summary["total_photos"] / tot_days, 2)

    summary.update({
        "most_common_label": most_label,
        "favourite_color": fav_color_rgb,
        "avg_photos_per_day": avg_per_day
    })

    # 5. Counters -> dict for JSON
    for k in ("label_counts","mood_counts","color_counts",
              "time_bucket_counts","per_day_counts"):
        summary[k] = dict(summary[k])

    # 6. write back
    s3_put_json(bucket, wrap_key, summary)
    log.info(f"updated summary → s3://{bucket}/{wrap_key}")
    return {"statusCode": 200}
