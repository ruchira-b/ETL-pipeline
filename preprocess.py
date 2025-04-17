from sklearn.cluster import KMeans
import os, io, json, uuid, logging, datetime
import numpy as np
import boto3,  botocore
from PIL import Image, ExifTags
from dotenv import load_dotenv
load_dotenv()

rekog = boto3.client("rekognition",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    region_name=os.getenv("AWS_REGION", "us-east-2")
)

# ---------- configuration ----------
PROC_BUCKET   = os.getenv("OUTPUT_BUCKET")               # destination bucket
THUMB_PREFIX  = os.getenv("THUMB_PREFIX", "thumbs/")    # key prefix for thumbs
META_PREFIX   = os.getenv("META_PREFIX",  "meta/")      # key prefix for JSON


s3    = boto3.client("s3")

log = logging.getLogger()
log.setLevel(logging.INFO)

# ---------- mood mapping table ----------
# Feel free to tweak / extend without touching code:
MOOD_MAP = {
        'happy': ['smile', 'happy', 'joy', 'celebration', 'party', 'fun', 'laugh'],
        'calm': ['nature', 'water', 'sea', 'ocean', 'sky', 'cloud', 'mountain', 'landscape', 'sunset'],
        'energetic': ['sport', 'running', 'exercise', 'adventure', 'action', 'jump', 'dance'],
        'romantic': ['couple', 'love', 'candle', 'flower', 'date', 'wedding'],
        'melancholy': ['rain', 'fog', 'mist', 'night', 'shadow', 'dark', 'alone'],
        'neutral': ['person', 'people', 'portrait', 'face', 'building', 'urban', 'city']
    }

# ---------- helpers ----------
def label_list(image_bytes, max_labels=25):
    resp = rekog.detect_labels(Image={"Bytes": image_bytes},
                               MaxLabels=max_labels, MinConfidence=70)
    return resp["Labels"]

def kmeans_palette(img_rgb, k=5):
    """
    Return k dominant colours as [[R,G,B], …] using scikit‑learn KMeans.
    img_rgb: np.ndarray (H,W,3) in RGB uint8 [0..255]
    """
    pixels = img_rgb.reshape(-1, 3)               # (N,3)
    km = KMeans(n_clusters=k, n_init="auto", random_state=0).fit(pixels)
    centers = km.cluster_centers_.astype(int)     # shape (k,3)
    return centers.tolist()

def choose_mood(labels):
    set_names = {l["Name"] for l in labels}
    for mood, keys in MOOD_MAP.items():
        if set_names.intersection(keys):
            return mood
    return "Undefined"

def hour_bucket(exif_ts, event_iso):
    """Return Morning / Afternoon / Evening / Night"""
    if exif_ts:
        try:
            hour = int(exif_ts.split()[1].split(":")[0])
        except Exception:
            hour = None
    else:
        hour = None
    if hour is None:
        hour = datetime.datetime.fromisoformat(event_iso.replace("Z","")).hour

    return ("Night"     if hour < 6  else
            "Morning"   if hour < 12 else
            "Afternoon" if hour < 18 else
            "Evening")

def is_nature(labels):
    return any(l["Name"] in ("Landscape", "Plant", "Outdoor", "Mountain", "Beach")
               for l in labels)

# ---------- main handler ----------
def handler(event, context):
    rec = event["Records"][0]
    src_bucket = rec["s3"]["bucket"]["name"]
    src_key    = rec["s3"]["object"]["key"]
    event_time = rec["eventTime"]
    log.info(f"Triggered by s3://{src_bucket}/{src_key}")

    try:
        # 1. fetch original
        obj = s3.get_object(Bucket=src_bucket, Key=src_key)
        orig_bytes = obj["Body"].read()

        # 2. open in Pillow, strip EXIF, resize to 1024 px max
        img = Image.open(io.BytesIO(orig_bytes))
        img_clean = Image.new(img.mode, img.size)
        img_clean.putdata(list(img.getdata()))
        img_clean.thumbnail((1024, 1024))

        # 3. Rekognition labels & faces
        labels = label_list(orig_bytes)
        faces  = rekog.detect_faces(Image={"Bytes": orig_bytes},
                                    Attributes=['DEFAULT'])["FaceDetails"]
        has_people = len(faces) > 0

        # 4. dominant colours (OpenCV wants RGB ndarray)
        img_rgb = np.array(img_clean)
        palette = kmeans_palette(img_rgb, k=5)

        # 5. extra attributes
        exif  = img.getexif()
        exif_ts = exif.get(36867) if exif else None
        mood  = choose_mood(labels)
        nature_flag = is_nature(labels)
        tod   = hour_bucket(exif_ts, event_time)

        # 6. build metadata doc
        photo_id = str(uuid.uuid4())
        user_prefix = src_key.split("/")[0]   # assumes <user_id>/filename.jpeg
        meta = {
            "photo_id":   photo_id,
            "user":       user_prefix,
            "src_key":    src_key,
            "timestamp":  event_time,
            "mood":       mood,
            "labels":     [l["Name"] for l in labels],
            "has_people": has_people,
            "dominant_colors": palette,       # [[R,G,B],…]
            "is_nature":  nature_flag,
            "time_bucket": tod
        }

        # 7. save cleaned image
        out_full = io.BytesIO()
        img_clean.save(out_full, format="JPEG", quality=90)
        s3.put_object(Bucket=PROC_BUCKET,
                      Key=f"images/{photo_id}.jpg",
                      Body=out_full.getvalue(),
                      ContentType="image/jpeg")
        log.info(f"Writing cleaned image to s3://{PROC_BUCKET}/images/{photo_id}.jpg")

        #    save thumbnail (256 px)
        thumb = img_clean.copy()
        thumb.thumbnail((256, 256))
        out_thumb = io.BytesIO()
        thumb.save(out_thumb, format="JPEG", quality=80)
        s3.put_object(Bucket=PROC_BUCKET,
                      Key=f"{THUMB_PREFIX}{photo_id}.jpg",
                      Body=out_thumb.getvalue(),
                      ContentType="image/jpeg")

        #    save meta JSON
        s3.put_object(Bucket=PROC_BUCKET,
                      Key=f"{META_PREFIX}{photo_id}.json",
                      Body=json.dumps(meta).encode("utf-8"),
                      ContentType="application/json")

        log.info(f"Processed {src_key} → photo_id={photo_id}")
        return {"statusCode": 200, "body": "ok"}

    except botocore.exceptions.ClientError as e:
        log.error(f"S3 error: {e}")
        raise
    except Exception as e:
        log.exception("Unhandled error in preprocess lambda")
        raise


