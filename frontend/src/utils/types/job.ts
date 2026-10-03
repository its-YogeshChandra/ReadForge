export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed';

export interface JobStatusResponse {
  job_id: string;
  document_id: string | null;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
}
