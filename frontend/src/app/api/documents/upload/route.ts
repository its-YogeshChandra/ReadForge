import crypto from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import {
  putObject,
  createMultipartUpload,
  uploadPart,
  completeMultipartUpload,
  abortMultipartUpload,
  MediaBucketError,
} from '@/utils/storage/mediaBucket';
import {
  createSession,
  getSession,
  deleteSession,
  purgeStale,
} from '@/utils/storage/multipartStore';

interface QueueResponse {
  success: boolean;
  message: string;
  job_id: string | null;
  document_id: string | null;
}

class UploadRouteError extends Error {
  constructor(
    message: string,
    readonly statusCode: number,
  ) {
    super(message);
    this.name = 'UploadRouteError';
  }
}

async function queueDocument(
  objectKey: string,
  checksum: string,
): Promise<QueueResponse> {
  let response: Response;
  try {
    response = await fetch(
      new URL('/documents', process.env.READFORGE_API_URL),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_name: objectKey,
          idem_key: crypto
            .createHash('sha256')
            .update(objectKey)
            .digest('hex')
            .slice(0, 20),
          checksum,
        }),
        cache: 'no-store',
      },
    );
  } catch {
    throw new UploadRouteError(
      'Document processing service is temporarily unavailable.',
      503,
    );
  }

  const result = (await response.json().catch(() => null)) as QueueResponse | null;
  if (!response.ok) {
    throw new UploadRouteError(
      result?.message || 'Could not queue the uploaded document.',
      response.status,
    );
  }
  if (!result?.document_id || !result.job_id) {
    throw new UploadRouteError('Document processing service returned an invalid response.', 502);
  }
  return result;
}

/**
 * POST /api/documents/upload
 *
 * Receives chunked (or single-part) file uploads via multipart/form-data and
 * streams them to the configured S3-compatible media bucket.
 *
 * Expected FormData fields:
 *   file        — Blob   (the chunk or whole file)
 *   checksum    — string (SHA-256 hex digest of the ENTIRE original file)
 *   fileName    — string (original file name)
 *   fileType    — string (MIME type, e.g. "application/pdf")
 *   chunkIndex  — string (0-based chunk index)
 *   totalChunks — string (total number of chunks; "1" if not chunked)
 *   fileSize    — string (total size of the original file in bytes)
 *
 * Upload strategy:
 *   • totalChunks === 1  →  Simple PutObject
 *   • totalChunks > 1    →  S3 Multipart Upload
 *       - chunkIndex 0   →  CreateMultipartUpload + UploadPart
 *       - middle chunks  →  UploadPart
 *       - final chunk    →  UploadPart + CompleteMultipartUpload
 */
