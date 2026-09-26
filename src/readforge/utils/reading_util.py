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

def get_file_buffer_streamJ(file_name:str) -> BytesIO:
    buffer= BytesIO()
    s3.download_fileobj(BUCKET_NAME, file_name, buffer)
    buffer.seek(0)
    return buffer
    


# List objects
def list_objects() -> dict[str,any]:
    response =s3.list_objects_v2(
        Bucket=BUCKET_NAME
    )

    return response.get('Contents', [])



#def read_from_cloudinary(public_id: str) -> BytesIO:
    #read the file from the cloudinary 