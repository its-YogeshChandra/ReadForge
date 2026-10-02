import { UploadPayload, UploadResponse } from '@/utils/types/upload';

/** API endpoint for document chunk uploads. */
export const UPLOAD_ENDPOINT = '/api/documents/upload';

/**
 * Uploads a single document chunk to the server.
 *
 * Constructs a `FormData` request containing the file chunk blob along with
 * metadata required by the backend to reassemble the complete document.
 *
 * @param payload - The chunk upload payload.
 * @param payload.file - The file chunk Blob to upload.
 * @param payload.checksum - SHA-256 hex digest of the **entire** original file.
 * @param payload.fileName - Original filename (e.g. `"report.pdf"`).
 * @param payload.fileType - MIME type of the file (e.g. `"application/pdf"`).
 * @param payload.chunkIndex - 0-based index of this chunk.
 * @param payload.totalChunks - Total number of chunks the file was split into.
 * @param payload.fileSize - Total size of the original file in bytes.
 * @returns A promise that resolves to an {@link UploadResponse}.
 *          On network or server errors the response will have
 *          `{ success: false, message: string }`.
 */
export async function uploadDocumentChunk(
  payload: UploadPayload,
): Promise<UploadResponse> {
  try {
    const formData = new FormData();

    // File chunk blob — the third argument sets the filename on the multipart part.
    formData.append('file', payload.file, payload.fileName);

    // Integrity: single SHA-256 hex string computed over the ENTIRE file.
    formData.append('checksum', payload.checksum);

    // Metadata fields
    formData.append('fileName', payload.fileName);
    formData.append('fileType', payload.fileType);
    formData.append('chunkIndex', String(payload.chunkIndex));
    formData.append('totalChunks', String(payload.totalChunks));
    formData.append('fileSize', String(payload.fileSize));

    // NOTE: Do NOT set the Content-Type header manually — the browser will
    // automatically generate the correct `multipart/form-data; boundary=…` value.
    const response = await fetch(UPLOAD_ENDPOINT, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(response.statusText);
    }

    const data: UploadResponse = await response.json();
    return data;
  } catch (error) {
    const message =
      error instanceof Error ? error.message : 'An unknown error occurred';
    return { success: false, message };
  }
}
