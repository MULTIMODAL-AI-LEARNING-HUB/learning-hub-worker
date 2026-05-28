import os
from minio import Minio
from dotenv import load_dotenv

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

if __name__ == "__main__":
    init_minio()
