import os
import time
from pathlib import Path
import boto3
from dotenv import load_dotenv

# The folder where image files live
DATA_FOLDER = "data-images"

# How frequently to upload a file, in seconds
UPLOAD_INTERVAL = 3

# The name of the s3 bucket you're uploading to (can override from .env)
S3_BUCKET_NAME = "landingpg1014"

# Load the values from .env into a dictionary
def load_env_variables():
    load_dotenv()
    return {
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_region": os.getenv("AWS_REGION", "us-east-1"),
        "s3_bucket_name": os.getenv("S3_BUCKET_NAME") or S3_BUCKET_NAME,
    }

# Get all image files in the folder
def get_all_image_files(folder_path):
    image_files = [f for f in Path(folder_path).glob("*") if f.suffix.lower() in [".jpg", ".jpeg", ".png"]]
    if not image_files:
        raise FileNotFoundError(f"No image files found in {folder_path}")
    return image_files

# Upload the selected file to the S3 bucket in the 'uploads' folder with metadata
def upload_to_s3(s3_client, file_path, bucket_name):
    try:
        content_type = "image/jpeg" if file_path.suffix.lower() in [".jpg", ".jpeg"] else "image/png"
        with open(file_path, "rb") as file:
            s3_client.upload_fileobj(
                Fileobj=file,
                Bucket=bucket_name,
                Key=f"uploads/{file_path.name}",
                ExtraArgs={
                    "ContentType": content_type,
                    "Metadata": {
                        "uploaded-by": "ruchira",
                        "project": "image-upload-test"
                    }
                },
            )
        print(f"Successfully uploaded {file_path.name} to S3")
    except Exception as e:
        print(f"Error uploading {file_path.name}: {str(e)}")

def main():
    # Load AWS credentials from .env
    aws_credentials = load_env_variables()

    # Validate required environment variables
    if not aws_credentials["aws_access_key_id"]:
        raise ValueError("No AWS Access key ID set")
    if not aws_credentials["aws_secret_access_key"]:
        raise ValueError("No AWS Secret Access Key set")
    if not aws_credentials["aws_region"]:
        raise ValueError("No AWS Region set")
    if not aws_credentials["s3_bucket_name"]:
        raise ValueError("S3_BUCKET_NAME is not set")

    # Initialize S3 client
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=aws_credentials["aws_access_key_id"],
        aws_secret_access_key=aws_credentials["aws_secret_access_key"],
        region_name=aws_credentials["aws_region"],
    )

    print(f"Starting S3 uploader. Uploading each image every {UPLOAD_INTERVAL} seconds.")

    # Upload each image file in the folder
    image_files = get_all_image_files(DATA_FOLDER)

    for file_path in image_files:
        upload_to_s3(s3_client, file_path, aws_credentials["s3_bucket_name"])
        time.sleep(UPLOAD_INTERVAL)

if __name__ == "__main__":
    main()
