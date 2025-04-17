import json
import os
import uuid
import boto3
import logging
from datetime import datetime
from PIL import Image, ExifTags
import numpy as np
from io import BytesIO

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3 = boto3.client('s3')
rekognition = boto3.client('rekognition')

# Configuration
THUMBNAIL_SIZE = (300, 300)
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET', 'processingdata4300')
THUMBS_PREFIX = 'thumbnails/'
META_PREFIX = 'metadata/'
UPLOADS_PREFIX = 'uploads/'


def extract_time_data(image):
    """Extract time data from image EXIF metadata"""
    time_data = {
        'hour_of_day': None,
        'date': None,
        'timestamp': None
    }

    try:
        exif_data = {}
        exif = image._getexif()
        if exif:
            for tag, value in exif.items():
                tag_name = ExifTags.TAGS.get(tag, tag)
                exif_data[tag_name] = value

            # Look for DateTimeOriginal or DateTime tag
            if 'DateTimeOriginal' in exif_data:
                dt_str = exif_data['DateTimeOriginal']
                dt = datetime.strptime(dt_str, '%Y:%m:%d %H:%M:%S')
                time_data['hour_of_day'] = dt.hour
                time_data['date'] = dt.strftime('%Y-%m-%d')
                time_data['timestamp'] = int(dt.timestamp())
            elif 'DateTime' in exif_data:
                dt_str = exif_data['DateTime']
                dt = datetime.strptime(dt_str, '%Y:%m:%d %H:%M:%S')
                time_data['hour_of_day'] = dt.hour
                time_data['date'] = dt.strftime('%Y-%m-%d')
                time_data['timestamp'] = int(dt.timestamp())
    except Exception as e:
        print(f"Error extracting time data: {e}")
        # Use current time as fallback
        now = datetime.now()
        time_data['hour_of_day'] = now.hour
        time_data['date'] = now.strftime('%Y-%m-%d')
        time_data['timestamp'] = int(now.timestamp())

    return time_data


def extract_dominant_colors(image, num_colors=5):
    """Extract the dominant colors from an image"""
    logger.info("Extracting dominant colors from image")

    # Resize image to speed up processing
    img_small = image.resize((150, 150))
    # Convert to RGB if not already
    if img_small.mode != 'RGB':
        img_small = img_small.convert('RGB')

    # Get image data as numpy array
    img_array = np.array(img_small)
    # Reshape the array to be a list of pixels
    pixels = img_array.reshape(-1, 3)

    # Use a simple clustering approach to find dominant colors
    # This is a simplified version - in production you might want to use k-means clustering
    unique_colors, counts = np.unique(pixels, axis=0, return_counts=True)

    # Sort colors by frequency
    indices = np.argsort(-counts)
    sorted_colors = unique_colors[indices]
    sorted_counts = counts[indices]

    # Get top colors
    top_colors = []
    for i in range(min(num_colors, len(sorted_colors))):
        rgb = sorted_colors[i]
        hex_color = '#{:02x}{:02x}{:02x}'.format(rgb[0], rgb[1], rgb[2])
        frequency = float(sorted_counts[i]) / len(pixels)
        top_colors.append({
            'hex': hex_color,
            'rgb': rgb.tolist(),
            'frequency': frequency
        })

    logger.info(f"Found {len(top_colors)} dominant colors")
    return top_colors


def map_mood_from_rekognition(labels):
    """Map image content to mood based on Rekognition labels"""
    # Define mood mappings
    mood_keywords = {
        'happy': ['smile', 'happy', 'joy', 'celebration', 'party', 'fun', 'laugh'],
        'calm': ['nature', 'water', 'sea', 'ocean', 'sky', 'cloud', 'mountain', 'landscape', 'sunset'],
        'energetic': ['sport', 'running', 'exercise', 'adventure', 'action', 'jump', 'dance'],
        'romantic': ['couple', 'love', 'candle', 'flower', 'date', 'wedding'],
        'melancholy': ['rain', 'fog', 'mist', 'night', 'shadow', 'dark', 'alone'],
        'neutral': ['person', 'people', 'portrait', 'face', 'building', 'urban', 'city']
    }

    # Count matches for each mood
    mood_scores = {mood: 0.0 for mood in mood_keywords}
    for label in labels:
        label_name = label['Name'].lower()
        label_confidence = label['Confidence'] / 100.0

        for mood, keywords in mood_keywords.items():
            if any(keyword in label_name for keyword in keywords):
                mood_scores[mood] += label_confidence

    # Get the highest scoring mood
    if all(score == 0 for score in mood_scores.values()):
        primary_mood = 'neutral'
    else:
        primary_mood = max(mood_scores, key=mood_scores.get)

    return {
        'primary_mood': primary_mood,
        'mood_scores': mood_scores
    }


