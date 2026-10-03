/** Same-origin proxy from the browser chat to the ReadForge FastAPI service. */
export async function POST(request: Request) {
  const requestId = request.headers.get('x-request-id') ?? crypto.randomUUID();
  try {
    const response = await fetch(
      new URL('/chat', process.env.READFORGE_API_URL),
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Request-ID': requestId,
        },
        body: await request.text(),
        cache: 'no-store',
      },
    );
    return new Response(await response.text(), {
      status: response.status,
      headers: {
        'Content-Type': 'application/json',
        'X-Request-ID': requestId,
      },
    });
  } catch (error) {
    console.error(`[trace] correlation_id=${requestId} stage=chat.proxy_failed`, error);
    return Response.json(
      { detail: 'Document assistant is unavailable' },
      { status: 502, headers: { 'X-Request-ID': requestId } },
    );
  }
}
