import { ChunkBoundary } from '@/utils/types/upload';

/** Files at or below this size (5 MB) are uploaded as a single chunk. */
export const CHUNK_THRESHOLD = 5 * 1024 * 1024;

/**
 * Calculate the byte boundaries for splitting a file into upload chunks.
 *
 * - Files ≤ {@link CHUNK_THRESHOLD} produce a single chunk covering the
 *   entire file.
 * - Larger files are divided into roughly 10 equal parts, with a per-chunk
 *   size clamped between 5 MB and 50 MB.  The last chunk is always sized so
 *   that its `end` equals `fileSize` exactly.
 *
 * @param fileSize - Total size of the file in bytes.
 * @returns An ordered array of {@link ChunkBoundary} objects.
 */
export function calculateChunkBoundaries(fileSize: number): ChunkBoundary[] {
  if (fileSize <= CHUNK_THRESHOLD) {
    return [{ start: 0, end: fileSize, index: 0 }];
  }

  const chunkSize = Math.max(
    5 * 1024 * 1024,
    Math.min(fileSize / 10, 50 * 1024 * 1024),
  );

  const boundaries: ChunkBoundary[] = [];
  let start = 0;
  let index = 0;

  while (start < fileSize) {
    const end = Math.min(start + chunkSize, fileSize);
    boundaries.push({ start, end, index });
    start = end;
    index++;
  }

  return boundaries;
}

/**
 * Extract a single chunk from a {@link File} as a {@link Blob}.
 *
 * Uses `File.slice` under the hood so the full file is **never** loaded into
 * memory at once.
 *
 * @param file     - The source file to slice.
 * @param boundary - The chunk boundary describing the byte range.
 * @returns A `Blob` representing the requested byte range.
 */
export function getChunkBlob(file: File, boundary: ChunkBoundary): Blob {
  return file.slice(boundary.start, boundary.end);
}
