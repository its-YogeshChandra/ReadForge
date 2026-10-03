export async function GET(
  _request: Request,
  { params }: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await params;
  try {
    const response = await fetch(
      new URL(`/jobs/${encodeURIComponent(jobId)}`, process.env.READFORGE_API_URL),
      { cache: 'no-store' },
    );
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json(
      { detail: 'Document processing service is unavailable' },
      { status: 502 },
    );
  }
}
