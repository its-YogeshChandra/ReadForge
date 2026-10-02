'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import UploadForm from '@/components/upload/UploadForm';
import ChatWindow from '@/components/chat/ChatWindow';

/** Delay (ms) after upload success before showing the chat window. */
const CHAT_REVEAL_DELAY = 10_000;

interface UploadResult {
  documentId: string;
  fileName: string;
  checksum: string;
}

export default function UploadPage() {
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [showChat, setShowChat] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /** Called when UploadForm finishes a successful upload. */
  const handleUploadComplete = useCallback(
    (info: { documentId: string; fileName: string; checksum: string }) => {
      setUploadResult(info);
      setShowChat(false);
      setCountdown(10);

      // Clear any existing timers
      if (timerRef.current) clearTimeout(timerRef.current);
      if (intervalRef.current) clearInterval(intervalRef.current);

      // Countdown ticker (every second)
      intervalRef.current = setInterval(() => {
        setCountdown((prev) => {
          if (prev === null || prev <= 1) {
            if (intervalRef.current) clearInterval(intervalRef.current);
            return null;
          }
          return prev - 1;
        });
      }, 1000);

      // Reveal chat after delay
      timerRef.current = setTimeout(() => {
        setShowChat(true);
        setCountdown(null);
        if (intervalRef.current) clearInterval(intervalRef.current);
      }, CHAT_REVEAL_DELAY);
    },
    [],
  );

  // Clean up timers on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  return (
    <main className="min-h-screen bg-[--color-bg-warm] py-12 px-4 sm:px-6 lg:px-8">
      {/* Page Header */}
      <div className="max-w-3xl mx-auto mb-8">
        <h1 className="text-3xl font-light text-[--color-charcoal]">
          Document Upload
        </h1>
        <p className="text-sm text-[--color-muted-grey] mt-1">
          Upload your PDF documents for processing
        </p>
      </div>

      {/* Upload Form */}
      <UploadForm onUploadComplete={handleUploadComplete} />

      {/* Countdown Indicator (between upload success and chat reveal) */}
      {uploadResult && countdown !== null && !showChat && (
        <div className="w-full max-w-3xl mx-auto mt-6">
          <div className="flex items-center justify-center gap-3 py-4 px-6 bg-[--color-card-white] rounded-[--radius-card] shadow-[--shadow-card]">
            <div className="w-5 h-5 rounded-full border-2 border-[--color-accent-gold] border-t-transparent animate-spin" />
            <p className="text-sm text-[--color-muted-grey]">
              Preparing document assistant...{' '}
              <span className="font-semibold text-[--color-charcoal]">
                {countdown}s
              </span>
            </p>
          </div>
        </div>
      )}

      {/* Chat Window (appears 10s after upload success) */}
      {uploadResult && showChat && (
        <div className="mt-6">
          <ChatWindow
            key={uploadResult.documentId}
            documentId={uploadResult.documentId}
            documentName={uploadResult.fileName}
          />
        </div>
      )}
    </main>
  );
}
