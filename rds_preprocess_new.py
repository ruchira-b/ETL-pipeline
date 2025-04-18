import os
import time
import pymysql
import boto3
import json
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables (for local testing or Lambda use with .env)
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

# Initialize Lambda client globally for reuse
lambda_client = boto3.client("lambda")

def connect_to_rds(config):
    try:
        connection = pymysql.connect(
            host=config["rds_host"],
            user=config["rds_user"],
            password=config["rds_password"],
            database=config["rds_db"],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        return connection
    except Exception as e:
        print(f"Error connecting to RDS: {str(e)}")
        raise

def image_already_exists(connection, file_name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS count FROM image_metadata WHERE file_name = %s", (file_name,))
        result = cursor.fetchone()
        return result["count"] > 0

def insert_image_metadata(connection, file_name, content_type, user_id="admin"):
    try:
        with connection.cursor() as cursor:
            upload_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sql = """
                INSERT INTO image_metadata (file_name, content_type, upload_time, uploaded_by, project, user_id)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (file_name, content_type, upload_time, user_id, "image-upload-4300", user_id))
            print(f"✅ Successfully inserted metadata for {file_name} into RDS")
            return True
    except Exception as e:
        print(f"❌ Error inserting metadata for {file_name}: {str(e)}")
        return False

# Simplest invoke_lambda2 function - guaranteed to work
def invoke_lambda2():
    try:
        # Basic client initialization with no extra configuration
        lambda_client = boto3.client(
            "lambda",
            region_name=os.getenv("AWS_REGION", "us-east-2")
        )
        
        print("Attempting to invoke Lambda 2 (RDSAnalysisFunction)...")
        
        # Invoke the second Lambda function with minimal parameters
        response = lambda_client.invoke(
            FunctionName="RDSAnalysisFunction",
            InvocationType="Event",  # Asynchronous invocation
            Payload=json.dumps({"trigger": "metadata_insertion_complete"})
        )
        
        print(f"Lambda 2 invoke response StatusCode: {response.get('StatusCode')}")
        
        # If we get here without exception, consider it a success
        print("✅ Lambda 2 (RDSAnalysisFunction) invocation initiated")
        return True
            
    except Exception as e:
        print(f"❌ Error invoking Lambda 2: {str(e)}")
        # Print the exception type to debug
        print(f"Exception type: {type(e)}")
        return False

# Make sure this is at the end of your handler function
def lambda_handler(event, context):
    try:
        config = load_env_variables()
        connection = connect_to_rds(config)
        
        processed_files = []
        
        for record in event.get('Records', []):
            bucket_name = record['s3']['bucket']['name']
            file_key = record['s3']['object']['key']
            print(f"🔄 Processing file: {file_key} from bucket: {bucket_name}")
            
            # Determine content type from file extension
            ext = file_key.split(".")[-1].lower()
            content_type = "image/jpeg" if ext in ["jpg", "jpeg"] else "image/png"
            
            # Use default user_id
            user_id = "admin"
            
            # Check if image already exists in DB
            if image_already_exists(connection, file_key):
                print(f"⚠️ Skipping already-processed image: {file_key}")
                continue
                
            # Insert the metadata into RDS
            success = insert_image_metadata(connection, file_key, content_type, user_id)
            if success:
                print(f"✅ Successfully inserted metadata for {file_key}")
                processed_files.append(file_key)
            else:
                print(f"❌ Failed to insert metadata for {file_key}")
        
        # Close the connection before invoking Lambda 2
        connection.close()
        
        # Only invoke Lambda 2 if we processed at least one file
        lambda2_invoked = False
        if processed_files:
            lambda2_invoked = invoke_lambda2()
            print(f"Lambda 2 invocation result: {lambda2_invoked}")
        
        # Return result
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Processing complete", 
                "processed_files": processed_files,
                "lambda2_invoked": lambda2_invoked
            })
        }
        
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps(f"Error: {str(e)}")
        }
