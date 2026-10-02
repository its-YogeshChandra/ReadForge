'use client';

import { FormEvent, useCallback, useRef, useState, DragEvent } from 'react';
import type { UploadProgress, UploadStatus } from '@/utils/types/upload';
import { computeFileChecksum } from '@/utils/file/checksum';
import { calculateChunkBoundaries, getChunkBlob } from '@/utils/file/chunker';
import { uploadDocumentChunk } from '@/utils/api/documentApi';

/* ─────────────────────── helpers ─────────────────────── */

/** Format bytes into a human-readable string. */
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

/** SVG thin-stroke upload icon (minimalist, unfilled). */
function UploadIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="48"
      height="48"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

/** SVG check circle icon. */
function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  );
}

/** SVG file icon. */
function FileIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

/** SVG X icon. */
function XIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

/** SVG alert circle icon. */
function AlertIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

/* ────────────────── status badge ────────────────── */

function StatusBadge({ status }: { status: UploadStatus }) {
  const config: Record<
    UploadStatus,
    { label: string; bg: string; text: string }
  > = {
    idle: { label: 'Ready', bg: 'bg-[#F5F4F1]', text: 'text-[#8E8E8E]' },
    validating: {
      label: 'Validating',
      bg: 'bg-amber-50',
      text: 'text-amber-600',
    },
    hashing: {
      label: 'Hashing',
      bg: 'bg-blue-50',
      text: 'text-blue-600',
    },
    uploading: {
      label: 'Uploading',
      bg: 'bg-[#FFC837]/10',
      text: 'text-[#222222]',
    },
    success: {
      label: 'Complete',
      bg: 'bg-green-50',
      text: 'text-[#34C759]',
    },
    error: { label: 'Error', bg: 'bg-red-50', text: 'text-[#FF3B30]' },
  };

  const { label, bg, text } = config[status];

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-[--radius-inner] ${bg} ${text}`}
    >
      {status === 'uploading' && (
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#FFC837] animate-pulse" />
      )}
      {status === 'hashing' && (
        <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
      )}
      {label}
    </span>
  );
}

/* ────────────────────── props ────────────────────── */

interface UploadFormProps {
  /** Callback fired when a file upload completes successfully. */
  onUploadComplete?: (info: {
    documentId: string;
    fileName: string;
    checksum: string;
  }) => void;
}

/* ────────────────────── main component ────────────────────── */

export default function UploadForm({ onUploadComplete }: UploadFormProps) {
  /* ── state ── */
  const [uploadProgress, setUploadProgress] = useState<UploadProgress>({
    status: 'idle',
    progress: 0,
    message: 'Select a PDF document to upload.',
  });
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [completedFiles, setCompletedFiles] = useState<
    { name: string; size: number; checksum: string; status: 'success' | 'error' }[]
  >([]);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef(false);

  /* ── drag & drop ── */
  const handleDragOver = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);

    const file = e.dataTransfer.files[0];
    if (file && file.type === 'application/pdf') {
      setSelectedFile(file);
      setUploadProgress({
        status: 'idle',
        progress: 0,
        message: `Selected: ${file.name}`,
        fileName: file.name,
        fileSize: file.size,
      });
    } else {
      setUploadProgress({
        status: 'error',
        progress: 0,
        message: 'Only PDF files are accepted.',
      });
    }
  }, []);

  /* ── file selection ── */
  const handleFileChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0] ?? null;
      setSelectedFile(file);
      if (file) {
        setUploadProgress({
          status: 'idle',
          progress: 0,
          message: `Selected: ${file.name}`,
          fileName: file.name,
          fileSize: file.size,
        });
      }
    },
    [],
  );

  /* ── reset ── */
  const handleReset = useCallback(() => {
    abortRef.current = true;
    setSelectedFile(null);
    setUploadProgress({
      status: 'idle',
      progress: 0,
      message: 'Select a PDF document to upload.',
    });
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, []);

  /* ── submit handler ── */
  const handleSubmit = useCallback(
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      abortRef.current = false;

      // Extract file from FormData (as required by spec)
      const formData = new FormData(e.currentTarget);
      const file = formData.get('file') as File | null;

      if (!file || file.size === 0) {
        setUploadProgress({
          status: 'error',
          progress: 0,
          message: 'Please select a file to upload.',
        });
        return;
      }

      /* ── Phase 0: Validate ── */
      setUploadProgress({
        status: 'validating',
        progress: 0,
        message: 'Validating file...',
        fileName: file.name,
        fileSize: file.size,
      });

      if (file.type !== 'application/pdf') {
        setUploadProgress({
          status: 'error',
          progress: 0,
          message: 'Invalid file type. Only PDF documents are accepted.',
        });
        return;
      }

      /* ── Phase 1: Checksum (Continuous Stream) ── */
      setUploadProgress({
        status: 'hashing',
        progress: 0,
        message: 'Calculating checksum...',
        fileName: file.name,
        fileSize: file.size,
      });

      let checksum: string;
      try {
        checksum = await computeFileChecksum(file, (processed, total) => {
          if (abortRef.current) return;
          const pct = Math.round((processed / total) * 100);
          setUploadProgress((prev) => ({
            ...prev,
            progress: pct,
            message: `Calculating checksum... ${pct}%`,
          }));
        });
      } catch {
        setUploadProgress({
          status: 'error',
          progress: 0,
          message: 'Failed to compute file checksum.',
        });
        return;
      }

      if (abortRef.current) return;

      setUploadProgress({
        status: 'hashing',
        progress: 100,
        message: 'Checksum calculated ✓',
        fileName: file.name,
        fileSize: file.size,
        checksum,
      });

      // Brief pause to show checksum success before upload phase
      await new Promise((r) => setTimeout(r, 600));
      if (abortRef.current) return;

      /* ── Phase 2: Chunking & Upload ── */
      const boundaries = calculateChunkBoundaries(file.size);
      const totalChunks = boundaries.length;

      for (let i = 0; i < boundaries.length; i++) {
        if (abortRef.current) return;

        const boundary = boundaries[i];
        const chunkBlob = getChunkBlob(file, boundary);
        const overallProgress = Math.round(((i + 1) / totalChunks) * 100);

        setUploadProgress({
          status: 'uploading',
          progress: overallProgress,
          message:
            totalChunks > 1
              ? `Uploading chunk ${i + 1} of ${totalChunks}... ${overallProgress}%`
              : `Uploading... ${overallProgress}%`,
          fileName: file.name,
          fileSize: file.size,
          checksum,
        });

        const result = await uploadDocumentChunk({
          file: chunkBlob,
          checksum,
          fileName: file.name,
          fileType: file.type,
          chunkIndex: i,
          totalChunks,
          fileSize: file.size,
        });

        if (!result.success) {
          setUploadProgress({
            status: 'error',
            progress: overallProgress,
            message: `Upload failed: ${result.message}`,
            fileName: file.name,
            fileSize: file.size,
            checksum,
          });
          setCompletedFiles((prev) => [
            ...prev,
            { name: file.name, size: file.size, checksum, status: 'error' },
          ]);
          return;
        }
      }

      /* ── Success ── */
      setUploadProgress({
        status: 'success',
        progress: 100,
        message: 'Upload complete!',
        fileName: file.name,
        fileSize: file.size,
        checksum,
      });

      setCompletedFiles((prev) => [
        ...prev,
        { name: file.name, size: file.size, checksum, status: 'success' },
      ]);

      // Notify parent so the chat window can be activated
      onUploadComplete?.({
        documentId: checksum.substring(0, 12),
        fileName: file.name,
        checksum,
      });
    },
    [onUploadComplete],
  );

  /* ── derived state ── */
  const isProcessing =
    uploadProgress.status === 'hashing' ||
    uploadProgress.status === 'uploading' ||
    uploadProgress.status === 'validating';

  /* ──────────────────────── render ──────────────────────── */
  return (
    <div className="w-full max-w-3xl mx-auto space-y-5">
      {/* ── Upload Card ── */}
      <div className="bg-[--color-card-white] rounded-[--radius-card] p-6 shadow-[--shadow-card] hover:shadow-[--shadow-card-hover]">
        {/* Card Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-lg font-semibold text-[--color-charcoal]">
              Upload Document
            </h2>
            <p className="text-xs text-[--color-muted-grey] mt-0.5">
              PDF files only • Supports large files with chunked upload
            </p>
          </div>
          <StatusBadge status={uploadProgress.status} />
        </div>

        {/* ── Form ── */}
        <form onSubmit={handleSubmit}>
          {/* Drop Zone */}
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`
              relative flex flex-col items-center justify-center
              rounded-[--radius-card] border-2 border-dashed cursor-pointer
              py-12 px-6 text-center
              transition-all duration-200
              ${
                isDragOver
                  ? 'border-[--color-accent-gold] bg-[#FFC837]/5 scale-[1.01]'
                  : selectedFile
                    ? 'border-[--color-accent-gold]/40 bg-[#FFC837]/[0.03]'
                    : 'border-[--color-muted-grey]/40 bg-[--color-bg-warm]/30 hover:border-[--color-muted-grey] hover:bg-[--color-bg-warm]/50'
              }
            `}
          >
            <UploadIcon
              className={`mb-4 ${
                isDragOver
                  ? 'text-[--color-accent-gold]'
                  : 'text-[--color-muted-grey]'
              }`}
            />

            {selectedFile ? (
              <div className="space-y-1">
                <div className="flex items-center justify-center gap-2">
                  <FileIcon className="text-[--color-charcoal]" />
                  <span className="text-base font-medium text-[--color-charcoal]">
                    {selectedFile.name}
                  </span>
                </div>
                <p className="text-sm text-[--color-muted-grey]">
                  {formatBytes(selectedFile.size)}
                </p>
              </div>
            ) : (
              <>
                <h3 className="text-lg font-normal text-[--color-charcoal]">
                  Drag and drop your documents here
                </h3>
                <p className="text-sm text-[--color-muted-grey] mt-1">
                  or click to browse
                </p>
              </>
            )}

            {/* Hidden file input */}
            <input
              ref={fileInputRef}
              type="file"
              name="file"
              accept="application/pdf"
              className="sr-only"
              onChange={handleFileChange}
            />
          </div>

          {/* ── Progress Section ── */}
          {isProcessing && (
            <div className="mt-5 space-y-3">
              {/* Progress Bar */}
              <div className="space-y-2">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-[--color-muted-grey] font-medium uppercase tracking-wider">
                    {uploadProgress.status === 'hashing'
                      ? 'Computing Checksum'
                      : uploadProgress.status === 'validating'
                        ? 'Validating'
                        : 'Uploading'}
                  </span>
                  <span className="font-semibold text-[--color-charcoal]">
                    {uploadProgress.progress}%
                  </span>
                </div>
                <div className="w-full h-2 bg-[--color-bg-warm] rounded-[--radius-pill] overflow-hidden">
                  <div
                    className="h-full rounded-[--radius-pill] transition-all duration-300 ease-out"
                    style={{
                      width: `${uploadProgress.progress}%`,
                      backgroundColor:
                        uploadProgress.status === 'hashing'
                          ? '#3B82F6'
                          : '#FFC837',
                    }}
                  />
                </div>
              </div>
              <p className="text-sm text-[--color-muted-grey]">
                {uploadProgress.message}
              </p>
            </div>
          )}

          {/* ── Success Message ── */}
          {uploadProgress.status === 'success' && (
            <div className="mt-5 flex items-center gap-3 p-4 bg-green-50 rounded-[--radius-inner]">
              <CheckIcon className="text-[#34C759] shrink-0" />
              <div>
                <p className="text-sm font-medium text-[--color-charcoal]">
                  {uploadProgress.message}
                </p>
                {uploadProgress.checksum && (
                  <p className="text-xs text-[--color-muted-grey] mt-0.5 font-mono truncate max-w-md">
                    SHA-256: {uploadProgress.checksum}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* ── Error Message ── */}
          {uploadProgress.status === 'error' && (
            <div className="mt-5 flex items-center gap-3 p-4 bg-red-50 rounded-[--radius-inner]">
              <AlertIcon className="text-[#FF3B30] shrink-0" />
              <p className="text-sm font-medium text-[#FF3B30]">
                {uploadProgress.message}
              </p>
            </div>
          )}

          {/* ── Action Buttons ── */}
          <div className="flex items-center gap-3 mt-6">
            <button
              type="submit"
              disabled={!selectedFile || isProcessing}
              className={`
                flex-1 py-3 px-6 rounded-[--radius-pill] text-sm font-semibold
                transition-all duration-200
                ${
                  !selectedFile || isProcessing
                    ? 'bg-[--color-charcoal]/20 text-[--color-muted-grey] cursor-not-allowed'
                    : 'bg-[--color-charcoal] text-white hover:bg-[--color-charcoal]/90 active:scale-[0.98]'
                }
              `}
            >
              {isProcessing
                ? 'Processing...'
                : uploadProgress.status === 'success'
                  ? 'Upload Another'
                  : 'Upload Document'}
            </button>

            {(selectedFile || uploadProgress.status !== 'idle') && (
              <button
                type="button"
                onClick={handleReset}
                className="py-3 px-5 rounded-[--radius-pill] text-sm font-medium border border-[--color-muted-light] text-[--color-muted-grey] hover:text-[--color-charcoal] hover:border-[--color-charcoal]/30 active:scale-[0.98]"
              >
                Clear
              </button>
            )}
          </div>
        </form>
      </div>

      {/* ── Uploaded Files Table ── */}
      {completedFiles.length > 0 && (
        <div className="bg-[--color-card-white] rounded-[--radius-card] p-6 shadow-[--shadow-card]">
          <h3 className="text-sm font-semibold text-[--color-charcoal] mb-4">
            Uploaded Files
          </h3>

          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-[--color-muted-light]/50">
                  <th className="text-left text-[10px] uppercase tracking-wider text-[--color-muted-grey] font-medium pb-3 pr-4">
                    Name
                  </th>
                  <th className="text-left text-[10px] uppercase tracking-wider text-[--color-muted-grey] font-medium pb-3 pr-4">
                    File Size
                  </th>
                  <th className="text-left text-[10px] uppercase tracking-wider text-[--color-muted-grey] font-medium pb-3 pr-4">
                    Status
                  </th>
                  <th className="text-right text-[10px] uppercase tracking-wider text-[--color-muted-grey] font-medium pb-3">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody>
                {completedFiles.map((f, i) => (
                  <tr
                    key={`${f.name}-${i}`}
                    className="border-b border-[--color-muted-light]/30 last:border-b-0 hover:bg-[--color-bg-warm]/40 group"
                  >
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-[--radius-inner] bg-[#FF3B30]/10 flex items-center justify-center shrink-0">
                          <FileIcon className="text-[#FF3B30] w-4 h-4" />
                        </div>
                        <span className="text-sm font-medium text-[--color-charcoal] truncate max-w-[200px]">
                          {f.name}
                        </span>
                      </div>
                    </td>
                    <td className="py-3 pr-4">
                      <span className="text-sm text-[--color-muted-grey]">
                        {formatBytes(f.size)}
                      </span>
                    </td>
                    <td className="py-3 pr-4">
                      {f.status === 'success' ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-[#34C759]">
                          <CheckIcon className="w-3.5 h-3.5" />
                          Complete
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-[#FF3B30]">
                          <AlertIcon className="w-3.5 h-3.5" />
                          Failed
                        </span>
                      )}
                    </td>
                    <td className="py-3 text-right">
                      <button
                        type="button"
                        onClick={() =>
                          setCompletedFiles((prev) =>
                            prev.filter((_, idx) => idx !== i),
                          )
                        }
                        className="opacity-0 group-hover:opacity-100 p-1.5 rounded-[--radius-inner] text-[--color-muted-grey] hover:text-[#FF3B30] hover:bg-red-50"
                        aria-label={`Remove ${f.name}`}
                      >
                        <XIcon />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