def is_nature_image(labels, threshold=0.6):
    """Determine if an image is a nature image based on Rekognition labels"""
    nature_keywords = [
        'nature', 'landscape', 'mountain', 'forest', 'tree', 'plant', 'flower',
        'water', 'sea', 'ocean', 'beach', 'sky', 'cloud', 'sunset', 'sunrise', 'grass',
        'park', 'lake', 'river', 'animal', 'bird', 'insect', 'outdoor'
    ]

    # Look for nature-related labels
    nature_score = 0.0
    highest_confidence = 0.0

    for label in labels:
        label_name = label['Name'].lower()
        confidence = label['Confidence'] / 100.0

        # Update highest confidence
        if confidence > highest_confidence:
            highest_confidence = confidence

        # Check if label is nature-related
        if any(keyword in label_name for keyword in nature_keywords):
            nature_score += confidence

    # Check for human-made objects that would indicate it's not nature
    human_keywords = [
        'building', 'city', 'urban', 'road', 'car', 'vehicle', 'electronics',
        'furniture', 'indoors', 'room', 'house', 'architecture', 'computer'
    ]

    human_score = 0.0
    for label in labels:
        label_name = label['Name'].lower()
        confidence = label['Confidence'] / 100.0

        if any(keyword in label_name for keyword in human_keywords):
            human_score += confidence

    # Calculate ratio (if both scores are non-zero)
    if human_score > 0 and nature_score > 0:
        ratio = nature_score / (nature_score + human_score)
    else:
        ratio = 1.0 if nature_score > 0 else 0.0

    return {
        'is_nature': ratio > threshold,
        'nature_score': nature_score,
        'nature_ratio': ratio
    }


def create_thumbnail(image):
    """Create a thumbnail of the image"""
    thumb = image.copy()
    thumb.thumbnail(THUMBNAIL_SIZE)

    # Save to BytesIO
    thumbnail_bytes = BytesIO()
    thumb.save(thumbnail_bytes, format='JPEG')
    thumbnail_bytes.seek(0)

    return thumbnail_bytes


def extract_objects(labels, min_confidence=70):
    """
    Extract the most common objects from Rekognition labels
    with counts and confidence scores
    """
    logger.info("Extracting objects from Rekognition labels")

    objects = []
    # Filter labels with confidence above threshold
    for label in labels:
        if label['Confidence'] >= min_confidence:
            objects.append({
                'name': label['Name'],
                'confidence': label['Confidence'],
                'parents': [parent['Name'] for parent in label.get('Parents', [])]
            })

    # Count instances of parent categories for better aggregation
    parent_counts = {}
    for obj in objects:
        for parent in obj.get('parents', []):
            if parent in parent_counts:
                parent_counts[parent] += 1
            else:
                parent_counts[parent] = 1

    logger.info(f"Found {len(objects)} objects above confidence threshold")
    return {
        'objects': objects,
        'parent_categories': parent_counts
    }


