import {
  AbortMultipartUploadCommand,
  CompleteMultipartUploadCommand,
  CreateMultipartUploadCommand,
  HeadBucketCommand,
  PutObjectCommand,
  S3Client,
  UploadPartCommand,
} from '@aws-sdk/client-s3';
import { getMinioBucket, getMinioClient } from '@/utils/storage/minioClient';
import { getR2Bucket, getR2Client } from '@/utils/storage/r2Client';

export class MediaBucketError extends Error {
  constructor(
    message: string,
    readonly statusCode: 502 | 503,
  ) {
    super(message);
    this.name = 'MediaBucketError';
  }
}

const unavailableErrorNames = new Set([
  'AccessDenied',
  'CredentialsProviderError',
  'ExpiredRequest',
  'InternalError',
  'NoSuchBucket',
  'NotEntitled',
  'RequestTimeout',
  'ServiceUnavailable',
  'SignatureDoesNotMatch',
  'SlowDown',
  'TooManyRequests',
  'Unauthorized',
]);

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

function storageError(error: unknown, healthCheck = false): MediaBucketError {
  if (error instanceof MediaBucketError) return error;

  const metadata =
    typeof error === 'object' && error !== null && '$metadata' in error
      ? (error as { $metadata?: { httpStatusCode?: number } }).$metadata
      : undefined;
  const name = error instanceof Error ? error.name : '';
  const status = metadata?.httpStatusCode;
  const unavailable =
    healthCheck ||
    status === undefined ||
    status === 429 ||
    status >= 500 ||
    unavailableErrorNames.has(name);

  return new MediaBucketError(
    unavailable
      ? 'Document storage is temporarily unavailable.'
      : 'Document storage rejected the request.',
    unavailable ? 503 : 502,
  );
}

async function send<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation();
  } catch (error) {
    throw storageError(error);
  }
}

export async function ensureMediaBucketAvailable(): Promise<void> {
  const { client, bucket } = storage();
  try {
    await client.send(new HeadBucketCommand({ Bucket: bucket }));
  } catch (error) {
    throw storageError(error, true);
  }
}

export async function putObject(
  key: string,
  body: Buffer,
  mimeType: string,
  checksum: string,
) {
  const { client, bucket } = storage();
  await send(() => client.send(
    new PutObjectCommand({
      Bucket: bucket,
      Key: key,
      Body: body,
      ContentType: mimeType,
      Metadata: { 'sha256-checksum': checksum },
    }),
  ));
}

export async function createMultipartUpload(
  key: string,
  mimeType: string,
  checksum: string,
): Promise<string> {
  const { client, bucket } = storage();
  const response = await send(() => client.send(
    new CreateMultipartUploadCommand({
      Bucket: bucket,
      Key: key,
      ContentType: mimeType,
      Metadata: { 'sha256-checksum': checksum },
    }),
  ));
  if (!response.UploadId) {
    throw new MediaBucketError('Document storage returned an invalid response.', 502);
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
  const response = await send(() => client.send(
    new UploadPartCommand({
      Bucket: bucket,
      Key: key,
      UploadId: uploadId,
      PartNumber: partNumber,
      Body: body,
    }),
  ));
  if (!response.ETag) {
    throw new MediaBucketError('Document storage returned an invalid response.', 502);
  }
  return response.ETag;
}

export async function completeMultipartUpload(
  key: string,
  uploadId: string,
  parts: { ETag: string; PartNumber: number }[],
) {
  const { client, bucket } = storage();
  await send(() => client.send(
    new CompleteMultipartUploadCommand({
      Bucket: bucket,
      Key: key,
      UploadId: uploadId,
      MultipartUpload: { Parts: parts },
    }),
  ));
}

export async function abortMultipartUpload(key: string, uploadId: string) {
  const { client, bucket } = storage();
  await send(() => client.send(
    new AbortMultipartUploadCommand({
      Bucket: bucket,
      Key: key,
      UploadId: uploadId,
    }),
  ));
}
