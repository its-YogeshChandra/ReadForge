import Link from 'next/link';
import ChatWindow from '@/components/chat/ChatWindow';

interface ChatPageProps {
  searchParams: Promise<{
    documentId?: string;
    documentName?: string;
  }>;
}

export default async function ChatPage({ searchParams }: ChatPageProps) {
  const { documentId, documentName } = await searchParams;

  return (
    <main className="min-h-screen bg-[--color-bg-warm] px-4 py-12 sm:px-6 lg:px-8">
      <div className="mx-auto mb-8 flex max-w-3xl items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-light text-[--color-charcoal]">
            Document Assistant
          </h1>
          <p className="mt-1 text-sm text-[--color-muted-grey]">
            Ask coverage questions grounded in your processed document.
          </p>
        </div>
        <Link
          href="/upload"
          className="shrink-0 rounded-[--radius-pill] bg-[--color-card-white] px-4 py-2 text-sm text-[--color-charcoal] shadow-[--shadow-card]"
        >
          Upload another
        </Link>
      </div>

      {documentId ? (
        <ChatWindow
          documentId={documentId}
          documentName={documentName || 'document'}
        />
      ) : (
        <div className="mx-auto max-w-3xl rounded-[--radius-card] bg-[--color-card-white] p-8 text-center shadow-[--shadow-card]">
          <p className="text-sm text-[--color-muted-grey]">
            Upload and process a document before starting a conversation.
          </p>
        </div>
      )}
    </main>
  );
}
