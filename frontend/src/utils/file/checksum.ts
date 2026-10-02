import { createSHA256 } from 'hash-wasm';
import type { ChecksumProgressCallback } from '@/utils/types/upload';

/** Read size per iteration — 2 MB chunks keep memory usage bounded. */
export const READ_SIZE = 2 * 1024 * 1024;

/**
 * Compute a SHA-256 hex digest for an entire {@link File} using streaming
 * (incremental) hashing.
 *
 * The file is read in {@link READ_SIZE} slices so that only a small buffer is
 * held in memory at any given time, rather than loading the full file contents
 * at once (which is what `crypto.subtle.digest()` would require).
 *
 * A single {@link https://github.com/nicolo-ribaudo/hash-wasm hash-wasm}
 * hasher instance is initialised and every slice is fed into it sequentially
 * via `hasher.update()`.  The final hex digest is produced only after all
 * bytes have been consumed.
 *
 * @param file       - The {@link File} to hash.
 * @param onProgress - Optional callback invoked after each chunk with
 *                     `(bytesProcessed, totalBytes)`.
 * @returns A lowercase hex-encoded SHA-256 digest string.
 */
export async function computeFileChecksum(
  file: File,
  onProgress?: ChecksumProgressCallback,
): Promise<string> {
  const hasher = await createSHA256();
  hasher.init();

  for (let offset = 0; offset < file.size; offset += READ_SIZE) {
    const slice = file.slice(offset, offset + READ_SIZE);
    const buffer = await slice.arrayBuffer();
    const uint8Array = new Uint8Array(buffer);

    hasher.update(uint8Array);

    const sliceSize = uint8Array.byteLength;
    onProgress?.(offset + sliceSize, file.size);
  }

  return hasher.digest('hex');
}
