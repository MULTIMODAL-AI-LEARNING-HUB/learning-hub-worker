import os
import base64
import hashlib
from dotenv import load_dotenv
from minio import Minio

# Load environment variables if running locally
load_dotenv()

def init_minio():
    endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
    bucket_name = os.getenv("MINIO_BUCKET_NAME", "documents-bucket")

    # Strip protocol prefix (e.g. http://) from endpoint if present
    if endpoint.startswith("http://"):
        endpoint = endpoint[7:]
    elif endpoint.startswith("https://"):
        endpoint = endpoint[8:]

    print(f"Connecting to MinIO at {endpoint}...")
    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False
    )

    if not client.bucket_exists(bucket_name):
        print(f"Bucket '{bucket_name}' does not exist. Creating...")
        client.make_bucket(bucket_name)
        print(f"Bucket '{bucket_name}' created successfully!")
    else:
        print(f"Bucket '{bucket_name}' already exists.")

    # Apply Lifecycle Policies
    print(f"Configuring lifecycle policies for bucket '{bucket_name}'...")

    # Define rules:
    # 1. Clean temporary files in temp/ folder after 1 day (86400 seconds)
    # 2. Clean deleted files in deleted/ folder after 30 days
    xml_data = (
        '<LifecycleConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        '<Rule>'
        '<ID>clean_temp_files</ID>'
        '<Status>Enabled</Status>'
        '<Filter><Prefix>temp/</Prefix></Filter>'
        '<Expiration>'
        '<Days>1</Days>'
        '</Expiration>'
        '</Rule>'
        '<Rule>'
        '<ID>clean_deleted_files</ID>'
        '<Status>Enabled</Status>'
        '<Filter><Prefix>deleted/</Prefix></Filter>'
        '<Expiration>'
        '<Days>30</Days>'
        '</Expiration>'
        '</Rule>'
        '</LifecycleConfiguration>'
    )

    xml_bytes = xml_data.encode('utf-8')
    content_md5 = base64.b64encode(hashlib.md5(xml_bytes).digest()).decode('utf-8')
    headers = {'Content-MD5': content_md5, 'Content-Type': 'application/xml'}

    # Execute raw S3 API request to upload the XML payload
    client._execute(
        'PUT',
        bucket_name=bucket_name,
        body=xml_bytes,
        headers=headers,
        query_params={'lifecycle': ''}
    )
    print("Lifecycle policies configured successfully!")

if __name__ == "__main__":
    init_minio()
