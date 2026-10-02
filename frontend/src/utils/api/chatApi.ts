import type { ChatRequest, ChatResponse, ChatMessage } from '@/utils/types/chat';

/**
 * Chat API endpoint.
 *
 * TODO: Replace with the real backend endpoint once implemented.
 */
export const CHAT_ENDPOINT = '/api/chat';

/**
 * Generate a unique message ID.
 */
function generateId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`;
}

/**
 * Send a chat message to the backend and receive the agent's reply.
 *
 * Currently uses a dummy implementation that simulates agent responses.
 * Replace the body of this function with a real `fetch` call once the
 * backend chat endpoint is available.
 *
 * @param request - The chat request payload.
 * @returns The agent's reply wrapped in a {@link ChatResponse}.
 */
export async function sendChatMessage(
  request: ChatRequest,
): Promise<ChatResponse> {
  try {
    // ──────────────────────────────────────────────────────────
    // DUMMY IMPLEMENTATION — Replace with real fetch when ready
    // ──────────────────────────────────────────────────────────
    //
    // Real implementation would look like:
    //
    // const res = await fetch(CHAT_ENDPOINT, {
    //   method: 'POST',
    //   headers: { 'Content-Type': 'application/json' },
    //   body: JSON.stringify(request),
    // });
    //
    // if (!res.ok) throw new Error(res.statusText);
    // return await res.json();
    //

    // Simulate network latency (800–1500ms)
    await new Promise((resolve) =>
      setTimeout(resolve, 800 + Math.random() * 700),
    );

    const dummyReplies = [
      `I've analysed the document (ID: ${request.documentId}). What would you like to know?`,
      `Based on the document content, I can help you with summaries, key points, or specific queries. What interests you?`,
      `That's a great question about the document. Let me look into that section for you — the document covers several key themes that are relevant.`,
      `I found some relevant passages in the document. The main points are: the document discusses important concepts that align with your query.`,
      `Looking at the document structure, I can see it has multiple sections. Could you narrow down which part you're most interested in?`,
    ];

    const replyContent =
      request.history && request.history.length > 2
        ? dummyReplies[Math.floor(Math.random() * (dummyReplies.length - 1)) + 1]
        : dummyReplies[0];

    const reply: ChatMessage = {
      id: generateId(),
      role: 'agent',
      content: replyContent,
      timestamp: new Date().toISOString(),
    };

    return { success: true, reply };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : 'Failed to send message.';

    return {
      success: false,
      reply: {
        id: generateId(),
        role: 'agent',
        content: 'Sorry, I encountered an error processing your request. Please try again.',
        timestamp: new Date().toISOString(),
      },
      error: errorMessage,
    };
  }
}
