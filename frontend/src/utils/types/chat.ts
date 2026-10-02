/**
 * Represents the role of a chat message sender.
 *
 * - `'user'`  — Message sent by the human user.
 * - `'agent'` — Message sent by the AI agent.
 * - `'system'`— System-generated message (e.g. "Document loaded").
 */
export type ChatRole = 'user' | 'agent' | 'system';

/**
 * A single message in the chat conversation.
 */
export interface ChatMessage {
  /** Unique identifier for this message. */
  id: string;
  /** Who sent the message. */
  role: ChatRole;
  /** The text content of the message. */
  content: string;
  /** ISO 8601 timestamp of when the message was created. */
  timestamp: string;
}

/**
 * Payload sent to the chat endpoint.
 */
export interface ChatRequest {
  /** The user's message text. */
  message: string;
  /** The document ID associated with this chat session. */
  documentId: string;
  /** Optional conversation history for context. */
  history?: ChatMessage[];
}

/**
 * Response returned by the chat endpoint.
 */
export interface ChatResponse {
  /** Whether the request was processed successfully. */
  success: boolean;
  /** The agent's reply message. */
  reply: ChatMessage;
  /** Error message if `success` is false. */
  error?: string;
}
