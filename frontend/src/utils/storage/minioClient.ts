import { S3Client } from '@aws-sdk/client-s3';

let minioClient: S3Client | null = null;

export function getMinioClient(): S3Client {
  if (!minioClient) {
    minioClient = new S3Client({
      region: process.env.MINIO_REGION ?? 'us-east-1',
      endpoint: process.env.MINIO_ENDPOINT,
      forcePathStyle: true,
      credentials: {
        accessKeyId: process.env.MINIO_ACCESS_KEY ?? '',
        secretAccessKey: process.env.MINIO_SECRET_KEY ?? '',
      },
    });
  }
  return minioClient;
}

export function getMinioBucket(): string {
  return process.env.MINIO_BUCKET_NAME ?? '';
}