# --- add this new reusable wrapper ---
def process_s3_image(src_bucket, src_key, event_time):
    log.info(f"Processing image from s3://{src_bucket}/{src_key}")

    # 1. fetch original
    obj = s3.get_object(Bucket=src_bucket, Key=src_key)
    orig_bytes = obj["Body"].read()

    # 2. open in Pillow, strip EXIF, resize to 1024 px max
    img = Image.open(io.BytesIO(orig_bytes))
    img_clean = Image.new(img.mode, img.size)
    img_clean.putdata(list(img.getdata()))
    img_clean.thumbnail((1024, 1024))

    # 3. Rekognition labels & faces
    labels = label_list(orig_bytes)
    faces = rekog.detect_faces(Image={"Bytes": orig_bytes},
                               Attributes=['DEFAULT'])["FaceDetails"]
    has_people = len(faces) > 0

    # 4. dominant colours (OpenCV wants RGB ndarray)
    img_rgb = np.array(img_clean)
    palette = kmeans_palette(img_rgb, k=5)

    # 5. extra attributes
    exif = img.getexif()
    exif_ts = exif.get(36867) if exif else None
    mood = choose_mood(labels)
    nature_flag = is_nature(labels)
    tod = hour_bucket(exif_ts, event_time)

    # 6. build metadata doc
    photo_id = str(uuid.uuid4())
    user_prefix = src_key.split("/")[0] if "/" in src_key else "unknown"
    meta = {
        "photo_id": photo_id,
        "user": user_prefix,
        "src_key": src_key,
        "timestamp": event_time,
        "mood": mood,
        "labels": [l["Name"] for l in labels],
        "has_people": has_people,
        "dominant_colors": palette,  # [[R,G,B],…]
        "is_nature": nature_flag,
        "time_bucket": tod
    }

    # 7. save cleaned image
    out_full = io.BytesIO()
    img_clean.save(out_full, format="JPEG", quality=90)
    s3.put_object(Bucket=PROC_BUCKET,
                  Key=f"images/{photo_id}.jpg",
                  Body=out_full.getvalue(),
                  ContentType="image/jpeg")

    #    save thumbnail (256 px)
    thumb = img_clean.copy()
    thumb.thumbnail((256, 256))
    out_thumb = io.BytesIO()
    thumb.save(out_thumb, format="JPEG", quality=80)
    s3.put_object(Bucket=PROC_BUCKET,
                  Key=f"{THUMB_PREFIX}{photo_id}.jpg",
                  Body=out_thumb.getvalue(),
                  ContentType="image/jpeg")

    #    save meta JSON
    s3.put_object(Bucket=PROC_BUCKET,
                  Key=f"{META_PREFIX}{photo_id}.json",
                  Body=json.dumps(meta).encode("utf-8"),
                  ContentType="application/json")

    log.info(f"Processed {src_key} → photo_id={photo_id}")
    return meta


if __name__ == "__main__":
    # Simulate an S3 event
    test_bucket = "landingpg1014"
    test_key = "uploads/tshirt.jpg"
    test_event_time = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        print(test_bucket, test_key)
        result = process_s3_image(test_bucket, test_key, test_event_time)
        print("✅ Successfully processed image!")
        print(json.dumps(result, indent=2))
    except Exception as e:
        print("❌ Error processing image:", e)