export async function POST(request: NextRequest) {
  // Housekeeping: purge stale multipart sessions
  purgeStale();

  try {
    /* ── Parse FormData ── */
    const formData = await request.formData();

    const file = formData.get('file') as File | null;
    const checksumValue = formData.get('checksum') as string | null;
    const fileName = formData.get('fileName') as string | null;
    const fileType = formData.get('fileType') as string | null;
    const chunkIndexStr = formData.get('chunkIndex') as string | null;
    const totalChunksStr = formData.get('totalChunks') as string | null;
    const fileSizeStr = formData.get('fileSize') as string | null;

    /* ── Validate required fields ── */
    if (!file || !checksumValue || !fileName || !fileType || !chunkIndexStr || !totalChunksStr || !fileSizeStr) {
      return NextResponse.json(
        { success: false, message: 'Missing required fields in upload payload.' },
        { status: 400 },
      );
    }

    if (!/^[0-9a-fA-F]{64}$/.test(checksumValue)) {
      return NextResponse.json(
        { success: false, message: 'Checksum must be a SHA-256 hex digest.' },
        { status: 400 },
      );
    }
    const checksum = checksumValue.toLowerCase();

    const chunkIndex = parseInt(chunkIndexStr, 10);
    const totalChunks = parseInt(totalChunksStr, 10);
    const fileSize = parseInt(fileSizeStr, 10);

    if (
      !Number.isInteger(chunkIndex) ||
      !Number.isInteger(totalChunks) ||
      !Number.isInteger(fileSize) ||
      totalChunks <= 0 ||
      chunkIndex < 0 ||
      chunkIndex >= totalChunks ||
      fileSize <= 0
    ) {
      return NextResponse.json(
        { success: false, message: 'Invalid numeric fields in upload payload.' },
        { status: 400 },
      );
    }

    /* ── Validate file type ── */
    if (fileType !== 'application/pdf') {
      return NextResponse.json(
        { success: false, message: 'Only PDF files are accepted.' },
        { status: 400 },
      );
    }

    /* ── Build the media object key with UUID ── */
    // Insert a UUID before the file extension to guarantee unique keys.
    // e.g. "report.pdf" → "report_a1b2c3d4-e5f6-7890-abcd-ef1234567890.pdf"
    const checksumPrefix = checksum.substring(0, 12);
    const uuid = crypto.randomUUID();
    const dotIndex = fileName.lastIndexOf('.');
    const uniqueFileName =
      dotIndex !== -1
        ? `${fileName.substring(0, dotIndex)}_${uuid}${fileName.substring(dotIndex)}`
        : `${fileName}_${uuid}`;
    const objectKey = `documents/${checksumPrefix}/${uniqueFileName}`;

    /* ── Read the chunk into a Buffer ── */
    const arrayBuffer = await file.arrayBuffer();
    const buffer = Buffer.from(arrayBuffer);

    /* ═══════════════════════════════════════════════════════
       SINGLE-CHUNK UPLOAD (file ≤ 5 MB)
       ═══════════════════════════════════════════════════════ */
    if (totalChunks === 1) {
      await putObject(objectKey, buffer, fileType, checksum);

      const queued = await queueDocument(objectKey, checksum);

      return NextResponse.json({
        success: true,
        message: 'File uploaded and queued for integrity verification.',
        documentId: queued.document_id,
        jobId: queued.job_id,
      });
    }

    /* ═══════════════════════════════════════════════════════
       MULTI-CHUNK UPLOAD (file > 5 MB) — S3 Multipart
       ═══════════════════════════════════════════════════════ */

    // S3 part numbers are 1-based
    const partNumber = chunkIndex + 1;

    /* ── First chunk: initiate multipart upload ── */
    if (chunkIndex === 0) {
      let uploadId: string | undefined;
      try {
        uploadId = await createMultipartUpload(objectKey, fileType, checksum);
        createSession(objectKey, uploadId, checksum, fileName, totalChunks);

        const eTag = await uploadPart(objectKey, uploadId, partNumber, buffer);
        const session = getSession(checksum, fileName);
        if (session) session.eTags[chunkIndex] = eTag;
      } catch (error) {
        if (uploadId) {
          await abortMultipartUpload(objectKey, uploadId).catch(() => {});
        }
        deleteSession(checksum, fileName);
        throw error;
      }

      return NextResponse.json({
        success: true,
        message: `Chunk ${chunkIndex + 1}/${totalChunks} uploaded.`,
      });
    }

    /* ── Subsequent chunks ── */
    const session = getSession(checksum, fileName);

    if (!session) {
      return NextResponse.json(
        {
          success: false,
          message: `No active upload session found. Chunk ${chunkIndex + 1} arrived before the first chunk or the session expired.`,
        },
        { status: 400 },
      );
    }

    // Verify checksum consistency
    if (session.checksum !== checksum) {
      return NextResponse.json(
        { success: false, message: 'Checksum mismatch — file integrity violation.' },
        { status: 400 },
      );
    }

    try {
      const eTag = await uploadPart(session.key, session.uploadId, partNumber, buffer);
      session.eTags[chunkIndex] = eTag;
    } catch (partError) {
      // If a part upload fails, abort the entire multipart upload
      await abortMultipartUpload(session.key, session.uploadId).catch(() => {
        // Best-effort abort — don't mask the original error
      });
      deleteSession(checksum, fileName);

      throw partError;
    }

    /* ── Final chunk: complete the multipart upload ── */
    if (chunkIndex === totalChunks - 1) {
      // Build the parts manifest for completion
      const parts = session.eTags.map((eTag, idx) => ({
        ETag: eTag,
        PartNumber: idx + 1,
      }));

      // Verify we have all parts
      const receivedParts = parts.filter((p) => p.ETag);
      if (receivedParts.length !== totalChunks) {
        await abortMultipartUpload(session.key, session.uploadId).catch(() => {});
        deleteSession(checksum, fileName);

        return NextResponse.json(
          {
            success: false,
            message: `Missing parts: received ${receivedParts.length}/${totalChunks}. Upload aborted.`,
          },
          { status: 400 },
        );
      }

      try {
        await completeMultipartUpload(session.key, session.uploadId, parts);
      } catch (completeError) {
        await abortMultipartUpload(session.key, session.uploadId).catch(() => {});
        deleteSession(checksum, fileName);

        throw completeError;
      }

      // Clean up the session
      deleteSession(checksum, fileName);

      const queued = await queueDocument(session.key, checksum);

      return NextResponse.json({
        success: true,
        message: 'File uploaded and queued for integrity verification.',
        documentId: queued.document_id,
        jobId: queued.job_id,
      });
    }

    /* ── Middle chunk: acknowledge receipt ── */
    return NextResponse.json({
      success: true,
      message: `Chunk ${chunkIndex + 1}/${totalChunks} uploaded.`,
    });
  } catch (error) {
    console.error('[upload] Unhandled error:', error);
    const expectedError =
      error instanceof MediaBucketError || error instanceof UploadRouteError;
    const status = expectedError ? error.statusCode : 500;
    const message = expectedError ? error.message : 'Internal server error.';
    return NextResponse.json(
      { success: false, message },
      { status },
    );
  }
}
