/** Same-origin SSE proxy for Redis-backed document job transitions. */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  try {
    const response = await fetch(
      new URL(
        `/jobs/${encodeURIComponent(jobId)}/events`,
        process.env.READFORGE_API_URL,
      ),
      {
        headers: { Accept: 'text/event-stream' },
        cache: 'no-store',
        signal: request.signal,
      },
    );
    return new Response(response.body, {
      status: response.status,
      headers: {
        'Content-Type': response.headers.get('Content-Type') ?? 'text/event-stream',
        'Cache-Control': 'no-cache, no-transform',
        'X-Accel-Buffering': 'no',
      },
    });
  } catch (error) {
    console.error('[job-events] Backend stream failed:', error);
    return Response.json(
      { detail: 'Document processing service is unavailable' },
      { status: 502 },
    );
  }
}
