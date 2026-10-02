import {
  S3Client,
  PutObjectCommand,
  CreateMultipartUploadCommand,
  UploadPartCommand,
  CompleteMultipartUploadCommand,
  AbortMultipartUploadCommand,
} from '@aws-sdk/client-s3';

/* ─────────────────────── R2 Client ─────────────────────── */

/**
 * Lazily-initialised S3-compatible client for Cloudflare R2.
 *
 * The client is created on first use rather than at module-import time,
 * ensuring that environment variables have been resolved by the runtime
 * before the SDK reads them.
 */
let _r2Client: S3Client | null = null;

function getR2Client(): S3Client {
  if (!_r2Client) {
    _r2Client = new S3Client({
      region: 'auto',
      endpoint: `https://${process.env.R2_ACCOUNT_ID}.r2.cloudflarestorage.com`,
      credentials: {
        accessKeyId: process.env.R2_ACCESS_KEY ?? '',
        secretAccessKey: process.env.R2_SECRET_ACESS_KEY ?? '',
      },
    });
  }
  return _r2Client;
}

/** The R2 bucket name to upload documents to. */
export function getR2Bucket(): string {
  return process.env.R2_BUCKET_NAME ?? '';
}



/* ─────────────────── Simple PUT Upload ─────────────────── */

/**
 * Upload a complete file (≤ 5 MB) to R2 with a single PUT request.
 *
 * Stores the whole-file SHA-256 checksum as custom metadata on the object
 * so it can be verified on download.
 *
 * @param key      - The object key (path) in the bucket.
 * @param body     - The file body as a Buffer.
 * @param mimeType - The MIME type (e.g. `application/pdf`).
 * @param checksum - The SHA-256 hex digest of the entire file.
 */
export async function putObject(
  key: string,
  body: Buffer,
  mimeType: string,
  checksum: string,
) {
  await getR2Client().send(
    new PutObjectCommand({
      Bucket: getR2Bucket(),
      Key: key,
      Body: body,
      ContentType: mimeType,
      Metadata: {
        'sha256-checksum': checksum,
      },
    }),
  );
}

/* ──────────────── S3 Multipart Upload Helpers ──────────── */

/**
 * Initiate a new S3 multipart upload and return the UploadId.
 *
 * @param key      - The object key in the bucket.
 * @param mimeType - The MIME type of the file.
 * @param checksum - The whole-file SHA-256 hex digest (stored as metadata).
 * @returns The `UploadId` string needed for subsequent part uploads.
 */
export async function createMultipartUpload(
  key: string,
  mimeType: string,
  checksum: string,
): Promise<string> {
  const response = await getR2Client().send(
    new CreateMultipartUploadCommand({
      Bucket: getR2Bucket(),
      Key: key,
      ContentType: mimeType,
      Metadata: {
        'sha256-checksum': checksum,
      },
    }),
  );

  if (!response.UploadId) {
    throw new Error('Failed to initiate multipart upload — no UploadId returned.');
  }

  return response.UploadId;
}

/**
 * Upload a single part of a multipart upload.
 *
 * @param key        - The object key in the bucket.
 * @param uploadId   - The multipart UploadId from {@link createMultipartUpload}.
 * @param partNumber - 1-based part number (S3 requires 1-indexed).
 * @param body       - The part body as a Buffer.
 * @returns The ETag of the uploaded part (needed for completion).
 */
export async function uploadPart(
  key: string,
  uploadId: string,
  partNumber: number,
  body: Buffer,
): Promise<string> {
  const response = await getR2Client().send(
    new UploadPartCommand({
      Bucket: getR2Bucket(),
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

/**
 * Complete a multipart upload by assembling all uploaded parts.
 *
 * @param key      - The object key in the bucket.
 * @param uploadId - The multipart UploadId.
 * @param parts    - Array of `{ ETag, PartNumber }` for each uploaded part, in order.
 */
export async function completeMultipartUpload(
  key: string,
  uploadId: string,
  parts: { ETag: string; PartNumber: number }[],
) {
  await getR2Client().send(
    new CompleteMultipartUploadCommand({
      Bucket: getR2Bucket(),
      Key: key,
      UploadId: uploadId,
      MultipartUpload: {
        Parts: parts,
      },
    }),
  );
}

/**
 * Abort an in-progress multipart upload, cleaning up any uploaded parts.
 *
 * @param key      - The object key in the bucket.
 * @param uploadId - The multipart UploadId to abort.
 */
export async function abortMultipartUpload(key: string, uploadId: string) {
  await getR2Client().send(
    new AbortMultipartUploadCommand({
      Bucket: getR2Bucket(),
      Key: key,
      UploadId: uploadId,
    }),
  );
}
