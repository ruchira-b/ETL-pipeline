from dotenv import load_dotenv
load_dotenv()
import os, io, json, uuid, logging, datetime
import boto3
import numpy as np
from PIL import Image
from sklearn.cluster import KMeans

# ---------- Config from env ----------
DEST_BUCKET  = os.getenv("OUTPUT_BUCKET")
THUMB_PFX    = os.getenv("THUMB_PREFIX", "thumbs/")
META_PFX     = os.getenv("META_PREFIX",  "meta/")

s3     = boto3.client("s3")
rekog = boto3.client("rekognition",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION", "us-east-2")
)
log = logging.getLogger()
log.setLevel(logging.INFO)

# ---------- Helpers ----------
EXIF_DATE_TAGS = (36867, 306)    # DateTimeOriginal, DateTime

def get_labels(image_bytes, max_labels=25):
    resp = rekog.detect_labels(Image={"Bytes": image_bytes},
                               MaxLabels=max_labels, MinConfidence=70)
    return [l["Name"] for l in resp["Labels"]]

def get_faces_count(image_bytes):
    resp = rekog.detect_faces(Image={"Bytes": image_bytes},
                              Attributes=['DEFAULT'])
    return len(resp["FaceDetails"])

def dominant_palette(img_rgb, k=5):
    """Return k dominant RGB colours as [[R,G,B], …]"""
    pixels = img_rgb.reshape(-1, 3).astype(np.float32)
    km = KMeans(n_clusters=k, n_init="auto", random_state=0).fit(pixels)
    return km.cluster_centers_.astype(int).tolist()

def read_capture_time(exif):
    for tag in EXIF_DATE_TAGS:
        ts = exif.get(tag)
        if ts:                       # format 'YYYY:MM:DD HH:MM:SS'
            return ts
    return None

# ---------- Lambda entry ----------
def handler(event, context):
    record     = event["Records"][0]
    src_bucket = record["s3"]["bucket"]["name"]
    src_key    = record["s3"]["object"]["key"]
    event_time = record["eventTime"]

    log.info(f"➜ preprocessing s3://{src_bucket}/{src_key}")

    try:
        # 1 ── fetch original
        obj         = s3.get_object(Bucket=src_bucket, Key=src_key)
        original    = obj["Body"].read()

        # 2 ── Pillow open, strip EXIF, resize
        img         = Image.open(io.BytesIO(original))
        img_clean   = Image.new(img.mode, img.size)
        img_clean.putdata(list(img.getdata()))
        img_clean.thumbnail((1024, 1024))          # keep aspect

        width, height = img_clean.size

        # 3 ── Rekognition basic calls
        labels      = get_labels(original)
        face_count  = get_faces_count(original)

        # 4 ── dominant colours (on resized RGB)
        palette     = dominant_palette(np.array(img_clean), k=5)

        # 5 ── capture timestamp (EXIF) or None
        capture_ts  = read_capture_time(img.getexif())

        # 6 ── Build raw‑metadata record
        photo_id = str(uuid.uuid4())
        user_id  = src_key.split("/")[0] if "/" in src_key else "unknown"

        meta = {
            "photo_id":        photo_id,
            "user":            user_id,
            "src_key":         src_key,
            "upload_time":     event_time,            # ISO from S3 event
            "capture_time":    capture_ts,            # may be null
            "labels":          labels,
            "face_count":      face_count,
            "dominant_colors": palette,               # 5×[R,G,B]
            "width":           width,
            "height":          height
        }

        # 7 ── Write outputs to processed bucket
        # 7‑a full‑res cleaned image
        buf_full = io.BytesIO()
        img_clean.save(buf_full, format="JPEG", quality=90)
        s3.put_object(Bucket=DEST_BUCKET,
                      Key=f"images/{photo_id}.jpg",
                      Body=buf_full.getvalue(),
                      ContentType="image/jpeg")

        # 7‑b thumbnail 256px
        thumb = img_clean.copy()
        thumb.thumbnail((256, 256))
        buf_thumb = io.BytesIO()
        thumb.save(buf_thumb, format="JPEG", quality=80)
        s3.put_object(Bucket=DEST_BUCKET,
                      Key=f"{THUMB_PFX}{photo_id}.jpg",
                      Body=buf_thumb.getvalue(),
                      ContentType="image/jpeg")

        # 7‑c metadata JSON
        s3.put_object(Bucket=DEST_BUCKET,
                      Key=f"{META_PFX}{photo_id}.json",
                      Body=json.dumps(meta).encode("utf-8"),
                      ContentType="application/json")

        log.info(f"saved cleaned image, thumb, and meta for {photo_id}")
        return {"statusCode": 200, "body": "ok"}

    except Exception as e:
        log.exception("❌ preprocess error")
        raise

def simulate_s3_event(bucket, key):
    return {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": bucket},
                    "object": {"key": key}
                },
                "eventTime": datetime.datetime.utcnow().isoformat() + "Z"
            }
        ]
    }
if __name__ == "__main__":
    # Simulate an S3 event
    # Configuration
    image_bucket = "landingpg1014"
    prefix = "uploads/"  # or "" if you want to get all files in the bucket

    try:
        # List objects in the bucket
        paginator = s3.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=image_bucket, Prefix=prefix)
    except Exception as e:
        log.exception("")

    for page in page_iterator:
        if "Contents" not in page:
            print("❌ No files found.")
            continue

        for obj in page["Contents"]:
            key = obj["Key"]

            # Filter by image extensions
            if not key.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".tiff")):
                log.info(f"Skipping non-image file: {key}")
                continue

            print(f"\n📷 Processing image: {key}")
            fake_event = simulate_s3_event(image_bucket, key)

            try:
                response = handler(fake_event, context={})
                print("✅ Processed successfully:", response)
            except Exception as e:
                print(f"❌ Error processing {key}: {e}")