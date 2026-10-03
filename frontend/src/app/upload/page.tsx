'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import UploadForm from '@/components/upload/UploadForm';
import type { JobStatus, JobStatusResponse } from '@/utils/types/job';

interface UploadResult {
  documentId: string;
  jobId: string;
  fileName: string;
  checksum: string;
}

export default function UploadPage() {
  const router = useRouter();
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [processingError, setProcessingError] = useState<string | null>(null);

  /** Called when UploadForm finishes a successful upload. */
  const handleUploadComplete = useCallback(
    (info: UploadResult) => {
      setUploadResult(info);
      setJobStatus('queued');
      setProcessingError(null);
    },
    [],
  );

  useEffect(() => {
    if (!uploadResult) return;

    const events = new EventSource(
      `/api/jobs/${encodeURIComponent(uploadResult.jobId)}/events`,
    );
    events.onmessage = (message) => {
      try {
        const job = JSON.parse(message.data) as JobStatusResponse;
        setJobStatus(job.status);
        setProcessingError(job.status === 'failed' ? job.error_message : null);
        if (job.status === 'completed') {
          if (job.document_id !== uploadResult.documentId) {
            setProcessingError('Completed job does not match the uploaded document.');
            setJobStatus('failed');
            events.close();
            return;
          }
          events.close();
          const params = new URLSearchParams({
            documentId: uploadResult.documentId,
            documentName: uploadResult.fileName,
          });
          router.push(`/chat?${params.toString()}`);
        }
        if (job.status === 'failed') events.close();
      } catch (error) {
        setProcessingError(
          error instanceof Error ? error.message : 'Invalid processing status received.',
        );
      }
    };
    events.onerror = () => {
      setProcessingError('Processing updates disconnected. Reconnecting...');
    };

    return () => events.close();
  }, [router, uploadResult]);

  return (
    <main className="min-h-screen bg-[--color-bg-warm] py-12 px-4 sm:px-6 lg:px-8">
      {/* Page Header */}
      <div className="max-w-3xl mx-auto mb-8">
        <h1 className="text-3xl font-light text-[--color-charcoal]">
          Document Upload
        </h1>
        <p className="text-sm text-[--color-muted-grey] mt-1">
          Upload your PDF documents for processing
        </p>
      </div>

      {/* Upload Form */}
      <UploadForm onUploadComplete={handleUploadComplete} />

      {uploadResult && (
        <div className="w-full max-w-3xl mx-auto mt-6">
          <div className="flex items-center justify-center gap-3 py-4 px-6 bg-[--color-card-white] rounded-[--radius-card] shadow-[--shadow-card]">
            {jobStatus !== 'failed' && (
              <div className="w-5 h-5 rounded-full border-2 border-[--color-accent-gold] border-t-transparent animate-spin" />
            )}
            <p className="text-sm text-[--color-muted-grey]">
              {jobStatus === 'failed'
                ? processingError || 'Document processing failed.'
                : processingError
                  ? `${processingError} Retrying...`
                  : jobStatus === 'processing'
                    ? 'Reading and indexing the document...'
                    : 'Document queued for processing...'}
            </p>
          </div>
        </div>
      )}

    </main>
  );
}
