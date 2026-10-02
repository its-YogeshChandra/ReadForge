import type {
  BackendChatResponse,
  ChatMessage,
  ChatRequest,
  ChatResponse,
} from '@/utils/types/chat';

export const CHAT_ENDPOINT = '/api/chat';

function generateId(): string {
  return `msg_${crypto.randomUUID()}`;
}

function replyContent(data: BackendChatResponse): string {
  if (data.response.clarification_question) {
    return data.response.clarification_question;
  }
  const conclusions = data.response.results.flatMap((result) =>
    result.findings.map((finding) => finding.conclusion),
  );
  return conclusions.join('\n') || 'No conclusion was produced.';
}

export async function sendChatMessage(
  request: ChatRequest,
): Promise<ChatResponse> {
  try {
    const response = await fetch(CHAT_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        document_id: request.documentId,
        conversation_id: request.conversationId,
        message: request.message,
        plan_name: request.planName,
        coverage_year: request.coverageYear,
        service_date: request.serviceDate,
      }),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail ?? 'Failed to send message.');
    }

    const data = body as BackendChatResponse;
    const reply: ChatMessage = {
      id: generateId(),
      role: 'agent',
      content: replyContent(data),
      timestamp: new Date().toISOString(),
      result: data.response,
    };
    return {
      success: true,
      reply,
      conversationId: data.conversation_id,
      evidenceCount: data.evidence_count,
    };
  } catch (error) {
    const errorMessage =
      error instanceof Error ? error.message : 'Failed to send message.';
    return {
      success: false,
      reply: {
        id: generateId(),
        role: 'agent',
        content: 'Sorry, I encountered an error processing your request.',
        timestamp: new Date().toISOString(),
      },
      error: errorMessage,
    };
  }
}
