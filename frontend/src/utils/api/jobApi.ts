import type { JobStatusResponse } from '@/utils/types/job';

export async function getJobStatus(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobStatusResponse> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
    cache: 'no-store',
    signal,
  });
  const result = (await response.json()) as JobStatusResponse & { detail?: string };
  if (!response.ok) {
    throw new Error(result.detail || 'Could not read document processing status.');
  }
  return result;
}
