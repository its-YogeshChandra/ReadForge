'use client';

import {
  FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import type { ChatMessage } from '@/utils/types/chat';
import { sendChatMessage } from '@/utils/api/chatApi';

/* ─────────────────────── Icons ─────────────────────── */

function SendIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}

function BotIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4" />
      <line x1="8" y1="16" x2="8" y2="16" />
      <line x1="16" y1="16" x2="16" y2="16" />
    </svg>
  );
}

function UserIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

/* ──────────────── Typing indicator ──────────────── */

function TypingIndicator() {
  return (
    <div className="flex items-center gap-3 px-4 py-3">
      <div className="w-8 h-8 rounded-full bg-[--color-accent-gold]/15 flex items-center justify-center shrink-0">
        <BotIcon className="w-4 h-4 text-[--color-accent-gold]" />
      </div>
      <div className="flex items-center gap-1 px-3 py-2 bg-[--color-bg-warm] rounded-[--radius-inner]">
        <span className="w-1.5 h-1.5 rounded-full bg-[--color-muted-grey] animate-bounce [animation-delay:0ms]" />
        <span className="w-1.5 h-1.5 rounded-full bg-[--color-muted-grey] animate-bounce [animation-delay:150ms]" />
        <span className="w-1.5 h-1.5 rounded-full bg-[--color-muted-grey] animate-bounce [animation-delay:300ms]" />
      </div>
    </div>
  );
}

/* ────────────────── Message bubble ────────────────── */

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  if (isSystem) {
    return (
      <div className="flex justify-center px-4 py-2">
        <span className="text-xs text-[--color-muted-grey] bg-[--color-bg-warm] px-3 py-1 rounded-[--radius-pill]">
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div
      className={`flex items-start gap-3 px-4 py-2 ${
        isUser ? 'flex-row-reverse' : ''
      }`}
    >
      {/* Avatar */}
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 ${
          isUser
            ? 'bg-[--color-charcoal]'
            : 'bg-[--color-accent-gold]/15'
        }`}
      >
        {isUser ? (
          <UserIcon className="w-4 h-4 text-white" />
        ) : (
          <BotIcon className="w-4 h-4 text-[--color-accent-gold]" />
        )}
      </div>

      {/* Bubble */}
      <div
        className={`max-w-[75%] px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? 'bg-[--color-charcoal] text-white rounded-2xl rounded-tr-md'
            : 'bg-[--color-bg-warm] text-[--color-charcoal] rounded-2xl rounded-tl-md'
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}

/* ──────────────────── Props ──────────────────── */

interface ChatWindowProps {
  /** The document ID returned after a successful upload. */
  documentId: string;
  /** The name of the uploaded document (shown in the header). */
  documentName: string;
}

/* ────────────────── Main Component ────────────────── */

export default function ChatWindow({
  documentId,
  documentName,
}: ChatWindowProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isVisible, setIsVisible] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  /* ── Entrance animation ── */
  useEffect(() => {
    // Trigger slide-in after mount
    const timer = setTimeout(() => setIsVisible(true), 50);
    return () => clearTimeout(timer);
  }, []);

  /* ── System welcome message on mount ── */
  useEffect(() => {
    const welcomeMessage: ChatMessage = {
      id: 'system_welcome',
      role: 'system',
      content: `Document "${documentName}" loaded — you can now ask questions about it.`,
      timestamp: new Date().toISOString(),
    };
    setMessages([welcomeMessage]);

    // Focus input after entrance animation
    const focusTimer = setTimeout(() => inputRef.current?.focus(), 500);
    return () => clearTimeout(focusTimer);
  }, [documentName]);

  /* ── Auto-scroll to bottom ── */
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  /* ── Send message ── */
  const handleSend = useCallback(
    async (e: FormEvent<HTMLFormElement>) => {
      e.preventDefault();

      const text = inputValue.trim();
      if (!text || isLoading) return;

      // Create user message
      const userMessage: ChatMessage = {
        id: `user_${Date.now()}`,
        role: 'user',
        content: text,
        timestamp: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMessage]);
      setInputValue('');
      setIsLoading(true);

      // Send via HTTP request
      const response = await sendChatMessage({
        message: text,
        documentId,
        history: [...messages, userMessage],
      });

      setIsLoading(false);

      if (response.success) {
        setMessages((prev) => [...prev, response.reply]);
      } else {
        setMessages((prev) => [
          ...prev,
          {
            id: `error_${Date.now()}`,
            role: 'agent' as const,
            content:
              response.error ??
              'Something went wrong. Please try again.',
            timestamp: new Date().toISOString(),
          },
        ]);
      }
    },
    [inputValue, isLoading, documentId, messages],
  );

  return (
    <div
      className={`
        w-full max-w-3xl mx-auto
        transition-all duration-700 ease-out
        ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}
      `}
    >
      <div className="bg-[--color-card-white] rounded-[--radius-card] shadow-[--shadow-card] overflow-hidden flex flex-col">
        {/* ── Chat Header ── */}
        <div className="flex items-center gap-3 px-6 py-4 border-b border-[--color-muted-light]/40">
          <div className="w-9 h-9 rounded-full bg-[--color-accent-gold]/15 flex items-center justify-center">
            <BotIcon className="w-5 h-5 text-[--color-accent-gold]" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-[--color-charcoal]">
              Document Assistant
            </h3>
            <p className="text-xs text-[--color-muted-grey] truncate">
              Chatting about {documentName}
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider bg-green-50 text-[#34C759] rounded-[--radius-pill]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#34C759] animate-pulse" />
            Online
          </span>
        </div>

        {/* ── Messages Area ── */}
        <div className="flex-1 overflow-y-auto py-4 space-y-1 max-h-[400px] min-h-[200px]">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          {isLoading && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* ── Input Area ── */}
        <div className="border-t border-[--color-muted-light]/40 px-4 py-3">
          <form onSubmit={handleSend} className="flex items-center gap-2">
            <input
              ref={inputRef}
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Ask a question about your document..."
              disabled={isLoading}
              className="
                flex-1 px-4 py-2.5 text-sm text-[--color-charcoal]
                bg-[--color-bg-warm] rounded-[--radius-pill]
                border border-transparent
                placeholder:text-[--color-muted-grey]
                focus:outline-none focus:border-[--color-accent-gold] focus:ring-2 focus:ring-[--color-accent-gold]/20
                disabled:opacity-60 disabled:cursor-not-allowed
              "
            />
            <button
              type="submit"
              disabled={!inputValue.trim() || isLoading}
              className={`
                p-2.5 rounded-full shrink-0
                transition-all duration-200
                ${
                  !inputValue.trim() || isLoading
                    ? 'bg-[--color-muted-light]/40 text-[--color-muted-grey] cursor-not-allowed'
                    : 'bg-[--color-charcoal] text-white hover:bg-[--color-charcoal]/90 active:scale-95'
                }
              `}
              aria-label="Send message"
            >
              <SendIcon />
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
