#goal : reading the file buffer from the media bucket 
import boto3;
from dotenv import load_dotenv;
import os;
from pathlib import Path;

load_dotenv()

#validate the required var available in environment 
for var in ["CLOUDFLARE_SECRET_KEY", "CLOUDFLARE_ACCESS_KEY", "BUCKET_NAME"]:
    if not os.getenv(var):
        raise ValueError(f"{var} is not set")   


SECRET_KEY = os.getenv("CLOUDFLARE_SECRET_KEY")
ACCESS_KEY = os.getenv("CLOUDFLARE_ACCESS_KEY")
BUCKET_NAME = os.getenv("BUCKET_NAME")
ACCOUNT_ID = os.getenv("ACCOUNT_ID")

#boto3 client setup for media bucket 
s3 = boto3.client(
    service_name='s3',
    # Provide your R2 endpoint: https://<ACCOUNT_ID>.r2.cloudflarestorage.com
    endpoint_url=f'https://{ACCOUNT_ID}.r2.cloudflarestorage.com',
    
    # Provide your R2 Access Key ID and Secret Access Key
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    region_name='auto',  # Required by boto3, not used by R2
)


#download files from the bucket and load them into a folder
# return : path to the file  
def download_files_from_s3(file_name : str, dest_folder: str)-> str:
    dest = Path(f"{dest_folder}/{file_name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    #s3.download_file writes directly to disk — no response to read
    s3.download_file(BUCKET_NAME, file_name, str(dest))
    return str(dest)

def get_file_buffer_stream(file_name:str) -> BytesIO:
    try:
        #read the file extenstion from the key
        file_extenstion = Path(file_name).suffix

        
        #read the file from the cloud 
        # get content length and check  
        #goal: reading pdf page by page without loading entire file into memory or disk  
        if file_extenstion == ".pdf":
            response = s3.get_object(Bucket=BUCKET_NAME, Key=file_name)

        elif file_extenstion == ".csv":
            response = s3.get_object(Bucket=BUCKET_NAME, Key=file_name)
        elif file_extenstion == ".txt":
            pass   
        #read the file type  
        buffer = BytesIO(response['Body'].read())
        
        return buffer
    except Exception as e:
        logger.error(f"Error downloading file from S3: {e}")
        return None
    


# List objects
def list_objects() -> dict[str,any]:
    response =s3.list_objects_v2(
        Bucket=BUCKET_NAME
    )

    return response.get('Contents', [])


#fucntion : create http range request to the bucket
# goal: to read the pdf and get a page   
def read_from_s3(file_name:str, range:str) -> BytesIO:
    base_chunk_size = 1024 * 1024 #1 mb
    