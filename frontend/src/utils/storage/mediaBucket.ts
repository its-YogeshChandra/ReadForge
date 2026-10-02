import {
  AbortMultipartUploadCommand,
  CompleteMultipartUploadCommand,
  CreateMultipartUploadCommand,
  PutObjectCommand,
  S3Client,
  UploadPartCommand,
} from '@aws-sdk/client-s3';
import { getMinioBucket, getMinioClient } from '@/utils/storage/minioClient';
import { getR2Bucket, getR2Client } from '@/utils/storage/r2Client';

function provider(): 'cloudflare' | 'minio' {
  const value = (process.env.MEDIA_BUCKET_PROVIDER ?? 'cloudflare').toLowerCase();
  if (value !== 'cloudflare' && value !== 'minio') {
    throw new Error("MEDIA_BUCKET_PROVIDER must be 'cloudflare' or 'minio'.");
  }
  return value;
}

function storage(): { client: S3Client; bucket: string } {
  return provider() === 'minio'
    ? { client: getMinioClient(), bucket: getMinioBucket() }
    : { client: getR2Client(), bucket: getR2Bucket() };
}

export async function putObject(
  key: string,
  body: Buffer,
  mimeType: string,
  checksum: string,
) {
  const { client, bucket } = storage();
  await client.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: body,
      ContentType: mimeType,
      Metadata: { 'sha256-checksum': checksum },
    }),
  );
}

export async function createMultipartUpload(
  key: string,
  mimeType: string,
  checksum: string,
): Promise<string> {
  const { client, bucket } = storage();
  const response = await client.send(
    new CreateMultipartUploadCommand({
      Bucket: bucket,
      Key: key,
      ContentType: mimeType,
      Metadata: { 'sha256-checksum': checksum },
    }),
  );
  if (!response.UploadId) {
    throw new Error('Failed to initiate multipart upload — no UploadId returned.');
  }
  return response.UploadId;
}

export async function uploadPart(
  key: string,
  uploadId: string,
  partNumber: number,
  body: Buffer,
): Promise<string> {
  const { client, bucket } = storage();
  const response = await client.send(
    new UploadPartCommand({
      Bucket: bucket,
      Key: key,
      UploadId: uploadId,
      PartNumber: partNumber,
      Body: body,
    }),
  );
  if (!response.ETag) {
    throw new Error(`UploadPart returned no ETag for part ${partNumber}.`);
  }
  return response.ETag;
}

export async function completeMultipartUpload(
  key: string,
  uploadId: string,
  parts: { ETag: string; PartNumber: number }[],
) {
  const { client, bucket } = storage();
  await client.send(
    new CompleteMultipartUploadCommand({
      Bucket: bucket,
      Key: key,
      UploadId: uploadId,
      MultipartUpload: { Parts: parts },
    }),
  );
}

export async function abortMultipartUpload(key: string, uploadId: string) {
  const { client, bucket } = storage();
  await client.send(
    new AbortMultipartUploadCommand({
      Bucket: bucket,
      Key: key,
      UploadId: uploadId,
    }),
  );
}
