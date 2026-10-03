'use client';

import { useCallback, useEffect, useState } from 'react';
import UploadForm from '@/components/upload/UploadForm';
import ChatWindow from '@/components/chat/ChatWindow';
import { getJobStatus } from '@/utils/api/jobApi';
import type { JobStatus } from '@/utils/types/job';

const JOB_POLL_INTERVAL = 2_000;

interface UploadResult {
  documentId: string;
  jobId: string;
  fileName: string;
  checksum: string;
}

export default function UploadPage() {
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [showChat, setShowChat] = useState(false);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [processingError, setProcessingError] = useState<string | null>(null);

  /** Called when UploadForm finishes a successful upload. */
  const handleUploadComplete = useCallback(
    (info: UploadResult) => {
      setUploadResult(info);
      setShowChat(false);
      setJobStatus('queued');
      setProcessingError(null);
    },
    [],
  );

  useEffect(() => {
    if (!uploadResult || showChat || jobStatus === 'failed') return;

    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const job = await getJobStatus(uploadResult.jobId, controller.signal);
        setJobStatus(job.status);
        setProcessingError(job.status === 'failed' ? job.error_message : null);
        if (job.status === 'completed') {
          if (job.document_id !== uploadResult.documentId) {
            setProcessingError('Completed job does not match the uploaded document.');
            setJobStatus('failed');
            return;
          }
          setShowChat(true);
          return;
        }
        if (job.status === 'failed') return;
      } catch (error) {
        if (controller.signal.aborted) return;
        setProcessingError(
          error instanceof Error ? error.message : 'Could not read processing status.',
        );
      }
      timer = setTimeout(poll, JOB_POLL_INTERVAL);
    };

    void poll();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [jobStatus, showChat, uploadResult]);

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

      {uploadResult && !showChat && (
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

      {uploadResult && showChat && (
        <div className="mt-6">
          <ChatWindow
            key={uploadResult.documentId}
            documentId={uploadResult.documentId}
            documentName={uploadResult.fileName}
          />
        </div>
      )}
    </main>
  );
}
