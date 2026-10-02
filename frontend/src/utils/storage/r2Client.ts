import { S3Client } from '@aws-sdk/client-s3';

let r2Client: S3Client | null = null;

export function getR2Client(): S3Client {
  if (!r2Client) {
    r2Client = new S3Client({
      region: 'auto',
      endpoint: `https://${process.env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
      credentials: {
        accessKeyId: process.env.R2_ACCESS_KEY ?? '',
        secretAccessKey:
          process.env.R2_SECRET_ACCESS_KEY ??
          process.env.R2_SECRET_ACESS_KEY ??
          '',
      },
    });
  }
  return r2Client;
}

export function getR2Bucket(): string {
  return process.env.R2_BUCKET_NAME ?? '';
}
