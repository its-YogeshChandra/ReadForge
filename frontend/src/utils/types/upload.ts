/**
 * Represents the current status of a file upload operation.
 *
 * - `'idle'` — No upload in progress.
 * - `'validating'` — The file is being validated (type, size, etc.).
 * - `'hashing'` — A checksum is being computed for integrity verification.
 * - `'uploading'` — The file is actively being uploaded to the server.
 * - `'success'` — The upload completed successfully.
 * - `'error'` — The upload encountered an error.
 */
export type UploadStatus =
  | 'idle'
  | 'validating'
  | 'hashing'
  | 'uploading'
  | 'success'
  | 'error';

/**
 * Defines the byte boundaries for a single chunk within a chunked upload.
 */
export interface ChunkBoundary {
  /** The starting byte offset of the chunk (inclusive). */
  start: number;
  /** The ending byte offset of the chunk (exclusive). */
  end: number;
  /** The zero-based index of this chunk in the sequence. */
  index: number;
}

/**
 * Tracks the real-time progress and metadata of an upload operation.
 */
export interface UploadProgress {
  /** The current status of the upload. */
  status: UploadStatus;
  /** Upload completion percentage, ranging from 0 to 100. */
  progress: number;
  /** A human-readable message describing the current state. */
  message: string;
  /** The name of the file being uploaded. */
  fileName?: string;
  /** The total size of the file in bytes. */
  fileSize?: number;
  /** The computed checksum of the file for integrity verification. */
  checksum?: string;
}

/**
 * The payload sent to the server for each chunk of a chunked file upload.
 */
export interface UploadPayload {
  /** The binary data for this chunk. */
  file: Blob;
  /** The checksum of the entire file for server-side integrity verification. */
  checksum: string;
  /** The original name of the file. */
  fileName: string;
  /** The MIME type of the file. */
  fileType: string;
  /** The zero-based index of this chunk. */
  chunkIndex: number;
  /** The total number of chunks the file has been split into. */
  totalChunks: number;
  /** The total size of the original file in bytes. */
  fileSize: number;
}

/**
 * The response returned by the server after processing an upload request.
 */
export interface UploadResponse {
  /** Whether the upload (or chunk) was processed successfully. */
  success: boolean;
  /** A human-readable message from the server. */
  message: string;
  /** The unique identifier assigned to the uploaded document, present on final success. */
  documentId?: string;
}

/**
 * Callback invoked periodically during checksum computation to report progress.
 *
 * @param bytesProcessed - The number of bytes processed so far.
 * @param totalBytes - The total number of bytes to process.
 */
export type ChecksumProgressCallback = (
  bytesProcessed: number,
  totalBytes: number,
) => void;
