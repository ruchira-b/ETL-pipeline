import os
import time
import pymysql
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

# The folder where image files live
DATA_FOLDER = "data-images"

# How frequently to upload a file, in seconds
UPLOAD_INTERVAL = 3

# Load environment variables
def load_env_variables():
    load_dotenv()
    return {
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_region": os.getenv("AWS_REGION", "us-east-2"),
        "rds_host": os.getenv("RDS_HOST"),
        "rds_user": os.getenv("RDS_USER"),
        "rds_password": os.getenv("RDS_PASSWORD"),
        "rds_db": os.getenv("RDS_DB"),
    }

# Get all image files in the folder
def get_all_image_files(folder_path):
    image_files = [f for f in Path(folder_path).glob("*") if f.suffix.lower() in [".jpg", ".jpeg", ".png"]]
    if not image_files:
        raise FileNotFoundError(f"No image files found in {folder_path}")
    return image_files

# Connect to the RDS MySQL database
def connect_to_rds(aws_credentials):
    try:
        connection = pymysql.connect(
            host=aws_credentials["rds_host"],
            user=aws_credentials["rds_user"],
            password=aws_credentials["rds_password"],
            database=aws_credentials["rds_db"],
            cursorclass=pymysql.cursors.DictCursor
        )
        return connection
    except Exception as e:
        print(f"Error connecting to RDS: {str(e)}")
        raise

# Insert image metadata into the RDS MySQL database
def insert_image_metadata(connection, file_path):
    try:
        with connection.cursor() as cursor:
            upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            content_type = "image/jpeg" if file_path.suffix.lower() in [".jpg", ".jpeg"] else "image/png"
            sql = """
                INSERT INTO image_metadata (file_name, content_type, upload_time, uploaded_by, project)
                VALUES (%s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (file_path.name, content_type, upload_time, "ruchira", "image-upload-4300"))
            connection.commit()
            print(f"Successfully inserted metadata for {file_path.name} into RDS")
    except Exception as e:
        print(f"Error inserting metadata for {file_path.name}: {str(e)}")

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
    if not aws_credentials["rds_host"] or not aws_credentials["rds_user"]:
        raise ValueError("RDS connection details are missing")

    # Connect to RDS
    connection = connect_to_rds(aws_credentials)

    print(f"Starting image metadata uploader. Uploading each image every {UPLOAD_INTERVAL} seconds.")

    # Get all image files
    image_files = get_all_image_files(DATA_FOLDER)

    for file_path in image_files:
        insert_image_metadata(connection, file_path)
        time.sleep(UPLOAD_INTERVAL)

    # Close the database connection
    connection.close()

if __name__ == "__main__":
    main()
