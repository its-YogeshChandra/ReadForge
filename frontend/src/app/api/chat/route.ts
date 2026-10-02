/** Same-origin proxy from the browser chat to the ReadForge FastAPI service. */
export async function POST(request: Request) {
  try {
    const response = await fetch(
      new URL('/chat', process.env.READFORGE_API_URL),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: await request.text(),
        cache: 'no-store',
      },
    );
    return new Response(await response.text(), {
      status: response.status,
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return Response.json(
      { detail: 'Document assistant is unavailable' },
      { status: 502 },
    );
  }
}