def lambda_handler(event, context):
    """
    Main Lambda handler function

    Expected event format:
    {
        "Records": [
            {
                "s3": {
                    "bucket": {
                        "name": "processingdata4300"
                    },
                    "object": {
                        "key": "uploads/image.jpg"
                    }
                },
                "userIdentity": {
                    "principalId": "user-id"  # Optional
                }
            }
        ]
    }
    """
    logger.info("Lambda function started")
    try:
        # Extract event info
        logger.info("Processing new image upload event")
        record = event['Records'][0]
        input_bucket = record['s3']['bucket']['name']
        input_key = record['s3']['object']['key']

        logger.info(f"Image uploaded to bucket: {input_bucket}, key: {input_key}")

        # Try to get user ID from various possible locations
        user_id = None

        # Check if the key starts with 'uploads/' as in your S3 uploader
        if input_key.startswith(UPLOADS_PREFIX):
            # Extract metadata from S3 object to get the 'uploaded-by' field
            try:
                response = s3.head_object(Bucket=input_bucket, Key=input_key)
                if 'Metadata' in response and 'uploaded-by' in response['Metadata']:
                    user_id = response['Metadata']['uploaded-by']
                    logger.info(f"Found user ID in metadata: {user_id}")
            except Exception as e:
                logger.warning(f"Error retrieving object metadata: {str(e)}")

        # Fallback if user ID is still not found
        if not user_id:
            # Check userIdentity in the event
            if 'userIdentity' in record and 'principalId' in record['userIdentity']:
                user_id = record['userIdentity']['principalId']
                logger.info(f"Using user ID from principalId: {user_id}")
            # Check if user ID is in the object key path
            else:
                key_parts = input_key.split('/')
                if len(key_parts) > 1 and key_parts[0] == 'users':
                    user_id = key_parts[1]
                    logger.info(f"Using user ID from path: {user_id}")

        # Final fallback
        if not user_id:
            user_id = 'ruchira'  # Match your uploader's default
            logger.info(f"No user ID found, using default: {user_id}")

        # Create a unique image ID (use original filename + UUID)
        filename = os.path.basename(input_key)
        file_base = os.path.splitext(filename)[0]
        image_id = f"{file_base}-{str(uuid.uuid4())[:8]}"

        # Get the image from S3
        s3_response = s3.get_object(Bucket=input_bucket, Key=input_key)
        image_bytes = s3_response['Body'].read()

        # Open image with PIL
        image = Image.open(BytesIO(image_bytes))

        # Extract time data
        time_data = extract_time_data(image)

        # Call Rekognition for object and scene detection
        logger.info("Calling AWS Rekognition for image analysis")
        rekognition_response = rekognition.detect_labels(
            Image={'Bytes': image_bytes},
            MaxLabels=50,
            MinConfidence=50
        )

        labels = rekognition_response['Labels']
        logger.info(f"Rekognition found {len(labels)} labels in the image")

        # Extract dominant colors
        colors = extract_dominant_colors(image)

        # Map mood from Rekognition labels
        logger.info("Mapping mood from image content")
        mood_data = map_mood_from_rekognition(labels)
        logger.info(f"Primary mood detected: {mood_data['primary_mood']}")

        # Check if it's a nature image
        logger.info("Analyzing if image contains nature")
        nature_data = is_nature_image(labels)
        logger.info(f"Nature image: {nature_data['is_nature']} (score: {nature_data['nature_score']:.2f})")

        # Extract objects for goal #2: most common objects
        logger.info("Extracting object information")
        object_data = extract_objects(labels)
        logger.info(f"Found {len(object_data['objects'])} significant objects")

        # Create metadata object
        metadata = {
            'image_id': image_id,
            'user_id': user_id,
            'original_key': input_key,
            'timestamp': time_data['timestamp'],
            'date': time_data['date'],
            'hour_of_day': time_data['hour_of_day'],
            'colors': colors,
            'labels': labels,
            'objects': object_data,  # Added dedicated objects section
            'mood': mood_data,
            'nature': nature_data,
            'processed_at': int(datetime.now().timestamp())
        }

        # Create thumbnail
        thumbnail_bytes = create_thumbnail(image)

        # Upload metadata to S3
        meta_key = f"{META_PREFIX}{user_id}/{image_id}.json"
        logger.info(f"Saving metadata to S3: {meta_key}")
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=meta_key,
            Body=json.dumps(metadata, indent=2),
            ContentType='application/json'
        )

        # Upload thumbnail to S3
        thumb_key = f"{THUMBS_PREFIX}{user_id}/{image_id}.jpg"
        logger.info(f"Saving thumbnail to S3: {thumb_key}")
        s3.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=thumb_key,
            Body=thumbnail_bytes.getvalue(),
            ContentType='image/jpeg'
        )

        # Print summary of processing
        logger.info("=== Image Processing Summary ===")
        logger.info(f"Image ID: {image_id}")
        logger.info(f"User ID: {user_id}")
        logger.info(f"Primary mood: {mood_data['primary_mood']}")
        logger.info(f"Nature score: {nature_data['nature_score']:.2f}")
        logger.info(f"Top objects: {', '.join([obj['name'] for obj in object_data['objects'][:3]])}")
        logger.info(f"Dominant color: {colors[0]['hex']}")
        logger.info(f"Time of day: {time_data['hour_of_day']}:00")
        logger.info("==============================")

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Image processed successfully',
                'metadata_key': meta_key,
                'thumbnail_key': thumb_key,
                'image_id': image_id,
                'summary': {
                    'mood': mood_data['primary_mood'],
                    'is_nature': nature_data['is_nature'],
                    'top_objects': [obj['name'] for obj in object_data['objects'][:3]],
                    'dominant_color': colors[0]['hex']
                }
            })
        }

    except Exception as e:
        logger.error(f"Error processing image: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': str(e)
            })
        }